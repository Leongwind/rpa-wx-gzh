# WeChat API notes

The API adapter uses the Official Account endpoints for:

- `cgi-bin/token` to obtain an app credential access token;
- `cgi-bin/material/add_material` to upload the cover image;
- `cgi-bin/media/uploadimg` to upload images referenced by article HTML;
- `cgi-bin/draft/add` to create an article draft;
- `cgi-bin/freepublish/submit` and `cgi-bin/freepublish/get` to submit and poll publication.

The draft payload also supports the safe subset of article metadata exposed by
this publisher: `author`, `content_source_url`, `need_open_comment`, and
`only_fans_can_comment`. The browser fallback reports these options as
unsupported instead of silently dropping them.

The account must have the corresponding Official Account API permissions. API
errors before submission may fall back to the browser provider in `auto` mode.
After submission, the publisher returns `unknown` on an ambiguous result and
must not start a second publication attempt automatically.

`freepublish/get` uses `publish_status=0` for success, `1` for in-progress,
and `2` through `6` for terminal failure/deletion/ban states. Other values are
`unknown`; `1` is never reported as published. Body images must be uploaded
through WeChat and may not remain local `file://` URLs. Browser notification
settings are fail-closed: publication stops with
`notification_state_unverified` unless disabled state is observed. Drafts are
reported only after save, reopen, and read-back verification. `unknown`,
`submitting`, and `verification_expired` runs are protected from automatic
resubmission; resume queries a known publication reference only.

Do not store `appid`, `appsecret`, access tokens, cookies, or browser profile
data in this Skill or in the repository.

Browser test integrations use the explicit `BrowserDraftAdapter` protocol. The
default browser implementation does not inspect mock callback attributes on a
Page; it uses the real saved-draft editor flow.
The browser editor also writes and verifies the article digest before saving;
missing or unverifiable digest controls fail closed.
