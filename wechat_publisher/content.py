"""Article body rendering and local asset substitution."""

from __future__ import annotations

import html
import re
from typing import Mapping

try:
    import markdown as markdown_lib
except ImportError:  # pragma: no cover - exercised by the CLI dependency check
    markdown_lib = None

from .models import Article, ValidationError


ASSET_TOKEN = re.compile(r"\{\{asset:([A-Za-z0-9_.-]+)\}\}")


def render_html(article: Article, image_urls: Mapping[str, str]) -> str:
    """Render an article as WeChat-compatible HTML.

    ``image_urls`` is supplied by the API adapter after uploading assets. The
    browser adapter can use the same result after it has uploaded images into
    the editor and obtained their resulting URLs.
    """

    if article.body_format == "markdown":
        if markdown_lib is None:
            raise ValidationError("Markdown 输入需要安装 markdown 依赖")
        rendered = markdown_lib.markdown(article.body, extensions=["extra"])
    else:
        rendered = article.body

    referenced = set(ASSET_TOKEN.findall(rendered))
    missing = sorted(referenced.difference(image_urls))
    if missing:
        raise ValidationError(f"正文引用的图片没有上传成功: {', '.join(missing)}")

    def replace(match: re.Match[str]) -> str:
        alias = match.group(1)
        url = html.escape(str(image_urls[alias]), quote=True)
        alt = html.escape(alias, quote=True)
        return f'<p><img src="{url}" alt="{alt}" /></p>'

    return ASSET_TOKEN.sub(replace, rendered)


def render_browser_html(article: Article) -> str:
    """Render body with local file URLs for a browser fixture or preview.

    The live publisher replaces these URLs through the platform's upload
    controls; this function is intentionally deterministic and testable.
    """

    urls = {alias: path.as_uri() for alias, path in article.asset_map().items()}
    return render_html(article, urls)
