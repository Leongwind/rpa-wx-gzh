# 微信公众号文章发布器

本项目提供微信公众号文章草稿和发布能力。正式入口是
`wechat_publisher` 和 `skills/wechat-mp-publisher`，会优先使用官方 API，未配置 API 凭证时使用独立的 Playwright 浏览器会话。

## 动态文章输入

Skill 会读取当前用户请求中的标题、正文、摘要和图片，不使用固定测试文案或 `test_pic` 目录。

- 标题和正文必填；正文默认按 Markdown 处理。
- 未提供摘要时自动取正文清理后的前 120 个字符。
- 未指定封面时使用第一张本地图片或对话附件。
- 附件默认只作为封面；正文图片使用 `{{asset:name}}` 或
  `![说明]({{asset:name}})` 指定位置。
- 用户只要求“写一篇”或“准备文章”时默认创建草稿；真实发布必须明确确认。

Skill 会把本次请求生成的文章 JSON 保存到被忽略的
`playwright_data/inputs/`，然后调用统一发布器。也可以直接准备如下 JSON：

```json
{
  "title": "文章标题",
  "body": "正文内容\n\n{{asset:image1}}",
  "body_format": "markdown",
  "digest": "可选摘要",
  "cover_image": "/absolute/path/cover.png",
  "assets": [{"alias": "image1", "path": "/absolute/path/image1.png"}],
  "publish": false
}
```

## 安装和运行

建议使用独立的 Anaconda 环境：

```bash
conda env create --override-channels -f environment.yml
conda activate rpa-wx-gzh
playwright install chromium
```

创建草稿：

```bash
python -m wechat_publisher publish \
  --input article.json \
  --mode draft \
  --json
```

确认后正式发布：

```bash
python -m wechat_publisher publish \
  --input article.json \
  --mode auto \
  --confirm-publish \
  --json
```

`--input -` 支持从标准输入读取 JSON。旧的 `main.py` 仅作为兼容入口，
会转发到同一套新版 CLI，不再启动旧 Selenium 固定流程。

## 登录、扫码和会话

浏览器会话默认保存到 `playwright_data/`，不会复用用户正在使用的 Chrome 配置。首次登录或发布验证可能需要扫码；Skill 会把二维码渲染为对话内图片卡片，后台 watcher 自动监测结果。

- `WX_SCAN_TIMEOUT`：扫码监测时间，默认 300 秒。
- `WX_QR_TTL`：二维码卡片有效时间，默认 120 秒。
- `WX_QR_REFRESH_LIMIT`：过期后自动刷新次数，默认 1 次。
- `WX_PLAYWRIGHT_PROFILE`：独立 Playwright 会话目录。
- `WX_PLAYWRIGHT_EXECUTABLE_PATH`：指定本机 Chrome/Edge 可执行文件。

会话仍可通过以下命令管理：

```bash
python -m wechat_publisher status --run-id <run-id> --json
python -m wechat_publisher resume --run-id <run-id> --json
python -m wechat_publisher cancel --run-id <run-id> --json
```

二维码按 `run_id` 和代数生成，过期刷新只刷新当前验证挑战，不会重新点击发表或重复提交文章。只有明确检测到发布成功才会返回 `published`；API 提交结果未知时不会自动回退浏览器。

## 凭证和安全

API 凭证只从环境变量读取：

```bash
export WX_APPID="..."
export WX_APPSECRET="..."
```

不要把凭证写入文章 JSON、Skill 文件、日志或 Git。浏览器 Cookie、二维码、会话记录和动态输入均保存在被 `.gitignore` 忽略的本地目录中。
