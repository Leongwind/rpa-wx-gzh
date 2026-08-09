"""Article body rendering and local asset substitution."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Mapping

try:
    import markdown as markdown_lib
except ImportError:  # pragma: no cover - exercised by the CLI dependency check
    markdown_lib = None

from .models import Article, ValidationError, _asset_references


ASSET_TOKEN = re.compile(r"\{\{asset:([A-Za-z0-9_.-]+)\}\}")
def sanitize_html(value: str) -> str:
    class AllowListParser(HTMLParser):
        allowed = {"p", "br", "strong", "em", "b", "i", "u", "s", "h1", "h2", "h3", "blockquote", "pre", "code", "ul", "ol", "li", "a", "img", "hr", "div", "span"}
        attrs = {"a": {"href", "title", "target"}, "img": {"src", "alt", "title", "width", "height"}}
        def __init__(self):
            super().__init__(convert_charrefs=True); self.out=[]; self.skip=0
        def handle_starttag(self, tag, attrs):
            tag=tag.lower()
            if self.skip: self.skip += 1; return
            if tag in {"script", "style", "iframe", "object", "embed", "svg", "math", "form", "base"}:
                self.skip=1; return
            if tag not in self.allowed: return
            clean=[]
            for key,val in attrs:
                key=key.lower(); val=html.unescape(val or "")
                if key not in self.attrs.get(tag,set()): continue
                if key in {"href","src"}:
                    normalized = re.sub(r"[\x00-\x20\u007f]+", "", val).lower()
                    if normalized.split(":", 1)[0] in {"javascript", "data", "file", "vbscript"}: continue
                clean.append((key, val))
            rendered="".join(f' {k}="{html.escape(v, quote=True)}"' for k,v in clean)
            self.out.append(f"<{tag}{rendered}{' /' if tag in {'img','br','hr'} else ''}>")
        def handle_endtag(self, tag):
            if self.skip:
                if tag.lower() in {"script","style","iframe","object","embed","svg","math","form","base"}: self.skip=0
                return
            if tag.lower() in self.allowed and tag.lower() not in {"img","br","hr"}: self.out.append(f"</{tag.lower()}>")
        def handle_data(self, data):
            if not self.skip: self.out.append(html.escape(data, quote=False))
    parser=AllowListParser(); parser.feed(value); parser.close(); return "".join(parser.out)


def render_html(article: Article, image_urls: Mapping[str, str]) -> str:
    """Render an article as WeChat-compatible HTML.

    ``image_urls`` is supplied by the API adapter after uploading assets. The
    browser adapter can use the same result after it has uploaded images into
    the editor and obtained their resulting URLs.
    """

    protected: dict[str, str] = {}
    body = article.body
    in_fence = False
    lines = []
    for line in body.splitlines(keepends=True):
        if line.strip().startswith(("```", "~~~")):
            in_fence = not in_fence
        if in_fence or line.startswith(("    ", "\t")):
            line = ASSET_TOKEN.sub(lambda m: _protect(m.group(0), protected), line)
        lines.append(line)
    body = "".join(lines)
    if article.body_format == "markdown":
        if markdown_lib is None:
            raise ValidationError("Markdown 输入需要安装 markdown 依赖")
        rendered = markdown_lib.markdown(body, extensions=["extra"])
    else:
        rendered = body

    rendered = sanitize_html(rendered)
    referenced = _asset_references(article.body)
    missing = sorted(referenced.difference(image_urls))
    if missing:
        raise ValidationError(f"正文引用的图片没有上传成功: {', '.join(missing)}")

    def replace(match: re.Match[str]) -> str:
        alias = match.group(1)
        url = html.escape(str(image_urls[alias]), quote=True)
        alt = html.escape(alias, quote=True)
        return f'<img src="{url}" alt="{alt}" />'

    rendered = ASSET_TOKEN.sub(replace, rendered)
    for marker, token in protected.items():
        rendered = rendered.replace(marker, token)
    return sanitize_html(rendered)


def _protect(token: str, protected: dict[str, str]) -> str:
    marker = f"WX_ASSET_LITERAL_{len(protected)}_WX"
    protected[marker] = token
    return marker


def render_browser_html(article: Article) -> str:
    """Render body with local file URLs for a browser fixture or preview.

    The live publisher replaces these URLs through the platform's upload
    controls; this function is intentionally deterministic and testable.
    """

    urls = {alias: path.as_uri() for alias, path in article.asset_map().items()}
    return render_html(article, urls)
