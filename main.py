"""
微信公众号平台自动化登录工具 - 主程序入口
"""
import os
import sys
import time
import argparse
from pathlib import Path
from modules.utils import logger, wait_for_seconds
from modules.browser import Browser
from modules.login import WxMpLogin
from config import BROWSER_CONFIG, LOGIN_CONFIG, WX_MP_URL

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="微信公众号平台自动化登录工具")
    
    # 浏览器参数
    parser.add_argument("--browser", choices=["chrome", "firefox", "edge"], default="chrome",
                      help="使用的浏览器类型")
    parser.add_argument("--headless", action="store_true", 
                      help="是否使用无头模式")
    
    # 登录参数
    parser.add_argument("--user-data-dir", type=str,
                      help="浏览器用户数据目录")
    parser.add_argument("--scan-timeout", type=int, default=120,
                      help="二维码扫描超时时间(秒)")
    
    # 其他参数
    parser.add_argument("--wait-close", type=int, default=0,
                      help="登录成功后等待关闭的时间(秒)，0表示不自动关闭")
    
    return parser.parse_args()

def main():
    """主函数"""
    # 解析命令行参数
    args = parse_args()
    
    # 更新配置
    browser_config = BROWSER_CONFIG.copy()
    browser_config["browser_type"] = args.browser
    browser_config["headless"] = args.headless
    
    if args.user_data_dir:
        browser_config["user_data_dir"] = args.user_data_dir
    
    login_config = LOGIN_CONFIG.copy()
    login_config["scan_timeout"] = args.scan_timeout
    
    try:
        logger.info("-" * 50)
        logger.info("微信公众号平台自动化登录工具启动")
        logger.info(f"浏览器类型: {browser_config['browser_type']}")
        logger.info(f"用户数据目录: {browser_config['user_data_dir']}")
        logger.info("-" * 50)
        
        # 创建浏览器实例
        browser = Browser(browser_config)
        
        # 创建登录实例
        login_handler = WxMpLogin(browser, login_config)
        
        # 执行登录
        success = login_handler.login()
        
        if success:
            logger.info("=" * 50)
            logger.info("登录成功！")
            logger.info("=" * 50)
            
            # 登录成功后等待
            if args.wait_close > 0:
                logger.info(f"将在 {args.wait_close} 秒后关闭浏览器")
                wait_for_seconds(args.wait_close)
                login_handler.close()
            else:
                # 保持浏览器打开
                logger.info("浏览器将保持打开状态，按Ctrl+C终止程序")
                while True:
                    wait_for_seconds(60)
        else:
            logger.error("登录失败")
            login_handler.close()
            return 1
            
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序运行出错: {e}")
        return 1
    finally:
        logger.info("程序退出")
        
    return 0

if __name__ == "__main__":
    sys.exit(main())