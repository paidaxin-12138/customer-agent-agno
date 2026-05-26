"""
知识库增强模块 - 基于继承的扩展

功能：
1. 进度追踪：实时反馈导入进度
2. 可中断操作：支持取消长时间运行的导入
3. 完全兼容：保持与 agno 的数据格式和接口兼容

作者：晋院悍匪派大星
日期：2025-12-25
"""

import asyncio
import logging
from enum import Enum
from typing import Callable, Optional, List, Any, Dict

# 导入 agno 基类
from agno.vectordb.lancedb import LanceDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.document import Document

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. 基础类型定义
# ==============================================================================

class ImportStage(Enum):
    """导入阶段枚举"""
    READING = "reading"        # 读取文件
    CHUNKING = "chunking"      # 文档分块
    EMBEDDING = "embedding"    # 生成向量
    SAVING = "saving"          # 保存到数据库


ProgressCallback = Callable[
    [ImportStage, int, int, str, Optional[Dict]],  # (stage, current, total, message, metadata)
    None
]


class CancelToken:
    """取消令牌 - 用于中断长时间运行的操作"""

    def __init__(self):
        self._cancelled = False

    def cancel(self):
        """请求取消操作"""
        logger.info("收到取消请求")
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """检查是否已取消"""
        return self._cancelled

    def reset(self):
        """重置令牌（可复用）"""
        self._cancelled = False


# ==============================================================================
# 2. 增强的 LanceDB
# ==============================================================================

class LanceDbWithProgress(LanceDb):
    """
    增强的 LanceDB - 添加进度追踪和取消支持

    继承自 agno.vectordb.lancedb.LanceDb
    保持完全的数据格式兼容性
    """

    def __init__(
        self,
        *args,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
        **kwargs
    ):
        """
        初始化

        参数：
            progress_callback: 进度回调函数
            cancel_token: 取消令牌
        """
        super().__init__(*args, **kwargs)
        self.progress_callback = progress_callback
        self.cancel_token = cancel_token

    def insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        重写同步 insert 方法，添加进度报告和取消支持
        """
        logger.debug(f"[LanceDbWithProgress] insert() 被调用，文档数: {len(documents)}, 进度回调: {self.progress_callback is not None}")

        if len(documents) <= 0:
            logger.info("没有文档需要插入")
            return

        # 报告开始嵌入
        if self.progress_callback:
            logger.info(f"开始向量化 {len(documents)} 个文档")
            self.progress_callback(
                ImportStage.EMBEDDING,
                0,
                len(documents),
                f"开始向量化 {len(documents)} 个文档"
            )

        # 处理每个文档
        processed_count = 0
        for idx, document in enumerate(documents):
            # 检查取消
            if self.cancel_token and self.cancel_token.is_cancelled:
                logger.info(f"插入已取消，已完成 {processed_count}/{len(documents)} 个文档")
                break

            # 检查文档是否已存在
            if self.doc_exists(document):
                logger.debug(f"文档已存在，跳过: {document.name}")
                continue

            # 添加 filters 到元数据
            if filters:
                meta_data = document.meta_data.copy() if document.meta_data else {}
                meta_data.update(filters)
                document.meta_data = meta_data

            # 嵌入文档（同步）
            try:
                logger.debug(f"正在嵌入文档 {idx+1}/{len(documents)}: {document.name}")
                document.embed(embedder=self.embedder)
                processed_count += 1

                # 报告进度
                if self.progress_callback:
                    self.progress_callback(
                        ImportStage.EMBEDDING,
                        idx + 1,
                        len(documents),
                        f"已处理: {document.name}",
                        metadata={"doc_name": document.name}
                    )

            except Exception as e:
                logger.error(f"嵌入文档失败 {document.name}: {e}")
                continue

        # 调用父类的 insert 方法保存
        try:
            logger.debug(f"调用父类 insert() 保存 {len(documents)} 个文档")
            super().insert(content_hash, documents, filters)

            # 报告完成
            if self.progress_callback:
                logger.info(f"完成！成功保存 {processed_count} 个文档")
                self.progress_callback(
                    ImportStage.SAVING,
                    len(documents),
                    len(documents),
                    f"完成！成功保存 {processed_count} 个文档"
                )

        except Exception as e:
            logger.error(f"保存文档失败: {e}")
            raise

    async def async_insert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        重写异步 insert 方法，添加进度报告和取消支持
        """
        logger.debug(f"[LanceDbWithProgress] async_insert() 被调用，文档数: {len(documents)}, 进度回调: {self.progress_callback is not None}")

        if len(documents) <= 0:
            logger.info("没有文档需要插入")
            return

        # 报告开始嵌入
        if self.progress_callback:
            logger.info(f"开始向量化 {len(documents)} 个文档")
            self.progress_callback(
                ImportStage.EMBEDDING,
                0,
                len(documents),
                f"开始向量化 {len(documents)} 个文档"
            )

        # 处理每个文档
        processed_count = 0
        for idx, document in enumerate(documents):
            # 检查取消
            if self.cancel_token and self.cancel_token.is_cancelled:
                logger.info(f"插入已取消，已完成 {processed_count}/{len(documents)} 个文档")
                break

            # 检查文档是否已存在
            if self.doc_exists(document):
                logger.debug(f"文档已存在，跳过: {document.name}")
                continue

            # 添加 filters 到元数据
            if filters:
                meta_data = document.meta_data.copy() if document.meta_data else {}
                meta_data.update(filters)
                document.meta_data = meta_data

            # 嵌入文档（异步）
            try:
                logger.debug(f"正在异步嵌入文档 {idx+1}/{len(documents)}: {document.name}")
                await document.async_embed(embedder=self.embedder)
                processed_count += 1

                # 报告进度
                if self.progress_callback:
                    self.progress_callback(
                        ImportStage.EMBEDDING,
                        idx + 1,
                        len(documents),
                        f"已处理: {document.name}",
                        metadata={"doc_name": document.name}
                    )

            except Exception as e:
                logger.error(f"嵌入文档失败 {document.name}: {e}")
                continue

        # 调用父类的 insert 方法保存
        # 注意：文档已经 embed 过了，所以直接调用父类的 insert
        try:
            logger.debug(f"调用父类 insert() 保存 {len(documents)} 个文档")
            super().insert(content_hash, documents, filters)

            # 报告完成
            if self.progress_callback:
                logger.info(f"完成！成功保存 {processed_count} 个文档")
                self.progress_callback(
                    ImportStage.SAVING,
                    len(documents),
                    len(documents),
                    f"完成！成功保存 {processed_count} 个文档"
                )

        except Exception as e:
            logger.error(f"保存文档失败: {e}")
            raise


# ==============================================================================
# 3. 增强的 Knowledge
# ==============================================================================

class KnowledgeWithProgress(Knowledge):
    """
    增强的 Knowledge - 添加进度反馈和取消支持

    继承自 agno.knowledge.knowledge.Knowledge
    保持完全的接口兼容性
    """

    def __init__(
        self,
        *args,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
        **kwargs
    ):
        """
        初始化

        参数：
            progress_callback: 进度回调函数
            cancel_token: 取消令牌
        """
        # 先初始化父类
        super().__init__(*args, **kwargs)

        # 替换 vector_db 为增强版本
        try:
            if self.vector_db and isinstance(self.vector_db, LanceDb):
                # 保存原始配置
                vector_db_config = {
                    "uri": self.vector_db.uri,
                    "table_name": self.vector_db.table_name,
                    "embedder": self.vector_db.embedder,
                    "search_type": self.vector_db.search_type,
                    "distance": self.vector_db.distance,
                    "nprobes": self.vector_db.nprobes,
                    "use_tantivy": self.vector_db.use_tantivy,
                }

                # 创建增强版本
                self.vector_db = LanceDbWithProgress(
                    **vector_db_config,
                    progress_callback=progress_callback,
                    cancel_token=cancel_token
                )
        except Exception as e:
            logger.error(f"替换 vector_db 时出错: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")

    async def add_content_async(
        self,
        *args,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
        **kwargs
    ) -> None:
        """
        重写 add_content_async，添加进度追踪

        这个方法会在每次导入时被调用，确保回调和令牌被正确设置到 vector_db
        """
        # 更新 vector_db 的回调和令牌
        if isinstance(self.vector_db, LanceDbWithProgress):
            self.vector_db.progress_callback = progress_callback
            self.vector_db.cancel_token = cancel_token

        # 调用父类方法
        await super().add_content_async(*args, **kwargs)
