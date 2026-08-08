# WeChat API notes

The API adapter uses the Official Account endpoints for:

- `cgi-bin/token` to obtain an app credential access token;
- `cgi-bin/material/add_material` to upload the cover image;
- `cgi-bin/media/uploadimg` to upload images referenced by article HTML;
- `cgi-bin/draft/add` to create an article draft;
- `cgi-bin/freepublish/submit` and `cgi-bin/freepublish/get` to submit and poll publication.

The account must have the corresponding Official Account API permissions. API
errors before submission may fall back to the browser provider in `auto` mode.
After submission, the publisher returns `unknown` on an ambiguous result and
must not start a second publication attempt automatically.

Do not store `appid`, `appsecret`, access tokens, cookies, or browser profile
data in this Skill or in the repository.
