"""
配置文件 - 存储应用程序的各种配置参数
"""
import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).parent.absolute()

# 微信公众号平台URL
WX_MP_URL = "https://mp.weixin.qq.com/"

# 浏览器配置
BROWSER_CONFIG = {
    "browser_type": "edge",  # 浏览器类型: chrome, firefox, edge
    "headless": False,  # 是否使用无头模式
    "user_data_dir": os.path.join(BASE_DIR, "browser_data"),  # 浏览器用户数据目录
    "timeout": 30,  # 等待元素超时时间(秒)
    "window_size": (1920, 1080),  # 浏览器窗口大小，修改为更大的尺寸
}

# 登录配置
LOGIN_CONFIG = {
    "max_retry": 3,  # 登录最大重试次数
    "scan_timeout": 120,  # 二维码扫描超时时间(秒)
    "check_login_interval": 2,  # 检查登录状态的间隔时间(秒)
    "save_qrcode": True,  # 是否保存二维码图片
    "qrcode_path": os.path.join(BASE_DIR, "qrcode.png"),  # 二维码保存路径
}

# 日志配置
LOG_CONFIG = {
    "log_dir": os.path.join(BASE_DIR, "logs"),  # 日志目录
    "log_level": "INFO",  # 日志级别: DEBUG, INFO, WARNING, ERROR, CRITICAL
    "log_format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",  # 日志格式
    "log_rotation": "100 MB",  # 日志滚动大小
    "log_retention": "7 days",  # 日志保留时间
} 