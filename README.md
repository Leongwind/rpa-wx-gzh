# 微信公众号文章发布器

这是一个用于微信公众号文章草稿和发布的 Skill。它可以从 Codex 当前对话中读取标题、正文和本地/对话附件，生成动态文章，并通过以下通道完成操作：

1. 已配置并具备权限时，优先使用微信公众号官方 API。
2. 未配置 API 或 API 权限不足时，使用独立的 Playwright 浏览器会话。

正式发布前必须明确确认外部发布副作用。首次浏览器登录和微信安全验证可能需要管理员扫码；二维码会展示在 Codex 对话中，浏览器窗口作为备用入口，后台 watcher 会自动监测结果。

## 从 0 开始：在 Codex 中使用 Skill

### 1. 安装 Skill

在 Codex 中打开本仓库，发送：

```text
请从 GitHub 仓库 Leongwind/rpa-wx-gzh 安装 skills/wechat-mp-publisher Skill。
```

安装完成后，Skill 文件位于：

```text
$CODEX_HOME/skills/wechat-mp-publisher/SKILL.md
```

也可以在 Codex 中直接使用 `$wechat-mp-publisher` 调用它。Skill 会优先从当前 Codex 工作区寻找本仓库；如果仓库不在当前目录，可以设置 `WX_GZH_ROOT`。可编辑安装 `pip install -e .` 后，也可以从其他目录使用 `wechat-publisher` 命令。

### 2. 创建独立的 Anaconda 环境

不要把依赖安装到系统 Python 或其他项目环境中：

```bash
git clone https://github.com/Leongwind/rpa-wx-gzh.git
cd rpa-wx-gzh

conda env create --override-channels -f environment.yml
conda activate rpa-wx-gzh
python -m playwright install chromium
python -m pip install -e .
```

确认当前 Python 来自该环境：

```bash
which python
python --version
```

如果已经创建过环境，后续只需：

```bash
conda activate rpa-wx-gzh
cd /path/to/rpa-wx-gzh
```

### 3. 在 Codex 中生成草稿

在已打开本仓库的 Codex 对话中，发送文章需求并附上本地图片。例如：

```text
$wechat-mp-publisher

写一篇微信公众号文章。
标题：周末徒步记录
正文：这是一段文章正文，默认使用 Markdown。
封面使用我附加的图片。
先保存为草稿，不要发布。
```

Skill 会自动完成以下工作：

- 从当前请求提取标题、正文、摘要和图片。
- 标题和非空正文缺一不可；标题缺失时会先询问。
- 未指定格式时按 Markdown 处理。
- 未提供摘要时，从清理 Markdown 后的正文开头提取最多 120 个字符。
- 未指定封面时，使用第一张本地图片或对话附件。
- 图片默认只作为封面，不会因为附加了图片就自动插入正文。
- 只有正文明确使用 `{{asset:name}}` 或 Markdown 图片标记时，图片才会插入指定位置。
- 本次输入会保存到被 Git 忽略的 `playwright_data/inputs/`，不会写入 Skill 或 Git 历史。

### 4. 确认后正式发布

草稿生成后，在同一对话中明确表达发布意图，例如：

```text
请发布刚才的文章，我确认这次会产生公众号正式发布副作用。
```

Skill 只有在获得明确确认后，才会使用 `--confirm-publish` 进入正式发布流程。用户只说“写一篇”“准备一下”时，默认只创建草稿。

正式发布时可能经历：

1. 打开独立 Playwright Chrome 会话。
2. 首次使用时展示登录二维码，请使用运营者微信扫码。
3. 填写标题、正文、摘要和封面。
4. 发表前默认关闭“群发通知”，避免意外消耗每日通知次数。
5. 微信要求验证时，在 Codex 对话中展示本次运行专属二维码卡片。
6. 使用管理员微信扫码并完成确认。
7. Skill 自动监测发布结果，只有明确确认发布成功才返回 `published`。

不要扫描旧的二维码文件，也不需要手动执行 `resume`；如果对话环境无法主动推送状态，保留 `run_id` 后再用状态命令恢复即可。

## 文章输入规则

Skill 适合自然语言调用；需要批量处理或精确复现时，也可以准备 JSON 文件：

```json
{
  "title": "文章标题",
  "body": "正文内容\n\n![正文图片]({{asset:image1}})",
  "body_format": "markdown",
  "digest": "可选摘要",
  "author": "可选作者",
  "source_url": "https://example.com/source",
  "need_open_comment": false,
  "only_fans_can_comment": false,
  "cover_image": "/absolute/path/cover.png",
  "assets": [
    {"alias": "image1", "path": "/absolute/path/body.png"}
  ],
  "publish": false
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `title` | 必填，文章标题 |
| `body` | 必填，正文；默认 Markdown |
| `body_format` | `markdown` 或 `html` |
| `digest` | 可选；省略时自动提取正文前 120 个字符 |
| `author` | 可选作者；API 通道支持 |
| `source_url` | 可选原文链接；API 通道支持 |
| `need_open_comment` | 是否开启留言；API 通道支持 |
| `only_fans_can_comment` | 是否仅粉丝可留言；API 通道支持 |
| `cover_image` | 可选的本地封面绝对路径 |
| `assets` | 正文图片列表，`alias` 必须与正文占位符一致 |
| `publish` | 草稿使用 `false`；正式发布使用 `true`，并且还必须传 `--confirm-publish` |

本版本只支持本地文件和对话附件，不会自动下载网络图片。正文中没有明确插入位置的图片只会作为封面候选，不会自动追加到正文末尾。

## 命令行调用

所有命令都应在本仓库目录、`rpa-wx-gzh` Anaconda 环境中执行。

### 创建草稿

```bash
conda activate rpa-wx-gzh
python -m wechat_publisher publish \
  --input article.json \
  --mode draft \
  --json
```

如果准备和正式发布之间会间隔较长，建议使用两阶段流程。第一步只创建草稿并返回 `run_id`；第二步会重新打开保存的草稿、校验内容，再进入发表确认，不依赖之前一直打开的编辑页面：

```bash
python -m wechat_publisher publish \
  --input article.json \
  --mode draft \
  --json

python -m wechat_publisher publish \
  --run-id <run-id> \
  --confirm-publish \
  --json
```

正式发布前可以只查看摘要，不打开浏览器、不调用 API：

```bash
python -m wechat_publisher publish \
  --input article.json \
  --mode auto \
  --preview \
  --json
```

### 自动选择 API 或浏览器发布

```bash
python -m wechat_publisher publish \
  --input article.json \
  --mode auto \
  --confirm-publish \
  --json
```

如果没有 API 凭证，或 API 通道不可用，`auto` 会回退到浏览器通道。API 已经提交但结果未知时不会自动回退浏览器，以避免重复发布。

同一篇文章如果已经有运行中的发布会话、未知结果或已确认发布记录，系统会默认阻止再次发布。确认公众号后台没有重复发布后，确实需要再次发送时才使用：

```bash
python -m wechat_publisher publish \
  --input article.json \
  --mode auto \
  --confirm-publish \
  --force-republish \
  --json
```

### 指定通道

```bash
python -m wechat_publisher publish --input article.json --mode api --json
python -m wechat_publisher publish --input article.json --mode browser --json
```

也支持从标准输入读取 JSON：

```bash
python -m wechat_publisher publish \
  --input - \
  --mode draft \
  --json < article.json
```

## 扫码、状态和恢复

结果状态包括：

| 状态 | 含义 |
| --- | --- |
| `published` | 已通过成功提示或公众号发布记录确认正式发布 |
| `draft_created` | 已创建草稿，没有公开发布 |
| `awaiting_scan` | 正在等待登录、发布验证或管理员确认扫码 |
| `verification_expired` | 当前二维码过期；不会重新提交文章 |
| `unknown` | 平台结果不明确，必须先去公众号后台核实，不能立即重试 |
| `failed` | 有明确错误原因，需要根据 `error_code` 处理 |

`awaiting_scan` 返回的结构化结果包含 `run_id`、`stage`、`qrcode_path`、`expires_at`、`generation` 和 `next_action`。常见阶段为：

- `login`：运营者微信扫码登录。
- `publish_verification`：微信安全验证。
- `admin_approval` 是扫码流程中的 stage，不是顶层发布结果状态；页面行为仅由本地 mock seam 验证，未宣称真实微信页面已验证。

如果需要手动查看状态：

```bash
python -m wechat_publisher status --run-id <run-id> --json
python -m wechat_publisher resume --run-id <run-id> --json
python -m wechat_publisher cancel --run-id <run-id> --json
python -m wechat_publisher cleanup --older-than 604800 --json
```

二维码按 `run_id + generation` 生成。二维码过期时最多自动刷新一次，只刷新当前验证挑战，不会再次点击“发表”或重复提交文章。

## 可选：官方 API 配置

如果公众号账号具备对应接口权限，可以在当前终端设置凭证：

```bash
export WX_APPID="公众号 AppID"
export WX_APPSECRET="公众号 AppSecret"
```

凭证只从环境变量读取，不要写入文章 JSON、README、Skill 文件、日志或 Git。API 通道还可能需要公众号后台配置服务器 IP 白名单，并具备素材上传、草稿和发布相关权限。具体接口说明见 [微信 API 参考](skills/wechat-mp-publisher/references/wechat-api.md)。

未配置 API 时无需填写这些变量，浏览器通道会使用独立的 Playwright 会话。

## 会话目录和环境变量

默认情况下，以下内容保存在被 `.gitignore` 忽略的 `playwright_data/`：

- Playwright 登录 Cookie 和浏览器配置。
- 二维码及诊断截图。
- 发布 run 记录和 watcher 状态。
- 动态生成的文章 JSON。

可按需配置：

```bash
export WX_PLAYWRIGHT_PROFILE="/absolute/path/wechat-playwright-profile"
export WX_PLAYWRIGHT_EXECUTABLE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
export WX_SCAN_TIMEOUT="300"
export WX_QR_TTL="120"
export WX_QR_REFRESH_LIMIT="1"
```

不要把正在运行的 Chrome/Edge 用户目录设置为 `WX_PLAYWRIGHT_PROFILE`，否则可能产生配置文件锁冲突。项目会使用独立目录。
同一个 Playwright profile 同时只能运行一个发布任务；如果返回 `profile_busy`，先等待已有任务结束，或为不同账号设置不同的 profile 目录。

## 常见问题

### 为什么没有自动发送？

“写一篇”“准备文章”“保存一下”默认是草稿。必须明确要求正式发布并确认外部副作用，Skill 才会进入发布流程。

### 为什么需要扫码？

这是微信公众号平台的登录或安全验证要求。Skill 不绕过扫码，只负责展示当前二维码、保持浏览器会话并自动监测结果。

### 二维码过期怎么办？

优先使用对话中最新的二维码。系统最多自动刷新一次；如果返回 `verification_expired`，保留 `run_id`，先确认公众号后台没有已经发布，再决定是否重新执行。

### 返回 `unknown` 怎么办？

不要立即重试。先在公众号后台的“发表记录”或“草稿”中确认文章是否已经提交，避免重复发布。

### 看到旧 Selenium 文件怎么办？

`modules/` 和旧入口仅作为历史兼容代码保留。Skill 和 README 中的正式路径统一使用 `python -m wechat_publisher`，不会调用旧 Selenium 流程。

## 开发和验证

```bash
conda activate rpa-wx-gzh
pytest -q
codegraph sync
```

Skill 定义见 [skills/wechat-mp-publisher/SKILL.md](skills/wechat-mp-publisher/SKILL.md)，兼容入口 [main.py](main.py) 只负责转发到新版 CLI。

浏览器草稿的 mock seam 使用 `BrowserDraftAdapter` 显式注入；生产默认路径通过 Playwright 保存并重新打开草稿。回读会逐个核对本次上传的正文图片 alias/URL 以及封面资源身份。
新建文章会在保存前写入并确认 `Article.digest`（包括派生摘要）；摘要控件缺失或写入结果无法确认时，流程 fail-closed。
Cleanup is dry-run by default; use `cleanup --apply` only after reviewing the
reported files. `doctor --json` performs local, side-effect-free diagnostics
without opening WeChat or reading credential values. Browser drafts require
save, leave/reopen through the draft seam, and read-back verification of the
actual digest, cover, and body image aliases. Final publication requires the
same read-back and an observed disabled notification guard; these guarantees
are covered by local mock seams.
