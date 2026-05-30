"""
OCR 前图像预处理：适当放大、长图分片，减轻缺字与长图被过度缩小的问题。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

from utils.logger_loguru import get_logger

logger = get_logger("OCRPreprocess")

_MIN_LONG_SIDE = 1200
_MAX_SLICE_HEIGHT = 2800
_SLICE_OVERLAP = 120


def prepare_ocr_image_paths(source_path: str) -> List[str]:
    """
    返回用于 OCR 的本地路径列表（可能 1 张或多张分片）。
    调用方负责删除返回的临时文件（除 source_path 本身外）。
    """
    try:
        from PIL import Image
    except ImportError:
        return [source_path]

    paths: List[str] = []
    own_temps: List[str] = []

    try:
        im = Image.open(source_path).convert("RGB")
        w, h = im.size

        long_side = max(w, h)
        if long_side < _MIN_LONG_SIDE and long_side > 0:
            scale = _MIN_LONG_SIDE / long_side
            nw, nh = int(w * scale), int(h * scale)
            im = im.resize((nw, nh), Image.Resampling.LANCZOS)
            w, h = im.size

        if h > _MAX_SLICE_HEIGHT and h > w * 1.2:
            y = 0
            idx = 0
            while y < h:
                y2 = min(y + _MAX_SLICE_HEIGHT, h)
                crop = im.crop((0, y, w, y2))
                fd, temp_path = tempfile.mkstemp(suffix=f"_slice{idx}.jpg")
                import os

                with os.fdopen(fd, "wb") as f:
                    crop.save(f, format="JPEG", quality=92)
                paths.append(temp_path)
                own_temps.append(temp_path)
                if y2 >= h:
                    break
                y = y2 - _SLICE_OVERLAP
                idx += 1
        else:
            orig = Image.open(source_path)
            orig_size = orig.size
            orig.close()
            if (w, h) != orig_size:
                fd, temp_path = tempfile.mkstemp(suffix=".jpg")
                import os

                with os.fdopen(fd, "wb") as f:
                    im.save(f, format="JPEG", quality=92)
                paths.append(temp_path)
            else:
                paths.append(source_path)

        return paths if paths else [source_path]
    except Exception as e:
        logger.debug(f"图像预处理失败，使用原图: {e}")
        return [source_path]
