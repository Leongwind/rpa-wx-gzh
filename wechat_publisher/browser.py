"""Playwright browser publisher with persistent login and real status checks."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from mimetypes import guess_type
from typing import Any, Iterable, Optional, Protocol

from .content import render_html
from .models import Article, PublishResult, PublishStatus, derive_digest, _asset_references
from .session import ProfileBusyError, ProfileLock, RunStore


class PlaywrightUnavailable(RuntimeError):
    pass


class BrowserDraftAdapter(Protocol):
    """Explicit test/automation seam for draft and asset operations."""

    def save_draft(self, page: Any) -> Optional[str]: ...
    def reopen_draft(self, context: Any, page: Any, draft_ref: str, title: str) -> Any: ...
    def upload_asset(self, page: Any, alias: str, path: Path) -> str: ...


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
        qr_ttl: float = 120.0,
        qr_refresh_limit: int = 1,
        browser_type: str = "chromium",
        executable_path: Optional[str] = None,
        adapter: Optional[BrowserDraftAdapter] = None,
    ) -> None:
        self.profile_dir = Path(profile_dir).expanduser().resolve()
        self.base_url = base_url
        self.headless = headless
        self.scan_timeout = scan_timeout
        self.poll_interval = poll_interval
        self.qr_ttl = qr_ttl
        self.qr_refresh_limit = max(0, int(qr_refresh_limit))
        self.browser_type = browser_type
        self.executable_path = executable_path
        self.adapter = adapter
        self._last_uploaded_urls: dict[str, str] = {}
        self._last_cover_url: Optional[str] = None

    def _import_playwright(self) -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise PlaywrightUnavailable("请安装 playwright，并运行 playwright install chromium") from exc
        return sync_playwright

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _chrome_executable(self) -> Optional[str]:
        if self.executable_path:
            return self.executable_path
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
        ]
        return next((path for path in candidates if path), None)

    def _connect_cdp_context(self, playwright: Any, run_id: str, store: RunStore) -> tuple[Any, Any]:
        """Connect to a profile-owned Chrome so later commands can reattach."""
        browser_type = playwright.chromium
        record = store.load(run_id)
        candidate_ports = [record.debug_port] if record.debug_port else [item.debug_port for item in store.active_records()]
        for candidate_port in candidate_ports:
            if not candidate_port:
                continue
            try:
                browser = browser_type.connect_over_cdp(f"http://127.0.0.1:{candidate_port}")
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                if record.debug_port != candidate_port:
                    store.update(run_id, debug_port=candidate_port)
                return browser, context
            except Exception:
                pass

        executable = self._chrome_executable()
        if not executable:
            raise PlaywrightUnavailable("未找到 Chrome/Edge，请设置 WX_PLAYWRIGHT_EXECUTABLE_PATH")
        port = self._free_port()
        args = [
            executable,
            f"--user-data-dir={self.profile_dir}",
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--window-size=1440,1000",
            self.base_url,
        ]
        if self.headless:
            args.insert(-1, "--headless=new")
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        store.update(run_id, debug_port=port)
        deadline = time.monotonic() + 15
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                browser = browser_type.connect_over_cdp(f"http://127.0.0.1:{port}")
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                return browser, context
            except Exception as exc:
                last_error = exc
                time.sleep(0.25)
        try:
            process.terminate()
        except Exception:
            pass
        raise RuntimeError(f"无法连接到持久化 Chrome 调试会话: {last_error}")

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

    def _restore_resource_refs(self, refs: dict[str, Any]) -> None:
        body = refs.get("body", {}) if isinstance(refs, dict) else {}
        self._last_uploaded_urls = dict(body) if isinstance(body, dict) else {}
        cover = refs.get("cover") if isinstance(refs, dict) else None
        self._last_cover_url = cover if isinstance(cover, str) else None

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

    @staticmethod
    def _qr_artifact(output_dir: Path, prefix: str, run_id: Optional[str], generation: int) -> Path:
        safe_run_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", run_id or "session")
        return output_dir / f"{prefix}_{safe_run_id}_{max(1, generation)}.png"

    def _capture_qrcode(
        self,
        page: Any,
        output_dir: Path,
        prefix: str,
        *,
        run_id: Optional[str] = None,
        generation: int = 1,
    ) -> Optional[str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        for locator in self._qr_locators(page):
            try:
                if locator.is_visible(timeout=500):
                    path = self._qr_artifact(output_dir, prefix, run_id, generation)
                    locator.screenshot(path=str(path))
                    return str(path)
            except Exception:
                continue
        return None

    def _capture_publish_qrcode(
        self,
        page: Any,
        output_dir: Path,
        *,
        run_id: Optional[str] = None,
        generation: int = 1,
    ) -> Optional[str]:
        """Capture a publish verification QR, including canvas-based dialogs."""
        output_dir.mkdir(parents=True, exist_ok=True)
        dialog = page.locator(".dialog_wrp, [role='dialog'], .weui-desktop-dialog").filter(has_text=re.compile("微信验证|扫码|二维码|安全验证|安全"))
        has_verification_dialog = False
        try:
            if dialog.first.is_visible(timeout=500):
                has_verification_dialog = True
                path = self._qr_artifact(output_dir, "wechat_publish_qrcode", run_id, generation)
                dialog.first.screenshot(path=str(path), animations="disabled")
                self._enlarge_qrcode(path)
                return str(path)
        except Exception:
            pass
        if not has_verification_dialog:
            try:
                body = page.locator("body").inner_text(timeout=500)
                if not re.search(r"微信验证|扫码验证|二维码验证|请使用微信扫码", body):
                    return None
            except Exception:
                return None
        for selector in self.PUBLISH_QR_SELECTORS:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=500):
                    path = self._qr_artifact(output_dir, "wechat_publish_qrcode", run_id, generation)
                    locator.screenshot(path=str(path))
                    self._enlarge_qrcode(path)
                    return str(path)
            except Exception:
                continue
        for selector in (".dialog_wrp iframe", "[role='dialog'] iframe", ".weui-desktop-dialog iframe"):
            frame = page.locator(selector).first
            try:
                if frame.is_visible(timeout=500):
                    path = self._qr_artifact(output_dir, "wechat_publish_qrcode", run_id, generation)
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

    @staticmethod
    def _scan_stage(body: str, *, default: str = "publish_verification") -> str:
        if re.search(r"管理员.*(?:验证|确认)|等待管理员|管理员微信", body):
            return "admin_approval"
        if re.search(r"微信验证|扫码验证|二维码验证|请使用微信扫码", body):
            return "publish_verification"
        return default

    @staticmethod
    def _next_action(stage: str) -> str:
        return {
            "login": "请使用运营者微信扫码登录",
            "publish_verification": "请使用微信扫码验证发布",
            "admin_approval": "请等待管理员微信确认",
        }.get(stage, "请查看当前 Chrome 验证窗口")

    def _scan_result(
        self,
        message: str,
        *,
        stage: str,
        qrcode_path: Optional[str],
        run_id: Optional[str],
        generation: int = 1,
        expires_at: Optional[float] = None,
        error_code: Optional[str] = "publish_scan_timeout",
    ) -> PublishResult:
        return PublishResult(
            PublishStatus.AWAITING_SCAN,
            "browser",
            message,
            qrcode_path=qrcode_path,
            error_code=error_code,
            run_id=run_id,
            stage=stage,
            expires_at=expires_at,
            generation=generation,
            next_action=self._next_action(stage),
        )

    def _wait_for_login(
        self,
        page: Any,
        qrcode_path: Optional[str],
        *,
        run_id: Optional[str] = None,
        generation: int = 1,
        expires_at: Optional[float] = None,
    ) -> PublishResult | None:
        deadline = time.monotonic() + self.scan_timeout
        while time.monotonic() < deadline:
            if self._logged_in(page):
                return None
            body_text = self._body_text(page)
            if not body_text:
                time.sleep(self.poll_interval)
                continue
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
                    run_id=run_id,
                    stage="login",
                    expires_at=expires_at,
                    generation=generation,
                    next_action="请重新生成登录二维码",
                )
            time.sleep(self.poll_interval)
        return self._scan_result(
            "等待用户扫码登录超时，浏览器会话已保留",
            stage="login",
            qrcode_path=qrcode_path,
            run_id=run_id,
            generation=generation,
            expires_at=expires_at,
            error_code="login_scan_timeout",
        )

    def _ensure_login(
        self,
        page: Any,
        output_dir: Path,
        *,
        run_id: Optional[str] = None,
    ) -> Optional[PublishResult]:
        page.goto(self.base_url, wait_until="domcontentloaded")
        if self._logged_in(page):
            return None
        qrcode_path = None
        generation = 1
        qr_deadline = time.monotonic() + 10
        while time.monotonic() < qr_deadline and not qrcode_path:
            qrcode_path = self._capture_qrcode(
                page,
                output_dir,
                "wechat_login_qrcode",
                run_id=run_id,
                generation=generation,
            )
            if not qrcode_path:
                time.sleep(0.5)
        expires_at = time.time() + self.qr_ttl if qrcode_path else None
        if run_id and qrcode_path:
            return self._scan_result(
                "请使用运营者微信扫描登录二维码",
                stage="login",
                qrcode_path=qrcode_path,
                run_id=run_id,
                generation=generation,
                expires_at=expires_at,
                error_code="login_scan_pending",
            )
        return self._wait_for_login(
            page,
            qrcode_path,
            run_id=run_id,
            generation=generation,
            expires_at=expires_at,
        )

    def _fill_article(self, page: Any, article: Article) -> Optional[str]:
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
        image_urls = self.upload_body_assets(page, article)
        editor.evaluate(
            """
            (node, html) => {
              node.innerHTML = html;
              node.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}));
              node.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """,
            render_html(article, image_urls),
        )
        digest = page.locator("[data-article-digest], input[placeholder*='摘要'], textarea[placeholder*='摘要']")
        if digest.count() != 1:
            raise RuntimeError("未找到唯一的摘要控件")
        digest = digest.first
        if not digest.is_visible(timeout=500):
            raise RuntimeError("摘要控件不可见")
        digest.fill(article.digest)
        if digest.input_value(timeout=500) != article.digest:
            raise RuntimeError("摘要写入结果无法确认")
        if article.cover_image:
            self._fill_cover_from_body(page, article)
        if not article.publish:
            draft_ref = self._save_draft_and_wait(page)
            if not draft_ref:
                raise RuntimeError("未观察到草稿保存完成信号")
            return str(draft_ref)
        return None

    def _save_draft_and_wait(self, page: Any) -> Optional[str]:
        if self.adapter is not None:
            result = self.adapter.save_draft(page)
            return str(result) if result else None
        buttons = page.get_by_text("保存", exact=True)
        if buttons.count() == 0:
            buttons = page.get_by_text("存为草稿", exact=True)
        if buttons.count() == 0:
            return None
        try:
            buttons.last.click()
            for text in ("保存成功", "草稿已保存", "已保存"):
                if self._has_visible_text(page, text):
                    return "observed"
        except Exception:
            return None
        return None

    def _reopen_and_verify_draft(self, page: Any, context: Any, draft_ref: str, article: Article) -> bool:
        """Leave the editor and reopen the saved draft through a testable seam."""
        if self.adapter is not None:
            reopened = self.adapter.reopen_draft(context, page, draft_ref, article.title)
        else:
            try:
                if hasattr(page, "close"):
                    page.close()
                listing_page = context.new_page() if hasattr(context, "new_page") else page
                reopened = self._open_saved_draft_editor(context, listing_page, article.title)
            except (RuntimeError, TimeoutError):
                return False
        if reopened is None:
            return False
        return self._verify_editor_content(reopened, article)

    def upload_body_assets(self, page: Any, article: Article) -> dict[str, str]:
        """Upload referenced local images through the editor seam.

        The live adapter may replace this seam with the editor's file input.
        The deterministic fallback is intentionally a hosted mock URL, never
        a ``file://`` URL, so local fixtures exercise the same boundary.
        """
        referenced = _asset_references(article.body)
        uploaded = {}
        seen_urls = set()
        for asset in article.assets:
            if asset.alias not in referenced:
                continue
            url = None
            # Test seam and supported editor seam: the fixture can expose a
            # deterministic upload callback, while production uses the file
            # input exposed by the editor.
            if self.adapter is not None:
                url = self.adapter.upload_asset(page, asset.alias, asset.path)
            else:
                inputs = page.locator("input[type='file'][accept*='image'], input[type='file']")
                if inputs.count() == 0:
                    raise RuntimeError(f"正文图片上传控件不存在: {asset.alias}")
                before = {
                    page.locator("img").nth(i).get_attribute("src")
                    for i in range(page.locator("img").count())
                }
                inputs.first.set_input_files(str(asset.path))
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    images = page.locator("img")
                    for index in range(images.count() - 1, -1, -1):
                        candidate = images.nth(index).get_attribute("src")
                        if candidate and candidate not in before and candidate not in seen_urls and not candidate.startswith(("file:", "https://wechat.local")):
                            url = candidate; break
                    if url: break
                    page.wait_for_timeout(100)
            if not isinstance(url, str) or not url.startswith(("https://", "http://")) or "wechat.local" in url or url.startswith("file:"):
                raise RuntimeError(f"正文图片未获得微信托管 URL: {asset.alias}")
            if url in seen_urls:
                raise RuntimeError(f"正文图片 URL 映射重复: {asset.alias}")
            seen_urls.add(url)
            uploaded[asset.alias] = url
        self._last_uploaded_urls = dict(uploaded)
        return uploaded

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
        images = page.locator("div.mock-iframe img.rich_pages")
        if images.count() > before_images:
            self._last_cover_url = images.nth(images.count() - 1).get_attribute("src")
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
        self._select_body_cover_in_dialog(page)
        preview = cover_area.locator(".js_cover_preview_new").first
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                style = preview.get_attribute("style") or ""
                has_image = bool(re.search(r"background-image\s*:\s*url\((?![\"']?\s*[\"']?\))", style))
                if preview.is_visible(timeout=500) and has_image:
                    self._remove_temporary_cover_image(page, before_images)
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("封面上传后未出现预览")

    @staticmethod
    def _remove_temporary_cover_image(page: Any, before_images: int) -> None:
        """Remove the body image used only to populate the cover picker."""
        images = page.locator("div.mock-iframe img.rich_pages")
        if images.count() <= before_images:
            return
        temporary = images.last
        temporary.evaluate(
            """
            node => {
              const paragraph = node.closest('p');
              if (paragraph && paragraph.querySelectorAll('img').length === 1) {
                paragraph.remove();
              } else {
                node.remove();
              }
            }
            """
        )
        editor = page.locator("div.mock-iframe .ProseMirror[contenteditable='true']").first
        if editor.count():
            editor.dispatch_event("input", {"inputType": "deleteContentBackward"})

    def _select_body_cover_in_dialog(self, page: Any) -> None:
        """Select the image itself and advance through the cover dialogs.

        WeChat renders the selectable click target inside the list item. A
        click on ``li.appmsg_content_img_item`` does not select the image and
        leaves the next action visually disabled.
        """
        items = page.locator("li.appmsg_content_img_item")
        selected_item = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and selected_item is None:
            for index in range(items.count() - 1, -1, -1):
                candidate = items.nth(index)
                try:
                    if candidate.is_visible(timeout=200):
                        selected_item = candidate
                        break
                except Exception:
                    continue
            if selected_item is None:
                page.wait_for_timeout(200)
        if selected_item is None:
            raise RuntimeError("从正文选择封面时未找到可用图片")

        image_target = selected_item.locator(".appmsg_content_img.cover").first
        if image_target.count() == 0:
            image_target = selected_item
        # Keep this step idempotent so a recovery/resume does not toggle an
        # already selected cover back to the unselected state.
        if "selected" not in (selected_item.get_attribute("class") or "").split():
            image_target.click(force=True)

        if not self._click_enabled_dialog_button(page, "下一步", timeout=5):
            raise RuntimeError("封面图片未被选中，“下一步”仍不可用")
        if not self._click_enabled_dialog_button(page, "确认", timeout=10):
            raise RuntimeError("封面裁剪弹窗未出现可用的“确认”按钮")

    @staticmethod
    def _click_enabled_dialog_button(page: Any, name: str, *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            buttons = page.get_by_role("button", name=name, exact=True)
            for index in range(buttons.count() - 1, -1, -1):
                button = buttons.nth(index)
                try:
                    class_name = button.get_attribute("class") or ""
                    disabled = button.get_attribute("disabled") is not None or "disabled" in class_name
                    if button.is_visible(timeout=200) and button.is_enabled() and not disabled:
                        button.click(force=True)
                        return True
                except Exception:
                    continue
            page.wait_for_timeout(200)
        return False

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
        dialogs = page.locator(".weui-desktop-dialog, .weui-desktop-dialog__wrp, .dialog_wrp, [role='dialog']")
        for index in range(dialogs.count() - 1, -1, -1):
            dialog = dialogs.nth(index)
            try:
                if not dialog.is_visible(timeout=200):
                    continue
            except Exception:
                continue
            if not self._disable_group_notification(dialog):
                continue
            buttons_in_dialog = dialog.get_by_role("button", name="发表", exact=True)
            for button_index in range(buttons_in_dialog.count() - 1, -1, -1):
                button = buttons_in_dialog.nth(button_index)
                try:
                    if button.is_visible(timeout=200):
                        button.click(force=True)
                        return True
                except Exception:
                    continue

        return False

    @staticmethod
    def _disable_group_notification(dialog: Any) -> bool:
        """Force the one-per-day group notification switch off before publish."""
        setting = dialog.locator(".mass_send__notify").first
        try:
            if setting.count() == 0:
                return False
            switch = setting.locator("input.weui-desktop-switch__input").first
            if switch.count() != 1 or not switch.is_visible(timeout=200):
                return False
            checked = switch.is_checked()
            if not isinstance(checked, bool):
                return False
            if not checked:
                return True
            # The native input is visually hidden. A DOM click still runs the
            # Vue change handler and avoids Playwright viewport failures.
            switch.evaluate("node => node.click()")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if not switch.is_checked():
                    return True
                time.sleep(0.1)
            return False
        except Exception:
            return False

    def _click_publish_confirmation(self, page: Any) -> bool:
        """Wait for and click the final publish modal's green action."""
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self._click_publish_confirmation_once(page):
                return True
            page.wait_for_timeout(300)
        return False

    def _click_continue_publish(self, page: Any) -> bool:
        """Wait for and click the group-notification continuation action."""
        if not self._notification_guard(page):
            return False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            buttons = page.locator("button")
            for index in range(buttons.count() - 1, -1, -1):
                button = buttons.nth(index)
                try:
                    if button.inner_text(timeout=200).strip() == "继续发表" and button.is_visible(timeout=200):
                        button.click(force=True)
                        return True
                except Exception:
                    continue
            continue_publish = page.get_by_text("继续发表", exact=True)
            for index in range(continue_publish.count() - 1, -1, -1):
                candidate = continue_publish.nth(index)
                try:
                    if candidate.is_visible(timeout=200):
                        candidate.evaluate("node => node.click()")
                        return True
                except Exception:
                    continue
            page.wait_for_timeout(300)
        return False

    def _notification_guard(self, page: Any) -> bool:
        dialogs = page.locator(".weui-desktop-dialog, .weui-desktop-dialog__wrp, .dialog_wrp, [role='dialog']")
        for index in range(dialogs.count() - 1, -1, -1):
            dialog = dialogs.nth(index)
            try:
                if dialog.is_visible(timeout=200) and self._disable_group_notification(dialog):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _has_visible_text(page: Any, text: str) -> bool:
        locator = page.get_by_text(text, exact=True)
        for index in range(locator.count()):
            try:
                if locator.nth(index).is_visible(timeout=200):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _body_text(page: Any, *, timeout: int = 1000) -> str:
        """Read page text without failing a run during a transient navigation."""
        try:
            return page.locator("body").inner_text(timeout=timeout)
        except Exception:
            return ""

    @staticmethod
    def _published_article_after(page: Any, title: str, after: float) -> bool:
        """Confirm that the recent-publish list contains this run's article."""
        titles = page.locator("a.weui-desktop-mass-appmsg__title")
        for index in range(titles.count()):
            candidate = titles.nth(index)
            try:
                if candidate.inner_text(timeout=200).strip() != title:
                    continue
                card = candidate.locator(
                    "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), "
                    "' weui-desktop-mass-appmsg ')][1]"
                )
                links = card.locator("a[href*='send_time=']")
                for link_index in range(links.count()):
                    href = links.nth(link_index).get_attribute("href") or ""
                    match = re.search(r"(?:[?&])send_time=(\d+)", href)
                    if match and float(match.group(1)) >= after:
                        return True
            except Exception:
                continue
        return False

    def _wait_for_publish_qrcode(
        self,
        context: Any,
        page: Any,
        output_dir: Path,
        *,
        run_id: Optional[str] = None,
        generation: int = 1,
    ) -> tuple[Any, Optional[str]]:
        """Wait until the post-confirmation verification UI actually exists."""
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for candidate in reversed(context.pages):
                qrcode_path = self._capture_publish_qrcode(
                    candidate,
                    output_dir,
                    run_id=run_id,
                    generation=generation,
                )
                if qrcode_path:
                    return candidate, qrcode_path
            page.wait_for_timeout(300)
        return page, None

    def _refresh_publish_qrcode(
        self,
        context: Any,
        page: Any,
        output_dir: Path,
        *,
        run_id: str,
        generation: int,
    ) -> tuple[Any, Optional[str]]:
        """Refresh only the current verification challenge after expiry."""
        refresh_texts = ("重新获取二维码", "刷新二维码", "重新生成二维码")
        for text in refresh_texts:
            candidates = [
                page.get_by_role("button", name=text, exact=True),
                page.get_by_text(text, exact=True),
            ]
            for locator in candidates:
                for index in range(locator.count() - 1, -1, -1):
                    candidate = locator.nth(index)
                    try:
                        if candidate.is_visible(timeout=300):
                            candidate.click(force=True)
                            return self._wait_for_publish_qrcode(
                                context,
                                page,
                                output_dir,
                                run_id=run_id,
                                generation=generation + 1,
                            )
                    except Exception:
                        continue
        return page, None

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

    def _open_saved_draft_editor(self, context: Any, page: Any, title: str) -> Any:
        """Open the newest visible draft matching the saved article title."""
        page.goto(self.base_url, wait_until="domcontentloaded")
        all_drafts = page.get_by_role("button", name="全部草稿", exact=True)
        if all_drafts.count() and all_drafts.first.is_visible(timeout=1000):
            all_drafts.first.click()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            candidates = page.get_by_text(title, exact=True)
            for index in range(candidates.count() - 1, -1, -1):
                candidate = candidates.nth(index)
                try:
                    if candidate.is_visible(timeout=200):
                        candidate.click(force=True)
                        page.wait_for_timeout(800)
                        for editor_page in reversed(context.pages):
                            if editor_page.locator("textarea#title, input[placeholder*='标题'], div[name='title']").count():
                                return editor_page
                except Exception:
                    continue
            page.wait_for_timeout(300)
        raise RuntimeError(f"未找到标题为 {title!r} 的可恢复草稿")

    def _wait_for_final_result(
        self,
        page: Any,
        qrcode_path: Optional[str],
        *,
        context: Any = None,
        store: Optional[RunStore] = None,
        run_id: Optional[str] = None,
        generation: int = 1,
        expires_at: Optional[float] = None,
        output_dir: Optional[Path] = None,
    ) -> PublishResult:
        deadline = time.monotonic() + self.scan_timeout
        observed_dialog = False
        grace_deadline = time.monotonic() + 10
        current_stage = "publish_verification"
        refresh_count = max(0, generation - 1)
        last_recorded_stage: Optional[str] = None
        article_title: Optional[str] = None
        run_started_at = 0.0
        if store and run_id:
            try:
                record = store.load(run_id)
                article_title = record.article_title
                run_started_at = record.created_at
            except (KeyError, ValueError):
                pass
        while time.monotonic() < deadline:
            body = self._body_text(page)
            if not body:
                time.sleep(self.poll_interval)
                continue
            current_stage = self._scan_stage(body)
            if store and run_id and current_stage != last_recorded_stage:
                store.update(
                    run_id,
                    status=PublishStatus.AWAITING_SCAN.value,
                    stage=current_stage,
                    qrcode_path=qrcode_path,
                    expires_at=expires_at,
                    generation=generation,
                    next_action=self._next_action(current_stage),
                    message=self._next_action(current_stage),
                )
                last_recorded_stage = current_stage
            if "二维码已过期" in body or "验证已过期" in body:
                if (
                    context is not None
                    and store is not None
                    and run_id
                    and output_dir is not None
                    and refresh_count < self.qr_refresh_limit
                ):
                    refreshed_page, refreshed_qrcode = self._refresh_publish_qrcode(
                        context,
                        page,
                        output_dir,
                        run_id=run_id,
                        generation=generation,
                    )
                    if refreshed_qrcode:
                        page = refreshed_page
                        qrcode_path = refreshed_qrcode
                        generation += 1
                        refresh_count += 1
                        expires_at = time.time() + self.qr_ttl
                        store.update(
                            run_id,
                            status=PublishStatus.AWAITING_SCAN.value,
                            stage="publish_verification",
                            qrcode_path=qrcode_path,
                            expires_at=expires_at,
                            generation=generation,
                            next_action=self._next_action("publish_verification"),
                            message="二维码已刷新，请使用微信扫码验证发布",
                        )
                        continue
                return PublishResult(
                    PublishStatus.VERIFICATION_EXPIRED,
                    "browser",
                    "发布验证二维码已过期",
                    qrcode_path=qrcode_path,
                    error_code="publish_qrcode_expired",
                    run_id=run_id,
                    stage=current_stage,
                    expires_at=expires_at,
                    generation=generation,
                    next_action="请重新执行验证，不会重新提交文章",
                )
            if any(self.SUCCESS_TEXT.search(line.strip()) for line in body.splitlines()):
                return PublishResult(
                    PublishStatus.PUBLISHED,
                    "browser",
                    "文章发布成功",
                    qrcode_path=qrcode_path,
                    run_id=run_id,
                    stage=current_stage,
                    generation=generation,
                )
            if article_title and self._published_article_after(page, article_title, run_started_at):
                return PublishResult(
                    PublishStatus.PUBLISHED,
                    "browser",
                    "文章已出现在公众号近期发表记录中",
                    qrcode_path=qrcode_path,
                    run_id=run_id,
                    stage=current_stage,
                    generation=generation,
                )
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
                        run_id=run_id,
                        stage=current_stage,
                        expires_at=expires_at,
                        generation=generation,
                        next_action="请在公众号后台确认文章状态，不要重复发布",
                    )
            except Exception:
                pass
            time.sleep(self.poll_interval)
        return self._scan_result(
            "等待微信发布验证超时，请检查浏览器中的验证状态",
            stage=current_stage,
            qrcode_path=qrcode_path,
            run_id=run_id,
            generation=generation,
            expires_at=expires_at,
            error_code="publish_scan_timeout",
        )

    @staticmethod
    def _process_alive(pid: Optional[int]) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    @staticmethod
    def _result_from_record(record: Any) -> Optional[PublishResult]:
        if not record.result:
            return None
        payload = record.result
        try:
            status = PublishStatus(payload["status"])
        except (KeyError, ValueError):
            return None
        return PublishResult(
            status,
            str(payload.get("provider", "browser")),
            str(payload.get("message", "")),
            qrcode_path=payload.get("qrcode_path"),
            draft_id=payload.get("draft_id"),
            publish_id=payload.get("publish_id"),
            article_id=payload.get("article_id"),
            error_code=payload.get("error_code"),
            run_id=payload.get("run_id", record.run_id),
            stage=payload.get("stage", record.stage),
            expires_at=payload.get("expires_at", record.expires_at),
            generation=payload.get("generation", record.generation),
            next_action=payload.get("next_action", record.next_action),
            metadata=payload.get("metadata", {}),
        )

    def _start_watcher(self, run_id: str) -> Optional[int]:
        """Start one detached watcher without creating a second publish action."""
        store = RunStore(self.profile_dir)
        record = store.load(run_id)
        if record.watcher_pid and self._process_alive(record.watcher_pid):
            return record.watcher_pid
        command = [sys.executable, "-m", "wechat_publisher", "_watch", "--run-id", run_id]
        process = subprocess.Popen(
            command,
            cwd=str(Path(__file__).resolve().parents[1]),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        store.update(
            run_id,
            watcher_pid=process.pid,
            watcher_status="running",
            monitor_until=time.time() + self.scan_timeout,
        )
        return process.pid

    def watch(self, run_id: str) -> PublishResult:
        try:
            with ProfileLock(self.profile_dir, timeout=max(15.0, self.poll_interval * 10)):
                return self._watch_unlocked(run_id)
        except ProfileBusyError as exc:
            return PublishResult(
                PublishStatus.FAILED,
                "browser",
                str(exc),
                error_code="profile_busy",
                run_id=run_id,
            )

    def _watch_unlocked(self, run_id: str) -> PublishResult:
        """Monitor login or publish verification without submitting again."""
        store = RunStore(self.profile_dir)
        try:
            record = store.load(run_id)
        except (KeyError, ValueError) as exc:
            return PublishResult(PublishStatus.FAILED, "browser", str(exc), error_code="run_not_found", run_id=run_id)
        own_pid = os.getpid()
        if record.watcher_pid and record.watcher_pid != own_pid and self._process_alive(record.watcher_pid):
            return self._result_from_record(record) or self._scan_result(
                "后台 watcher 正在监测扫码状态",
                stage=record.stage or "publish_verification",
                qrcode_path=record.qrcode_path,
                run_id=run_id,
                generation=record.generation or 1,
                expires_at=record.expires_at,
            )
        store.update(
            run_id,
            watcher_pid=own_pid,
            watcher_status="running",
            monitor_until=record.monitor_until or time.time() + self.scan_timeout,
        )
        result: Optional[PublishResult] = None
        browser = None
        try:
            sync_playwright = self._import_playwright()
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{record.debug_port}")
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[-1] if context.pages else context.new_page()
                output_dir = self.profile_dir / "artifacts"
                deadline = record.monitor_until or time.time() + self.scan_timeout

                if record.stage == "login":
                    while time.time() < deadline:
                        if self._logged_in(page):
                            article = store.load_article(run_id)
                            store.update(run_id, watcher_pid=None, watcher_status="not_started")
                            return self._publish_unlocked(article, confirm_publish=article.publish, run_id=run_id)
                        body = self._body_text(page)
                        if not body:
                            time.sleep(self.poll_interval)
                            continue
                        if "二维码已过期" in body or "已过期" in body:
                            result = PublishResult(
                                PublishStatus.VERIFICATION_EXPIRED,
                                "browser",
                                "登录二维码已过期，请重新生成登录二维码",
                                qrcode_path=record.qrcode_path,
                                error_code="login_qrcode_expired",
                                run_id=run_id,
                                stage="login",
                                expires_at=record.expires_at,
                                generation=record.generation,
                                next_action="请重新执行登录",
                            )
                            break
                        time.sleep(self.poll_interval)
                    if result is None:
                        result = self._scan_result(
                            "等待用户扫码登录超时，浏览器会话已保留",
                            stage="login",
                            qrcode_path=record.qrcode_path,
                            run_id=run_id,
                            generation=record.generation or 1,
                            expires_at=record.expires_at,
                            error_code="login_scan_timeout",
                        )
                else:
                    if self._has_visible_text(page, "继续发表"):
                        if not self._click_continue_publish(page):
                            result = PublishResult(
                                PublishStatus.FAILED,
                                "browser",
                                "继续发表弹窗未能确认，未生成验证二维码",
                                error_code="continue_publish_stuck",
                                run_id=run_id,
                            )
                        else:
                            page.wait_for_timeout(1000)
                    if result is None:
                        result_page, qrcode_path = self._wait_for_publish_qrcode(
                            context,
                            page,
                            output_dir,
                            run_id=run_id,
                            generation=record.generation or 1,
                        )
                        page = result_page
                        qrcode_path = qrcode_path or record.qrcode_path
                        result = self._wait_for_final_result(
                            page,
                            qrcode_path,
                            context=context,
                            store=store,
                            run_id=run_id,
                            generation=record.generation or 1,
                            expires_at=record.expires_at,
                            output_dir=output_dir,
                        )
                result = replace(result, run_id=run_id)
                store.save_result(run_id, result)
                if result.status is PublishStatus.PUBLISHED:
                    try:
                        browser.close()
                    except Exception:
                        pass
                return result
        except Exception as exc:
            result = PublishResult(
                PublishStatus.FAILED,
                "browser",
                f"后台扫码监测失败: {exc}",
                error_code="watcher_error",
                run_id=run_id,
            )
            try:
                if store.load(run_id).status != "cancelled":
                    store.save_result(run_id, result)
            except (KeyError, ValueError):
                pass
            return result
        finally:
            try:
                current = store.load(run_id)
                if current.watcher_pid == own_pid:
                    store.update(run_id, watcher_pid=None, watcher_status="stopped")
            except (KeyError, ValueError):
                pass

    def resume(self, run_id: str) -> PublishResult:
        """Reattach to a timed-out verification window and continue monitoring."""
        store = RunStore(self.profile_dir)
        try:
            record = store.load(run_id)
        except (KeyError, ValueError) as exc:
            return PublishResult(PublishStatus.FAILED, "browser", str(exc), error_code="run_not_found", run_id=run_id)
        if record.status in {PublishStatus.PUBLISHED.value, PublishStatus.DRAFT_CREATED.value, "cancelled"}:
            return self._result_from_record(record) or PublishResult(
                PublishStatus.FAILED,
                "browser",
                f"run 已结束: {record.status}",
                error_code="run_already_finished",
                run_id=run_id,
            )
        if not record.debug_port:
            return PublishResult(
                PublishStatus.FAILED,
                "browser",
                "run 没有可恢复的浏览器调试会话，请重新执行 publish",
                error_code="session_not_available",
                run_id=run_id,
            )
        if record.watcher_pid and self._process_alive(record.watcher_pid) and record.watcher_pid != os.getpid():
            return self._result_from_record(record) or self._scan_result(
                "后台 watcher 正在监测扫码状态",
                stage=record.stage or "publish_verification",
                qrcode_path=record.qrcode_path,
                run_id=run_id,
                generation=record.generation or 1,
                expires_at=record.expires_at,
            )
        store.update(run_id, watcher_pid=os.getpid(), watcher_status="running", monitor_until=time.time() + self.scan_timeout)
        return self.watch(run_id)

    def cancel(self, run_id: str) -> dict[str, Any]:
        """Close a profile-owned Chrome session and mark the run cancelled."""
        store = RunStore(self.profile_dir)
        record = store.load(run_id)
        if record.watcher_pid and record.watcher_pid != os.getpid() and self._process_alive(record.watcher_pid):
            try:
                os.kill(record.watcher_pid, 15)
            except OSError:
                pass
        if record.debug_port:
            sync_playwright = self._import_playwright()
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{record.debug_port}")
                    browser.close()
                except Exception:
                    pass
        return store.update(
            run_id,
            status="cancelled",
            watcher_pid=None,
            watcher_status="stopped",
            message="已取消浏览器发布会话",
        ).to_dict()

    def publish(self, article: Article, *, confirm_publish: bool = False, run_id: Optional[str] = None) -> PublishResult:
        try:
            with ProfileLock(self.profile_dir, timeout=15.0) as lock:
                return self._publish_unlocked(article, confirm_publish=confirm_publish, run_id=run_id, lock=lock)
        except ProfileBusyError as exc:
            return PublishResult(
                PublishStatus.FAILED,
                "browser",
                str(exc),
                error_code="profile_busy",
                run_id=run_id,
            )

    def publish_existing(self, run_id: str, *, confirm_publish: bool = False) -> PublishResult:
        """Reopen a saved browser draft and publish it with a fresh session."""
        try:
            with ProfileLock(self.profile_dir, timeout=15.0) as lock:
                return self._publish_existing_unlocked(run_id, confirm_publish=confirm_publish, lock=lock)
        except ProfileBusyError as exc:
            return PublishResult(PublishStatus.FAILED, "browser", str(exc), error_code="profile_busy", run_id=run_id)

    def _publish_existing_unlocked(self, run_id: str, *, confirm_publish: bool, lock: Optional[ProfileLock] = None) -> PublishResult:
        store = RunStore(self.profile_dir)
        try:
            record = store.load(run_id)
            article = store.load_article(run_id)
        except (KeyError, ValueError) as exc:
            return PublishResult(PublishStatus.FAILED, "browser", str(exc), error_code="run_not_found", run_id=run_id)
        if record.status != PublishStatus.DRAFT_CREATED.value:
            return PublishResult(
                PublishStatus.FAILED,
                "browser",
                f"只有 draft_created 会话可以重新发布，当前状态为 {record.status}",
                error_code="run_not_publishable",
                run_id=run_id,
            )
        self._restore_resource_refs(record.resource_refs)
        if not confirm_publish:
            return PublishResult(
                PublishStatus.FAILED,
                "browser",
                "发布草稿必须显式传入 confirm_publish=True",
                error_code="confirmation_required",
                run_id=run_id,
            )
        sync_playwright = self._import_playwright()
        output_dir = self.profile_dir / "artifacts"
        last_result: Optional[PublishResult] = None
        with sync_playwright() as playwright:
            browser, context = self._connect_cdp_context(playwright, run_id, store)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                login_result = self._ensure_login(page, output_dir, run_id=run_id)
                if login_result:
                    result = replace(login_result, run_id=run_id)
                    store.save_result(run_id, result)
                    last_result = result
                    if result.status is PublishStatus.AWAITING_SCAN:
                        self._start_watcher(run_id)
                    return result
                page = self._open_saved_draft_editor(context, page, article.title)
                if not self._verify_editor_content(page, article):
                    return PublishResult(
                        PublishStatus.FAILED,
                        "browser",
                        "恢复的草稿内容与运行快照不一致，已停止发布",
                        error_code="content_verification_failed",
                        run_id=run_id,
                    )
                store.transition(run_id, ("draft_created",), "submitting", lock=lock, submit_started_at=time.time())
                result = self._submit_current_editor(context, page, output_dir, run_id=run_id)
                result = replace(result, run_id=run_id, metadata={**result.metadata, "confirmation_summary": article.confirmation_summary()})
                store.save_result(run_id, result)
                last_result = result
                if result.status is PublishStatus.AWAITING_SCAN:
                    self._start_watcher(run_id)
                return result
            except Exception as exc:
                result = PublishResult(PublishStatus.FAILED, "browser", f"恢复草稿发布失败: {exc}", error_code="browser_error", run_id=run_id)
                store.save_result(run_id, result)
                last_result = result
                return result
            finally:
                if last_result and last_result.status not in {
                    PublishStatus.AWAITING_SCAN,
                    PublishStatus.UNKNOWN,
                    PublishStatus.VERIFICATION_EXPIRED,
                }:
                    try:
                        browser.close()
                    except Exception:
                        pass

    def _submit_current_editor(
        self,
        context: Any,
        page: Any,
        output_dir: Path,
        *,
        run_id: Optional[str] = None,
    ) -> PublishResult:
        """Submit the currently open editor without refilling its content."""
        if not self._open_initial_publish_confirmation(page):
            return PublishResult(PublishStatus.FAILED, "browser", "未打开发表确认弹窗", error_code="notification_state_unverified", run_id=run_id)
        clicked_confirmation = self._guarded_final_submit(page)
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
                error_code="notification_state_unverified",
                run_id=run_id,
            )
        page.wait_for_timeout(1000)
        generation = 1
        page, qrcode_path = self._wait_for_publish_qrcode(
            context,
            page,
            output_dir,
            run_id=run_id,
            generation=generation,
        )
        if not qrcode_path:
            screenshot = output_dir / "wechat_publish_verification_not_reached.png"
            try:
                page.screenshot(path=str(screenshot), full_page=True)
            except Exception:
                screenshot = None
            return PublishResult(
                PublishStatus.FAILED,
                "browser",
                "已点击继续发表，但未进入微信验证页面，已阻止继续等待",
                qrcode_path=str(screenshot) if screenshot else None,
                error_code="publish_verification_not_reached",
                run_id=run_id,
            )
        body = self._body_text(page)
        stage = self._scan_stage(body)
        expires_at = time.time() + self.qr_ttl
        if run_id:
            return self._scan_result(
                "请使用微信扫码验证发布",
                stage=stage,
                qrcode_path=qrcode_path,
                run_id=run_id,
                generation=generation,
                expires_at=expires_at,
                error_code="publish_scan_pending",
            )
        return self._wait_for_final_result(page, qrcode_path, generation=generation, expires_at=expires_at)

    def _open_initial_publish_confirmation(self, page: Any) -> bool:
        dialogs = page.locator(".weui-desktop-dialog, .weui-desktop-dialog__wrp, .dialog_wrp, [role='dialog']")
        if dialogs.count() and dialogs.last.is_visible(timeout=300):
            return True
        # Initial editor action is distinct from the guarded final submit.
        try:
            clicked = self._click_text(page, "发表")
        except (AttributeError, TypeError):
            return False
        if not clicked:
            return False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if dialogs.count() and dialogs.last.is_visible(timeout=300):
                return True
            page.wait_for_timeout(100)
        return False

    def _guarded_final_submit(self, page: Any) -> bool:
        """The sole gate for every final publish click."""
        if not self._notification_guard(page):
            return False
        dialogs = page.locator(".weui-desktop-dialog, .weui-desktop-dialog__wrp, .dialog_wrp, [role='dialog']")
        for index in range(dialogs.count() - 1, -1, -1):
            dialog = dialogs.nth(index)
            try:
                buttons = dialog.get_by_role("button", name="发表", exact=True)
                if buttons.count() and buttons.last.is_visible(timeout=300):
                    buttons.last.click(force=True); return True
                buttons = dialog.get_by_role("button", name="继续发表", exact=True)
                if buttons.count() and buttons.last.is_visible(timeout=300):
                    buttons.last.click(force=True); return True
            except Exception:
                continue
        return False

    def _publish_unlocked(self, article: Article, *, confirm_publish: bool = False, run_id: Optional[str] = None, lock: Optional[ProfileLock] = None) -> PublishResult:
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
        store = RunStore(self.profile_dir)
        if run_id:
            try:
                existing = store.load(run_id)
            except KeyError:
                store.create(run_id)
            else:
                if existing.status in {"submitting", "unknown", "awaiting_scan", "verification_expired", "published"}:
                    return PublishResult(PublishStatus.UNKNOWN, "browser", f"run 已处于保护状态: {existing.status}", error_code="run_protected", run_id=run_id)
            store.update(run_id, provider="browser")
        last_result: Optional[PublishResult] = None

        def finish(result: PublishResult) -> PublishResult:
            nonlocal last_result
            if run_id:
                record = store.load(run_id)
                metadata = dict(result.metadata)
                if record.article_title:
                    metadata.setdefault("article_title", record.article_title)
                result = replace(result, run_id=run_id)
                result = replace(result, metadata=metadata)
                store.save_result(run_id, result)
            last_result = result
            return result

        with sync_playwright() as playwright:
            browser_launcher = getattr(playwright, self.browser_type, playwright.chromium)
            if run_id:
                browser, context = self._connect_cdp_context(playwright, run_id, store)
            else:
                launch_options = {
                    "user_data_dir": str(self.profile_dir),
                    "headless": self.headless,
                    "viewport": {"width": 1440, "height": 1000},
                }
                if self.executable_path:
                    launch_options["executable_path"] = self.executable_path
                context = browser_launcher.launch_persistent_context(**launch_options)
                browser = None
            page = context.pages[0] if context.pages else context.new_page()
            try:
                if run_id:
                    store.save_article(run_id, article)
                login_result = self._ensure_login(page, output_dir, run_id=run_id)
                if login_result:
                    result = finish(login_result)
                    if run_id and result.status is PublishStatus.AWAITING_SCAN:
                        self._start_watcher(run_id)
                    return result
                page.goto(self.base_url, wait_until="domcontentloaded")
                try:
                    page = self._open_article_editor(context, page)
                except Exception as exc:
                    return finish(PublishResult(PublishStatus.FAILED, "browser", f"未能打开文章入口: {exc}", error_code="article_menu_missing"))
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                draft_ref = self._fill_article(page, article)
                if run_id:
                    store.update(run_id, resource_refs={"body": dict(self._last_uploaded_urls), "cover": self._last_cover_url})
                if not article.publish:
                    if not self._reopen_and_verify_draft(page, context, draft_ref or "", article):
                        return finish(PublishResult(PublishStatus.FAILED, "browser", "草稿保存后回读核验不一致", error_code="content_verification_failed"))
                    return finish(PublishResult(PublishStatus.DRAFT_CREATED, "browser", "文章已保存并完成回读核验"))
                if not self._verify_editor_content(page, article):
                    return finish(PublishResult(PublishStatus.FAILED, "browser", "发布前内容回读核验不一致", error_code="content_verification_failed"))
                if run_id:
                    store.transition(run_id, ("running",), "submitting", lock=lock, submit_started_at=time.time())
                result = self._submit_current_editor(context, page, output_dir, run_id=run_id)
                result = finish(result)
                if run_id and result.status is PublishStatus.AWAITING_SCAN:
                    self._start_watcher(run_id)
                return result
            except Exception as exc:
                screenshot = output_dir / "wechat_publish_error.png"
                try:
                    page.screenshot(path=str(screenshot), full_page=True)
                except Exception:
                    screenshot = None
                return finish(PublishResult(
                    PublishStatus.FAILED,
                    "browser",
                    f"浏览器发布失败: {exc}",
                    qrcode_path=str(screenshot) if screenshot else None,
                    error_code="browser_error",
                ))

            finally:
                if run_id:
                    if last_result and last_result.status not in {
                        PublishStatus.AWAITING_SCAN,
                        PublishStatus.UNKNOWN,
                        PublishStatus.VERIFICATION_EXPIRED,
                    }:
                        try:
                            browser.close()
                        except Exception:
                            pass
                else:
                    context.close()

    def _verify_editor_content(self, page: Any, article: Article) -> bool:
        try:
            title = page.locator("div[name='title'] .ProseMirror, textarea#title, input[placeholder*='标题']").first.inner_text(timeout=500)
            body = page.locator("div.mock-iframe .ProseMirror, .ProseMirror[contenteditable='true']").last.inner_text(timeout=500)
            images = page.locator("div.mock-iframe img, .ProseMirror img")
            digest_locator = page.locator("[data-article-digest], input[placeholder*='摘要'], textarea[placeholder*='摘要']")
            if digest_locator.count() != 1:
                return False
            digest = digest_locator.first.input_value(timeout=500)
            expected_aliases = _asset_references(article.body)
            actual_nodes = []
            for i in range(images.count()):
                node = images.nth(i)
                alias = node.get_attribute("data-asset-alias") or node.get_attribute("alt")
                src = node.get_attribute("src") or ""
                actual_nodes.append((alias, src))
            aliases = [alias for alias, _ in actual_nodes]
            urls = [src for _, src in actual_nodes]
            expected_urls = [self._last_uploaded_urls.get(alias) for alias in expected_aliases]
            urls_ok = (len(actual_nodes) == len(expected_aliases) and
                       len(set(aliases)) == len(aliases) and set(aliases) == expected_aliases and
                       all(isinstance(src, str) and src.startswith(("http://", "https://")) and
                           "wechat.local" not in src and not src.startswith("file:") for src in urls) and
                       all(self._last_uploaded_urls.get(alias) == src for alias, src in actual_nodes) and
                       len(set(urls)) == len(urls) and all(expected_urls))
            cover_ok = True
            if article.cover_image:
                cover = page.locator("[data-cover-url], .cover-preview img, img[data-cover]")
                cover_value = cover.first.get_attribute("src") or cover.first.get_attribute("data-cover-url") or ""
                expected_cover = self._last_cover_url
                if expected_cover is None:
                    expected_cover = next((url for alias, url in self._last_uploaded_urls.items()
                                           if article.asset_map().get(alias) == article.cover_image), None)
                cover_ok = cover.count() == 1 and bool(expected_cover) and cover_value == expected_cover
            return (article.title in title and digest == article.digest and
                    derive_digest(body) == derive_digest(article.body) and urls_ok and cover_ok)
        except (TimeoutError, ValueError, KeyError):
            return False
