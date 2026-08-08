import io
import json
import sys

from wechat_publisher import cli
from wechat_publisher.models import PublishResult, PublishStatus


def test_cli_accepts_dynamic_article_from_stdin(monkeypatch, tmp_path):
    captured = {}

    class FakePublisher:
        def publish(self, article, *, mode, confirm_publish, run_id):
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
