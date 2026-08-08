---
name: wechat-mp-publisher
description: Publish a WeChat Official Account article from structured JSON. Use when the user asks to create a draft or publish a public-account article with local images. Prefer the official API when WX_APPID/WX_APPSECRET are configured; otherwise use the Playwright persistent browser session and surface any QR-code scan step to the user.
---

# WeChat Official Account Publisher

Use the repository publisher rather than editing the legacy Selenium flow.

## Workflow

1. Validate the article JSON before opening a browser or calling an external API.
2. Use `python -m wechat_publisher publish --input <file> --mode auto --confirm-publish` for a real publication. The command returns a `run_id`; keep it for status, resume, or cancel. Omit `--confirm-publish` for validation or draft-only work.
3. Keep `WX_APPID` and `WX_APPSECRET` in the environment only. Never put them in article JSON, logs, skill files, or chat output.
4. If the result is `awaiting_scan`, render `qrcode_path` as an in-conversation image using its absolute path. Show a compact card with the article title, `stage`, `next_action`, and the `expires_at` countdown. Tell the user to scan the displayed QR; the isolated Chrome window is a fallback and diagnostics surface. Do not ask the user to find a file or run `resume` manually.
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
- `awaiting_scan`: show the current QR card and stage. A background watcher automatically checks the existing browser session for scan success; the session remains resumable through `run_id`.
- `verification_expired`: explain that the current verification challenge expired after the allowed refresh; keep the `run_id` and do not resubmit the article automatically.
- `failed`: report the error code and message.
- `unknown`: stop and ask the user to verify the publication in the Official Account console before retrying.

## Recovering a verification session

The browser publisher uses the isolated `WX_PLAYWRIGHT_PROFILE` directory and a local run registry under `playwright_data/sessions/`. It does not reuse the user's normal Chrome profile. If the initial command times out while the verification window is still open:

```bash
python -m wechat_publisher status --run-id <run_id> --json
python -m wechat_publisher resume --run-id <run_id> --json
python -m wechat_publisher cancel --run-id <run_id> --json
```

`resume` reattaches to the existing profile-owned Chrome window. `cancel` closes that window and marks the run cancelled. The publisher refreshes only the current verification challenge once after expiry; it never clicks “发表” again or resubmits the article. Never reuse an old QR image from a previous run; every QR uses the run ID and generation in its filename.

The scan stages are `login`, `publish_verification`, and `admin_approval`. Treat `admin_approval` as waiting for the administrator, not as a failure. Only an explicit `published` result is a successful publication.
