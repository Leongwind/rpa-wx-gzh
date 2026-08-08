"""
工具函数模块 - 包含日志配置和通用功能
"""
import os
import sys
import time
import random
from pathlib import Path
from loguru import logger
from PIL import Image
import yaml
import requests
from datetime import datetime

# 导入配置
sys.path.append(str(Path(__file__).parent.parent))
from config import LOG_CONFIG

# 配置日志
def setup_logger():
    """配置和初始化日志系统"""
    # 创建日志目录
    log_dir = LOG_CONFIG.get("log_dir")
    os.makedirs(log_dir, exist_ok=True)
    
    # 设置日志文件路径
    log_file = os.path.join(
        log_dir, 
        f"wx_mp_{datetime.now().strftime('%Y%m%d')}.log"
    )
    
    # 清除现有的日志处理器
    logger.remove()
    
    # 添加控制台处理器
    logger.add(
        sys.stderr, 
        level=LOG_CONFIG.get("log_level"), 
        format=LOG_CONFIG.get("log_format")
    )
    
    # 添加文件处理器
    logger.add(
        log_file,
        rotation=LOG_CONFIG.get("log_rotation"),
        retention=LOG_CONFIG.get("log_retention"),
        level=LOG_CONFIG.get("log_level"),
        format=LOG_CONFIG.get("log_format")
    )
    
    return logger

# 初始化日志
logger = setup_logger()

def save_image(img_data, file_path):
    """
    保存图片数据到文件
    
    Args:
        img_data: 图片数据(bytes)
        file_path: 文件保存路径
    
    Returns:
        bool: 是否保存成功
    """
    try:
        with open(file_path, 'wb') as f:
            f.write(img_data)
        logger.info(f"图片已保存到: {file_path}")
        return True
    except Exception as e:
        logger.error(f"保存图片失败: {e}")
        return False

def show_qrcode(qrcode_path):
    """
    显示二维码图片
    
    Args:
        qrcode_path: 二维码图片路径
    """
    try:
        img = Image.open(qrcode_path)
        img.show()
        logger.info("已显示二维码图片，请扫描")
    except Exception as e:
        logger.error(f"显示二维码失败: {e}")

def wait_for_seconds(seconds, message=None):
    """
    等待指定的秒数，并显示消息
    
    Args:
        seconds: 等待的秒数
        message: 显示的消息
    """
    if message:
        logger.info(message)
    time.sleep(seconds)

def random_delay(min_seconds=1, max_seconds=5):
    """
    随机延迟一段时间，模拟人类操作
    
    Args:
        min_seconds: 最小延迟时间(秒)
        max_seconds: 最大延迟时间(秒)
    
    Returns:
        float: 实际延迟时间
    """
    delay_time = min_seconds + random.random() * (max_seconds - min_seconds)
    logger.info(f"随机延迟 {delay_time:.2f} 秒")
    time.sleep(delay_time)
    return delay_time

def wait_for_url_change(driver, current_url, timeout=30, check_interval=0.5):
    """
    等待页面URL变化
    
    Args:
        driver: WebDriver实例
        current_url: 当前URL
        timeout: 超时时间(秒)
        check_interval: 检查间隔时间(秒)
    
    Returns:
        str: 新的URL，如果超时则返回空字符串
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            new_url = driver.current_url
            if new_url != current_url:
                logger.info(f"URL已变化: {new_url}")
                return new_url
        except Exception as e:
            logger.warning(f"获取URL时出错: {e}")
        
        time.sleep(check_interval)
    
    logger.warning(f"等待URL变化超时")
    return ""

def wait_for_url_contains(driver, keyword, timeout=30, check_interval=0.5):
    """
    等待URL包含特定关键词
    
    Args:
        driver: WebDriver实例
        keyword: 关键词
        timeout: 超时时间(秒)
        check_interval: 检查间隔时间(秒)
    
    Returns:
        bool: URL是否包含关键词
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            current_url = driver.current_url
            if keyword in current_url:
                logger.info(f"URL包含关键词'{keyword}': {current_url}")
                return True
        except Exception as e:
            logger.warning(f"获取URL时出错: {e}")
        
        time.sleep(check_interval)
    
    logger.warning(f"等待URL包含关键词'{keyword}'超时")
    return False

def save_cookies_to_file(cookies, file_path):
    """
    将Cookies保存到文件
    
    Args:
        cookies: cookies数据
        file_path: 文件保存路径
    
    Returns:
        bool: 是否保存成功
    """
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as f:
            yaml.dump(cookies, f)
        logger.info(f"Cookies已保存到: {file_path}")
        return True
    except Exception as e:
        logger.error(f"保存Cookies失败: {e}")
        return False

def load_cookies_from_file(file_path):
    """
    从文件加载Cookies
    
    Args:
        file_path: 文件路径
    
    Returns:
        dict: cookies数据，如果加载失败返回None
    """
    try:
        if not os.path.exists(file_path):
            logger.warning(f"Cookies文件不存在: {file_path}")
            return None
        with open(file_path, 'r') as f:
            cookies = yaml.safe_load(f)
        logger.info(f"已从文件加载Cookies: {file_path}")
        return cookies
    except Exception as e:
        logger.error(f"加载Cookies失败: {e}")
        return None 