#!/usr/bin/env python3
"""
OCR 工具模块
使用 PaddleOCR 识别商品图片文字
"""

from typing import List, Optional, Dict, Any
import os
import requests
import tempfile
from utils.logger_loguru import get_logger

logger = get_logger("OCR")

# OCR 引擎（单例）
_ocr_engine = None


def get_ocr_engine():
    """获取 OCR 引擎（单例模式）"""
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from paddleocr import PaddleOCR
            _ocr_engine = PaddleOCR(
                use_angle_cls=True,
                lang='ch'
            )
            logger.info("PaddleOCR 初始化成功")
        except ImportError as e:
            logger.error(f"PaddleOCR 未安装，请运行：pip install paddlepaddle paddleocr")
            raise
        except Exception as e:
            logger.error(f"PaddleOCR 初始化失败：{e}")
            raise
    return _ocr_engine


def download_image(image_url: str, timeout: int = 10) -> Optional[str]:
    """
    下载图片到临时文件
    
    Args:
        image_url: 图片 URL
        timeout: 下载超时时间（秒）
        
    Returns:
        本地文件路径，失败返回 None
    """
    try:
        response = requests.get(image_url, timeout=timeout)
        response.raise_for_status()
        
        # 确定文件后缀
        suffix = 'jpg'
        if '?' in image_url:
            image_url = image_url.split('?')[0]
        if '.' in image_url:
            suffix = image_url.split('.')[-1]
            if len(suffix) > 5:
                suffix = 'jpg'
        
        # 保存到临时文件
        fd, temp_path = tempfile.mkstemp(suffix=f'.{suffix}')
        with os.fdopen(fd, 'wb') as f:
            f.write(response.content)
        
        return temp_path
        
    except Exception as e:
        logger.debug(f"下载图片失败 {image_url}: {e}")
        return None


def extract_text_from_image(image_path: str) -> List[str]:
    """
    从单张图片提取文字
    
    Args:
        image_path: 图片文件路径
        
    Returns:
        识别的文字列表
    """
    try:
        engine = get_ocr_engine()
        result = engine.ocr(image_path, cls=True)
        
        if result and result[0]:
            texts = [line[1][0] for line in result[0]]
            return texts
        return []
        
    except Exception as e:
        logger.debug(f"OCR 识别失败 {image_path}: {e}")
        return []


def extract_text_from_images(
    image_urls: List[str],
    max_images: int = 5,
    max_lines_per_image: int = 10
) -> Dict[str, Any]:
    """
    从多张图片提取文字
    
    Args:
        image_urls: 图片 URL 列表
        max_images: 最多处理的图片数量
        max_lines_per_image: 每张图最多保留的文字行数
        
    Returns:
        {
            "success": True/False,
            "texts": ["文字 1", "文字 2", ...],
            "full_text": "完整的文字内容",
            "count": 识别成功的图片数量
        }
    """
    result = {
        "success": False,
        "texts": [],
        "full_text": "",
        "count": 0
    }
    
    if not image_urls:
        return result
    
    all_texts = []
    success_count = 0
    
    for i, url in enumerate(image_urls[:max_images]):
        try:
            logger.debug(f"正在 OCR 识别图片 {i+1}/{len(image_urls)}: {url[:80]}...")
            
            # 下载图片
            temp_path = download_image(url)
            if not temp_path:
                continue
            
            # OCR 识别
            texts = extract_text_from_image(temp_path)
            
            if texts:
                # 限制每张图的行数
                limited_texts = texts[:max_lines_per_image]
                all_texts.append({
                    "image_index": i,
                    "texts": limited_texts,
                    "full": ' | '.join(limited_texts)
                })
                success_count += 1
            
            # 清理临时文件
            try:
                os.remove(temp_path)
            except:
                pass
                
        except Exception as e:
            logger.debug(f"OCR 识别失败 {url}: {e}")
    
    if all_texts:
        result["success"] = True
        result["texts"] = all_texts
        result["count"] = success_count
        result["full_text"] = '\n\n'.join([
            f"图片{i['image_index']+1}: {i['full']}"
            for i in all_texts
        ])
    
    return result


def format_ocr_result(ocr_data: Dict[str, Any]) -> str:
    """
    格式化 OCR 结果为 Markdown
    
    Args:
        ocr_data: extract_text_from_images 返回的结果
        
    Returns:
        Markdown 格式的文字
    """
    if not ocr_data.get("success"):
        return "暂无图片文字信息"
    
    lines = [
        "## 图片文字信息（OCR 识别）",
        "",
        f"共识别 {ocr_data['count']} 张图片",
        "",
        ocr_data["full_text"],
        ""
    ]
    
    return '\n'.join(lines)


# ========== 便捷函数 ==========

def ocr_product_images(image_urls: List[str]) -> str:
    """
    识别商品图片文字并返回 Markdown 格式
    
    Args:
        image_urls: 商品图片 URL 列表
        
    Returns:
        Markdown 格式的文字内容
    """
    ocr_result = extract_text_from_images(image_urls)
    return format_ocr_result(ocr_result)


if __name__ == "__main__":
    # 测试示例
    test_urls = [
        "https://example.com/product1.jpg",
        "https://example.com/product2.jpg"
    ]
    
    result = ocr_product_images(test_urls)
    print(result)
