"""Small, local-only run registry for resumable browser sessions."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


def new_run_id() -> str:
    return f"wx-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


@dataclass
class RunRecord:
    run_id: str
    status: str
    provider: str = "browser"
    profile_dir: str = ""
    artifact_dir: str = ""
    debug_port: Optional[int] = None
    qrcode_path: Optional[str] = None
    message: str = ""
    error_code: Optional[str] = None
    result: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "provider": self.provider,
            "profile_dir": self.profile_dir,
            "artifact_dir": self.artifact_dir,
            "debug_port": self.debug_port,
            "qrcode_path": self.qrcode_path,
            "message": self.message,
            "error_code": self.error_code,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "RunRecord":
        fields = {field for field in cls.__dataclass_fields__}
        return cls(**{key: value[key] for key in fields if key in value})


class RunStore:
    """Persist run metadata under the ignored Playwright profile directory."""

    def __init__(self, profile_dir: Path) -> None:
        self.profile_dir = Path(profile_dir).expanduser().resolve()
        self.directory = self.profile_dir / "sessions"

    def path(self, run_id: str) -> Path:
        safe_id = "".join(char for char in run_id if char.isalnum() or char in "-_.")
        if not safe_id:
            raise ValueError("run_id 不能为空")
        return self.directory / f"{safe_id}.json"

    def create(self, run_id: Optional[str] = None, **fields: Any) -> RunRecord:
        record = RunRecord(
            run_id=run_id or new_run_id(),
            status="running",
            profile_dir=str(self.profile_dir),
            artifact_dir=str(self.profile_dir / "artifacts"),
            **fields,
        )
        self.save(record)
        return record

    def load(self, run_id: str) -> RunRecord:
        path = self.path(run_id)
        try:
            return RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError as exc:
            raise KeyError(f"找不到 run_id: {run_id}") from exc
        except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ValueError(f"无法读取 run_id: {run_id}") from exc

    def save(self, record: RunRecord) -> RunRecord:
        self.directory.mkdir(parents=True, exist_ok=True)
        record.updated_at = time.time()
        target = self.path(record.run_id)
        fd, temp_name = tempfile.mkstemp(prefix=f".{record.run_id}.", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
        return record

    def update(self, run_id: str, **fields: Any) -> RunRecord:
        record = self.load(run_id)
        for key, value in fields.items():
            if key not in record.__dataclass_fields__:
                raise ValueError(f"不支持的 run 字段: {key}")
            setattr(record, key, value)
        return self.save(record)

    def save_result(self, run_id: str, result: Any) -> RunRecord:
        payload = result.to_dict()
        return self.update(
            run_id,
            status=payload["status"],
            provider=payload["provider"],
            qrcode_path=payload.get("qrcode_path"),
            message=payload.get("message", ""),
            error_code=payload.get("error_code"),
            result=payload,
        )

    def active_records(self) -> list[RunRecord]:
        if not self.directory.is_dir():
            return []
        records: list[RunRecord] = []
        for path in sorted(self.directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                record = RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, KeyError):
                continue
            if record.status in {"running", "awaiting_scan", "unknown", "verification_expired"} and record.debug_port:
                records.append(record)
        return records
