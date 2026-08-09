from pathlib import Path

from wechat_publisher.api import WeChatAPI
from wechat_publisher.models import Article, PublishStatus


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, timeout, **kwargs):
        self.calls.append((method, url, kwargs))
        if "/cgi-bin/token" in url:
            return FakeResponse({"access_token": "token"})
        if "/cgi-bin/media/uploadimg" in url:
            return FakeResponse({"url": "https://example.test/body.png"})
        if "/cgi-bin/material/add_material" in url:
            return FakeResponse({"media_id": "cover-media"})
        if "/cgi-bin/draft/add" in url:
            return FakeResponse({"media_id": "draft-media"})
        if "/cgi-bin/freepublish/submit" in url:
            return FakeResponse({"publish_id": "publish-1"})
        if "/cgi-bin/freepublish/get" in url:
            return FakeResponse({"publish_status": 0, "article_id": "article-1"})
        raise AssertionError(f"unexpected URL: {url}")


def article(tmp_path: Path) -> Article:
    image = tmp_path / "cover.png"
    image.write_bytes(b"png")
    return Article.from_dict(
        {
            "title": "API 测试",
            "body": "正文 {{asset:hero}}",
            "body_format": "markdown",
            "cover_image": str(image),
            "assets": [{"alias": "hero", "path": str(image)}],
            "publish": True,
        }
    )


def test_api_publish_polls_success(tmp_path: Path):
    session = FakeSession()
    api = WeChatAPI("appid", "secret", session=session, poll_interval=0, poll_timeout=1)
    result = api.publish(article(tmp_path), confirm_publish=True)
    assert result.status is PublishStatus.PUBLISHED
    assert result.draft_id == "draft-media"
    assert result.publish_id == "publish-1"
    assert result.article_id == "article-1"


def test_api_requires_explicit_confirmation(tmp_path: Path):
    api = WeChatAPI("appid", "secret", session=FakeSession())
    result = api.publish(article(tmp_path), confirm_publish=False)
    assert result.status is PublishStatus.FAILED
    assert result.error_code == "confirmation_required"


def test_api_retries_transient_server_error_before_submission(tmp_path: Path):
    class FlakySession(FakeSession):
        def __init__(self):
            super().__init__()
            self.failures = 1

        def request(self, method, url, timeout, **kwargs):
            if self.failures and "/cgi-bin/token" in url:
                self.failures -= 1
                return FakeResponse({}, status_code=503)
            return super().request(method, url, timeout, **kwargs)

    session = FlakySession()
    api = WeChatAPI("appid", "secret", session=session, poll_interval=0, poll_timeout=1)
    result = api.publish(article(tmp_path), confirm_publish=True)

    assert result.status is PublishStatus.PUBLISHED


def test_api_maps_article_metadata_to_draft_payload(tmp_path: Path):
    session = FakeSession()
    value = article(tmp_path)
    value = Article.from_dict(
        {
            **value.to_dict(),
            "author": "作者",
            "source_url": "https://example.test/source",
            "need_open_comment": True,
            "only_fans_can_comment": True,
            "publish": False,
        }
    )
    api = WeChatAPI("appid", "secret", session=session, poll_interval=0, poll_timeout=1)
    result = api.publish(value, confirm_publish=False)

    assert result.status is PublishStatus.DRAFT_CREATED
    draft_calls = [call for call in session.calls if "/cgi-bin/draft/add" in call[1]]
    payload = draft_calls[0][2]["json"]["articles"][0]
    assert payload["author"] == "作者"
    assert payload["content_source_url"] == "https://example.test/source"
    assert payload["need_open_comment"] == 1
    assert payload["only_fans_can_comment"] == 1


def test_api_refreshes_expired_token_before_non_submit_request():
    class ExpiredTokenSession:
        def __init__(self):
            self.calls = []
            self.expired = True

        def request(self, method, url, timeout, **kwargs):
            self.calls.append(url)
            if "/cgi-bin/token" in url:
                return FakeResponse({"access_token": "fresh-token"})
            if self.expired:
                self.expired = False
                return FakeResponse({"errcode": 42001, "errmsg": "expired"})
            return FakeResponse({"ok": True})

    session = ExpiredTokenSession()
    api = WeChatAPI("appid", "secret", session=session)
    api._access_token = "old-token"

    assert api._request("GET", "/cgi-bin/draft/get", params={"access_token": "old-token"}) == {"ok": True}
    assert any("fresh-token" in url for url in session.calls)
