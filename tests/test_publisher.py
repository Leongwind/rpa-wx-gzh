from pathlib import Path

from wechat_publisher.models import Article, PublishResult, PublishStatus
from wechat_publisher.publisher import AutoPublisher


def article(tmp_path: Path) -> Article:
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"png")
    return Article.from_dict({"title": "测试", "body": "正文", "cover_image": str(cover), "publish": True})


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


def test_real_publish_without_cover_fails_before_provider_calls():
    class ExplodingProvider:
        def publish(self, *args, **kwargs):
            raise AssertionError("provider must not be called")

    article = Article.from_dict({"title": "无封面", "body": "正文", "publish": True})
    publisher = AutoPublisher(api=ExplodingProvider(), browser=ExplodingProvider())
    result = publisher.publish(article, mode="auto", confirm_publish=True)

    assert result.status is PublishStatus.FAILED
    assert result.error_code == "cover_required"


def test_auto_publisher_blocks_duplicate_content(tmp_path: Path):
    class Browser:
        profile_dir = tmp_path / "profile"

        def publish(self, article, *, confirm_publish, run_id=None):
            return PublishResult(PublishStatus.PUBLISHED, "browser", "已发布", run_id=run_id)

    publisher = AutoPublisher(browser=Browser())
    first = publisher.publish(article(tmp_path), mode="browser", confirm_publish=True, run_id="wx-first")
    second = publisher.publish(article(tmp_path), mode="browser", confirm_publish=True, run_id="wx-second")

    assert first.status is PublishStatus.PUBLISHED
    assert second.status is PublishStatus.FAILED
    assert second.error_code == "duplicate_content"


def test_auto_publisher_allows_explicit_duplicate_override(tmp_path: Path):
    class Browser:
        profile_dir = tmp_path / "profile"

        def publish(self, article, *, confirm_publish, run_id=None):
            return PublishResult(PublishStatus.PUBLISHED, "browser", "已发布", run_id=run_id)

    publisher = AutoPublisher(browser=Browser())
    publisher.publish(article(tmp_path), mode="browser", confirm_publish=True, run_id="wx-first")
    result = publisher.publish(
        article(tmp_path),
        mode="browser",
        confirm_publish=True,
        run_id="wx-second",
        force_republish=True,
    )

    assert result.status is PublishStatus.PUBLISHED


def test_publish_run_reuses_existing_api_draft(tmp_path: Path):
    class DraftAPI:
        def publish_draft(self, draft_id, *, confirm_publish):
            assert draft_id == "draft-1"
            assert confirm_publish is True
            return PublishResult(PublishStatus.PUBLISHED, "api", "已发布", draft_id=draft_id)

    profile = tmp_path / "profile"
    browser = type("Browser", (), {"profile_dir": profile})()
    from wechat_publisher.session import RunStore

    store = RunStore(profile)
    store.create("wx-draft")
    store.save_article("wx-draft", article(tmp_path))
    store.save_result(
        "wx-draft",
        PublishResult(PublishStatus.DRAFT_CREATED, "api", "草稿创建成功", draft_id="draft-1", run_id="wx-draft"),
    )

    result = AutoPublisher(api=DraftAPI(), browser=browser).publish_run("wx-draft", confirm_publish=True)

    assert result.status is PublishStatus.PUBLISHED
    assert result.draft_id == "draft-1"
