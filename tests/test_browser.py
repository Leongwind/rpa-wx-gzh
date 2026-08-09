from pathlib import Path
from dataclasses import replace

import pytest

from wechat_publisher.browser import BrowserPublisher
from wechat_publisher.models import Article, PublishStatus


class _BodyReadFailure:
    def locator(self, _selector: str):
        return self

    def inner_text(self, *, timeout: int):
        raise TimeoutError(timeout)


def test_transient_body_read_timeout_returns_empty_text():
    assert BrowserPublisher._body_text(_BodyReadFailure()) == ""


def test_recent_publish_record_must_be_newer_than_run(tmp_path: Path):
    sync_playwright = __import__("playwright.sync_api", fromlist=["sync_playwright"]).sync_playwright
    executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not executable.is_file():
        pytest.skip("本机没有可用于浏览器模拟的 Chrome")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
        page = browser.new_page()
        page.set_content(
            """
            <div class='weui-desktop-mass-media weui-desktop-mass-appmsg'>
              <a class='weui-desktop-mass-appmsg__title'>0808测试</a>
              <a href='/stats?send_time=200'>数据</a>
            </div>
            """
        )

        assert BrowserPublisher._published_article_after(page, "0808测试", 150)
        assert not BrowserPublisher._published_article_after(page, "0808测试", 201)
        assert not BrowserPublisher._published_article_after(page, "其他标题", 150)


def test_browser_requires_confirmation_before_external_publish(tmp_path: Path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"png")
    article = Article.from_dict({"title": "浏览器测试", "body": "正文", "cover_image": str(cover), "publish": True})
    result = BrowserPublisher(tmp_path / "profile").publish(article, confirm_publish=False)
    assert result.status is PublishStatus.FAILED
    assert result.error_code == "confirmation_required"


def test_browser_editor_receives_dynamic_title_and_body(tmp_path: Path):
    image = tmp_path / "body.png"
    image.write_bytes(b"png")
    article = Article.from_dict(
        {
            "title": "用户自定义标题",
            "body": "用户自定义正文 {{asset:body}}",
            "assets": [{"alias": "body", "path": str(image)}],
        }
    )
    class Page:
        def __init__(self): self.calls = []
        def upload_asset(self, alias, path):
            self.calls.append((alias, path)); return f"https://mp.weixin.qq.com/upload/{alias}"
    page = Page()
    adapter = type("A", (), {"upload_asset": lambda _, p, alias, path: p.upload_asset(alias, path), "save_draft": lambda *_: None, "reopen_draft": lambda *_: None})()
    urls = BrowserPublisher(tmp_path / "profile", adapter=adapter).upload_body_assets(page, article)
    assert urls == {"body": "https://mp.weixin.qq.com/upload/body"}
    assert page.calls == [("body", image)]
    assert "file://" not in urls["body"] and "wechat.local" not in urls["body"]


def test_publish_confirmation_prefers_visible_dialog_button(tmp_path: Path):
    class EmptyLocator:
        def count(self): return 0
    class Page:
        def locator(self, _selector): return EmptyLocator()
    page = Page()
    publisher = BrowserPublisher(tmp_path / "profile")
    assert not publisher._click_publish_confirmation_once(page)
    assert not publisher._notification_guard(page)
def test_publish_confirmation_disables_group_notification(tmp_path: Path):
    sync_playwright = __import__("playwright.sync_api", fromlist=["sync_playwright"]).sync_playwright
    executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not executable.is_file():
        pytest.skip("本机没有可用于浏览器模拟的 Chrome")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
        page = browser.new_page()
        page.set_content(
            """
            <div class='weui-desktop-dialog'>
              <div class='mass_send__notify'>
                <label class='weui-desktop-switch'>
                  <input type='checkbox' checked class='weui-desktop-switch__input'>
                  <div class='weui-desktop-switch__box'></div>
                </label>
              </div>
              <button onclick="document.body.dataset.clicked='yes'">发表</button>
            </div>
            """
        )

        assert BrowserPublisher(tmp_path / "profile")._click_publish_confirmation_once(page)
        assert not page.locator("input.weui-desktop-switch__input").is_checked()
        assert page.locator("body").get_attribute("data-clicked") == "yes"
        browser.close()


def test_cover_selection_clicks_inner_image_and_enabled_dialog_buttons(tmp_path: Path):
    sync_playwright = __import__("playwright.sync_api", fromlist=["sync_playwright"]).sync_playwright
    executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not executable.is_file():
        pytest.skip("本机没有可用于浏览器模拟的 Chrome")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
        page = browser.new_page()
        page.set_content(
            """
            <div role='dialog' id='select-dialog'>
              <li class='appmsg_content_img_item'>
                <span class='appmsg_content_img cover' style='display:block;width:120px;height:80px'
                      onclick="this.parentElement.classList.add('selected');
                               const button=document.querySelector('#next');
                               button.classList.remove('weui-desktop-btn_disabled');
                               button.disabled=false"></span>
              </li>
              <button id='next' class='weui-desktop-btn_disabled' disabled
                      onclick="document.querySelector('#confirm').style.display='block'">下一步</button>
            </div>
            <div role='dialog' id='crop-dialog'>
              <button id='confirm' style='display:none'
                      onclick="document.body.dataset.confirmed='yes'">确认</button>
            </div>
            """
        )

        BrowserPublisher(tmp_path / "profile")._select_body_cover_in_dialog(page)

        assert page.locator("li.appmsg_content_img_item").get_attribute("class").endswith("selected")
        assert page.locator("body").get_attribute("data-confirmed") == "yes"
        browser.close()


def test_cover_selection_keeps_an_already_selected_image(tmp_path: Path):
    sync_playwright = __import__("playwright.sync_api", fromlist=["sync_playwright"]).sync_playwright
    executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not executable.is_file():
        pytest.skip("本机没有可用于浏览器模拟的 Chrome")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
        page = browser.new_page()
        page.set_content(
            """
            <li class='appmsg_content_img_item selected'>
              <span class='appmsg_content_img cover' style='display:block;width:120px;height:80px'
                    onclick="this.parentElement.classList.remove('selected')"></span>
            </li>
            <button onclick="document.querySelector('#confirm').style.display='block'">下一步</button>
            <button id='confirm' style='display:none'
                    onclick="document.body.dataset.confirmed='yes'">确认</button>
            """
        )

        BrowserPublisher(tmp_path / "profile")._select_body_cover_in_dialog(page)

        assert "selected" in page.locator("li.appmsg_content_img_item").get_attribute("class")
        assert page.locator("body").get_attribute("data-confirmed") == "yes"
        browser.close()


def test_cover_upload_cleanup_does_not_leave_cover_in_body(tmp_path: Path):
    sync_playwright = __import__("playwright.sync_api", fromlist=["sync_playwright"]).sync_playwright
    executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not executable.is_file():
        pytest.skip("本机没有可用于浏览器模拟的 Chrome")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
        page = browser.new_page()
        page.set_content(
            """
            <div class='mock-iframe'>
              <div class='ProseMirror' contenteditable='true'>
                <p><img class='rich_pages' src='body.png'></p>
                <p><img class='rich_pages' src='temporary-cover.png'></p>
              </div>
            </div>
            """
        )

        BrowserPublisher(tmp_path / "profile")._remove_temporary_cover_image(page, 1)

        assert page.locator("div.mock-iframe img.rich_pages").count() == 1
        assert page.locator("div.mock-iframe img.rich_pages").first.get_attribute("src") == "body.png"
        browser.close()
