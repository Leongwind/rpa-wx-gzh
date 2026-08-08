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
        browser.close()


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
