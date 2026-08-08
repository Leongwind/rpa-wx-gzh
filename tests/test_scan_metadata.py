from pathlib import Path

from wechat_publisher.browser import BrowserPublisher
from wechat_publisher.models import PublishStatus


def test_scan_stage_and_card_metadata(tmp_path: Path):
    publisher = BrowserPublisher(tmp_path)
    assert publisher._scan_stage("微信验证\n请使用微信扫码") == "publish_verification"
    assert publisher._scan_stage("扫码后，请联系管理员进行验证") == "admin_approval"
    assert publisher._scan_stage("登录", default="login") == "login"

    result = publisher._scan_result(
        "请扫码",
        stage="publish_verification",
        qrcode_path="/tmp/wx-1-1.png",
        run_id="wx-1",
        generation=1,
        expires_at=123.0,
    )
    payload = result.to_dict()
    assert result.status is PublishStatus.AWAITING_SCAN
    assert payload["stage"] == "publish_verification"
    assert payload["generation"] == 1
    assert payload["expires_at"] == 123.0
    assert payload["next_action"] == "请使用微信扫码验证发布"


def test_qr_artifacts_are_unique_per_run_and_generation(tmp_path: Path):
    first = BrowserPublisher._qr_artifact(tmp_path, "wechat_publish_qrcode", "wx-1", 1)
    second = BrowserPublisher._qr_artifact(tmp_path, "wechat_publish_qrcode", "wx-1", 2)
    other = BrowserPublisher._qr_artifact(tmp_path, "wechat_publish_qrcode", "wx-2", 1)
    assert len({first, second, other}) == 3


def test_watcher_start_is_idempotent(tmp_path: Path, monkeypatch):
    class Process:
        pid = 321

    calls = []
    monkeypatch.setattr("wechat_publisher.browser.subprocess.Popen", lambda *args, **kwargs: calls.append((args, kwargs)) or Process())
    monkeypatch.setattr(BrowserPublisher, "_process_alive", staticmethod(lambda pid: pid == 321))

    publisher = BrowserPublisher(tmp_path)
    from wechat_publisher.session import RunStore

    store = RunStore(tmp_path)
    store.create("wx-watch")
    assert publisher._start_watcher("wx-watch") == 321
    assert publisher._start_watcher("wx-watch") == 321
    assert len(calls) == 1
    assert store.load("wx-watch").watcher_status == "running"


def test_browser_page_refreshes_only_the_expired_qr(tmp_path: Path):
    from playwright.sync_api import sync_playwright
    from wechat_publisher.session import RunStore

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
        page = browser.new_page()
        page.set_content(
            """
            <div id='state'>二维码已过期</div>
            <button id='refresh' onclick='document.body.innerHTML="<div>微信验证</div><img class=qrcode src=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=>"'>重新获取二维码</button>
            """
        )
        publisher = BrowserPublisher(tmp_path, scan_timeout=0.05, poll_interval=0.01, qr_refresh_limit=1)
        store = RunStore(tmp_path)
        store.create("wx-refresh")
        result = publisher._wait_for_final_result(
            page,
            None,
            context=page.context,
            store=store,
            run_id="wx-refresh",
            generation=1,
            expires_at=1.0,
            output_dir=tmp_path / "artifacts",
        )
        browser.close()

    assert result.status is PublishStatus.AWAITING_SCAN
    assert result.generation == 2
    assert result.qrcode_path is not None
    assert "_2.png" in result.qrcode_path
