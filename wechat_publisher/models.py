"""Input and output models for the publisher."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


class ValidationError(ValueError):
    """Raised when an article payload cannot be published safely."""


class PublishStatus(str, Enum):
    PUBLISHED = "published"
    DRAFT_CREATED = "draft_created"
    LOGIN_REQUIRED = "login_required"
    AWAITING_SCAN = "awaiting_scan"
    VERIFICATION_EXPIRED = "verification_expired"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Asset:
    alias: str
    path: Path

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, base_dir: Optional[Path] = None) -> "Asset":
        if not isinstance(value, Mapping):
            raise ValidationError("每个 asset 必须是对象")
        alias = str(value.get("alias", "")).strip()
        path_value = value.get("path")
        if not alias:
            raise ValidationError("asset.alias 不能为空")
        if not path_value:
            raise ValidationError(f"asset {alias!r} 缺少 path")
        path = Path(str(path_value)).expanduser()
        if not path.is_absolute() and base_dir is not None:
            path = base_dir / path
        path = path.resolve()
        if not path.is_file():
            raise ValidationError(f"asset 文件不存在: {path}")
        return cls(alias=alias, path=path)


@dataclass(frozen=True)
class Article:
    title: str
    body: str
    body_format: str = "markdown"
    digest: str = ""
    author: str = ""
    source_url: str = ""
    need_open_comment: bool = False
    only_fans_can_comment: bool = False
    cover_image: Optional[Path] = None
    assets: List[Asset] = field(default_factory=list)
    publish: bool = False

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, base_dir: Optional[Path] = None) -> "Article":
        if not isinstance(value, Mapping):
            raise ValidationError("文章输入必须是 JSON 对象")

        title_value = value.get("title", "")
        body_value = value.get("body", "")
        title = str(title_value).strip() if title_value is not None else ""
        body = str(body_value) if body_value is not None else ""
        body_format = str(value.get("body_format", "markdown")).lower().strip()
        if not title:
            raise ValidationError("title 不能为空")
        if not body.strip():
            raise ValidationError("body 不能为空")
        if body_format not in {"markdown", "html"}:
            raise ValidationError("body_format 只能是 markdown 或 html")

        cover_value = value.get("cover_image")
        cover_image = None
        if cover_value:
            cover_image = Path(str(cover_value)).expanduser()
            if not cover_image.is_absolute() and base_dir is not None:
                cover_image = base_dir / cover_image
            cover_image = cover_image.resolve()
            if not cover_image.is_file():
                raise ValidationError(f"cover_image 文件不存在: {cover_image}")

        raw_assets = value.get("assets", []) or []
        if not isinstance(raw_assets, Iterable) or isinstance(raw_assets, (str, bytes, Mapping)):
            raise ValidationError("assets 必须是数组")
        assets = [Asset.from_dict(item, base_dir=base_dir) for item in raw_assets]
        aliases = [asset.alias for asset in assets]
        if len(aliases) != len(set(aliases)):
            raise ValidationError("assets.alias 不能重复")

        referenced = _asset_references(body)
        missing = sorted(referenced.difference(aliases))
        if missing:
            raise ValidationError(f"正文引用了未声明的 asset: {', '.join(missing)}")

        digest = str(value.get("digest", "") or "").strip() or derive_digest(body)
        if cover_image is None and assets:
            cover_image = assets[0].path

        return cls(
            title=title,
            body=body,
            body_format=body_format,
            digest=digest,
            author=str(value.get("author", "") or "").strip(),
            source_url=str(value.get("source_url", value.get("content_source_url", "")) or "").strip(),
            need_open_comment=_strict_bool(value.get("need_open_comment", False), "need_open_comment"),
            only_fans_can_comment=_strict_bool(value.get("only_fans_can_comment", False), "only_fans_can_comment"),
            cover_image=cover_image,
            assets=assets,
            publish=_strict_bool(value.get("publish", False), "publish"),
        )

    @classmethod
    def from_json_file(cls, path: Path) -> "Article":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"无法读取文章 JSON: {path}: {exc}") from exc
        return cls.from_dict(value, base_dir=path.parent.resolve())

    def asset_map(self) -> Dict[str, Path]:
        return {asset.alias: asset.path for asset in self.assets}

    def fingerprint(self) -> str:
        """Return a content identity that is independent of local file paths."""
        digest = hashlib.sha256()
        for value in (
            self.title,
            self.body_format,
            self.digest,
            self.author,
            self.source_url,
            str(self.need_open_comment),
            str(self.only_fans_can_comment),
            self.body,
        ):
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
        if self.cover_image:
            digest.update(b"cover\0")
            digest.update(_file_digest(self.cover_image).encode("ascii"))
        for asset in self.assets:
            digest.update(asset.alias.encode("utf-8"))
            digest.update(b"\0")
            digest.update(_file_digest(asset.path).encode("ascii"))
        return digest.hexdigest()

    def confirmation_summary(self) -> Dict[str, Any]:
        """Return safe metadata for the final external-side-effect review."""
        return {
            "title": self.title,
            "body_format": self.body_format,
            "digest": self.digest,
            "author": self.author,
            "source_url": self.source_url,
            "need_open_comment": self.need_open_comment,
            "only_fans_can_comment": self.only_fans_can_comment,
            "cover_image": str(self.cover_image) if self.cover_image else None,
            "assets": [asset.alias for asset in self.assets],
            "body_preview": derive_digest(self.body, limit=160),
            "publish": self.publish,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "body_format": self.body_format,
            "digest": self.digest,
            "author": self.author,
            "source_url": self.source_url,
            "need_open_comment": self.need_open_comment,
            "only_fans_can_comment": self.only_fans_can_comment,
            "cover_image": str(self.cover_image) if self.cover_image else None,
            "assets": [{"alias": asset.alias, "path": str(asset.path)} for asset in self.assets],
            "publish": self.publish,
        }


@dataclass(frozen=True)
class PublishResult:
    status: PublishStatus
    provider: str
    message: str = ""
    qrcode_path: Optional[str] = None
    draft_id: Optional[str] = None
    publish_id: Optional[str] = None
    article_id: Optional[str] = None
    error_code: Optional[str] = None
    run_id: Optional[str] = None
    stage: Optional[str] = None
    expires_at: Optional[float] = None
    generation: int = 0
    next_action: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {PublishStatus.PUBLISHED, PublishStatus.DRAFT_CREATED}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "provider": self.provider,
            "message": self.message,
            "qrcode_path": self.qrcode_path,
            "draft_id": self.draft_id,
            "publish_id": self.publish_id,
            "article_id": self.article_id,
            "error_code": self.error_code,
            "run_id": self.run_id,
            "stage": self.stage,
            "expires_at": self.expires_at,
            "generation": self.generation,
            "next_action": self.next_action,
            "metadata": self.metadata,
        }


def _asset_references(body: str) -> set[str]:
    import re
    # Fenced code is literal text, not an image instruction.
    body = re.sub(r"(?:```|~~~).*?(?:```|~~~)", "", body, flags=re.S)
    body = "\n".join(line for line in body.splitlines() if not re.match(r"^(?: {4}|\t)", line))
    return set(re.findall(r"\{\{asset:([A-Za-z0-9_.-]+)\}\}", body))


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field_name} 必须是 JSON boolean")
    return value


def derive_digest(body: str, *, limit: int = 120) -> str:
    """Create a short WeChat digest without changing the article body.

    The digest is only a default for callers that omit one. Markdown image
    markers, asset tokens, HTML tags, and formatting punctuation are removed
    so the result remains readable in the article list.
    """
    import html
    import re

    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", body)
    text = re.sub(r"\{\{asset:[A-Za-z0-9_.-]+\}\}", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[#*_`~>\[\]()]+", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
