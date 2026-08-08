#!/usr/bin/env python3
"""Thin Skill wrapper around the repository CLI."""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    command = [sys.executable, "-m", "wechat_publisher", *sys.argv[1:]]
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
