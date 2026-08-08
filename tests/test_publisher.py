from pathlib import Path

from wechat_publisher.models import Article, PublishResult, PublishStatus
from wechat_publisher.publisher import AutoPublisher


def article(tmp_path: Path) -> Article:
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"png")
    return Article.from_dict({"title": "测试", "body": "正文", "cover_image": str(cover)})


class FailingAPI:
    def publish(self, article, *, confirm_publish):
        return PublishResult(PublishStatus.FAILED, "api", "权限不足", error_code="api_error")


class Browser:
    def publish(self, article, *, confirm_publish):
        return PublishResult(PublishStatus.AWAITING_SCAN, "browser", "请扫码", qrcode_path="/tmp/qrcode.png")


def test_auto_provider_falls_back_before_api_submission(tmp_path: Path):
    result = AutoPublisher(api=FailingAPI(), browser=Browser()).publish(
        article(tmp_path), mode="auto", confirm_publish=True
    )
    assert result.status is PublishStatus.AWAITING_SCAN
    assert result.provider == "browser"


class UnknownAPI:
    def publish(self, article, *, confirm_publish):
        return PublishResult(PublishStatus.UNKNOWN, "api", "提交结果未知", error_code="publish_status_timeout")


def test_auto_provider_does_not_fallback_after_unknown_submission(tmp_path: Path):
    result = AutoPublisher(api=UnknownAPI(), browser=Browser()).publish(
        article(tmp_path), mode="auto", confirm_publish=True
    )
    assert result.status is PublishStatus.UNKNOWN
    assert result.provider == "api"
