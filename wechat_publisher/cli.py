"""Command-line entry point for the publisher."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import Article, PublishStatus, ValidationError
from .publisher import AutoPublisher
from .session import new_run_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="微信公众号文章发布器")
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish = subparsers.add_parser("publish", help="发布或创建公众号文章草稿")
    publish.add_argument("--input", required=True, type=Path, help="文章 JSON 文件；传 - 从标准输入读取")
    publish.add_argument("--mode", choices=["auto", "api", "browser", "draft"], default="auto")
    publish.add_argument("--confirm-publish", action="store_true", help="允许产生真实发布副作用")
    publish.add_argument("--json", action="store_true", help="只输出 JSON 结果")
    resume = subparsers.add_parser("resume", help="恢复一个仍在浏览器中的发布验证会话")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--json", action="store_true")
    status = subparsers.add_parser("status", help="查看发布会话状态")
    status.add_argument("--run-id", required=True)
    status.add_argument("--json", action="store_true")
    cancel = subparsers.add_parser("cancel", help="关闭并取消发布会话")
    cancel.add_argument("--run-id", required=True)
    cancel.add_argument("--json", action="store_true")
    watcher = subparsers.add_parser("_watch", help=argparse.SUPPRESS)
    watcher.add_argument("--run-id", required=True)
    subparsers._choices_actions = [
        action for action in subparsers._choices_actions if action.dest != "_watch"
    ]
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    publisher = AutoPublisher.from_environment()
    if args.command == "_watch":
        result = publisher.watch(args.run_id)
        print(json.dumps(result.to_dict(), ensure_ascii=False))
        return 0 if result.status in {PublishStatus.PUBLISHED, PublishStatus.DRAFT_CREATED} else 1
    if args.command == "status":
        try:
            payload = publisher.status(args.run_id)
        except (KeyError, ValueError) as exc:
            payload = {"status": PublishStatus.FAILED.value, "error_code": "run_not_found", "message": str(exc)}
            print(json.dumps(payload, ensure_ascii=False, indent=not args.json))
            return 1
        print(json.dumps(payload, ensure_ascii=False, indent=not args.json))
        return 0
    if args.command == "cancel":
        try:
            payload = publisher.cancel(args.run_id)
        except (KeyError, ValueError) as exc:
            payload = {"status": PublishStatus.FAILED.value, "error_code": "run_not_found", "message": str(exc)}
            print(json.dumps(payload, ensure_ascii=False, indent=not args.json))
            return 1
        print(json.dumps(payload, ensure_ascii=False, indent=not args.json))
        return 0
    if args.command == "resume":
        result = publisher.resume(args.run_id)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=not args.json))
        if result.qrcode_path:
            print(f"二维码/诊断截图: {result.qrcode_path}", file=sys.stderr)
        if result.status in {PublishStatus.PUBLISHED, PublishStatus.DRAFT_CREATED}:
            return 0
        if result.status in {PublishStatus.AWAITING_SCAN, PublishStatus.VERIFICATION_EXPIRED, PublishStatus.LOGIN_REQUIRED}:
            return 2
        return 1
    if args.command != "publish":
        return 2
    try:
        if str(args.input) == "-":
            try:
                payload = json.load(sys.stdin)
            except (OSError, json.JSONDecodeError) as exc:
                raise ValidationError(f"无法从标准输入读取文章 JSON: {exc}") from exc
            article = Article.from_dict(payload)
        else:
            article = Article.from_json_file(args.input)
    except ValidationError as exc:
        result = {"status": PublishStatus.FAILED.value, "error_code": "invalid_article", "message": str(exc)}
        print(json.dumps(result, ensure_ascii=False))
        return 1

    run_id = new_run_id()
    result = publisher.publish(
        article,
        mode=args.mode,
        confirm_publish=args.confirm_publish,
        run_id=run_id,
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
