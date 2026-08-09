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
            scan_timeout=float(os.getenv("WX_SCAN_TIMEOUT", "300")),
            qr_ttl=float(os.getenv("WX_QR_TTL", "120")),
            qr_refresh_limit=int(os.getenv("WX_QR_REFRESH_LIMIT", "1")),
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
        force_republish: bool = False,
    ) -> PublishResult:
        mode = mode.lower()
        if mode not in {"auto", "api", "browser", "draft"}:
            return PublishResult(PublishStatus.FAILED, "none", f"不支持的发布模式: {mode}", error_code="invalid_mode")

        effective_article = replace(article, publish=False) if mode == "draft" else article

        profile_dir = getattr(self.browser, "profile_dir", Path("playwright_data"))
        store = RunStore(profile_dir)
        if run_id:
            try:
                record = store.load(run_id)
                if record.fingerprint and record.fingerprint != effective_article.fingerprint():
                    return PublishResult(
                        PublishStatus.FAILED,
                        "none",
                        "run_id 已绑定另一篇文章，不能复用",
                        error_code="run_article_mismatch",
                        run_id=run_id,
                    )
            except KeyError:
                store.create(run_id)
            store.save_article(run_id, effective_article)
            if effective_article.publish and not force_republish:
                duplicate = store.find_by_fingerprint(
                    effective_article.fingerprint(),
                    exclude_run_id=run_id,
                )
                if duplicate:
                    return self._record_result(store, run_id, effective_article, PublishResult(
                        PublishStatus.FAILED,
                        "none",
                        f"检测到相同文章已有发布会话: {duplicate.run_id} ({duplicate.status})，为避免重复发布已停止",
                        error_code="duplicate_content",
                        run_id=run_id,
                        metadata={"duplicate_run_id": duplicate.run_id, "confirmation_summary": effective_article.confirmation_summary()},
                    ))

        has_cover = effective_article.cover_image or (effective_article.assets[0].path if effective_article.assets else None)
        if effective_article.publish and confirm_publish and has_cover is None:
            return self._record_result(store, run_id, effective_article, PublishResult(
                PublishStatus.FAILED,
                "none",
                "正式发布前必须提供封面图片，或至少提供一张可作为封面的正文图片",
                error_code="cover_required",
            ))

        if mode in {"auto", "api", "draft"} and self.api is not None:
            result = self.api.publish(effective_article, confirm_publish=confirm_publish)
            if mode in {"api", "draft"} or result.status in {
                PublishStatus.PUBLISHED,
                PublishStatus.DRAFT_CREATED,
                PublishStatus.UNKNOWN,
            }:
                return self._record_result(store, run_id, effective_article, result)
            # API failures before submission are eligible for browser fallback.
            if mode == "auto" and result.status is not PublishStatus.FAILED:
                return self._record_result(store, run_id, effective_article, result)

        if mode == "api":
            return self._record_result(
                store,
                run_id,
                effective_article,
                PublishResult(PublishStatus.FAILED, "api", "未配置 WX_APPID/WX_APPSECRET", error_code="credentials_missing"),
            )
        if self.browser is None:
            return self._record_result(
                store,
                run_id,
                effective_article,
                PublishResult(PublishStatus.FAILED, "none", "没有可用的浏览器发布器", error_code="browser_unavailable"),
            )
        unsupported = []
        if effective_article.author:
            unsupported.append("author")
        if effective_article.source_url:
            unsupported.append("source_url")
        if effective_article.need_open_comment:
            unsupported.append("need_open_comment")
        if effective_article.only_fans_can_comment:
            unsupported.append("only_fans_can_comment")
        if unsupported:
            return self._record_result(store, run_id, effective_article, PublishResult(
                PublishStatus.FAILED,
                "browser",
                f"浏览器通道暂不支持文章选项: {', '.join(unsupported)}，请使用 API 通道",
                error_code="browser_option_unsupported",
                run_id=run_id,
                metadata={"unsupported_options": unsupported},
            ))
        if run_id is None:
            return self.browser.publish(effective_article, confirm_publish=confirm_publish)
        result = self.browser.publish(effective_article, confirm_publish=confirm_publish, run_id=run_id)
        return self._record_result(store, run_id, effective_article, result)

    @staticmethod
    def _record_result(store: RunStore, run_id: Optional[str], article: Article, result: PublishResult) -> PublishResult:
        if run_id is None:
            return result
        metadata = dict(result.metadata)
        metadata.setdefault("confirmation_summary", article.confirmation_summary())
        result = replace(result, run_id=run_id, metadata=metadata)
        store.save_result(run_id, result)
        return result

    def resume(self, run_id: str) -> PublishResult:
        if self.browser is None:
            return PublishResult(PublishStatus.FAILED, "none", "没有可用的浏览器发布器", error_code="browser_unavailable", run_id=run_id)
        return self.browser.resume(run_id)

    def publish_run(self, run_id: str, *, confirm_publish: bool = False) -> PublishResult:
        """Publish a previously created draft without recreating its content."""
        profile_dir = getattr(self.browser, "profile_dir", Path("playwright_data"))
        store = RunStore(profile_dir)
        try:
            record = store.load(run_id)
            article = store.load_article(run_id)
        except (KeyError, ValueError) as exc:
            return PublishResult(PublishStatus.FAILED, "none", str(exc), error_code="run_not_found", run_id=run_id)
        if record.status != PublishStatus.DRAFT_CREATED.value:
            return PublishResult(
                PublishStatus.FAILED,
                record.provider,
                f"只有 draft_created 会话可以发布，当前状态为 {record.status}",
                error_code="run_not_publishable",
                run_id=run_id,
            )
        if not confirm_publish:
            return PublishResult(
                PublishStatus.FAILED,
                record.provider,
                "发布草稿必须显式传入 confirm_publish=True",
                error_code="confirmation_required",
                run_id=run_id,
            )
        draft_id = record.result.get("draft_id") if record.result else None
        if record.provider == "api" and self.api is not None and draft_id:
            result = self.api.publish_draft(str(draft_id), confirm_publish=True)
            return self._record_result(store, run_id, article, result)
        if self.browser is None:
            return PublishResult(PublishStatus.FAILED, "none", "没有可用的浏览器发布器", error_code="browser_unavailable", run_id=run_id)
        return self.browser.publish_existing(run_id, confirm_publish=True)

    def watch(self, run_id: str) -> PublishResult:
        if self.browser is None:
            return PublishResult(PublishStatus.FAILED, "none", "没有可用的浏览器发布器", error_code="browser_unavailable", run_id=run_id)
        return self.browser.watch(run_id)

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
    force_republish: bool = False,
    publisher: Optional[AutoPublisher] = None,
) -> PublishResult:
    return (publisher or AutoPublisher.from_environment()).publish(
        article,
        mode=mode,
        confirm_publish=confirm_publish,
        run_id=run_id,
        force_republish=force_republish,
    )
