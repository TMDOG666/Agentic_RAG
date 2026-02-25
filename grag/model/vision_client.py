"""grag.model.vision_client

视觉模型客户端（Vision Model Client）

职责：
- 提供图像OCR和理解能力
- 支持多种视觉模型提供商
- 处理图像输入并返回文本结果

说明：
- 支持本地图像文件和URL
- 使用OpenAI兼容的API格式
- 支持base64编码的图像
"""

import os
import base64
from typing import Optional, Dict, Any, Union
from pathlib import Path
from openai import OpenAI

from ..config import get_config_manager, ProviderType


class VisionClient:
    """视觉模型客户端
    
    用于图像OCR和理解，支持多种视觉模型提供商
    """
    
    def __init__(self, provider_name: Optional[str] = None):
        """初始化视觉模型客户端
        
        Args:
            provider_name: 提供商名称，为None时使用配置中的默认值
        """
        self.provider_name = provider_name
        self._client: Optional[OpenAI] = None
        self._settings = get_config_manager().get_settings()
        
    def _get_config(self):
        """获取当前提供商的配置"""
        return self._settings.get_provider_config(
            ProviderType.VISION,
            self.provider_name or self._settings.vision_provider
        )
    
    def _get_client(self) -> OpenAI:
        """获取或创建OpenAI客户端（懒加载）"""
        if self._client is not None:
            return self._client
            
        config = self._get_config()
        api_key = os.environ.get(config.api_key_env, "dummy-key")
        
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.timeout
        )
        return self._client
    
    def _encode_image(self, image_path: Union[str, Path]) -> str:
        """将图像文件编码为base64字符串
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            base64编码的图像字符串
        """
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    
    def _get_image_mime_type(self, image_path: Union[str, Path]) -> str:
        """获取图像的MIME类型
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            MIME类型字符串
        """
        suffix = Path(image_path).suffix.lower()
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.webp': 'image/webp'
        }
        return mime_types.get(suffix, 'image/jpeg')
    
    def ocr_image(
        self,
        image_path: Union[str, Path],
        prompt: Optional[str] = None,
        detail: str = "high"
    ) -> str:
        """对图像进行OCR识别
        
        Args:
            image_path: 图像文件路径
            prompt: 自定义提示词，默认为OCR提示
            detail: 图像细节级别，可选 "low", "high", "auto"
            
        Returns:
            识别出的文本内容
        """
        if prompt is None:
            prompt = """请仔细识别图像中的所有文字内容，包括：
1. 标题、正文、注释等所有文本
2. 表格中的内容
3. 图表中的标签和数值
4. 保持原有的格式和结构

请直接输出识别的文字，不要添加额外说明。"""
        
        return self.understand_image(image_path, prompt, detail)
    
    def understand_image(
        self,
        image_path: Union[str, Path],
        prompt: str,
        detail: str = "high"
    ) -> str:
        """理解图像内容
        
        Args:
            image_path: 图像文件路径
            prompt: 提示词，描述需要从图像中提取什么信息
            detail: 图像细节级别，可选 "low", "high", "auto"
            
        Returns:
            模型的响应文本
        """
        client = self._get_client()
        config = self._get_config()
        
        # 编码图像
        base64_image = self._encode_image(image_path)
        mime_type = self._get_image_mime_type(image_path)
        
        # 构建消息
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}",
                            "detail": detail
                        }
                    }
                ]
            }
        ]
        
        # 调用API
        response = client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens
        )
        
        return response.choices[0].message.content
    
    def batch_ocr(
        self,
        image_paths: list[Union[str, Path]],
        prompt: Optional[str] = None
    ) -> list[str]:
        """批量OCR识别
        
        Args:
            image_paths: 图像文件路径列表
            prompt: 自定义提示词
            
        Returns:
            识别结果列表
        """
        results = []
        for image_path in image_paths:
            try:
                result = self.ocr_image(image_path, prompt)
                results.append(result)
            except Exception as e:
                results.append(f"[OCR失败: {e}]")
        return results
    
    def get_config_info(self) -> Dict[str, Any]:
        """返回当前配置信息"""
        config = self._get_config()
        return {
            "provider": self.provider_name or self._settings.vision_provider,
            "model": config.model,
            "base_url": config.base_url,
            "timeout": config.timeout
        }


# 全局单例
_default_vision_client: Optional[VisionClient] = None


def get_vision_client(provider_name: Optional[str] = None) -> VisionClient:
    """获取视觉模型客户端实例
    
    Args:
        provider_name: 提供商名称，为None时使用默认配置
        
    Returns:
        VisionClient实例
    """
    global _default_vision_client
    if _default_vision_client is None or provider_name is not None:
        _default_vision_client = VisionClient(provider_name)
    return _default_vision_client
