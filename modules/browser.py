"""
浏览器操作模块 - 包含浏览器初始化和操作功能
"""
import os
import sys
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager

# 导入配置和工具
sys.path.append(str(Path(__file__).parent.parent))
from config import BROWSER_CONFIG
from modules.utils import logger

class Browser:
    """浏览器操作类"""
    
    def __init__(self, config=None):
        """
        初始化浏览器操作类
        
        Args:
            config: 浏览器配置，如果为None则使用默认配置
        """
        self.config = config or BROWSER_CONFIG
        self.driver = None
        self._init_browser()
    
    def _init_browser(self):
        """初始化浏览器实例"""
        browser_type = self.config.get("browser_type", "chrome").lower()
        headless = self.config.get("headless", False)
        user_data_dir = self.config.get("user_data_dir")
        window_size = self.config.get("window_size", (1366, 768))
        
        # 确保用户数据目录存在
        if user_data_dir:
            os.makedirs(user_data_dir, exist_ok=True)
        
        try:
            if browser_type == "chrome":
                self.driver = self._init_chrome(headless, user_data_dir, window_size)
            elif browser_type == "firefox":
                self.driver = self._init_firefox(headless, user_data_dir, window_size)
            elif browser_type == "edge":
                self.driver = self._init_edge(headless, user_data_dir, window_size)
            else:
                logger.error(f"不支持的浏览器类型: {browser_type}")
                raise ValueError(f"不支持的浏览器类型: {browser_type}")
                
            # 设置隐式等待时间
            self.driver.implicitly_wait(self.config.get("timeout", 30))
            
            logger.info(f"已初始化 {browser_type} 浏览器")
        except Exception as e:
            logger.error(f"初始化浏览器失败: {e}")
            raise
    
    def _init_chrome(self, headless, user_data_dir, window_size):
        """
        初始化Chrome浏览器
        
        Args:
            headless: 是否使用无头模式
            user_data_dir: 用户数据目录
            window_size: 窗口大小
            
        Returns:
            WebDriver: Chrome WebDriver实例
        """
        options = ChromeOptions()
        
        # 添加通用选项
        self._add_common_options(options, headless)
        
        # 设置用户数据目录
        if user_data_dir:
            options.add_argument(f"--user-data-dir={user_data_dir}")
            # 如果需要设置配置文件，可以使用 --profile-directory 参数
            # options.add_argument("--profile-directory=Default")
        
        # 设置窗口大小
        if window_size:
            options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
        
        # 创建Chrome驱动
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)
    
    def _init_firefox(self, headless, user_data_dir, window_size):
        """
        初始化Firefox浏览器
        
        Args:
            headless: 是否使用无头模式
            user_data_dir: 用户数据目录
            window_size: 窗口大小
            
        Returns:
            WebDriver: Firefox WebDriver实例
        """
        options = FirefoxOptions()
        
        # 添加通用选项
        self._add_common_options(options, headless)
        
        # 设置用户数据目录
        if user_data_dir:
            options.add_argument("-profile")
            options.add_argument(user_data_dir)
        
        # 创建Firefox驱动
        service = Service(GeckoDriverManager().install())
        driver = webdriver.Firefox(service=service, options=options)
        
        # 设置窗口大小
        if window_size:
            driver.set_window_size(window_size[0], window_size[1])
            
        return driver
    
    def _init_edge(self, headless, user_data_dir, window_size):
        """
        初始化Edge浏览器
        
        Args:
            headless: 是否使用无头模式
            user_data_dir: 用户数据目录
            window_size: 窗口大小
            
        Returns:
            WebDriver: Edge WebDriver实例
        """
        options = EdgeOptions()
        
        # 添加通用选项
        self._add_common_options(options, headless)
        
        # 设置用户数据目录
        if user_data_dir:
            options.add_argument(f"--user-data-dir={user_data_dir}")
        
        # 设置窗口大小
        if window_size:
            options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
        
        # 创建Edge驱动
        service = Service(EdgeChromiumDriverManager().install())
        return webdriver.Edge(service=service, options=options)
    
    def _add_common_options(self, options, headless):
        """
        添加通用的浏览器选项
        
        Args:
            options: 浏览器选项对象
            headless: 是否使用无头模式
        """
        # 无头模式
        if headless:
            options.add_argument("--headless")
        
        # 关闭GPU加速
        options.add_argument("--disable-gpu")
        
        # 禁用沙箱
        options.add_argument("--no-sandbox")
        
        # 禁用共享内存
        options.add_argument("--disable-dev-shm-usage")
        
        # 禁用扩展
        options.add_argument("--disable-extensions")
        
        # 禁用自动化控制提示
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        # 禁用密码管理器
        options.add_argument("--disable-save-password-bubble")
        
        # 设置UA
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")
        
        # 禁用隐私模式
        options.add_argument("--disable-incognito")
        
        # 启用SwiftShader（解决WebGL错误）
        options.add_argument("--enable-unsafe-swiftshader")
        
        # 禁用WebGL错误
        options.add_argument("--disable-webgl")
        options.add_argument("--ignore-gpu-blocklist")
        
        # 禁用通知
        options.add_argument("--disable-notifications")
        
        # 最大化窗口
        options.add_argument("--start-maximized")
    
    def navigate_to(self, url):
        """
        导航到指定URL
        
        Args:
            url: 目标URL
            
        Returns:
            bool: 是否导航成功
        """
        try:
            self.driver.get(url)
            logger.info(f"导航到URL: {url}")
            return True
        except Exception as e:
            logger.error(f"导航到URL失败: {e}")
            return False
    
    def wait_for_element(self, locator, timeout=None):
        """
        等待元素可见
        
        Args:
            locator: 元素定位器，(By.XXX, "value")的形式
            timeout: 超时时间(秒)，如果为None则使用默认配置
            
        Returns:
            WebElement: 元素对象，如果未找到则返回None
        """
        if timeout is None:
            timeout = self.config.get("timeout", 30)
            
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.visibility_of_element_located(locator)
            )
            return element
        except TimeoutException:
            logger.warning(f"等待元素超时: {locator}")
            return None
        except Exception as e:
            logger.error(f"等待元素出错: {e}")
            return None
    
    def wait_for_elements(self, locator, timeout=None):
        """
        等待多个元素可见
        
        Args:
            locator: 元素定位器，(By.XXX, "value")的形式
            timeout: 超时时间(秒)，如果为None则使用默认配置
            
        Returns:
            list: 元素对象列表，如果未找到则返回空列表
        """
        if timeout is None:
            timeout = self.config.get("timeout", 30)
            
        try:
            elements = WebDriverWait(self.driver, timeout).until(
                EC.visibility_of_all_elements_located(locator)
            )
            return elements
        except TimeoutException:
            logger.warning(f"等待元素超时: {locator}")
            return []
        except Exception as e:
            logger.error(f"等待元素出错: {e}")
            return []
    
    def get_cookies(self):
        """
        获取当前页面的cookies
        
        Returns:
            list: cookies列表
        """
        try:
            cookies = self.driver.get_cookies()
            logger.info(f"获取到 {len(cookies)} 个cookies")
            return cookies
        except Exception as e:
            logger.error(f"获取cookies失败: {e}")
            return []
    
    def add_cookies(self, cookies):
        """
        添加cookies到浏览器
        
        Args:
            cookies: cookies列表或字典
            
        Returns:
            bool: 是否添加成功
        """
        try:
            if not cookies:
                logger.warning("没有cookies可添加")
                return False
                
            # 如果是列表，遍历添加
            if isinstance(cookies, list):
                for cookie in cookies:
                    self.driver.add_cookie(cookie)
                logger.info(f"已添加 {len(cookies)} 个cookies")
            # 如果是字典，直接添加
            elif isinstance(cookies, dict):
                self.driver.add_cookie(cookies)
                logger.info("已添加cookie")
            else:
                logger.warning(f"不支持的cookies类型: {type(cookies)}")
                return False
                
            return True
        except Exception as e:
            logger.error(f"添加cookies失败: {e}")
            return False
    
    def refresh_page(self):
        """
        刷新当前页面
        
        Returns:
            bool: 是否刷新成功
        """
        try:
            self.driver.refresh()
            logger.info("页面刷新成功")
            return True
        except Exception as e:
            logger.error(f"页面刷新失败: {e}")
            return False
    
    def execute_script(self, script, *args):
        """
        执行JavaScript脚本
        
        Args:
            script: JavaScript脚本
            *args: 脚本参数
            
        Returns:
            any: 脚本执行结果
        """
        try:
            result = self.driver.execute_script(script, *args)
            return result
        except Exception as e:
            logger.error(f"执行JavaScript脚本失败: {e}")
            return None
    
    def get_page_source(self):
        """
        获取页面源代码
        
        Returns:
            str: 页面源代码
        """
        try:
            return self.driver.page_source
        except Exception as e:
            logger.error(f"获取页面源代码失败: {e}")
            return ""
    
    def get_current_url(self):
        """
        获取当前URL
        
        Returns:
            str: 当前URL
        """
        try:
            return self.driver.current_url
        except Exception as e:
            logger.error(f"获取当前URL失败: {e}")
            return ""
    
    def take_screenshot(self, file_path):
        """
        截图并保存到文件
        
        Args:
            file_path: 文件保存路径
            
        Returns:
            bool: 是否截图成功
        """
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            self.driver.save_screenshot(file_path)
            logger.info(f"截图已保存到: {file_path}")
            return True
        except Exception as e:
            logger.error(f"截图失败: {e}")
            return False
    
    def close(self):
        """关闭浏览器"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("浏览器已关闭")
            except Exception as e:
                logger.error(f"关闭浏览器失败: {e}")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close() 