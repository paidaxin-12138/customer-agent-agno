# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
知识库UI模块

提供知识库管理相关的UI组件和数据模型。
"""

from .models import (
    SimpleDocument,
    DocumentTitleExtractor,
    MarkdownConverter,
    ImportError as KnowledgeImportError  # 重命名避免与内置冲突
)
from .widgets import KnowledgeCard, AddKnowledgeDialog, KnowledgeDetailFlyout

__all__ = [
    'SimpleDocument',
    'DocumentTitleExtractor',
    'MarkdownConverter',
    'KnowledgeImportError',  # 使用重命名后的版本
    'KnowledgeCard',
    'AddKnowledgeDialog',
    'KnowledgeDetailFlyout',
]
