from pathlib import Path

import pytest

from wechat_publisher.content import render_browser_html, render_html, sanitize_html
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


def test_render_browser_html_does_not_expose_local_file_uri(tmp_path: Path):
    article = make_article(tmp_path)
    result = render_browser_html(article)
    assert "file://" not in result


def test_article_derives_digest_and_uses_first_asset_as_cover(tmp_path: Path):
    image = tmp_path / "attached.png"
    image.write_bytes(b"png")
    article = Article.from_dict(
        {
            "title": "动态标题",
            "body": "# 动态标题\n\n这是用户提供的正文。\n\n{{asset:attached}}",
            "assets": [{"alias": "attached", "path": str(image)}],
        }
    )

    assert article.cover_image == image.resolve()
    assert article.digest.startswith("动态标题 这是用户提供的正文")


def test_article_defaults_to_draft_and_fingerprint_changes_with_metadata(tmp_path: Path):
    article = Article.from_dict({"title": "安全默认", "body": "正文"})
    with_author = Article.from_dict({"title": "安全默认", "body": "正文", "author": "作者"})

    assert article.publish is False
    assert article.fingerprint() != with_author.fingerprint()


def test_asset_is_not_inserted_without_an_explicit_body_reference(tmp_path: Path):
    image = tmp_path / "attached.png"
    image.write_bytes(b"png")
    article = Article.from_dict(
        {
            "title": "只有封面",
            "body": "正文没有图片占位符",
            "assets": [{"alias": "attached", "path": str(image)}],
        }
    )

    assert "<img" not in render_browser_html(article)


def test_html_sanitizer_blocks_unquoted_protocols_and_svg():
    result = sanitize_html('<p onclick=x>ok</p><img src=javascript:alert(1) onerror=x><svg onload=x>bad</svg>')
    assert "onclick" not in result and "onerror" not in result
    assert "javascript" not in result and "svg" not in result


def test_code_fences_are_not_asset_instructions(tmp_path: Path):
    article = make_article(tmp_path, "~~~\n{{asset:literal}}\n~~~\n正文")
    assert "literal" not in article.asset_map()
