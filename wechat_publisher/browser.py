"""Playwright browser publisher with persistent login and real status checks."""

from __future__ import annotations

import re
import time
from pathlib import Path
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
    SUCCESS_TEXT = re.compile(r"发布成功|发表成功|保存成功")

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
            file_input = page.locator("input[type='file']").first
            try:
                file_input.set_input_files(str(article.cover_image))
            except Exception:
                # Some versions only expose the picker after clicking cover;
                # publish flow will surface a precise failure if no cover was set.
                pass

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
            if self.SUCCESS_TEXT.search(body):
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
                self._click_text(page, "发表")
                self._click_text(page, "继续发表")
                qrcode_path = self._capture_qrcode(page, output_dir, "wechat_publish_qrcode.png")
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
