from pathlib import Path

from wechat_publisher.browser import BrowserPublisher
from wechat_publisher.models import Article, PublishStatus


def test_browser_requires_confirmation_before_external_publish(tmp_path: Path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"png")
    article = Article.from_dict({"title": "浏览器测试", "body": "正文", "cover_image": str(cover)})
    result = BrowserPublisher(tmp_path / "profile").publish(article, confirm_publish=False)
    assert result.status is PublishStatus.FAILED
    assert result.error_code == "confirmation_required"
