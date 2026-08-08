"""Input and output models for the publisher."""

from __future__ import annotations

import json
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
    def from_dict(cls, value: Mapping[str, Any]) -> "Asset":
        if not isinstance(value, Mapping):
            raise ValidationError("每个 asset 必须是对象")
        alias = str(value.get("alias", "")).strip()
        path_value = value.get("path")
        if not alias:
            raise ValidationError("asset.alias 不能为空")
        if not path_value:
            raise ValidationError(f"asset {alias!r} 缺少 path")
        path = Path(str(path_value)).expanduser().resolve()
        if not path.is_file():
            raise ValidationError(f"asset 文件不存在: {path}")
        return cls(alias=alias, path=path)


@dataclass(frozen=True)
class Article:
    title: str
    body: str
    body_format: str = "markdown"
    digest: str = ""
    cover_image: Optional[Path] = None
    assets: List[Asset] = field(default_factory=list)
    publish: bool = True

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Article":
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
            cover_image = Path(str(cover_value)).expanduser().resolve()
            if not cover_image.is_file():
                raise ValidationError(f"cover_image 文件不存在: {cover_image}")

        raw_assets = value.get("assets", []) or []
        if not isinstance(raw_assets, Iterable) or isinstance(raw_assets, (str, bytes, Mapping)):
            raise ValidationError("assets 必须是数组")
        assets = [Asset.from_dict(item) for item in raw_assets]
        aliases = [asset.alias for asset in assets]
        if len(aliases) != len(set(aliases)):
            raise ValidationError("assets.alias 不能重复")

        referenced = _asset_references(body)
        missing = sorted(referenced.difference(aliases))
        if missing:
            raise ValidationError(f"正文引用了未声明的 asset: {', '.join(missing)}")

        return cls(
            title=title,
            body=body,
            body_format=body_format,
            digest=str(value.get("digest", "") or "").strip(),
            cover_image=cover_image,
            assets=assets,
            publish=bool(value.get("publish", True)),
        )

    @classmethod
    def from_json_file(cls, path: Path) -> "Article":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"无法读取文章 JSON: {path}: {exc}") from exc
        return cls.from_dict(value)

    def asset_map(self) -> Dict[str, Path]:
        return {asset.alias: asset.path for asset in self.assets}


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
            "metadata": self.metadata,
        }


def _asset_references(body: str) -> set[str]:
    import re

    return set(re.findall(r"\{\{asset:([A-Za-z0-9_.-]+)\}\}", body))
