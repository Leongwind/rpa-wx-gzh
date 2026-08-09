import io
import json
import sys

from wechat_publisher import cli
from wechat_publisher.models import PublishResult, PublishStatus


def test_cli_accepts_dynamic_article_from_stdin(monkeypatch, tmp_path):
    captured = {}

    class FakePublisher:
        def publish(self, article, *, mode, confirm_publish, run_id, force_republish):
            captured["article"] = article
            captured["mode"] = mode
            return PublishResult(PublishStatus.DRAFT_CREATED, "fake", "草稿创建成功", run_id=run_id)

    image = tmp_path / "cover.png"
    image.write_bytes(b"png")
    payload = {
        "title": "临时输入标题",
        "body": "临时输入正文",
        "assets": [{"alias": "cover", "path": str(image)}],
        "publish": False,
    }
    monkeypatch.setattr(cli.AutoPublisher, "from_environment", classmethod(lambda cls: FakePublisher()))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload, ensure_ascii=False)))

    exit_code = cli.main(["publish", "--input", "-", "--mode", "draft", "--json"])

    assert exit_code == 0
    assert captured["article"].title == "临时输入标题"
    assert captured["article"].cover_image == image.resolve()
    assert captured["article"].digest == "临时输入正文"


def test_cli_preview_never_calls_provider(monkeypatch, tmp_path, capsys):
    class FakePublisher:
        @classmethod
        def from_environment(cls):
            return cls()

        def publish(self, *args, **kwargs):
            raise AssertionError("preview 不应调用 provider")

    image = tmp_path / "cover.png"
    image.write_bytes(b"png")
    payload = {
        "title": "预览标题",
        "body": "预览正文",
        "cover_image": str(image),
        "publish": True,
    }
    monkeypatch.setattr(cli.AutoPublisher, "from_environment", FakePublisher.from_environment)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload, ensure_ascii=False)))

    assert cli.main(["publish", "--input", "-", "--preview", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "preview"
    assert output["confirmation_summary"]["title"] == "预览标题"
