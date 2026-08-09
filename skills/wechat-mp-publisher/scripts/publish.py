#!/usr/bin/env python3
"""Thin Skill wrapper around the repository CLI."""

import os
from pathlib import Path
import subprocess
import sys


def find_repo_root(start: Path | None = None) -> Path | None:
    """Find the active checkout without assuming the Skill install path."""
    configured = os.getenv("WX_GZH_ROOT", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    current = (start or Path.cwd()).expanduser().resolve()
    candidates.extend([current, *current.parents])
    for candidate in candidates:
        if (candidate / "wechat_publisher" / "__main__.py").is_file():
            return candidate
    return None


def main() -> int:
    command = [sys.executable, "-m", "wechat_publisher", *sys.argv[1:]]
    root = find_repo_root()
    try:
        return subprocess.call(command, cwd=str(root) if root else None)
    except FileNotFoundError as exc:
        raise SystemExit(
            "找不到 wechat_publisher。请在项目仓库目录中运行，或设置 WX_GZH_ROOT，"
            "也可以在当前 Anaconda 环境执行 pip install -e <项目目录>。"
        ) from exc


if __name__ == "__main__":
    raise SystemExit(main())
