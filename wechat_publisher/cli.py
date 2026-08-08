"""Command-line entry point for the publisher."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import Article, PublishStatus, ValidationError
from .publisher import AutoPublisher


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="微信公众号文章发布器")
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish = subparsers.add_parser("publish", help="发布或创建公众号文章草稿")
    publish.add_argument("--input", required=True, type=Path, help="文章 JSON 文件")
    publish.add_argument("--mode", choices=["auto", "api", "browser", "draft"], default="auto")
    publish.add_argument("--confirm-publish", action="store_true", help="允许产生真实发布副作用")
    publish.add_argument("--json", action="store_true", help="只输出 JSON 结果")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "publish":
        return 2
    try:
        article = Article.from_json_file(args.input)
    except ValidationError as exc:
        result = {"status": PublishStatus.FAILED.value, "error_code": "invalid_article", "message": str(exc)}
        print(json.dumps(result, ensure_ascii=False))
        return 1

    result = AutoPublisher.from_environment().publish(
        article,
        mode=args.mode,
        confirm_publish=args.confirm_publish,
    )
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        if result.qrcode_path:
            print(f"二维码/诊断截图: {result.qrcode_path}", file=sys.stderr)
    if result.status in {PublishStatus.PUBLISHED, PublishStatus.DRAFT_CREATED}:
        return 0
    if result.status in {PublishStatus.AWAITING_SCAN, PublishStatus.VERIFICATION_EXPIRED, PublishStatus.LOGIN_REQUIRED}:
        return 2
    return 1
