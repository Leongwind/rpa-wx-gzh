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
            return FakeResponse({"publish_status": 1, "article_id": "article-1"})
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
