from pathlib import Path
from dataclasses import replace

import pytest

from wechat_publisher.browser import BrowserPublisher
from wechat_publisher.models import Article, PublishStatus


def test_browser_requires_confirmation_before_external_publish(tmp_path: Path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"png")
    article = Article.from_dict({"title": "浏览器测试", "body": "正文", "cover_image": str(cover)})
    result = BrowserPublisher(tmp_path / "profile").publish(article, confirm_publish=False)
    assert result.status is PublishStatus.FAILED
    assert result.error_code == "confirmation_required"


def test_browser_editor_receives_dynamic_title_and_body(tmp_path: Path):
    sync_playwright = __import__("playwright.sync_api", fromlist=["sync_playwright"]).sync_playwright
    executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not executable.is_file():
        pytest.skip("本机没有可用于浏览器模拟的 Chrome")
    image = tmp_path / "body.png"
    image.write_bytes(b"png")
    article = Article.from_dict(
        {
            "title": "用户自定义标题",
            "body": "用户自定义正文 {{asset:body}}",
            "assets": [{"alias": "body", "path": str(image)}],
        }
    )
    article = replace(article, cover_image=None)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
        page = browser.new_page()
        page.set_content(
            """
            <div name='title'><div class='ProseMirror' contenteditable='true'></div></div>
            <div class='mock-iframe'><div class='ProseMirror' contenteditable='true'></div></div>
            """
        )
        BrowserPublisher(tmp_path / "profile")._fill_article(page, article)

        assert page.locator("div[name='title'] .ProseMirror").inner_text() == "用户自定义标题"
        assert "用户自定义正文" in page.locator("div.mock-iframe .ProseMirror").inner_text()
        assert "file://" in page.locator("div.mock-iframe img").get_attribute("src")
        browser.close()


def test_publish_confirmation_prefers_visible_dialog_button(tmp_path: Path):
    sync_playwright = __import__("playwright.sync_api", fromlist=["sync_playwright"]).sync_playwright
    executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not executable.is_file():
        pytest.skip("本机没有可用于浏览器模拟的 Chrome")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
        page = browser.new_page()
        page.set_content(
            """
            <button class='mass_send' onclick="document.body.dataset.clicked='editor'">发表</button>
            <div class='weui-desktop-dialog'>
              <button class='weui-desktop-btn_primary' onclick="document.body.dataset.clicked='dialog'">发表</button>
            </div>
            """
        )

        assert BrowserPublisher(tmp_path / "profile")._click_publish_confirmation_once(page)
        assert page.locator("body").get_attribute("data-clicked") == "dialog"
        browser.close()
