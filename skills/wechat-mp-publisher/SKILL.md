---
name: wechat-mp-publisher
description: Create a WeChat Official Account article from the user's current request, local files, or conversation attachments, then create a draft or publish it through the official API or isolated Playwright session. Use when the user asks to write, draft, send, or publish a public-account article.
---

# WeChat Official Account Publisher

Use the repository's API/Playwright publisher. Do not call the legacy Selenium
flow in `main.py` or `modules/login.py`.

## Build the article from the current request

The article is supplied by the user; never reuse `article.acceptance.json`, a
fixed title/body, or the `test_pic` directory as implicit input.

1. Extract the title, body, requested format, digest, cover, and images from the
   current request. The title and non-empty body are required. Ask for the
   title if it is missing. Use Markdown when no format is specified.
2. For an omitted digest, let the publisher derive one from the cleaned first
   120 characters of the body. An explicitly supplied digest always wins.
3. Resolve local files and conversation attachments to absolute paths. If no
   cover is specified, use the first supplied image as the cover. Do not
   download network URLs in this version.
4. Do not insert attached images into the body merely because they exist. Add
   a body image only when the user specifies its position with
   `{{asset:name}}` or Markdown such as `![说明]({{asset:name}})`; declare the
   matching asset with its absolute path.
5. Write the normalized payload to an ignored temporary path such as
   `playwright_data/inputs/<unique-id>.json`. Do not put user content,
   credentials, or generated inputs in the Skill directory or Git history.

Payload shape:

```json
{
  "title": "用户提供的标题",
  "body": "用户提供的正文，可使用 {{asset:image1}}",
  "body_format": "markdown",
  "digest": "可选摘要",
  "cover_image": "/absolute/path/cover.png",
  "assets": [{"alias": "image1", "path": "/absolute/path/image1.png"}],
  "publish": false
}
```

When the user only asks to write or prepare an article, set `publish` to
`false` and use draft mode. Only an explicit request to publish/send, followed
by confirmation of the external side effect, may set `publish` to `true` and
pass `--confirm-publish`.

## Run and report

Use the active Anaconda environment and the generated input:

```bash
python -m wechat_publisher publish \
  --input playwright_data/inputs/<unique-id>.json \
  --mode auto \
  --json
```

For a confirmed real publication, add `--confirm-publish`. For an explicit
draft request, use `--mode draft`. The CLI also accepts `--input -` when a
caller supplies the JSON through standard input.

If the result is `awaiting_scan`, render the absolute `qrcode_path` as an
in-conversation image card. Show the article title, scan stage, next action,
and expiry countdown; tell the user to scan that card. The isolated Chrome
window is only a fallback and diagnostics surface. The background watcher
checks the scan automatically.

Handle results as follows:

- `published`: report success only when the publisher explicitly verified it.
- `draft_created`: report the draft result and that it was not publicly sent.
- `awaiting_scan`: show the current QR card; do not ask the user to locate a
  file or manually run `resume`.
- `admin_approval`: keep reporting that administrator confirmation is pending.
- `verification_expired`: keep the `run_id`; do not resubmit automatically.
- `unknown`: stop and ask the user to verify the Official Account console
  before any retry.
- `failed`: report the error code and actionable message.

## Session recovery and secrets

The isolated profile is `WX_PLAYWRIGHT_PROFILE` (default
`playwright_data/`). QR files, cookies, run records, and temporary article
inputs stay there and are ignored by Git. Credentials come only from
`WX_APPID` and `WX_APPSECRET` in the environment; never print or persist them.

Public recovery commands are:

```bash
python -m wechat_publisher status --run-id <run-id> --json
python -m wechat_publisher resume --run-id <run-id> --json
python -m wechat_publisher cancel --run-id <run-id> --json
```

The publisher uses unique QR files per `run_id` and generation, refreshes only
the current verification challenge once after expiry, and never clicks
`发表` again to resubmit an already submitted article.
