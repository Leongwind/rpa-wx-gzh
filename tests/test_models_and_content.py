from pathlib import Path

import pytest

from wechat_publisher.content import render_browser_html, render_html
from wechat_publisher.models import Article, PublishStatus, ValidationError


def make_article(tmp_path: Path, body: str = "正文 {{asset:hero}}") -> Article:
    image = tmp_path / "hero.png"
    image.write_bytes(b"png")
    return Article.from_dict(
        {
            "title": "测试文章",
            "body": body,
            "body_format": "markdown",
            "cover_image": str(image),
            "assets": [{"alias": "hero", "path": str(image)}],
        }
    )


def test_article_validation_and_asset_reference(tmp_path: Path):
    article = make_article(tmp_path)
    assert article.title == "测试文章"
    assert article.asset_map()["hero"].name == "hero.png"

    with pytest.raises(ValidationError, match="未声明的 asset"):
        Article.from_dict({"title": "x", "body": "{{asset:nope}}"})


def test_render_html_replaces_asset_token(tmp_path: Path):
    article = make_article(tmp_path, "# 标题\n\n{{asset:hero}}")
    result = render_html(article, {"hero": "https://example.test/image.png"})
    assert "<h1>标题</h1>" in result
    assert 'src="https://example.test/image.png"' in result


def test_render_browser_html_uses_local_file_uri(tmp_path: Path):
    article = make_article(tmp_path)
    result = render_browser_html(article)
    assert "file://" in result
