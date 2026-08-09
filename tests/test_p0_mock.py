from pathlib import Path

import pytest

from wechat_publisher.api import WeChatAPI
from wechat_publisher.browser import BrowserPublisher
from wechat_publisher.models import Article, PublishStatus, ValidationError
from wechat_publisher.session import ProfileLock, RunStore


class EmptyLocator:
    def count(self): return 0


class EmptyPage:
    clicks = 0
    def locator(self, _): return EmptyLocator()


def test_notification_missing_region_has_zero_clicks(tmp_path):
    page = EmptyPage(); publisher = BrowserPublisher(tmp_path)
    assert not publisher._click_publish_confirmation_once(page)
    assert not publisher._click_continue_publish(page)
    assert page.clicks == 0


def test_submit_current_editor_missing_notification_never_clicks(tmp_path):
    page = EmptyPage(); publisher = BrowserPublisher(tmp_path)
    result = publisher._submit_current_editor(None, page, tmp_path)
    assert result.error_code == "notification_state_unverified"
    assert page.clicks == 0


class MissingSwitchLocator:
    def count(self): return 1
    @property
    def first(self): return self
    def locator(self, _): return EmptyLocator()


class MissingSwitchDialog:
    def locator(self, selector):
        return MissingSwitchLocator() if "mass_send__notify" in selector else EmptyLocator()


class DialogPage:
    def __init__(self, dialog): self.dialog = dialog; self.clicks = 0
    def locator(self, _):
        class L:
            def __init__(self, d): self.d=d
            def count(self): return 1
            def nth(self, _): return self.d
        return L(self.dialog)


def test_notification_missing_switch_has_zero_clicks(tmp_path):
    page = DialogPage(MissingSwitchDialog()); publisher = BrowserPublisher(tmp_path)
    assert not publisher._notification_guard(page)
    assert page.clicks == 0


def test_readback_rejects_missing_alias_and_zero_images(tmp_path):
    image = tmp_path / "a.png"; image.write_bytes(b"x")
    article = Article.from_dict({"title": "T", "body": "正文 {{asset:a}}", "digest": "D", "assets": [{"alias": "a", "path": str(image)}]})
    class L:
        def __init__(self, text="", items=None): self.text=text; self.items=items or []
        @property
        def first(self): return self
        @property
        def last(self): return self.items[-1] if self.items else self
        def inner_text(self, **_): return self.text
        def input_value(self, **_): return "D"
        def count(self): return len(self.items)
        def nth(self, i): return self.items[i]
        def is_visible(self, **_): return True
        def text_content(self, **_): return self.text
        def get_attribute(self, key, **_): return {"alt":"wrong", "src":"https://old"}.get(key)
        def all(self): return self.items
    class P:
        def locator(self, selector):
            if "title" in selector: return L("T")
            if "digest" in selector: return L("D")
            if "img" in selector: return L(items=[])
            return L("正文")
    assert not BrowserPublisher(tmp_path)._verify_editor_content(P(), article)


def test_readback_requires_actual_digest_control(tmp_path):
    image = tmp_path / "a.png"; image.write_bytes(b"x")
    article = Article.from_dict({"title":"T", "body":"正文", "digest":"explicit", "cover_image":str(image)})
    class L:
        @property
        def first(self): return self
        def count(self): return 1
        @property
        def last(self): return self
        def inner_text(self, **_): return "T"
        def text_content(self, **_): return "T"
        def is_visible(self, **_): return True
        def all(self): return [self]
        def get_attribute(self, key): return "https://cover" if key in {"src", "data-cover-url"} else None
    class P:
        def locator(self, selector):
            if "title" in selector: return L()
            if "摘要" in selector or "data-article-digest" in selector: return type("Missing", (), {"count":lambda self:0})()
            if "img" in selector: return type("Images", (), {"count":lambda self:0})()
            return L()
    assert not BrowserPublisher(tmp_path)._verify_editor_content(P(), article)


def test_upload_aliases_are_path_bound_and_unique(tmp_path):
    a=tmp_path/"a.png"; b=tmp_path/"b.png"; a.write_bytes(b"a"); b.write_bytes(b"b")
    article=Article.from_dict({"title":"T", "body":"{{asset:a}} {{asset:b}}", "assets":[{"alias":"a","path":str(a)},{"alias":"b","path":str(b)}]})
    calls=[]
    class P:
        def upload_asset(self, alias, path): calls.append((alias,path)); return f"https://mp.weixin.qq.com/{alias}"
    adapter=type("A", (), {"upload_asset": lambda _, page, alias, path: page.upload_asset(alias, path), "save_draft": lambda *_: None, "reopen_draft": lambda *_: None})()
    urls=BrowserPublisher(tmp_path, adapter=adapter).upload_body_assets(P(), article)
    assert urls == {"a":"https://mp.weixin.qq.com/a", "b":"https://mp.weixin.qq.com/b"}
    assert calls == [("a",a),("b",b)]


def test_upload_rejects_duplicate_url(tmp_path):
    a=tmp_path/"a.png"; b=tmp_path/"b.png"; a.write_bytes(b"a"); b.write_bytes(b"b")
    article=Article.from_dict({"title":"T", "body":"{{asset:a}} {{asset:b}}", "assets":[{"alias":"a","path":str(a)},{"alias":"b","path":str(b)}]})
    class P:
        def upload_asset(self, alias, path): return "https://mp.weixin.qq.com/same"
    with pytest.raises(RuntimeError, match="重复"):
        adapter=type("A", (), {"upload_asset": lambda _, page, alias, path: page.upload_asset(alias, path), "save_draft": lambda *_: None, "reopen_draft": lambda *_: None})()
        BrowserPublisher(tmp_path, adapter=adapter).upload_body_assets(P(), article)


def test_query_only_publish_id_does_not_checkpoint_or_submit():
    class S:
        def request(self, method, url, timeout, **kwargs):
            class R:
                status_code=200
                def json(self):
                    if "/cgi-bin/token" in url: return {"access_token":"t"}
                    return {"publish_status":0,"article_id":"a"}
            return R()
    calls=[]; api=WeChatAPI("i","s",session=S(),poll_interval=0,poll_timeout=1)
    api.submission_checkpoint=lambda *_: calls.append("checkpoint")
    api.publish_id_checkpoint=lambda *_: calls.append("saved")
    api.submit_publish=lambda *_: calls.append("submit") or "new"
    result=api.publish_draft("draft", confirm_publish=True, publish_id="known")
    assert result.status is PublishStatus.PUBLISHED and result.publish_id=="known"
    assert calls == []


def test_transition_reuses_outer_lock(tmp_path):
    store=RunStore(tmp_path/"profile"); store.create("wx-lock")
    with ProfileLock(tmp_path/"profile") as lock:
        record=store.transition("wx-lock", ("running",), "submitting", lock=lock, submit_started_at=1.0)
    assert record.status == "submitting"


def test_cleanup_default_is_dry_run(tmp_path):
    store=RunStore(tmp_path/"profile"); store.create("wx-clean")
    store.update("wx-clean", status="failed")
    assert store.cleanup(older_than=0) == {"runs":1,"files":0}
    assert store.path("wx-clean").exists()
