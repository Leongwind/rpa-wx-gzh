"""Compatibility entry point for the supported WeChat publisher."""

from wechat_publisher.cli import main as publisher_main


def main(argv=None):
    """Delegate all publishing work to the API/Playwright publisher."""
    return publisher_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
