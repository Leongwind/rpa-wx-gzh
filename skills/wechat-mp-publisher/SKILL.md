---
name: wechat-mp-publisher
description: Publish a WeChat Official Account article from structured JSON. Use when the user asks to create a draft or publish a public-account article with local images. Prefer the official API when WX_APPID/WX_APPSECRET are configured; otherwise use the Playwright persistent browser session and surface any QR-code scan step to the user.
---

# WeChat Official Account Publisher

Use the repository publisher rather than editing the legacy Selenium flow.

## Workflow

1. Validate the article JSON before opening a browser or calling an external API.
2. Use `python -m wechat_publisher publish --input <file> --mode auto --confirm-publish` for a real publication. Omit `--confirm-publish` for validation or draft-only work.
3. Keep `WX_APPID` and `WX_APPSECRET` in the environment only. Never put them in article JSON, logs, skill files, or chat output.
4. If the result is `awaiting_scan`, show the returned `qrcode_path` and ask the user to scan it with WeChat. Do not claim success until the publisher returns `published`.
5. If the result is `unknown`, do not retry through another provider: the API may already have accepted the publication.

## Article input

```json
{
  "title": "文章标题",
  "body": "正文，可使用 {{asset:image1}}",
  "body_format": "markdown",
  "digest": "摘要",
  "cover_image": "/absolute/path/cover.png",
  "assets": [{"alias": "image1", "path": "/absolute/path/image1.png"}],
  "publish": true
}
```

Supported `body_format` values are `markdown` and `html`. All referenced asset aliases must be declared and point to existing local files.

## Result handling

- `published`: report the publication as successful.
- `draft_created`: report the draft ID and state that it was not publicly published.
- `awaiting_scan`: surface the QR path and keep the session available for a later retry.
- `verification_expired`: ask the user to rerun so a fresh QR code can be generated.
- `failed`: report the error code and message.
- `unknown`: stop and ask the user to verify the publication in the Official Account console before retrying.
