"""Provider selection and public publish function."""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Optional

from .api import WeChatAPI
from .browser import BrowserPublisher
from .models import Article, PublishResult, PublishStatus
from .session import RunStore


@dataclass
class AutoPublisher:
    api: Optional[WeChatAPI] = None
    browser: Optional[BrowserPublisher] = None

    @classmethod
    def from_environment(cls) -> "AutoPublisher":
        appid = os.getenv("WX_APPID", "").strip()
        appsecret = os.getenv("WX_APPSECRET", "").strip()
        api = WeChatAPI(appid, appsecret) if appid and appsecret else None
        profile = Path(os.getenv("WX_PLAYWRIGHT_PROFILE", "playwright_data"))
        browser = BrowserPublisher(
            profile,
            base_url=os.getenv("WX_MP_URL", BrowserPublisher.BASE_URL),
            headless=os.getenv("WX_HEADLESS", "0").lower() in {"1", "true", "yes"},
            scan_timeout=float(os.getenv("WX_SCAN_TIMEOUT", "120")),
            executable_path=os.getenv("WX_PLAYWRIGHT_EXECUTABLE_PATH") or None,
        )
        return cls(api=api, browser=browser)

    def publish(
        self,
        article: Article,
        *,
        mode: str = "auto",
        confirm_publish: bool = False,
        run_id: Optional[str] = None,
    ) -> PublishResult:
        mode = mode.lower()
        if mode not in {"auto", "api", "browser", "draft"}:
            return PublishResult(PublishStatus.FAILED, "none", f"不支持的发布模式: {mode}", error_code="invalid_mode")

        effective_article = replace(article, publish=False) if mode == "draft" else article

        if mode in {"auto", "api", "draft"} and self.api is not None:
            result = self.api.publish(effective_article, confirm_publish=confirm_publish)
            if mode in {"api", "draft"} or result.status in {
                PublishStatus.PUBLISHED,
                PublishStatus.DRAFT_CREATED,
                PublishStatus.UNKNOWN,
            }:
                return result
            # API failures before submission are eligible for browser fallback.
            if mode == "auto" and result.status is not PublishStatus.FAILED:
                return result

        if mode == "api":
            return PublishResult(PublishStatus.FAILED, "api", "未配置 WX_APPID/WX_APPSECRET", error_code="credentials_missing")
        if self.browser is None:
            return PublishResult(PublishStatus.FAILED, "none", "没有可用的浏览器发布器", error_code="browser_unavailable")
        if run_id is None:
            return self.browser.publish(effective_article, confirm_publish=confirm_publish)
        return self.browser.publish(effective_article, confirm_publish=confirm_publish, run_id=run_id)

    def resume(self, run_id: str) -> PublishResult:
        if self.browser is None:
            return PublishResult(PublishStatus.FAILED, "none", "没有可用的浏览器发布器", error_code="browser_unavailable", run_id=run_id)
        return self.browser.resume(run_id)

    def status(self, run_id: str) -> dict:
        if self.browser is None:
            raise KeyError(run_id)
        return RunStore(self.browser.profile_dir).load(run_id).to_dict()

    def cancel(self, run_id: str) -> dict:
        if self.browser is None:
            raise KeyError(run_id)
        return self.browser.cancel(run_id)


def publish(
    article: Article,
    *,
    mode: str = "auto",
    confirm_publish: bool = False,
    run_id: Optional[str] = None,
    publisher: Optional[AutoPublisher] = None,
) -> PublishResult:
    return (publisher or AutoPublisher.from_environment()).publish(
        article,
        mode=mode,
        confirm_publish=confirm_publish,
        run_id=run_id,
    )
