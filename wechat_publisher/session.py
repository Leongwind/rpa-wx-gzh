"""Small, local-only run registry for resumable browser sessions."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


class ProfileBusyError(RuntimeError):
    """Raised when another publisher is using the same browser profile."""


class ProfileLock:
    """Process lock for one isolated Playwright profile."""

    def __init__(self, profile_dir: Path, *, timeout: float = 15.0) -> None:
        self.profile_dir = Path(profile_dir).expanduser().resolve()
        self.timeout = timeout
        self.path = self.profile_dir / ".publisher.lock"
        self._handle = None

    def acquire(self) -> "ProfileLock":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                import fcntl

                handle = self.path.open("a+", encoding="utf-8")
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                handle.seek(0)
                handle.truncate()
                handle.write(f"pid={os.getpid()}\ntime={time.time()}\n")
                handle.flush()
                self._handle = handle
                return self
            except (BlockingIOError, OSError):
                try:
                    handle.close()
                except UnboundLocalError:
                    pass
                time.sleep(0.1)
        raise ProfileBusyError(f"Playwright profile 正在被其他发布任务使用: {self.profile_dir}")

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "ProfileLock":
        return self.acquire()

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.release()


def new_run_id() -> str:
    return f"wx-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


@dataclass
class RunRecord:
    run_id: str
    status: str
    provider: str = "browser"
    profile_dir: str = ""
    artifact_dir: str = ""
    article_path: Optional[str] = None
    article_title: Optional[str] = None
    fingerprint: Optional[str] = None
    confirmation_summary: Dict[str, Any] = field(default_factory=dict)
    debug_port: Optional[int] = None
    qrcode_path: Optional[str] = None
    stage: Optional[str] = None
    expires_at: Optional[float] = None
    generation: int = 0
    next_action: Optional[str] = None
    watcher_pid: Optional[int] = None
    watcher_status: str = "not_started"
    monitor_until: Optional[float] = None
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
            "article_path": self.article_path,
            "article_title": self.article_title,
            "fingerprint": self.fingerprint,
            "confirmation_summary": self.confirmation_summary,
            "debug_port": self.debug_port,
            "qrcode_path": self.qrcode_path,
            "stage": self.stage,
            "expires_at": self.expires_at,
            "generation": self.generation,
            "next_action": self.next_action,
            "watcher_pid": self.watcher_pid,
            "watcher_status": self.watcher_status,
            "monitor_until": self.monitor_until,
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
            stage=payload.get("stage"),
            expires_at=payload.get("expires_at"),
            generation=payload.get("generation", 0),
            next_action=payload.get("next_action"),
            message=payload.get("message", ""),
            error_code=payload.get("error_code"),
            result=payload,
        )

    def save_article(self, run_id: str, article: Any) -> str:
        record = self.load(run_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{record.run_id}.article.json"
        fd, temp_name = tempfile.mkstemp(prefix=f".{record.run_id}.article.", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(article.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
        self.update(
            run_id,
            article_path=str(path),
            article_title=article.title,
            fingerprint=article.fingerprint(),
            confirmation_summary=article.confirmation_summary(),
        )
        return str(path)

    def load_article(self, run_id: str) -> Any:
        from .models import Article

        record = self.load(run_id)
        if not record.article_path:
            raise ValueError(f"run 没有可恢复的文章快照: {run_id}")
        return Article.from_dict(json.loads(Path(record.article_path).read_text(encoding="utf-8")))

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

    def find_by_fingerprint(
        self,
        fingerprint: str,
        *,
        exclude_run_id: Optional[str] = None,
        statuses: tuple[str, ...] = ("running", "awaiting_scan", "unknown", "published"),
    ) -> Optional[RunRecord]:
        """Find the newest matching run that could cause a duplicate publish."""
        if not self.directory.is_dir():
            return None
        for path in sorted(self.directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                record = RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, KeyError):
                continue
            if record.run_id != exclude_run_id and record.fingerprint == fingerprint and record.status in statuses:
                return record
        return None

    def cleanup(self, *, older_than: float, now: Optional[float] = None) -> Dict[str, int]:
        """Remove only finished run records and their run-scoped artifacts."""
        now = now or time.time()
        protected = {"running", "awaiting_scan", "unknown", "verification_expired"}
        removed_runs = 0
        removed_files = 0
        if not self.directory.is_dir():
            return {"runs": 0, "files": 0}
        artifact_dir = self.profile_dir / "artifacts"
        for path in list(self.directory.glob("*.json")):
            try:
                record = RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, KeyError):
                continue
            if record.status in protected or now - record.updated_at < older_than:
                continue
            safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", record.run_id)
            for candidate in (path, self.directory / f"{safe_id}.article.json"):
                try:
                    candidate.unlink()
                    removed_files += 1
                except FileNotFoundError:
                    pass
            if artifact_dir.is_dir():
                for candidate in artifact_dir.glob(f"*{safe_id}*"):
                    try:
                        candidate.unlink()
                        removed_files += 1
                    except FileNotFoundError:
                        pass
            removed_runs += 1
        return {"runs": removed_runs, "files": removed_files}
