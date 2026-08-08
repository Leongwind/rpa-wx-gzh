"""Playwright browser publisher with persistent login and real status checks."""

from __future__ import annotations

import re
import time
from pathlib import Path
from mimetypes import guess_type
from typing import Any, Iterable, Optional

from .content import render_browser_html
from .models import Article, PublishResult, PublishStatus


class PlaywrightUnavailable(RuntimeError):
    pass


class BrowserPublisher:
    """Publish through the web console when API credentials are unavailable.

    ``playwright`` is imported lazily so article validation and API-only use do
    not require a browser installation.
    """

    BASE_URL = "https://mp.weixin.qq.com/"
    LOGIN_QR_SELECTORS = (
        "iframe#login_wx_iframe img.qrcode",
        "img.qrcode",
        "img[class*='qrcode']",
    )
    LOGGED_IN_SELECTORS = (
        ".new-creation__menu-content",
        "a.account_info",
        "span.avatar img",
    )
    SUCCESS_TEXT = re.compile(r"(?<!原创)(?:发布|发表)成功")
    PUBLISH_QR_SELECTORS = (
        ".dialog_wrp img[class*='qrcode']",
        "[role='dialog'] img[class*='qrcode']",
        "img[class*='qrcode']",
        "img[src*='qrcode']",
        ".dialog_wrp canvas",
        "[role='dialog'] canvas",
    )

    def __init__(
        self,
        profile_dir: Path,
        *,
        base_url: str = BASE_URL,
        headless: bool = False,
        scan_timeout: float = 120.0,
        poll_interval: float = 1.0,
        browser_type: str = "chromium",
        executable_path: Optional[str] = None,
    ) -> None:
        self.profile_dir = Path(profile_dir).expanduser().resolve()
        self.base_url = base_url
        self.headless = headless
        self.scan_timeout = scan_timeout
        self.poll_interval = poll_interval
        self.browser_type = browser_type
        self.executable_path = executable_path

    def _import_playwright(self) -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise PlaywrightUnavailable("请安装 playwright，并运行 playwright install chromium") from exc
        return sync_playwright

    @staticmethod
    def _visible(page: Any, selectors: Iterable[str]) -> Optional[Any]:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=500):
                    return locator
            except Exception:
                continue
        return None

    def _logged_in(self, page: Any) -> bool:
        return self._visible(page, self.LOGGED_IN_SELECTORS) is not None

    @staticmethod
    def _qr_locators(page: Any) -> list[Any]:
        locators = [page.locator(selector).first for selector in BrowserPublisher.LOGIN_QR_SELECTORS[1:]]
        try:
            locators.insert(0, page.frame_locator("iframe#login_wx_iframe").locator("img.qrcode").first)
        except Exception:
            pass
        return locators

    def _capture_qrcode(self, page: Any, output_dir: Path, name: str) -> Optional[str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        for locator in self._qr_locators(page):
            try:
                if locator.is_visible(timeout=500):
                    path = output_dir / name
                    locator.screenshot(path=str(path))
                    return str(path)
            except Exception:
                continue
        return None

    def _capture_publish_qrcode(self, page: Any, output_dir: Path) -> Optional[str]:
        """Capture a publish verification QR, including canvas-based dialogs."""
        output_dir.mkdir(parents=True, exist_ok=True)
        dialog = page.locator(".dialog_wrp, [role='dialog'], .weui-desktop-dialog").filter(has_text=re.compile("微信验证|扫码|二维码|发表|发布"))
        try:
            if dialog.first.is_visible(timeout=500):
                path = output_dir / "wechat_publish_qrcode.png"
                dialog.first.screenshot(path=str(path), animations="disabled")
                self._enlarge_qrcode(path)
                return str(path)
        except Exception:
            pass
        for selector in self.PUBLISH_QR_SELECTORS:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=500):
                    path = output_dir / "wechat_publish_qrcode.png"
                    locator.screenshot(path=str(path))
                    self._enlarge_qrcode(path)
                    return str(path)
            except Exception:
                continue
        for selector in (".dialog_wrp iframe", "[role='dialog'] iframe", ".weui-desktop-dialog iframe"):
            frame = page.locator(selector).first
            try:
                if frame.is_visible(timeout=500):
                    path = output_dir / "wechat_publish_qrcode.png"
                    frame.screenshot(path=str(path))
                    self._enlarge_qrcode(path)
                    return str(path)
            except Exception:
                continue
        return None

    @staticmethod
    def _enlarge_qrcode(path: Path) -> None:
        """Make a small browser-rendered QR easier for phone cameras to read."""
        try:
            from PIL import Image

            image = Image.open(path)
            width, height = image.size
            if max(width, height) < 400:
                image.resize((width * 4, height * 4), Image.Resampling.NEAREST).save(path)
        except Exception:
            # QR capture should not fail solely because optional image tooling
            # is unavailable; the original screenshot remains usable.
            return

    def _wait_for_login(self, page: Any, qrcode_path: Optional[str]) -> PublishResult | None:
        deadline = time.monotonic() + self.scan_timeout
        while time.monotonic() < deadline:
            if self._logged_in(page):
                return None
            body_text = page.locator("body").inner_text(timeout=1000)
            try:
                frame_text = page.frame_locator("iframe#login_wx_iframe").locator("body").inner_text(timeout=500)
                body_text = f"{body_text}\n{frame_text}"
            except Exception:
                pass
            if "二维码已过期" in body_text or "已过期" in body_text:
                return PublishResult(
                    PublishStatus.VERIFICATION_EXPIRED,
                    "browser",
                    "登录二维码已过期",
                    qrcode_path=qrcode_path,
                    error_code="login_qrcode_expired",
                )
            time.sleep(self.poll_interval)
        return PublishResult(
            PublishStatus.AWAITING_SCAN,
            "browser",
            "等待用户扫码登录超时，浏览器会话已保留",
            qrcode_path=qrcode_path,
            error_code="login_scan_timeout",
        )

    def _ensure_login(self, page: Any, output_dir: Path) -> Optional[PublishResult]:
        page.goto(self.base_url, wait_until="domcontentloaded")
        if self._logged_in(page):
            return None
        qrcode_path = None
        qr_deadline = time.monotonic() + 10
        while time.monotonic() < qr_deadline and not qrcode_path:
            qrcode_path = self._capture_qrcode(page, output_dir, "wechat_login_qrcode.png")
            if not qrcode_path:
                time.sleep(0.5)
        return self._wait_for_login(page, qrcode_path)

    def _fill_article(self, page: Any, article: Article) -> None:
        title = page.locator("div[name='title'] .ProseMirror[contenteditable='true']")
        if title.count() != 1:
            raise RuntimeError("未找到唯一的可见标题编辑器")
        title.wait_for(state="visible", timeout=15000)
        title.fill(article.title)

        editor = page.locator("div.mock-iframe .ProseMirror[contenteditable='true']")
        if editor.count() != 1:
            raise RuntimeError("未找到唯一的正文编辑器")
        editor.wait_for(state="visible", timeout=15000)
        editor.click()
        # Keep the data in the DOM as a stable fallback. The live editor may
        # rewrite this structure, so we also dispatch input/change events.
        editor.evaluate(
            """
            (node, html) => {
              node.innerHTML = html;
              node.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}));
              node.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """,
            render_browser_html(article),
        )

        if article.cover_image:
            self._fill_cover_from_body(page, article)

    def _fill_cover_from_body(self, page: Any, article: Article) -> None:
        """Upload the cover into the body, then select it as the cover.

        Current editor builds expose no direct local-file input in the cover
        menu. They do expose local upload from the image toolbar and then
        offer the uploaded body image through ``从正文选择``.
        """
        editor = page.locator("div.mock-iframe .ProseMirror[contenteditable='true']")
        before_images = page.locator("div.mock-iframe img.rich_pages").count()
        editor.click()
        page.get_by_text("图片", exact=True).first.click()
        image_input = page.locator("input[type='file']").first
        image_input.set_input_files(self._file_payload(article.cover_image))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if page.locator("div.mock-iframe img.rich_pages").count() > before_images:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("正文图片上传后未出现图片")

        cover_area = page.locator("#js_cover_area")
        if cover_area.count() != 1:
            raise RuntimeError("未找到封面区域")
        cover_label = cover_area.get_by_text("拖拽或选择封面", exact=True)
        if cover_label.count() == 1 and cover_label.is_visible(timeout=1000):
            cover_label.click()
        else:
            cover_area.locator(".select-cover__btn, .js_cover_btn_area:visible").first.click()
        page.wait_for_timeout(300)
        select_from_body = page.locator("a.js_selectCoverFromContent:visible").first
        if select_from_body.count() != 1:
            raise RuntimeError("未找到从正文选择封面入口")
        select_from_body.evaluate("node => node.click()")
        image_item = page.locator("li.appmsg_content_img_item").first
        image_item.wait_for(state="visible", timeout=10000)
        image_item.click()
        next_button = page.get_by_role("button", name="下一步", exact=True)
        next_button.click()
        page.get_by_role("button", name="确认", exact=True).click()
        preview = cover_area.locator(".js_cover_preview_new").first
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                style = preview.get_attribute("style") or ""
                if preview.is_visible(timeout=500) and "background-image: url(\"\")" not in style:
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("封面上传后未出现预览")

    @staticmethod
    def _file_payload(path: Path) -> dict[str, Any] | str:
        """Return a Playwright upload payload with a trustworthy MIME type."""
        raw = path.read_bytes()
        if raw.startswith(b"\xff\xd8\xff"):
            return {"name": f"{path.stem}.jpg", "mimeType": "image/jpeg", "buffer": raw}
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            return {"name": f"{path.stem}.png", "mimeType": "image/png", "buffer": raw}
        mime = guess_type(path.name)[0] or "application/octet-stream"
        return {"name": path.name, "mimeType": mime, "buffer": raw}

    def _click_text(self, page: Any, text: str) -> bool:
        candidates = [
            page.get_by_role("button", name=text, exact=True),
            page.get_by_text(text, exact=True),
        ]
        for locator in candidates:
            try:
                if locator.first.is_visible(timeout=800):
                    locator.first.click()
                    return True
            except Exception:
                continue
        return False

    def _click_publish_confirmation_once(self, page: Any) -> bool:
        """Click the green publish action in the final publish modal."""
        continue_publish = page.get_by_text("继续发表", exact=True)
        try:
            if continue_publish.count() > 0 and continue_publish.last.is_visible(timeout=500):
                continue_publish.last.click()
                return True
        except Exception:
            pass
        matching_buttons = []
        buttons = page.locator("button")
        for index in range(buttons.count() - 1, -1, -1):
            button = buttons.nth(index)
            try:
                if button.is_visible(timeout=200) and button.inner_text(timeout=200).strip() == "发表":
                    matching_buttons.append(button)
            except Exception:
                continue
        if len(matching_buttons) >= 2:
            try:
                matching_buttons[0].click()
                return True
            except Exception:
                pass
        primary_publish = page.locator("button.weui-desktop-btn_primary").filter(has_text="发表").last
        try:
            if primary_publish.count() == 1 and primary_publish.is_visible(timeout=500):
                primary_publish.click()
                return True
        except Exception:
            pass
        exact_publish = page.get_by_text("发表", exact=True)
        try:
            if exact_publish.count() > 1 and exact_publish.last.is_visible(timeout=500):
                exact_publish.last.click()
                return True
        except Exception:
            pass
        for selector in (".weui-desktop-dialog", ".weui-desktop-dialog__wrp", ".dialog_wrp", "[role='dialog']"):
            dialog = page.locator(selector).filter(has_text=re.compile("群发通知|分组通知|定时发表|发表"))
            try:
                if not dialog.first.is_visible(timeout=500):
                    continue
            except Exception:
                continue
            for locator in (
                dialog.first.get_by_role("button", name="发表", exact=True),
                dialog.first.get_by_text("发表", exact=True),
            ):
                try:
                    if locator.count() == 1 and locator.is_visible(timeout=500):
                        locator.click()
                        return True
                except Exception:
                    continue
        return False

    def _click_publish_confirmation(self, page: Any) -> bool:
        """Wait for and click the final publish modal's green action."""
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self._click_publish_confirmation_once(page):
                return True
            page.wait_for_timeout(300)
        return False

    def _open_article_editor(self, context: Any, page: Any) -> Any:
        """Open the new-creation article card and return its editor page."""
        menu = page.locator("div.new-creation__menu-item").filter(has_text="文章")
        count = menu.count()
        if count != 1:
            raise RuntimeError(f"文章入口不唯一或不存在: {count}")
        menu.click()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            pages = context.pages
            for candidate in reversed(pages):
                try:
                    if candidate.locator("textarea#title, input[placeholder*='标题']").count() == 1:
                        return candidate
                except Exception:
                    continue
            page.wait_for_timeout(500)
        return page

    def _wait_for_final_result(self, page: Any, qrcode_path: Optional[str]) -> PublishResult:
        deadline = time.monotonic() + self.scan_timeout
        observed_dialog = False
        grace_deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            body = page.locator("body").inner_text(timeout=1000)
            if "二维码已过期" in body or "验证已过期" in body:
                return PublishResult(
                    PublishStatus.VERIFICATION_EXPIRED,
                    "browser",
                    "发布验证二维码已过期",
                    qrcode_path=qrcode_path,
                    error_code="publish_qrcode_expired",
                )
            if any(self.SUCCESS_TEXT.search(line.strip()) for line in body.splitlines()):
                return PublishResult(PublishStatus.PUBLISHED, "browser", "文章发布成功", qrcode_path=qrcode_path)
            dialog = page.locator(".dialog_wrp, [role='dialog']").filter(has_text=re.compile("微信验证|发表|发布"))
            try:
                dialog_visible = dialog.first.is_visible(timeout=500)
                observed_dialog = observed_dialog or dialog_visible
                if observed_dialog and not dialog_visible and time.monotonic() > grace_deadline:
                    # A disappeared publish dialog without an explicit success
                    # banner is not proof of publication.
                    return PublishResult(
                        PublishStatus.UNKNOWN,
                        "browser",
                        "发表弹窗已关闭，但页面没有明确成功标志",
                        qrcode_path=qrcode_path,
                        error_code="publish_status_unconfirmed",
                    )
            except Exception:
                pass
            time.sleep(self.poll_interval)
        return PublishResult(
            PublishStatus.AWAITING_SCAN,
            "browser",
            "等待微信发布验证超时，请检查浏览器中的验证状态",
            qrcode_path=qrcode_path,
            error_code="publish_scan_timeout",
        )

    def publish(self, article: Article, *, confirm_publish: bool = False) -> PublishResult:
        if not confirm_publish and article.publish:
            return PublishResult(
                PublishStatus.FAILED,
                "browser",
                "发布文章必须显式传入 confirm_publish=True",
                error_code="confirmation_required",
            )
        sync_playwright = self._import_playwright()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        output_dir = self.profile_dir / "artifacts"
        with sync_playwright() as playwright:
            browser_launcher = getattr(playwright, self.browser_type, playwright.chromium)
            launch_options = {
                "user_data_dir": str(self.profile_dir),
                "headless": self.headless,
                "viewport": {"width": 1440, "height": 1000},
            }
            if self.executable_path:
                launch_options["executable_path"] = self.executable_path
            context = browser_launcher.launch_persistent_context(
                **launch_options,
            )
            page = context.pages[0] if context.pages else context.new_page()
            try:
                login_result = self._ensure_login(page, output_dir)
                if login_result:
                    return login_result
                page.goto(self.base_url, wait_until="domcontentloaded")
                try:
                    page = self._open_article_editor(context, page)
                except Exception as exc:
                    return PublishResult(PublishStatus.FAILED, "browser", f"未能打开文章入口: {exc}", error_code="article_menu_missing")
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                self._fill_article(page, article)
                if not article.publish:
                    return PublishResult(PublishStatus.DRAFT_CREATED, "browser", "文章已填写，未执行发布")
                if not self._click_text(page, "发表"):
                    return PublishResult(PublishStatus.FAILED, "browser", "未找到发表按钮", error_code="publish_button_missing")
                page.wait_for_timeout(800)
                clicked_confirmation = self._click_publish_confirmation(page)
                if not clicked_confirmation:
                    continue_button = page.get_by_role("button", name="继续发表", exact=True)
                    if continue_button.count() == 1 and continue_button.is_visible(timeout=500):
                        continue_button.click()
                        clicked_confirmation = True
                if not clicked_confirmation:
                    screenshot = output_dir / "wechat_publish_confirmation_missing.png"
                    try:
                        page.screenshot(path=str(screenshot), full_page=True)
                    except Exception:
                        screenshot = None
                    return PublishResult(
                        PublishStatus.FAILED,
                        "browser",
                        "未确认点击发表弹窗，已阻止生成无效验证二维码",
                        qrcode_path=str(screenshot) if screenshot else None,
                        error_code="publish_confirmation_missing",
                    )
                page.wait_for_timeout(1000)
                qrcode_path = None
                for candidate in reversed(context.pages):
                    qrcode_path = self._capture_publish_qrcode(candidate, output_dir)
                    if qrcode_path:
                        page = candidate
                        break
                return self._wait_for_final_result(page, qrcode_path)
            except Exception as exc:
                screenshot = output_dir / "wechat_publish_error.png"
                try:
                    page.screenshot(path=str(screenshot), full_page=True)
                except Exception:
                    screenshot = None
                return PublishResult(
                    PublishStatus.FAILED,
                    "browser",
                    f"浏览器发布失败: {exc}",
                    qrcode_path=str(screenshot) if screenshot else None,
                    error_code="browser_error",
                )
            finally:
                context.close()
