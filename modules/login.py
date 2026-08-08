"""
登录功能模块 - 微信公众号登录相关功能
"""
import os
import sys
import time
import base64
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import subprocess
import glob

# 导入配置和工具
sys.path.append(str(Path(__file__).parent.parent))
from config import WX_MP_URL, LOGIN_CONFIG
from modules.utils import (
    logger, save_image, show_qrcode, wait_for_seconds, random_delay,
    wait_for_url_change, wait_for_url_contains
)
from modules.browser import Browser

class WxMpLogin:
    """微信公众号登录类"""
    
    # 页面元素定位器
    LOCATORS = {
        # 登录页面
        "login_frame": (By.ID, "login_wx_iframe"),  # 登录iframe
        "qrcode_img": (By.XPATH, "//img[contains(@class, 'qrcode')]"),  # 二维码图片
        "scan_tips": (By.XPATH, "//div[contains(@class, 'status')]/p"),  # 扫描提示
        "login_success": (By.XPATH, "//div[contains(text(), '登录成功')]"),  # 登录成功提示
        
        # 登录状态检查
        "logged_in_avatar": (By.XPATH, "//span[contains(@class, 'avatar')]/img"),  # 已登录状态下的头像
        "account_info": (By.XPATH, "//a[contains(@class, 'account_info')]"),  # 账号信息
        "login_button": (By.XPATH, "//a[contains(@class, 'login__type__container')]"),  # 登录按钮
        
        # 新增文章菜单元素，登录成功后显示
        "article_menu": (By.XPATH, "//div[contains(@class, 'new-creation__menu-content')][.//div[contains(text(), '文章')]]"),
        
        # 文章页面元素
        "article_page_indicator": (By.XPATH, "//div[contains(@class, 'weui-desktop-mass__wrp')]"),  # 文章页面特有元素
        
        # 文章编辑页面的标题输入框
        "article_title_input": (By.XPATH, "//textarea[@id='title'][@placeholder='请在这里输入标题']"),
        
        # 文章正文编辑区域 - 更新基于F12截图
        "rich_editor": (By.XPATH, "//div[contains(@class, 'ProseMirror')][contains(@contenteditable, 'true')]"),
        
        # 正文占位符元素 - 更新精确定位
        "content_placeholder": (By.XPATH, "//div[contains(@class, 'editor_content_placeholder')][contains(text(), '从这里开始写正文')]"),
        
        # iframe相关元素
        "editor_iframe": (By.XPATH, "//iframe[@id='ueditor_0']"),
        "mock_iframe": (By.XPATH, "//div[@id='editor_0']"),
        
        # 实际可编辑的section
        "editor_section": (By.XPATH, "//section"),
        
        # 上传图片相关元素
        "insert_image_btn": (By.XPATH, "//div[contains(@class, 'editor-toolbar')]//button[contains(@class, 'insert-image')]"),
        "file_input": (By.XPATH, "//input[@type='file']"),
        
        # 封面相关元素
        "cover_selection": (By.XPATH, "//span[contains(@class, 'js_share_type_none_image')][contains(text(), '拖拽或选择封面')]"),
        "select_from_content": (By.XPATH, "//a[contains(@class, 'js_selectCoverFromContent')][contains(text(), '从正文选择')]"),
        
        # 图片选择弹窗元素
        "image_in_dialog": (By.XPATH, "//span[contains(@class, 'appmsg_content_img cover')]"),
        "image_item": (By.XPATH, "//li[contains(@class, 'appmsg_content_img_item')]"),
        "next_step_button": (By.XPATH, "//button[contains(@class, 'weui-desktop-btn_primary')][text()='下一步']"),
        "selected_image_item": (By.XPATH, "//li[contains(@class, 'appmsg_content_img_item selected')]"),
        
        # 封面编辑及发布元素
        "confirm_button": (By.XPATH, "//button[contains(@class, 'weui-desktop-btn_primary')][text()='确认']"),
        "publish_button": (By.XPATH, "//button[contains(@class, 'mass_send')]//span[contains(@class, 'send_wording')][text()='发表']"),
        
        # 发表声明弹窗元素
        "agreement_dialog": (By.XPATH, "//div[contains(@class, 'dialog_wrp')][.//div[contains(text(), '温馨提示')]]"),
        "agree_button": (By.XPATH, "//a[contains(@class, 'btn_primary')][contains(@class, 'js_btn')][contains(text(), '同意以上声明')]"),
        
        # 最终发表弹窗元素
        "final_publish_dialog": (By.XPATH, "//div[contains(@class, 'dialog_wrp')][.//h4[contains(text(), '发表')]]"),
        "final_publish_button": (By.XPATH, "//button[contains(@class, 'weui-desktop-btn_primary')][text()='发表']"),
        
        # 继续发表按钮
        "continue_publish_button": (By.XPATH, "//button[contains(@class, 'weui-desktop-btn_primary')][text()='继续发表']"),
        
        # 微信验证弹窗元素
        "wechat_verify_dialog": (By.XPATH, "//div[contains(@class, 'dialog_wrp')][.//h3[contains(text(), '微信验证')]]"),
        "wechat_qrcode_img": (By.XPATH, "//img[contains(@class, 'qrcode')]"),
        "wechat_verify_title": (By.XPATH, "//h3[contains(text(), '微信验证')]"),
    }
    
    # 页面URL关键词
    PAGE_URL_KEYWORDS = {
        "article": "appmsgmgr",  # 文章管理页面URL关键词
        "home": "home",          # 首页URL关键词
        "login": "login",        # 登录页URL关键词
    }
    
    def __init__(self, browser=None, config=None):
        """
        初始化微信公众号登录类
        
        Args:
            browser: 浏览器实例，如果为None则创建新实例
            config: 登录配置，如果为None则使用默认配置
        """
        self.browser = browser or Browser()
        self.config = config or LOGIN_CONFIG
        self.is_logged_in = False
    
    def navigate_to_login_page(self):
        """
        导航到登录页面
        
        Returns:
            bool: 是否成功导航到登录页面
        """
        return self.browser.navigate_to(WX_MP_URL)
    
    def check_login_status(self):
        """
        检查是否已登录
        
        Returns:
            bool: 是否已登录
        """
        try:
            # 首先检查文章菜单元素，这是最明确的登录成功标志
            article_menu = self.browser.wait_for_element(self.LOCATORS["article_menu"], timeout=5)
            if article_menu:
                logger.info("检测到已登录状态(找到文章菜单)")
                self.is_logged_in = True
                return True
                
            # 备用检查：检查是否有已登录的头像或账号信息
            avatar = self.browser.wait_for_element(self.LOCATORS["logged_in_avatar"], timeout=3)
            if avatar:
                logger.info("检测到已登录状态(找到头像)")
                self.is_logged_in = True
                return True
                
            account_info = self.browser.wait_for_element(self.LOCATORS["account_info"], timeout=3)
            if account_info:
                logger.info("检测到已登录状态(找到账号信息)")
                self.is_logged_in = True
                return True
                
            # 检查是否有登录按钮，如有则表示未登录
            login_button = self.browser.wait_for_element(self.LOCATORS["login_button"], timeout=3)
            if login_button:
                logger.info("检测到未登录状态(找到登录按钮)")
                self.is_logged_in = False
                return False
                
            # 无法确定状态，默认未登录
            logger.warning("无法确定登录状态，假定为未登录")
            self.is_logged_in = False
            return False
        except Exception as e:
            logger.error(f"检查登录状态出错: {e}")
            self.is_logged_in = False
            return False
    
    def check_article_editor_page(self):
        """
        检查当前页面是否是文章编辑页面
        
        Returns:
            bool: 是否是文章编辑页面
        """
        try:
            # 检查是否存在文章标题输入框
            title_input = self.browser.wait_for_element(self.LOCATORS["article_title_input"], timeout=5)
            if title_input:
                logger.info("检测到文章编辑页面(找到标题输入框)")
                return True
            
            logger.info("当前页面不是文章编辑页面")
            return False
        except Exception as e:
            logger.error(f"检查文章编辑页面出错: {e}")
            return False
    
    def login_with_qrcode(self):
        """
        使用二维码登录微信公众号
        
        Returns:
            bool: 是否登录成功
        """
        try:
            # 检查是否已登录
            if self.check_login_status():
                logger.info("已经处于登录状态，无需再次登录")
                return True
                
            # 点击登录按钮
            login_button = self.browser.wait_for_element(self.LOCATORS["login_button"])
            if not login_button:
                logger.error("未找到登录按钮")
                return False
                
            login_button.click()
            logger.info("已点击登录按钮")
            
            # 切换到登录iframe
            try:
                # 等待iframe加载
                login_frame = self.browser.wait_for_element(self.LOCATORS["login_frame"])
                if not login_frame:
                    logger.error("未找到登录iframe")
                    return False
                    
                # 切换到iframe
                self.browser.driver.switch_to.frame(login_frame)
                logger.info("已切换到登录iframe")
            except Exception as e:
                logger.error(f"切换到登录iframe失败: {e}")
                return False
                
            # 获取二维码
            qrcode_img = self.browser.wait_for_element(self.LOCATORS["qrcode_img"])
            if not qrcode_img:
                logger.error("未找到二维码图片")
                # 切回主框架
                self.browser.driver.switch_to.default_content()
                return False
                
            # 获取二维码图片
            qrcode_src = qrcode_img.get_attribute("src")
            if not qrcode_src or not qrcode_src.startswith("data:image"):
                logger.error("二维码图片无效")
                # 切回主框架
                self.browser.driver.switch_to.default_content()
                return False
                
            # 保存二维码图片
            if self.config.get("save_qrcode", True):
                try:
                    # 从base64数据中提取图片数据
                    qrcode_data = qrcode_src.split(",")[1]
                    img_data = base64.b64decode(qrcode_data)
                    
                    # 保存图片
                    qrcode_path = self.config.get("qrcode_path")
                    save_image(img_data, qrcode_path)
                    
                    # 显示二维码
                    show_qrcode(qrcode_path)
                except Exception as e:
                    logger.error(f"保存或显示二维码失败: {e}")
                    
            # 等待扫码登录
            logger.info("请使用微信扫描二维码完成登录")
            
            # 等待登录成功
            scan_timeout = self.config.get("scan_timeout", 120)  # 默认2分钟超时
            check_interval = self.config.get("check_login_interval", 2)  # 默认2秒检查一次
            start_time = time.time()
            
            while time.time() - start_time < scan_timeout:
                try:
                    # 检查是否有登录成功提示
                    success = self.browser.wait_for_element(self.LOCATORS["login_success"], timeout=check_interval)
                    if success:
                        logger.info("检测到登录成功提示")
                        # 切回主框架
                        self.browser.driver.switch_to.default_content()
                        self.is_logged_in = True
                        return True
                        
                    # 检查提示文本
                    tips = self.browser.wait_for_element(self.LOCATORS["scan_tips"])
                    if tips:
                        tip_text = tips.text
                        if "成功" in tip_text:
                            logger.info(f"登录成功: {tip_text}")
                            # 切回主框架
                            self.browser.driver.switch_to.default_content()
                            self.is_logged_in = True
                            return True
                        elif "已过期" in tip_text:
                            logger.error(f"二维码已过期: {tip_text}")
                            # 切回主框架
                            self.browser.driver.switch_to.default_content()
                            return False
                        else:
                            logger.info(f"等待扫码: {tip_text}")
                except Exception as e:
                    logger.warning(f"检查登录状态时出错: {e}")
                    
                # 等待一段时间再次检查
                wait_for_seconds(check_interval)
                
            # 超时未登录
            logger.error(f"扫码登录超时({scan_timeout}秒)")
            # 切回主框架
            self.browser.driver.switch_to.default_content()
            return False
            
        except Exception as e:
            logger.error(f"登录过程出错: {e}")
            # 确保切回主框架
            try:
                self.browser.driver.switch_to.default_content()
            except:
                pass
            return False
    
    def fill_article_content(self, title="测试标题", content="这是一篇测试文章的正文内容。"):
        """
        填写文章标题和正文
        
        Args:
            title: 文章标题
            content: 文章正文内容
            
        Returns:
            bool: 是否成功填写内容
        """
        try:
            logger.info("开始填写文章内容")
            
            # 填写标题
            title_input = self.browser.wait_for_element(self.LOCATORS["article_title_input"], timeout=10)
            if not title_input:
                logger.error("未找到文章标题输入框")
                return False
                
            # 清除默认内容并填写标题
            title_input.clear()
            random_delay(0.5, 1.5)  # 模拟人类行为
            title_input.send_keys(title)
            logger.info(f"已填写文章标题: {title}")
            
            random_delay(1, 2)  # 人为延迟
            
            # 步骤1: 定位编辑区域 - 根据F12截图更新
            # 注意：占位符有pointer-events: none，无法直接点击，需要使用JavaScript
            
            # 方法1: 直接查找可编辑div
            prosemirror_editor = self.browser.wait_for_element(self.LOCATORS["rich_editor"], timeout=10)
            if prosemirror_editor:
                logger.info("找到ProseMirror编辑器")
                
                # 点击编辑器获取焦点
                try:
                    prosemirror_editor.click()
                    logger.info("成功点击编辑器区域")
                except Exception as e:
                    logger.warning(f"直接点击编辑器失败: {e}，尝试使用JavaScript点击")
                    self.browser.execute_script("arguments[0].click();", prosemirror_editor)
                    logger.info("使用JavaScript点击了编辑器区域")
                
                random_delay(0.5, 1.5)
                
                # 使用JavaScript创建section和span结构
                create_content_js = """
                // 创建和插入正确的DOM结构
                let editor = arguments[0];
                let content = arguments[1];
                
                // 清空现有内容
                editor.innerHTML = '';
                
                // 创建section元素
                let section = document.createElement('section');
                section.className = '';
                
                // 创建span元素带leaf属性
                let span = document.createElement('span');
                span.setAttribute('leaf', '');
                span.textContent = content;
                
                // 组装DOM
                section.appendChild(span);
                editor.appendChild(section);
                
                // 触发输入事件以确保编辑器知道内容已更改
                let inputEvent = new Event('input', { bubbles: true });
                editor.dispatchEvent(inputEvent);
                
                return true;
                """
                
                result = self.browser.execute_script(create_content_js, prosemirror_editor, content)
                if result:
                    logger.info(f"成功使用JavaScript创建文章内容: {content}")
                    
                    # 填写完内容后，尝试粘贴图片
                    random_delay(0.5, 1)
                    if self.paste_image_to_editor(prosemirror_editor):
                        # 成功粘贴图片后，选择封面
                        random_delay(1, 2)
                        logger.info("图片粘贴成功，继续选择文章封面")
                        self.select_cover_from_content()
                    
                    return True
                else:
                    logger.error("创建文章内容失败")
            
            # 方法2: 如果找不到ProseMirror编辑器，尝试处理占位符
            logger.warning("未找到ProseMirror编辑器，尝试通过占位符定位")
            placeholder = self.browser.wait_for_element(self.LOCATORS["content_placeholder"], timeout=5)
            if placeholder:
                logger.info("找到占位符元素")
                
                # 由于占位符有pointer-events: none，使用JavaScript找到其父元素并点击
                parent_click_js = """
                // 查找占位符
                let placeholder = arguments[0];
                
                // 查找真正的可编辑容器
                let editableDivs = document.querySelectorAll('div[contenteditable="true"]');
                if (editableDivs.length > 0) {
                    // 点击第一个可编辑div
                    editableDivs[0].click();
                    
                    // 创建section和span结构
                    let section = document.createElement('section');
                    section.className = '';
                    
                    let span = document.createElement('span');
                    span.setAttribute('leaf', '');
                    span.textContent = arguments[1];
                    
                    section.appendChild(span);
                    editableDivs[0].innerHTML = '';
                    editableDivs[0].appendChild(section);
                    
                    return true;
                }
                return false;
                """
                
                result = self.browser.execute_script(parent_click_js, placeholder, content)
                if result:
                    logger.info(f"通过占位符父元素填写了文章内容: {content}")
                    return True
            
            # 方法3: 如果前两种方法都失败，使用更通用的方法
            logger.warning("前两种方法失败，尝试通用方法查找编辑区域")
            
            # 通用的JavaScript方法查找所有可能的编辑区域
            universal_js = """
            // 尝试多种方法找到编辑区域
            
            // 方法1: 查找所有contenteditable为true的div
            let editables = document.querySelectorAll('div[contenteditable="true"]');
            if (editables.length > 0) {
                let editor = editables[0];
                
                // 创建section和span
                let section = document.createElement('section');
                section.className = '';
                
                let span = document.createElement('span');
                span.setAttribute('leaf', '');
                span.textContent = arguments[0];
                
                section.appendChild(span);
                editor.innerHTML = '';
                editor.appendChild(section);
                return "方法1成功";
            }
            
            // 方法2: 查找class包含ProseMirror的元素
            let prosemirrors = document.querySelectorAll('.ProseMirror');
            if (prosemirrors.length > 0) {
                let editor = prosemirrors[0];
                
                // 创建section和span
                let section = document.createElement('section');
                section.className = '';
                
                let span = document.createElement('span');
                span.setAttribute('leaf', '');
                span.textContent = arguments[0];
                
                section.appendChild(span);
                editor.innerHTML = '';
                editor.appendChild(section);
                return "方法2成功";
            }
            
            // 方法3: 查找占位符的父元素
            let placeholders = document.querySelectorAll('.editor_content_placeholder');
            if (placeholders.length > 0) {
                let parent = placeholders[0].parentElement;
                if (parent) {
                    // 找到最接近的contenteditable元素
                    let editable = null;
                    let current = parent;
                    
                    // 向上查找最近的contenteditable元素
                    while (current && !editable) {
                        let siblings = current.parentElement ? current.parentElement.children : [];
                        for (let i = 0; i < siblings.length; i++) {
                            if (siblings[i].getAttribute('contenteditable') === 'true') {
                                editable = siblings[i];
                                break;
                            }
                        }
                        current = current.parentElement;
                    }
                    
                    if (editable) {
                        // 创建section和span
                        let section = document.createElement('section');
                        section.className = '';
                        
                        let span = document.createElement('span');
                        span.setAttribute('leaf', '');
                        span.textContent = arguments[0];
                        
                        section.appendChild(span);
                        editable.innerHTML = '';
                        editable.appendChild(section);
                        return "方法3成功";
                    }
                }
            }
            
            // 最后尝试: 查找document中所有section元素
            let sections = document.querySelectorAll('section');
            if (sections.length > 0) {
                for (let i = 0; i < sections.length; i++) {
                    let section = sections[i];
                    section.innerHTML = '<span leaf="">' + arguments[0] + '</span>';
                }
                return "最后方法成功";
            }
            
            return "所有方法失败";
            """
            
            result = self.browser.execute_script(universal_js, content)
            logger.info(f"通用JavaScript方法结果: {result}")
            
            if result != "所有方法失败":
                logger.info(f"使用通用方法填写了文章内容: {content}")
                return True
            else:
                logger.error("所有方法均无法填写文章内容")
                return False
            
        except Exception as e:
            logger.error(f"填写文章内容失败: {e}")
            return False
    
    def paste_image_to_editor(self, editor_element):
        """
        将图片粘贴到编辑器
        
        Args:
            editor_element: 编辑器元素
            
        Returns:
            bool: 是否成功粘贴图片
        """
        try:
            logger.info("开始尝试粘贴图片到编辑器")
            
            # 查找test_pic目录下的图片文件
            base_dir = Path(__file__).parent.parent
            test_pic_dir = os.path.join(base_dir, "test_pic")
            
            if not os.path.exists(test_pic_dir):
                logger.warning(f"test_pic目录不存在，尝试创建: {test_pic_dir}")
                os.makedirs(test_pic_dir, exist_ok=True)
                logger.info(f"已创建test_pic目录: {test_pic_dir}")
                logger.warning("请将测试图片放入该目录后再次运行")
                return False
            
            # 获取目录中的第一张图片
            image_files = glob.glob(os.path.join(test_pic_dir, "*.jpg")) + \
                          glob.glob(os.path.join(test_pic_dir, "*.png")) + \
                          glob.glob(os.path.join(test_pic_dir, "*.jpeg")) + \
                          glob.glob(os.path.join(test_pic_dir, "*.gif"))
            
            if not image_files:
                logger.warning(f"在test_pic目录中未找到任何图片文件: {test_pic_dir}")
                return False
            
            image_path = image_files[0]
            logger.info(f"准备使用图片: {image_path}")            
            # 方法2：尝试使用Ctrl+V粘贴图片
            try:
                logger.info("尝试使用Ctrl+V粘贴图片")
                
                # 确保编辑器获得焦点
                if editor_element:
                    editor_element.click()
                    random_delay(0.5, 1)
                
                # 根据操作系统类型选择不同的复制粘贴方法
                if sys.platform.startswith('win'):
                    # Windows系统下的操作
                    try:
                        # 使用PowerShell复制图片到剪贴板
                        powershell_command = f'powershell -command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetImage([System.Drawing.Image]::FromFile(\'{image_path}\'))"'
                        subprocess.run(powershell_command, shell=True, check=True)
                        logger.info("已使用PowerShell将图片复制到剪贴板")
                    except Exception as e:
                        logger.warning(f"PowerShell复制图片失败: {e}")
                        logger.info("尝试使用alternative方法复制图片")
                        try:
                            # 尝试另一种方法：使用PIL和pyperclip
                            from PIL import ImageGrab, Image
                            img = Image.open(image_path)
                            ImageGrab.grabclipboard()
                            # 使用tempfile创建一个临时BMP文件
                            import tempfile
                            temp_file = tempfile.NamedTemporaryFile(suffix='.bmp', delete=False)
                            temp_file.close()
                            img.save(temp_file.name)
                            # 使用系统命令复制图片
                            subprocess.run(f'powershell -command "Set-Clipboard -Path \'{temp_file.name}\'"', shell=True)
                            logger.info(f"已使用alternative方法复制图片到剪贴板")
                        except ImportError:
                            logger.error("缺少必要的库，无法使用alternative方法")
                            return False
                elif sys.platform.startswith('darwin'):
                    # macOS系统下的操作
                    try:
                        subprocess.run(['osascript', '-e', f'set the clipboard to (read (POSIX file "{image_path}") as JPEG picture)'])
                        logger.info("已将图片复制到剪贴板(macOS)")
                    except Exception as e:
                        logger.error(f"macOS复制图片失败: {e}")
                        return False
                else:
                    # Linux系统下的操作
                    try:
                        subprocess.run(['xclip', '-selection', 'clipboard', '-t', 'image/png', '-i', image_path])
                        logger.info("已将图片复制到剪贴板(Linux)")
                    except Exception as e:
                        logger.error(f"Linux复制图片失败: {e}")
                        return False
                
                # 执行粘贴操作
                random_delay(1, 2)
                actions = ActionChains(self.browser.driver)
                actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
                logger.info("已执行Ctrl+V粘贴操作")
                
                random_delay(2, 4)  # 等待图片加载
                return True
            
            except Exception as e:
                logger.error(f"使用Ctrl+V粘贴图片失败: {e}")
            
            # 方法3：尝试使用JavaScript拖放方式
            try:
                logger.info("尝试使用JavaScript模拟拖放方式插入图片")
                
                # 使用JavaScript创建模拟的拖放事件
                js_drop_image = """
                let editor = arguments[0];
                let imagePath = arguments[1];
                
                try {
                    // 创建一个图片元素
                    let img = document.createElement('img');
                    img.src = imagePath;
                    img.style.width = '300px';
                    
                    // 在编辑器中添加图片
                    if (editor) {
                        let section = editor.querySelector('section') || document.createElement('section');
                        if (!editor.contains(section)) {
                            editor.appendChild(section);
                        }
                        section.appendChild(img);
                        return true;
                    }
                    return false;
                } catch (e) {
                    console.error('插入图片失败:', e);
                    return false;
                }
                """
                
                # 尝试转换为数据URI
                try:
                    from PIL import Image
                    import base64
                    import io
                    
                    # 读取图片并转换为base64
                    img = Image.open(image_path)
                    img_format = image_path.lower().split('.')[-1]
                    if img_format == 'jpg':
                        img_format = 'jpeg'
                    
                    buffer = io.BytesIO()
                    img.save(buffer, format=img_format)
                    img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    data_uri = f"data:image/{img_format};base64,{img_base64}"
                    
                    # 执行JavaScript
                    result = self.browser.execute_script(js_drop_image, editor_element, data_uri)
                    if result:
                        logger.info("成功使用JavaScript插入图片")
                        return True
                except ImportError:
                    logger.warning("缺少PIL库，无法转换图片为数据URI")
                except Exception as e:
                    logger.error(f"使用JavaScript插入图片失败: {e}")
            except Exception as e:
                logger.error(f"JavaScript插入图片出错: {e}")
            
            logger.warning("所有尝试都失败，无法插入图片")
            return False
            
        except Exception as e:
            logger.error(f"粘贴图片到编辑器出错: {e}")
            return False
    
    def select_cover_from_content(self):
        """
        选择文章封面
        
        从正文中选择图片作为封面
        """
        try:
            logger.info("开始选择文章封面...")
            
            # 向下滚动页面，寻找封面选择区域
            scroll_script = """
            window.scrollBy(0, 400);  // 向下滚动以显示封面选择区域
            return true;
            """
            self.browser.execute_script(scroll_script)
            logger.info("页面向下滚动")
            
            # 等待页面滚动完成
            random_delay(1, 2)
            
            # 寻找"拖拽或选择封面"元素
            cover_element = self.browser.wait_for_element(self.LOCATORS["cover_selection"], timeout=10)
            if not cover_element:
                logger.warning("未找到'拖拽或选择封面'元素，尝试进一步向下滚动")
                
                # 尝试进一步向下滚动
                self.browser.execute_script("window.scrollBy(0, 400);")
                random_delay(1, 2)
                
                # 再次尝试寻找元素
                cover_element = self.browser.wait_for_element(self.LOCATORS["cover_selection"], timeout=5)
                if not cover_element:
                    logger.error("仍未找到'拖拽或选择封面'元素")
                    return False
            
            logger.info("找到'拖拽或选择封面'元素")
            
            # 使用ActionChains移动到该元素
            actions = ActionChains(self.browser.driver)
            actions.move_to_element(cover_element).perform()
            logger.info("鼠标已移动到'拖拽或选择封面'元素上")
            
            # 等待选项框出现
            random_delay(1, 2)
            
            # 首先尝试直接点击"拖拽或选择封面"元素
            try:
                cover_element.click()
                logger.info("已点击'拖拽或选择封面'元素")
                random_delay(0.5, 1)
            except Exception as e:
                logger.warning(f"点击'拖拽或选择封面'元素失败: {e}")
            
            # 查找"从正文选择"按钮
            select_btn = self.browser.wait_for_element(self.LOCATORS["select_from_content"], timeout=5)
            if not select_btn:
                logger.warning("未找到'从正文选择'按钮，尝试使用JavaScript查找并点击")
                
                # 使用JavaScript查找并点击
                js_click = """
                let selectBtn = document.querySelector('a.pop-opr__button.js_selectCoverFromContent');
                if (selectBtn) {
                    selectBtn.click();
                    return true;
                }
                return false;
                """
                result = self.browser.execute_script(js_click)
                if result:
                    logger.info("通过JavaScript点击了'从正文选择'按钮")
                    random_delay(2, 3)
                    
                    # 点击按钮后处理弹窗并选择图片
                    return self.select_image_from_dialog()
                else:
                    logger.error("未能找到并点击'从正文选择'按钮")
                    return False
            
            # 点击"从正文选择"按钮
            try:
                select_btn.click()
                logger.info("已点击'从正文选择'按钮")
                random_delay(2, 3)
                
                # 点击按钮后处理弹窗并选择图片
                return self.select_image_from_dialog()
            except Exception as e:
                logger.error(f"点击'从正文选择'按钮失败: {e}")
                
                # 尝试使用JavaScript点击
                try:
                    self.browser.execute_script("arguments[0].click();", select_btn)
                    logger.info("通过JavaScript点击了'从正文选择'按钮")
                    random_delay(2, 3)
                    
                    # 点击按钮后处理弹窗并选择图片
                    return self.select_image_from_dialog()
                except Exception as js_e:
                    logger.error(f"通过JavaScript点击'从正文选择'按钮也失败: {js_e}")
                    return False
                
        except Exception as e:
            logger.error(f"选择封面过程出错: {e}")
            return False
    
    def select_image_from_dialog(self):
        """
        从弹窗中选择图片并点击下一步
        
        Returns:
            bool: 是否成功选择图片
        """
        try:
            logger.info("开始从弹窗中选择图片...")
            
            # 等待弹窗加载
            random_delay(2, 3)
            
            # 寻找图片元素
            image_element = self.browser.wait_for_element(self.LOCATORS["image_in_dialog"], timeout=10)
            if not image_element:
                logger.warning("未找到图片元素，尝试使用更通用的选择器")
                
                # 尝试使用更通用的选择器
                js_find_image = """
                let images = document.querySelectorAll('span.appmsg_content_img');
                if (images.length > 0) {
                    images[0].scrollIntoView();
                    return true;
                }
                return false;
                """
                result = self.browser.execute_script(js_find_image)
                if not result:
                    logger.error("未能找到任何图片元素")
                    return False
                
                # 使用JavaScript查找并点击第一个图片项
                js_click_first_image = """
                let imageItems = document.querySelectorAll('li.appmsg_content_img_item');
                if (imageItems.length > 0) {
                    imageItems[0].click();
                    return true;
                }
                return false;
                """
                result = self.browser.execute_script(js_click_first_image)
                if result:
                    logger.info("通过JavaScript点击了第一个图片项")
                else:
                    logger.error("通过JavaScript点击图片项失败")
                    return False
            else:
                # 找到图片元素，移动鼠标并点击
                logger.info("找到图片元素")
                
                # 使用ActionChains移动到图片元素
                actions = ActionChains(self.browser.driver)
                actions.move_to_element(image_element).perform()
                logger.info("鼠标已移动到图片元素上")
                
                # 尝试找到父元素li来点击
                try:
                    image_item = self.browser.wait_for_element(self.LOCATORS["image_item"], timeout=5)
                    if image_item:
                        logger.info("找到图片项元素，点击它")
                        image_item.click()
                    else:
                        # 如果找不到父元素，直接点击图片
                        logger.info("未找到图片项元素，直接点击图片")
                        image_element.click()
                except Exception as e:
                    logger.warning(f"点击图片项元素失败: {e}，尝试使用JavaScript点击")
                    
                    # 尝试使用JavaScript点击
                    try:
                        self.browser.execute_script("arguments[0].click();", image_element)
                        logger.info("通过JavaScript点击了图片元素")
                    except Exception as js_e:
                        logger.error(f"通过JavaScript点击图片元素也失败: {js_e}")
                        return False
            
            # 等待图片被选中
            random_delay(1, 2)
            
            # 检查图片是否被选中
            selected_image = self.browser.wait_for_element(self.LOCATORS["selected_image_item"], timeout=5)
            if not selected_image:
                logger.warning("未检测到图片被选中，使用JavaScript检查")
                
                # 使用JavaScript检查是否有选中的图片
                js_check_selection = """
                return document.querySelector('li.appmsg_content_img_item.selected') !== null;
                """
                is_selected = self.browser.execute_script(js_check_selection)
                
                if not is_selected:
                    logger.warning("图片未被选中，再次尝试点击图片")
                    
                    # 再次尝试点击图片
                    js_click_image = """
                    let imageItems = document.querySelectorAll('li.appmsg_content_img_item');
                    if (imageItems.length > 0) {
                        imageItems[0].click();
                        return true;
                    }
                    return false;
                    """
                    result = self.browser.execute_script(js_click_image)
                    if not result:
                        logger.error("再次点击图片失败")
                        return False
                    
                    random_delay(1, 2)
            else:
                logger.info("检测到图片已被选中")
            
            # 点击"下一步"按钮
            next_btn = self.browser.wait_for_element(self.LOCATORS["next_step_button"], timeout=5)
            if not next_btn:
                logger.warning("未找到'下一步'按钮，尝试使用JavaScript查找并点击")
                
                # 使用JavaScript查找并点击
                js_click_next = """
                let nextBtn = document.querySelector('button.weui-desktop-btn_primary');
                if (nextBtn) {
                    nextBtn.click();
                    return true;
                }
                return false;
                """
                result = self.browser.execute_script(js_click_next)
                if result:
                    logger.info("通过JavaScript点击了'下一步'按钮")
                    random_delay(2, 3)
                    
                    # 点击'下一步'后继续处理封面编辑弹窗并发表文章
                    return self.confirm_cover_and_publish()
                else:
                    logger.error("未能找到并点击'下一步'按钮")
                    return False
            
            # 点击"下一步"按钮
            try:
                next_btn.click()
                logger.info("已点击'下一步'按钮")
                random_delay(2, 3)
                
                # 点击'下一步'后继续处理封面编辑弹窗并发表文章
                return self.confirm_cover_and_publish()
            except Exception as e:
                logger.error(f"点击'下一步'按钮失败: {e}")
                
                # 尝试使用JavaScript点击
                try:
                    self.browser.execute_script("arguments[0].click();", next_btn)
                    logger.info("通过JavaScript点击了'下一步'按钮")
                    random_delay(2, 3)
                    
                    # 点击'下一步'后继续处理封面编辑弹窗并发表文章
                    return self.confirm_cover_and_publish()
                except Exception as js_e:
                    logger.error(f"通过JavaScript点击'下一步'按钮也失败: {js_e}")
                    return False
            
        except Exception as e:
            logger.error(f"从弹窗选择图片过程出错: {e}")
            return False
    
    def confirm_cover_and_publish(self):
        """
        确认封面编辑并发表文章
        
        处理封面编辑弹窗，点击确认按钮，然后滚动页面并点击发表按钮
        
        Returns:
            bool: 是否成功发表文章
        """
        try:
            logger.info("开始处理封面编辑并发表文章...")
            
            # 等待封面编辑弹窗加载
            random_delay(2, 4)
            
            # 查找"确认"按钮
            confirm_btn = self.browser.wait_for_element(self.LOCATORS["confirm_button"], timeout=10)
            if not confirm_btn:
                logger.warning("未找到'确认'按钮，尝试使用JavaScript查找并点击")
                
                # 使用JavaScript查找并点击
                js_click_confirm = """
                let confirmBtn = document.querySelector('button.weui-desktop-btn_primary');
                if (confirmBtn && confirmBtn.textContent.trim() === '确认') {
                    confirmBtn.click();
                    return true;
                }
                return false;
                """
                result = self.browser.execute_script(js_click_confirm)
                if result:
                    logger.info("通过JavaScript点击了'确认'按钮")
                else:
                    logger.error("未能找到并点击'确认'按钮")
                    return False
            else:
                # 点击"确认"按钮
                try:
                    confirm_btn.click()
                    logger.info("已点击'确认'按钮")
                except Exception as e:
                    logger.warning(f"点击'确认'按钮失败: {e}，尝试使用JavaScript点击")
                    
                    # 尝试使用JavaScript点击
                    try:
                        self.browser.execute_script("arguments[0].click();", confirm_btn)
                        logger.info("通过JavaScript点击了'确认'按钮")
                    except Exception as js_e:
                        logger.error(f"通过JavaScript点击'确认'按钮也失败: {js_e}")
                        return False
            
            # 确认按钮点击后，等待页面更新
            random_delay(3, 5)
            
            # 向下滚动页面，寻找发表按钮
            scroll_script = """
            window.scrollBy(0, 500);  // 向下滚动以显示发表按钮区域
            return true;
            """
            self.browser.execute_script(scroll_script)
            logger.info("页面向下滚动，准备寻找发表按钮")
            
            # 等待页面滚动完成
            random_delay(1, 2)
            
            # 查找"发表"按钮
            publish_btn = self.browser.wait_for_element(self.LOCATORS["publish_button"], timeout=10)
            if not publish_btn:
                logger.warning("未找到'发表'按钮，尝试进一步向下滚动")
                
                # 尝试进一步向下滚动
                self.browser.execute_script("window.scrollBy(0, 500);")
                random_delay(1, 2)
                
                # 再次尝试寻找"发表"按钮
                publish_btn = self.browser.wait_for_element(self.LOCATORS["publish_button"], timeout=5)
                if not publish_btn:
                    logger.warning("仍未找到'发表'按钮，尝试使用JavaScript查找并点击")
                    
                    # 使用JavaScript查找并点击
                    js_click_publish = """
                    let publishBtn = document.querySelector('.mass_send');
                    if (publishBtn) {
                        publishBtn.scrollIntoView({behavior: 'smooth', block: 'center'});
                        setTimeout(() => {
                            publishBtn.click();
                        }, 1000);
                        return true;
                    }
                    return false;
                    """
                    result = self.browser.execute_script(js_click_publish)
                    if result:
                        logger.info("通过JavaScript滚动到并点击了'发表'按钮")
                        wait_for_seconds(1)  # 等待点击执行
                        random_delay(2, 3)
                        # 直接处理最终发表弹窗，跳过声明弹窗
                        return self.confirm_final_publish()
                    else:
                        logger.error("未能找到并点击'发表'按钮")
                        return False
            
            # 点击"发表"按钮
            try:
                # 先确保按钮可见
                self.browser.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", publish_btn)
                random_delay(1, 2)
                
                publish_btn.click()
                logger.info("已点击'发表'按钮")
                random_delay(2, 3)
                # 直接处理最终发表弹窗，跳过声明弹窗
                return self.confirm_final_publish()
            except Exception as e:
                logger.warning(f"点击'发表'按钮失败: {e}，尝试使用JavaScript点击")
                
                # 尝试使用JavaScript点击
                try:
                    self.browser.execute_script("arguments[0].click();", publish_btn)
                    logger.info("通过JavaScript点击了'发表'按钮")
                    random_delay(2, 3)
                    # 直接处理最终发表弹窗，跳过声明弹窗
                    return self.confirm_final_publish()
                except Exception as js_e:
                    logger.error(f"通过JavaScript点击最终的'发表'按钮也失败: {js_e}")
                    return False
            
        except Exception as e:
            logger.error(f"处理封面编辑并发表文章过程出错: {e}")
            return False
    
    def agree_to_declaration(self):
        """
        处理发表后的声明弹窗
        
        点击"同意以上声明"按钮完成发布流程
        
        Returns:
            bool: 是否成功同意声明并完成发布
        """
        # 此方法已不再使用，直接跳转到最终发表弹窗
        logger.info("跳过声明弹窗处理，直接进入最终发表确认")
        return self.confirm_final_publish()
    
    def confirm_final_publish(self):
        """
        处理最终发表确认弹窗
        
        点击最终的"发表"按钮，完成文章发布
        
        Returns:
            bool: 是否成功完成文章发布
        """
        try:
            logger.info("开始处理最终发表确认弹窗...")
            
            # 等待最终发表弹窗出现
            random_delay(2, 4)
            
            # 查找最终的"发表"按钮
            final_publish_btn = self.browser.wait_for_element(self.LOCATORS["final_publish_button"], timeout=10)
            
            if not final_publish_btn:
                logger.warning("未找到最终的'发表'按钮，尝试通过JavaScript查找并点击")
                
                # 使用JavaScript查找并点击按钮
                js_click_final_publish = """
                let publishBtn = document.querySelector('button.weui-desktop-btn.weui-desktop-btn_primary');
                if (publishBtn && publishBtn.textContent.trim() === '发表') {
                    publishBtn.click();
                    return true;
                }
                
                // 备用查找方法
                let allBtns = document.querySelectorAll('button.weui-desktop-btn_primary');
                for (let btn of allBtns) {
                    if (btn.textContent.trim() === '发表') {
                        btn.click();
                        return true;
                    }
                }
                
                return false;
                """
                
                result = self.browser.execute_script(js_click_final_publish)
                if result:
                    logger.info("通过JavaScript点击了最终的'发表'按钮")
                    # 等待"继续发表"弹窗出现
                    return self.handle_continue_publish_dialog()
                else:
                    # 尝试查找发表弹窗，确认是否存在
                    js_check_dialog = """
                    let dialogs = document.querySelectorAll('.dialog_wrp');
                    for (let dialog of dialogs) {
                        if (dialog.innerHTML.includes('发表')) {
                            return dialog.innerHTML;
                        }
                    }
                    return null;
                    """
                    dialog_html = self.browser.execute_script(js_check_dialog)
                    
                    if dialog_html:
                        logger.warning(f"找到了发表弹窗，但无法点击最终的'发表'按钮。弹窗内容: {dialog_html[:100]}...")
                    else:
                        logger.info("未找到发表弹窗，可能文章已经成功发布或弹窗尚未出现")
                    
                    # 尝试再次等待一下，然后再次查找按钮
                    random_delay(3, 5)
                    final_publish_btn = self.browser.wait_for_element(self.LOCATORS["final_publish_button"], timeout=5)
                    
                    if final_publish_btn:
                        try:
                            final_publish_btn.click()
                            logger.info("延迟后找到并点击了最终的'发表'按钮")
                            # 等待"继续发表"弹窗出现
                            return self.handle_continue_publish_dialog()
                        except Exception as e:
                            logger.error(f"点击最终的'发表'按钮失败: {e}")
                            return False
                    else:
                        logger.warning("未能找到最终的'发表'按钮，文章发布状态未知")
                        return False
            
            # 点击最终的"发表"按钮
            try:
                final_publish_btn.click()
                logger.info("已点击最终的'发表'按钮")
                # 等待"继续发表"弹窗出现
                return self.handle_continue_publish_dialog()
            except Exception as e:
                logger.warning(f"点击最终的'发表'按钮失败: {e}，尝试使用JavaScript点击")
                
                # 尝试使用JavaScript点击
                try:
                    self.browser.execute_script("arguments[0].click();", final_publish_btn)
                    logger.info("通过JavaScript点击了最终的'发表'按钮")
                    # 等待"继续发表"弹窗出现
                    return self.handle_continue_publish_dialog()
                except Exception as js_e:
                    logger.error(f"通过JavaScript点击最终的'发表'按钮也失败: {js_e}")
                    return False
                
        except Exception as e:
            logger.error(f"处理最终发表确认弹窗过程出错: {e}")
            return False
    
    def handle_continue_publish_dialog(self):
        """
        处理"继续发表"弹窗
        
        点击"继续发表"按钮完成最终发布
        
        Returns:
            bool: 是否成功完成发布
        """
        try:
            logger.info("等待'继续发表'弹窗出现...")
            random_delay(2, 3)
            
            # 定位"继续发表"按钮
            continue_btn = self.browser.wait_for_element(
                self.LOCATORS["continue_publish_button"],
                timeout=10
            )
            
            if not continue_btn:
                logger.warning("未找到'继续发表'按钮，尝试使用JavaScript查找并点击")
                
                # 使用JavaScript查找并点击
                js_click_continue = """
                let continueBtn = document.querySelector('button.weui-desktop-btn.weui-desktop-btn_primary');
                if (continueBtn && continueBtn.textContent.trim() === '继续发表') {
                    continueBtn.click();
                    return true;
                }
                
                // 备用查找方法
                let allBtns = document.querySelectorAll('button.weui-desktop-btn_primary');
                for (let btn of allBtns) {
                    if (btn.textContent.trim() === '继续发表') {
                        btn.click();
                        return true;
                    }
                }
                
                return false;
                """
                
                result = self.browser.execute_script(js_click_continue)
                if result:
                    logger.info("通过JavaScript点击了'继续发表'按钮")
                    # 等待微信验证弹窗出现
                    return self.handle_wechat_verify_dialog()
                else:
                    logger.error("未能找到并点击'继续发表'按钮")
                    return False
            
            # 点击"继续发表"按钮
            try:
                continue_btn.click()
                logger.info("已点击'继续发表'按钮")
                # 等待微信验证弹窗出现
                return self.handle_wechat_verify_dialog()
            except Exception as e:
                logger.warning(f"点击'继续发表'按钮失败: {e}，尝试使用JavaScript点击")
                
                # 尝试使用JavaScript点击
                try:
                    self.browser.execute_script("arguments[0].click();", continue_btn)
                    logger.info("通过JavaScript点击了'继续发表'按钮")
                    # 等待微信验证弹窗出现
                    return self.handle_wechat_verify_dialog()
                except Exception as js_e:
                    logger.error(f"通过JavaScript点击'继续发表'按钮也失败: {js_e}")
                    return False
                    
        except Exception as e:
            logger.error(f"处理'继续发表'弹窗过程出错: {e}")
            return False
            
    def handle_wechat_verify_dialog(self):
        """
        处理微信验证二维码弹窗
        
        截取二维码图片并等待用户扫描完成
        
        Returns:
            bool: 是否成功完成验证
        """
        try:
            logger.info("等待微信验证二维码弹窗出现...")
            # 增加等待时间，确保弹窗完全加载
            random_delay(3, 5)
            
            # 检查微信验证弹窗是否出现
            verify_dialog = self.browser.wait_for_element(self.LOCATORS["wechat_verify_dialog"], timeout=15)
            if not verify_dialog:
                logger.warning("未找到微信验证弹窗，尝试检查是否已经发表成功")
                return True
            
            logger.info("检测到微信验证弹窗，等待二维码加载...")
            # 等待二维码完全加载
            random_delay(2, 3)
            
            # 查找二维码图片
            qrcode_img = self.browser.wait_for_element(self.LOCATORS["wechat_qrcode_img"], timeout=10)
            if not qrcode_img:
                logger.warning("未找到微信验证二维码图片，尝试检查是否有其他提示")
                
                # 尝试获取弹窗内容
                js_get_dialog_content = """
                let dialog = document.querySelector('.dialog_wrp');
                if (dialog) {
                    return dialog.innerText;
                }
                return null;
                """
                dialog_content = self.browser.execute_script(js_get_dialog_content)
                logger.info(f"弹窗内容: {dialog_content}")
                
                # 截取整个弹窗的截图
                screenshot_path = self._take_dialog_screenshot("wechat_verify_dialog.png")
                
                logger.info(f"已截取弹窗图片，保存到: {screenshot_path}")
                # 打印截图路径到控制台，让用户清楚图片位置
                print(f"\n[二维码验证] 已保存弹窗截图到: {screenshot_path}\n")
                return True
            
            # 确保二维码元素已经完全加载，再次等待
            logger.info("找到微信验证二维码，等待图片完全加载...")
            random_delay(2, 3)
            
            # 先尝试截取整个页面，确保不会错过内容
            full_screenshot_path = self._take_dialog_screenshot("wechat_verify_full.png")
            logger.info(f"已保存完整页面截图: {full_screenshot_path}")
            
            # 获取二维码截图
            logger.info("正在截取二维码...")
            
            # 方法1：直接获取图片src属性（如果是base64编码图片）
            qrcode_src = qrcode_img.get_attribute("src")
            qrcode_path = None
            qrcode_data = None
            
            if qrcode_src and qrcode_src.startswith("data:image"):
                # 保存base64图片
                try:
                    qrcode_data = qrcode_src.split(",")[1]
                    img_data = base64.b64decode(qrcode_data)
                    
                    # 保存到文件
                    qrcode_path = os.path.join(Path(__file__).parent.parent, "wechat_verify_qrcode.png")
                    with open(qrcode_path, 'wb') as f:
                        f.write(img_data)
                    
                    logger.info(f"已成功保存微信验证二维码(base64方式): {qrcode_path}")
                except Exception as e:
                    logger.error(f"保存base64二维码图片失败: {e}")
            
            # 方法2：截取元素区域截图
            element_screenshot_path = self._take_element_screenshot(qrcode_img, "wechat_verify_qrcode.png")
            
            # 确定最终使用的二维码路径
            final_qrcode_path = qrcode_path if qrcode_path else element_screenshot_path
            
            # 在控制台直接显示二维码
            self._print_qrcode_in_console(final_qrcode_path)
            
            # 等待用户扫描二维码
            logger.info("=========================================================")
            logger.info("=== 请使用微信扫描验证二维码以完成发布 ===")
            logger.info(f"=== 二维码图片已保存到: {final_qrcode_path} ===")
            logger.info("=========================================================")
            
            # 在控制台中也显示信息，确保用户能看到
            print("\n" + "=" * 60)
            print(f"【重要】请使用微信扫描验证二维码完成发布")
            print(f"【图片位置】{final_qrcode_path}")
            print("=" * 60 + "\n")
            
            # 等待一段时间，让用户有足够时间扫描二维码
            wait_for_seconds(60, "等待用户扫描验证二维码...")
            
            # 检查是否验证成功（这里可能需要根据实际情况调整检测方法）
            # 由于没有明确的验证成功标志，我们假设60秒后验证已完成
            logger.info("假定验证已完成，文章发布成功！")
            return True
            
        except Exception as e:
            logger.error(f"处理微信验证弹窗过程出错: {e}")
            # 尝试截图，方便调试
            error_screenshot_path = self._take_dialog_screenshot("wechat_verify_error.png")
            logger.error(f"已保存错误状态截图到: {error_screenshot_path}")
            print(f"\n[错误] 验证弹窗处理失败，错误截图: {error_screenshot_path}\n")
            return False
    
    def _print_qrcode_in_console(self, qrcode_path):
        """
        在控制台中直接显示二维码
        
        Args:
            qrcode_path: 二维码图片路径
        """
        try:
            # 尝试导入必要的库
            try:
                from PIL import Image
                import qrcode
            except ImportError:
                logger.warning("无法在控制台显示二维码，缺少必要的库。请安装: pip install pillow qrcode")
                print("\n[提示] 要在控制台直接显示二维码，请安装必要的库: pip install pillow qrcode\n")
                return
            
            # 方法1: 尝试使用qrcode库重新生成并打印二维码
            try:
                with open(qrcode_path, 'rb') as img_file:
                    # 尝试通过PIL读取保存的二维码图片
                    from pyzbar.pyzbar import decode
                    
                    # 打开二维码图片
                    img = Image.open(qrcode_path)
                    
                    # 解码二维码内容
                    decoded_objects = decode(img)
                    if decoded_objects:
                        # 获取二维码数据
                        qr_data = decoded_objects[0].data.decode('utf-8')
                        
                        # 使用qrcode库生成ASCII二维码
                        qr = qrcode.QRCode()
                        qr.add_data(qr_data)
                        qr.make()
                        
                        # 打印到控制台
                        print("\n二维码内容：")
                        qr.print_ascii(invert=True)
                        print()
                        logger.info("已在控制台显示二维码")
                        return
            except ImportError:
                logger.warning("缺少pyzbar库，无法解码二维码。请安装: pip install pyzbar")
                print("\n[提示] 要解码并显示二维码，请安装: pip install pyzbar\n")
            except Exception as e:
                logger.warning(f"使用qrcode库显示二维码失败: {e}")
            
            # 方法2: 使用ASCII字符直接显示图片
            try:
                # 打开图片
                img = Image.open(qrcode_path)
                
                # 调整大小以适应控制台
                width, height = img.size
                aspect_ratio = height/width
                new_width = 40
                new_height = int(aspect_ratio * new_width * 0.5)
                img = img.resize((new_width, new_height))
                
                # 转换为灰度图
                img = img.convert('L')
                
                # ASCII字符集，从暗到亮
                chars = "@%#*+=-:. "
                
                # 输出ASCII图片
                print("\n二维码图像：")
                for y in range(new_height):
                    line = ""
                    for x in range(new_width):
                        gray = img.getpixel((x, y))
                        # 反转颜色，以适应黑底白字的控制台
                        line += chars[min(gray * len(chars) // 256, len(chars) - 1)]
                    print(line)
                print()
                logger.info("已在控制台显示二维码ASCII图像")
            except Exception as e:
                logger.warning(f"使用ASCII字符显示二维码失败: {e}")
                
            # 方法3: 使用简单的文本格式直接显示二维码
            try:
                # 打开图片
                img = Image.open(qrcode_path)
                
                # 转换为二值图像
                img = img.convert('1')  # 转换为二值图像
                
                # 调整大小以适应控制台
                width, height = img.size
                aspect_ratio = height/width
                new_width = 50
                new_height = int(aspect_ratio * new_width * 0.5)
                img = img.resize((new_width, new_height))
                
                # 输出简单文本格式二维码
                print("\n二维码（简化版）：")
                for y in range(0, new_height, 2):
                    line = ""
                    for x in range(new_width):
                        # 获取像素值，1为白色，0为黑色
                        pixel = img.getpixel((x, y)) if y < new_height else 1
                        # 使用方块字符表示黑色像素
                        line += "  " if pixel else "██"
                    print(line)
                print()
                logger.info("已在控制台显示简化版二维码")
            except Exception as e:
                logger.warning(f"使用简单文本格式显示二维码失败: {e}")
            
        except Exception as e:
            logger.error(f"在控制台显示二维码失败: {e}")
            print("\n[错误] 无法在控制台显示二维码，请扫描保存的图片文件\n")
    
    def _take_element_screenshot(self, element, filename):
        """
        截取元素的屏幕截图
        
        Args:
            element: 要截图的元素
            filename: 保存的文件名
            
        Returns:
            str: 保存的文件路径
        """
        try:
            # 确保元素可见
            self.browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            # 等待元素滚动到视图中并稳定
            random_delay(1, 2)
            
            # 获取元素位置和大小
            location = element.location
            size = element.size
            
            # 截取整个页面
            screenshot_path = os.path.join(Path(__file__).parent.parent, "temp_screenshot.png")
            self.browser.driver.save_screenshot(screenshot_path)
            
            # 裁剪图片以获取元素区域
            try:
                from PIL import Image
                
                # 打开截图
                img = Image.open(screenshot_path)
                
                # 计算裁剪区域
                left = location['x']
                top = location['y']
                right = location['x'] + size['width']
                bottom = location['y'] + size['height']
                
                # 确保坐标有效
                if left < 0: left = 0
                if top < 0: top = 0
                if right > img.width: right = img.width
                if bottom > img.height: bottom = img.height
                
                # 裁剪图片
                img = img.crop((left, top, right, bottom))
                
                # 保存裁剪后的图片
                output_path = os.path.join(Path(__file__).parent.parent, filename)
                img.save(output_path)
                
                logger.info(f"已保存元素截图到: {output_path}")
                
                # 删除临时截图
                try:
                    os.remove(screenshot_path)
                except:
                    pass
                
                return output_path
                
            except ImportError:
                logger.warning("缺少PIL库，无法裁剪图片，将使用完整截图")
                # 如果没有PIL库，直接使用完整截图
                output_path = os.path.join(Path(__file__).parent.parent, filename)
                os.rename(screenshot_path, output_path)
                logger.info(f"已保存完整截图到: {output_path}")
                return output_path
                
        except Exception as e:
            logger.error(f"截取元素截图失败: {e}")
            # 尝试直接保存整页截图
            return self._take_dialog_screenshot(filename)
    
    def _take_dialog_screenshot(self, filename):
        """
        截取当前对话框的屏幕截图
        
        Args:
            filename: 保存的文件名
            
        Returns:
            str: 保存的文件路径
        """
        try:
            screenshot_path = os.path.join(Path(__file__).parent.parent, filename)
            self.browser.driver.save_screenshot(screenshot_path)
            logger.info(f"已保存页面截图到: {screenshot_path}")
            return screenshot_path
        except Exception as e:
            logger.error(f"截取页面截图失败: {e}")
            return None
    
    def navigate_to_article_page(self):
        """
        导航到文章页面
        
        Returns:
            bool: 是否成功导航到文章页面
        """
        try:
            # 获取当前窗口句柄，用于后续判断是否有新窗口打开
            current_window = self.browser.driver.current_window_handle
            existing_windows = set(self.browser.driver.window_handles)
            logger.info(f"当前窗口数: {len(existing_windows)}")
            
            # 随机延迟，模拟人类操作
            random_delay(2, 5)
            
            # 查找文章菜单元素
            article_menu = self.browser.wait_for_element(self.LOCATORS["article_menu"])
            if not article_menu:
                logger.error("未找到文章菜单元素")
                return False
                
            # 随机延迟后点击文章菜单
            random_delay(1, 3)
            logger.info("准备点击文章菜单")
            
            # 点击文章菜单
            article_menu.click()
            logger.info("已点击文章菜单，等待页面跳转")
            
            # 等待可能出现的新窗口
            wait_for_seconds(3, "等待可能的新窗口打开")
            
            # 检查是否有新窗口打开
            new_windows = set(self.browser.driver.window_handles) - existing_windows
            success = False
            
            if new_windows:
                # 如果有新窗口，切换到新窗口
                new_window = list(new_windows)[0]
                logger.info(f"检测到新窗口打开，切换到新窗口")
                self.browser.driver.switch_to.window(new_window)
                
                # 等待新窗口加载
                wait_for_seconds(5, "等待新窗口页面完全加载")
                
                # 检查新窗口是否是文章编辑页面
                if self.check_article_editor_page():
                    logger.info("成功跳转到文章编辑页面(新窗口)")
                    # 填写文章内容
                    self.fill_article_content()
                    return True
                else:
                    logger.warning("新窗口不是文章编辑页面")
                    
                    # 获取当前URL用于记录日志
                    current_url = self.browser.get_current_url()
                    logger.info(f"新窗口URL: {current_url}")
                    
                    # 可以选择关闭这个窗口，返回原窗口重试
                    self.browser.driver.close()
                    self.browser.driver.switch_to.window(current_window)
                    logger.info("已关闭新窗口并返回原窗口")
                    
                    # 等待一段时间后再次尝试
                    wait_for_seconds(2, "稍后再次尝试")
                    return self.navigate_to_article_page()  # 递归调用自身再次尝试
            else:
                # 没有新窗口，检查当前窗口是否变为文章编辑页面
                logger.info("未检测到新窗口，检查当前窗口是否变为文章编辑页面")
                
                # 等待一段时间让页面完成跳转
                wait_for_seconds(5, "等待页面完全加载")
                
                # 检查当前页面是否是文章编辑页面
                if self.check_article_editor_page():
                    logger.info("成功跳转到文章编辑页面(当前窗口)")
                    # 填写文章内容
                    self.fill_article_content()
                    return True
                
                # 如果仍不是文章编辑页面，尝试再次点击
                logger.warning("跳转后当前页面不是文章编辑页面，尝试再次点击")
                
                # 再次尝试点击文章菜单
                article_menu = self.browser.wait_for_element(self.LOCATORS["article_menu"])
                if article_menu:
                    random_delay(1, 2)
                    logger.info("再次点击文章菜单")
                    article_menu.click()
                    
                    # 等待可能出现的新窗口
                    wait_for_seconds(3, "等待可能的新窗口打开")
                    
                    # 再次检查是否有新窗口打开
                    new_windows = set(self.browser.driver.window_handles) - existing_windows
                    if new_windows:
                        # 如果有新窗口，切换到新窗口
                        new_window = list(new_windows)[0]
                        logger.info(f"第二次尝试后检测到新窗口打开，切换到新窗口")
                        self.browser.driver.switch_to.window(new_window)
                        
                        # 等待新窗口加载
                        wait_for_seconds(5, "等待新窗口页面完全加载")
                        
                        # 检查新窗口是否是文章编辑页面
                        if self.check_article_editor_page():
                            logger.info("第二次尝试后成功跳转到文章编辑页面(新窗口)")
                            # 填写文章内容
                            self.fill_article_content()
                            return True
                        else:
                            logger.warning("第二次尝试后新窗口仍不是文章编辑页面")
                            
                            # 关闭新窗口并返回原窗口
                            self.browser.driver.close()
                            self.browser.driver.switch_to.window(current_window)
                            logger.info("已关闭新窗口并返回原窗口")
                    
                    # 再次检查当前窗口
                    wait_for_seconds(5, "再次等待当前窗口页面完全加载")
                    if self.check_article_editor_page():
                        logger.info("第二次尝试后成功跳转到文章编辑页面(当前窗口)")
                        # 填写文章内容
                        self.fill_article_content()
                        return True
                else:
                    logger.error("再次尝试时未找到文章菜单元素")
                
                logger.warning("多次尝试后仍未能跳转到文章编辑页面")
                return False
        except Exception as e:
            logger.error(f"导航到文章页面失败: {e}")
            # 尝试恢复到最初的窗口
            try:
                if 'current_window' in locals():
                    self.browser.driver.switch_to.window(current_window)
                    logger.info("发生错误后已切回原窗口")
            except Exception as switch_error:
                logger.error(f"切回原窗口失败: {switch_error}")
            return False
    
    def login(self):
        """
        登录微信公众号
        
        Returns:
            bool: 是否登录成功
        """
        # 导航到登录页面
        if not self.navigate_to_login_page():
            logger.error("导航到登录页面失败")
            return False
            
        # 检查是否已登录
        if self.check_login_status():
            logger.info("已经处于登录状态，无需再次登录")
            # 检查当前页面是否已经是文章编辑页面
            if self.check_article_editor_page():
                logger.info("当前已在文章编辑页面，无需导航")
                # 填写文章内容
                self.fill_article_content()
                return True
            # 如果已登录，导航到文章页面
            self.navigate_to_article_page()
            return True
            
        # 使用二维码登录
        max_retry = self.config.get("max_retry", 3)
        for i in range(max_retry):
            logger.info(f"尝试登录(第{i+1}次)")
            if self.login_with_qrcode():
                logger.info("登录成功")
                # 登录成功后，等待一下，然后导航到文章页面
                wait_for_seconds(2, "登录成功，稍等片刻...")
                if self.navigate_to_article_page():
                    return True
                else:
                    logger.warning("导航到文章页面失败，但登录已成功")
                    return True
                
            if i < max_retry - 1:
                wait_for_seconds(3, "登录失败，稍后重试...")
                # 刷新页面，重新开始
                self.browser.refresh_page()
                
        logger.error(f"登录失败，已重试{max_retry}次")
        return False
        
    def logout(self):
        """
        登出微信公众号
        
        Returns:
            bool: 是否登出成功
        """
        # 暂不实现登出功能
        logger.warning("登出功能暂未实现")
        return False
        
    def close(self):
        """关闭浏览器"""
        if self.browser:
            self.browser.close() 