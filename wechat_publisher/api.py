"""WeChat Official Account API adapter.

The adapter does not silently retry a submitted publication. A result that is
unknown after submission is returned to the caller so it cannot create a
duplicate article through the browser fallback.
"""

from __future__ import annotations

import mimetypes
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional
from urllib.parse import urlencode

import requests

from .content import render_html
from .models import Article, PublishResult, PublishStatus, _asset_references


class WeChatAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        submitted: bool = False,
        draft_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.submitted = submitted
        self.draft_id = draft_id


@dataclass
class WeChatAPI:
    appid: str
    appsecret: str
    base_url: str = "https://api.weixin.qq.com"
    timeout: float = 30.0
    session: Optional[requests.Session] = None
    poll_interval: float = 2.0
    poll_timeout: float = 120.0
    submission_checkpoint: Optional[Callable[[str], None]] = None
    publish_id_checkpoint: Optional[Callable[[str, str], None]] = None

    def __post_init__(self) -> None:
        self.session = self.session or requests.Session()
        self._access_token: Optional[str] = None

    def _url(self, path: str, **params: str) -> str:
        query = urlencode(params)
        return f"{self.base_url.rstrip('/')}{path}?{query}" if query else f"{self.base_url.rstrip('/')}{path}"

    def _json_response(self, response: requests.Response) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise WeChatAPIError(f"微信 API 返回了非 JSON 响应: HTTP {response.status_code}") from exc
        if not isinstance(payload, Mapping):
            raise WeChatAPIError("微信 API 返回格式不是对象")
        if payload.get("errcode") not in (None, 0, "0"):
            raise WeChatAPIError(
                str(payload.get("errmsg", "微信 API 请求失败")),
                code=str(payload.get("errcode")),
            )
        return payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, str]] = None,
        _token_retry: bool = False,
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        retryable = path != "/cgi-bin/freepublish/submit"
        last_error: Optional[Exception] = None
        for attempt in range(3 if retryable else 1):
            try:
                response = self.session.request(method, self._url(path, **(params or {})), timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 >= (3 if retryable else 1):
                    raise WeChatAPIError(f"微信 API 网络请求失败: {_redact(str(exc))}") from exc
                time.sleep(0.5 * (2**attempt))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_error = WeChatAPIError(f"微信 API 服务端错误: HTTP {response.status_code}")
                if attempt + 1 >= (3 if retryable else 1):
                    raise last_error
                time.sleep(0.5 * (2**attempt))
                continue
            try:
                return self._json_response(response)
            except WeChatAPIError as exc:
                if (
                    exc.code in {"40001", "40014", "42001"}
                    and not _token_retry
                    and path != "/cgi-bin/freepublish/submit"
                    and params
                    and "access_token" in params
                ):
                    refreshed_params = dict(params)
                    self._access_token = None
                    refreshed_params["access_token"] = self.access_token()
                    return self._request(
                        method,
                        path,
                        params=refreshed_params,
                        _token_retry=True,
                        **kwargs,
                    )
                raise
        raise WeChatAPIError(f"微信 API 请求失败: {_redact(str(last_error))}")

    def access_token(self) -> str:
        if self._access_token:
            return self._access_token
        payload = self._request(
            "GET",
            "/cgi-bin/token",
            params={"grant_type": "client_credential", "appid": self.appid, "secret": self.appsecret},
        )
        token = str(payload.get("access_token", ""))
        if not token:
            raise WeChatAPIError("微信 API 没有返回 access_token")
        self._access_token = token
        return token

    def _token_params(self) -> Dict[str, str]:
        return {"access_token": self.access_token()}

    def upload_permanent_image(self, path: Path) -> str:
        with path.open("rb") as handle:
            payload = self._request(
                "POST",
                "/cgi-bin/material/add_material",
                params={**self._token_params(), "type": "image"},
                files={"media": (path.name, handle, mimetypes.guess_type(path.name)[0] or "application/octet-stream")},
            )
        media_id = str(payload.get("media_id", ""))
        if not media_id:
            raise WeChatAPIError("上传封面后没有返回 media_id")
        return media_id

    def upload_content_image(self, path: Path) -> str:
        with path.open("rb") as handle:
            payload = self._request(
                "POST",
                "/cgi-bin/media/uploadimg",
                params=self._token_params(),
                files={"media": (path.name, handle, mimetypes.guess_type(path.name)[0] or "application/octet-stream")},
            )
        url = str(payload.get("url", ""))
        if not url:
            raise WeChatAPIError("上传正文图片后没有返回 URL")
        return url

    def create_draft(self, article: Article, html_body: str, cover_media_id: str) -> str:
        payload = self._request(
            "POST",
            "/cgi-bin/draft/add",
            params=self._token_params(),
            json={
                "articles": [
                    {
                        "title": article.title,
                        "author": article.author,
                        "digest": article.digest,
                        "content": html_body,
                        "content_source_url": article.source_url,
                        "thumb_media_id": cover_media_id,
                        "need_open_comment": int(article.need_open_comment),
                        "only_fans_can_comment": int(article.only_fans_can_comment),
                    }
                ]
            },
        )
        draft_id = str(payload.get("media_id", ""))
        if not draft_id:
            raise WeChatAPIError("创建草稿后没有返回 media_id")
        return draft_id

    def submit_publish(self, draft_id: str) -> str:
        try:
            payload = self._request(
                "POST",
                "/cgi-bin/freepublish/submit",
                params=self._token_params(),
                json={"media_id": draft_id},
            )
        except WeChatAPIError as exc:
            raise WeChatAPIError(str(exc), code=exc.code, submitted=True, draft_id=draft_id) from exc
        publish_id = str(payload.get("publish_id", ""))
        if not publish_id:
            raise WeChatAPIError("提交发布后没有返回 publish_id", submitted=True, draft_id=draft_id)
        return publish_id

    def publish_draft(self, draft_id: str, *, confirm_publish: bool = False, publish_id: Optional[str] = None) -> PublishResult:
        """Publish an existing draft without recreating or uploading it."""
        if not confirm_publish:
            return PublishResult(
                PublishStatus.FAILED,
                "api",
                "发布草稿必须显式传入 confirm_publish=True",
                draft_id=draft_id,
                error_code="confirmation_required",
            )
        query_only = publish_id is not None
        try:
            if publish_id is None and self.submission_checkpoint:
                self.submission_checkpoint(draft_id)
            publish_id = publish_id or self.submit_publish(draft_id)
            if not query_only and self.publish_id_checkpoint:
                self.publish_id_checkpoint(draft_id, publish_id)
            deadline = time.monotonic() + self.poll_timeout
            last: Mapping[str, Any] = {}
            while time.monotonic() < deadline:
                last = self.get_publish_status(publish_id)
                status = str(last.get("publish_status", last.get("status", ""))).lower()
                if status in {"0", "published", "success", "成功"}:
                    return PublishResult(
                        PublishStatus.PUBLISHED,
                        "api",
                        "文章发布成功",
                        draft_id=draft_id,
                        publish_id=publish_id,
                        article_id=str(last.get("article_id", "")) or None,
                        metadata=dict(last),
                    )
                if status in {"2", "3", "4", "5", "6", "failed", "fail", "失败"}:
                    return PublishResult(
                        PublishStatus.FAILED,
                        "api",
                        str(last.get("reason", "文章发布失败")),
                        draft_id=draft_id,
                        publish_id=publish_id,
                        error_code="publish_failed",
                        metadata=dict(last),
                    )
                time.sleep(self.poll_interval)
            return PublishResult(
                PublishStatus.UNKNOWN,
                "api",
                "已提交发布但在超时时间内无法确认结果，禁止自动回退以避免重复发布",
                draft_id=draft_id,
                publish_id=publish_id,
                error_code="publish_status_timeout",
                metadata=dict(last),
            )
        except WeChatAPIError as exc:
            return PublishResult(
                PublishStatus.UNKNOWN,
                "api",
                str(exc),
                draft_id=draft_id,
                publish_id=publish_id,
                error_code=exc.code or "publish_submit_error",
            )

    def get_publish_status(self, publish_id: str) -> Mapping[str, Any]:
        return self._request(
            "POST",
            "/cgi-bin/freepublish/get",
            params=self._token_params(),
            json={"publish_id": publish_id},
        )

    def publish(self, article: Article, *, confirm_publish: bool = False) -> PublishResult:
        if not confirm_publish and article.publish:
            return PublishResult(
                PublishStatus.FAILED,
                "api",
                "发布文章必须显式传入 confirm_publish=True",
                error_code="confirmation_required",
            )
        try:
            referenced = _asset_references(article.body)
            image_urls = {asset.alias: self.upload_content_image(asset.path)
                          for asset in article.assets if asset.alias in referenced}
            html_body = render_html(article, image_urls)
            cover = article.cover_image or (article.assets[0].path if article.assets else None)
            if cover is None:
                raise WeChatAPIError("API 发布需要 cover_image 或至少一个正文图片")
            draft_id = self.create_draft(article, html_body, self.upload_permanent_image(cover))
            if not article.publish:
                return PublishResult(PublishStatus.DRAFT_CREATED, "api", "草稿创建成功", draft_id=draft_id)

            return self.publish_draft(draft_id, confirm_publish=confirm_publish)
        except WeChatAPIError as exc:
            return PublishResult(
                PublishStatus.UNKNOWN if exc.submitted else PublishStatus.FAILED,
                "api",
                str(exc),
                draft_id=exc.draft_id,
                error_code=exc.code or "api_error",
            )


def _redact(value: str) -> str:
    return re.sub(r"((?:access_token|secret)=)[^&\s]+", r"\1<redacted>", value, flags=re.IGNORECASE)
