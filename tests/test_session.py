from pathlib import Path

from wechat_publisher.models import Article, PublishResult, PublishStatus
from wechat_publisher.session import ProfileBusyError, ProfileLock, RunStore


def test_run_store_round_trips_result_without_secrets(tmp_path: Path):
    store = RunStore(tmp_path / "profile")
    record = store.create("wx-test-1")
    assert record.status == "running"

    result = PublishResult(
        PublishStatus.AWAITING_SCAN,
        "browser",
        "请扫码",
        qrcode_path="/tmp/qr.png",
        error_code="publish_scan_timeout",
        run_id="wx-test-1",
    )
    saved = store.save_result("wx-test-1", result)
    loaded = store.load("wx-test-1")

    assert saved.status == PublishStatus.AWAITING_SCAN.value
    assert loaded.to_dict()["result"]["run_id"] == "wx-test-1"
    assert "appsecret" not in store.path("wx-test-1").read_text(encoding="utf-8")


def test_run_store_persists_article_snapshot(tmp_path: Path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"png")
    article = Article.from_dict({"title": "卡片测试", "body": "正文", "cover_image": str(cover)})
    store = RunStore(tmp_path / "profile")
    store.create("wx-article-1")

    path = store.save_article("wx-article-1", article)
    restored = store.load_article("wx-article-1")

    assert Path(path).is_file()
    assert restored.title == article.title
    assert restored.cover_image == article.cover_image


def test_run_store_tracks_fingerprint_and_cleanup_removes_finished_run(tmp_path: Path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"png")
    article = Article.from_dict({"title": "清理测试", "body": "正文", "cover_image": str(cover)})
    store = RunStore(tmp_path / "profile")
    store.create("wx-clean")
    store.save_article("wx-clean", article)
    store.save_result("wx-clean", PublishResult(PublishStatus.DRAFT_CREATED, "api", run_id="wx-clean"))
    assert store.load("wx-clean").fingerprint == article.fingerprint()
    assert store.cleanup(older_than=0, dry_run=False) == {"runs": 1, "files": 2}


def test_profile_lock_prevents_concurrent_publishers(tmp_path: Path):
    first = ProfileLock(tmp_path / "profile", timeout=0.1).acquire()
    try:
        second = ProfileLock(tmp_path / "profile", timeout=0.01)
        try:
            second.acquire()
        except ProfileBusyError:
            pass
        else:
            raise AssertionError("第二个 publisher 不应取得同一个 profile 锁")
    finally:
        first.release()
