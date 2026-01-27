"""
基金插件本地图片生成模块
使用 Playwright 浏览器渲染 HTML 模板并截图
"""

import asyncio
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Dict, Any

from astrbot.api import logger

# Jinja2 模板引擎
try:
    from jinja2 import Template, Environment, select_autoescape
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False
    logger.warning("Jinja2未安装，将使用简单字符串替换")

# Playwright 浏览器
try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright未安装，本地图片生成功能将不可用")


class ImageGenerationError(Exception):
    """图片生成异常"""
    pass


class LocalImageGenerator:
    """本地图片生成器
    
    使用 Playwright 浏览器渲染 HTML 模板并截图，
    确保图片宽度与内容宽度完全一致。
    """

    def __init__(self, width: int = 420, device_scale_factor: float = 2.0):
        """初始化图片生成器
        
        Args:
            width: 图片宽度（像素）
            device_scale_factor: 设备像素比，用于生成高清图片
        """
        self.width = width
        self.device_scale_factor = device_scale_factor
        self.browser: Optional[Browser] = None
        self.playwright = None
        self._initialized = False
        
        # Jinja2 环境
        self.jinja_env = None
        if JINJA2_AVAILABLE:
            self.jinja_env = Environment(
                autoescape=select_autoescape(['html', 'xml']),
                trim_blocks=True,
                lstrip_blocks=True
            )

    async def initialize(self):
        """初始化 Playwright 浏览器"""
        if self._initialized:
            return
            
        if not PLAYWRIGHT_AVAILABLE:
            raise ImageGenerationError("Playwright 未安装，请执行: pip install playwright && playwright install chromium")
        
        try:
            logger.info("正在初始化本地图片生成器...")
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions"
                ]
            )
            self._initialized = True
            logger.info("本地图片生成器初始化成功")
        except Exception as e:
            logger.error(f"初始化图片生成器失败: {e}")
            raise ImageGenerationError(f"初始化失败: {e}")

    async def cleanup(self):
        """清理资源"""
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            self._initialized = False
            logger.info("图片生成器资源已清理")
        except Exception as e:
            logger.error(f"清理资源失败: {e}")

    async def render_template(
        self,
        template_str: str,
        template_data: Dict[str, Any],
        width: Optional[int] = None
    ) -> str:
        """渲染 HTML 模板并生成图片
        
        Args:
            template_str: HTML 模板字符串
            template_data: 模板数据
            width: 可选的自定义宽度
            
        Returns:
            生成的图片文件路径
        """
        if not self._initialized:
            await self.initialize()
        
        render_width = width or self.width
        page: Optional[Page] = None
        
        try:
            # 渲染 HTML 内容
            if JINJA2_AVAILABLE and self.jinja_env:
                template = self.jinja_env.from_string(template_str)
                html_content = template.render(**template_data)
            else:
                # 简单字符串替换
                html_content = template_str
                for key, value in template_data.items():
                    html_content = html_content.replace("{{ " + key + " }}", str(value))
                    html_content = html_content.replace("{{" + key + "}}", str(value))
            
            # 创建页面
            page = await self.browser.new_page(
                viewport={"width": render_width, "height": 1},
                device_scale_factor=self.device_scale_factor
            )
            
            # 设置页面内容
            await page.set_content(html_content, wait_until="networkidle")
            
            # 等待渲染完成
            await page.wait_for_timeout(500)
            
            # 获取实际内容高度
            body_height = await page.evaluate("document.body.scrollHeight")
            
            # 重新设置视口高度为实际内容高度
            await page.set_viewport_size({"width": render_width, "height": body_height})
            
            # 生成临时文件路径
            temp_filename = f"fund_image_{uuid.uuid4().hex}.png"
            temp_path = Path(tempfile.gettempdir()) / temp_filename
            
            # 截图 - 使用 full_page 确保完整截取
            await page.screenshot(
                path=str(temp_path),
                full_page=True,
                type="png"
            )
            
            logger.debug(f"图片生成成功: {temp_path}, 尺寸: {render_width}x{body_height}")
            return str(temp_path)
            
        except Exception as e:
            logger.error(f"生成图片失败: {e}")
            raise ImageGenerationError(f"生成图片失败: {e}")
        finally:
            if page:
                await page.close()

    async def render_template_file(
        self,
        template_path: Path,
        template_data: Dict[str, Any],
        width: Optional[int] = None
    ) -> str:
        """从文件加载模板并渲染
        
        Args:
            template_path: 模板文件路径
            template_data: 模板数据
            width: 可选的自定义宽度
            
        Returns:
            生成的图片文件路径
        """
        if not template_path.exists():
            raise ImageGenerationError(f"模板文件不存在: {template_path}")
        
        with open(template_path, "r", encoding="utf-8") as f:
            template_str = f.read()
        
        return await self.render_template(template_str, template_data, width)


# 全局实例（懒加载）
_generator: Optional[LocalImageGenerator] = None


async def get_generator(width: int = 420, device_scale_factor: float = 2.0) -> LocalImageGenerator:
    """获取全局图片生成器实例
    
    Args:
        width: 默认图片宽度
        device_scale_factor: 设备像素比
        
    Returns:
        LocalImageGenerator 实例
    """
    global _generator
    if _generator is None:
        _generator = LocalImageGenerator(width=width, device_scale_factor=device_scale_factor)
    return _generator


async def render_fund_image(
    template_path: Path,
    template_data: Dict[str, Any],
    width: int = 420
) -> str:
    """渲染基金图片的便捷函数
    
    Args:
        template_path: 模板文件路径
        template_data: 模板数据
        width: 图片宽度
        
    Returns:
        生成的图片文件路径
    """
    generator = await get_generator(width=width)
    return await generator.render_template_file(template_path, template_data, width)
