# 微信公众号平台自动化登录工具

这个工具可以自动化登录微信公众号平台，并保持登录状态，方便后续操作。

## 功能特点

- 自动打开浏览器并访问微信公众号平台
- 生成二维码供用户扫码登录
- 保持登录状态，即使关闭浏览器后再次打开仍然保持登录
- 模块化设计，易于维护和扩展
- 自动填写文章标题和内容
- 自动插入图片
- 自动选择并设置封面
- 自动完成发布流程
- 处理微信验证二维码并截图保存
- **直接在控制台显示二维码**，无需打开图片文件

## 项目结构

```
rpa-wx-gzh/
├── README.md          # 项目说明文档
├── main.py            # 主程序入口
├── requirements.txt   # 项目依赖
├── config.py          # 配置文件
├── test_pic/          # 测试图片目录，放置要插入的图片
└── modules/           # 功能模块目录
    ├── __init__.py    # 模块初始化
    ├── browser.py     # 浏览器操作模块
    ├── login.py       # 登录功能模块
    └── utils.py       # 工具函数模块
```

## 环境要求

- Python 3.7+
- Chrome浏览器
- PIL库（用于图片处理和截图）
- qrcode库（用于控制台显示二维码）
- pyzbar库（用于解码二维码，可选）

## 安装依赖

```bash
pip install -r requirements.txt

# 如需控制台显示二维码功能，请额外安装：
pip install pillow qrcode pyzbar
```

## 使用方法

1. 安装所需依赖
2. 在项目根目录创建 `test_pic` 文件夹，放入要插入的图片（支持JPG, PNG, JPEG, GIF格式）
3. 运行主程序
   ```bash
   python main.py --browser edge --user-data-dir "D:\rpa-wx-gzh\browser_data"
   ```
4. 按照提示扫描二维码完成登录
5. 登录成功后，系统会自动：
   - 导航到文章编辑页面
   - 填写测试标题和内容
   - 插入图片
   - 设置文章封面
   - 点击发表按钮完成发布
6. 如果出现微信验证弹窗：
   - 系统会自动截取验证二维码并保存到项目根目录
   - **直接在控制台显示二维码**（如果安装了相关依赖）
   - 使用微信扫描二维码完成验证
   - 验证完成后文章将成功发布

## 命令行参数

支持以下命令行参数：
- `--browser`: 选择浏览器类型 (chrome, firefox, edge)
- `--headless`: 无头模式运行（不显示浏览器界面）
- `--user-data-dir`: 浏览器用户数据目录
- `--scan-timeout`: 二维码扫描超时时间(秒)
- `--wait-close`: 登录成功后等待关闭的时间(秒)

例如：
```bash
python main.py --browser edge --user-data-dir "D:\rpa-wx-gzh\browser_data"
```

## 登录状态保持原理

本工具通过保存和复用浏览器的Cookies和本地存储数据来维持登录状态。工具使用Selenium的浏览器实例，配置了持久化的用户数据目录，确保登录信息被正确保存和恢复。

## 常见问题

1. **Q: 为什么登录后还是提示需要重新登录？**
   A: 可能是微信公众号平台的安全策略导致。请确保您没有在其他地方登录同一账号，且没有清除浏览器数据。

2. **Q: 工具突然无法正常工作？**
   A: 可能是微信公众号平台的页面结构发生变化。请更新工具到最新版本。

3. **Q: 没有看到微信验证二维码？**
   A: 验证二维码会自动保存到项目根目录，文件名为 `wechat_verify_qrcode.png`，请查看该文件并使用微信扫描。如果安装了相关依赖，二维码也会在控制台直接显示。

4. **Q: 控制台无法显示二维码？**
   A: 请确保安装了必要的依赖库：`pip install pillow qrcode pyzbar`

## 新版文章发布器

项目新增 `wechat_publisher` 包和 `skills/wechat-mp-publisher` Skill。新版优先使用微信公众号开放接口；未配置 `WX_APPID` / `WX_APPSECRET` 时使用 Playwright 持久化浏览器会话，首次登录或发布验证仍可能需要用户扫码。

```bash
conda env create --override-channels -f environment.yml
conda activate rpa-wx-gzh
playwright install chromium

python -m wechat_publisher publish \
  --input article.json \
  --mode auto \
  --confirm-publish
```

文章 JSON 使用 `title`、`body`、`body_format`、`cover_image` 和 `assets` 字段。正文图片使用 `{{asset:alias}}` 引用。浏览器会话默认保存在 `playwright_data/`，凭证通过环境变量提供，不要提交到仓库。

浏览器发布进入登录或微信验证时，Skill 会把本次二维码作为对话内图片卡片展示，并在后台 watcher 中自动监测扫码状态。二维码文件按 `run_id` 和代数生成，过期时最多只刷新当前验证一次，不会重新提交文章。默认监测 5 分钟，可通过 `WX_SCAN_TIMEOUT` 调整；`WX_QR_TTL` 控制卡片倒计时，`WX_QR_REFRESH_LIMIT` 控制自动刷新次数。会话仍可使用 `status`、`resume`、`cancel` 管理。

如果系统已经安装 Chrome，可设置 `WX_PLAYWRIGHT_EXECUTABLE_PATH` 指向浏览器程序，跳过 Playwright 浏览器下载。
