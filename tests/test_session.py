from pathlib import Path

from wechat_publisher.models import PublishResult, PublishStatus
from wechat_publisher.session import RunStore


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
