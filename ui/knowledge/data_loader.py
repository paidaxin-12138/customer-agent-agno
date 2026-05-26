"""
知识库数据加载器
负责从 LanceDB 和 Agno API 加载文档数据
"""
from __future__ import annotations
from typing import TYPE_CHECKING, List, Optional
import logging

from .models import SimpleDocument

if TYPE_CHECKING:
    from Agent.CustomerAgent.agent_knowledge import KnowledgeManager

logger = logging.getLogger(__name__)


class KnowledgeDataLoader:
    """知识库数据加载器 - 单一职责：数据加载"""

    def __init__(self, knowledge_manager: KnowledgeManager):
        """
        初始化数据加载器

        Args:
            knowledge_manager: 知识库管理器实例
        """
        self.knowledge_manager = knowledge_manager

    def load_documents(
        self,
        limit: Optional[int] = None,
        platform_shop_id: Optional[str] = None,
    ) -> List[SimpleDocument]:
        """
        加载文档列表

        Args:
            limit: 最大文档数量限制

        Returns:
            文档列表
        """
        try:
            docs: List[SimpleDocument] = []

            # 优先从本地知识库 JSON（完整元数据：import_format、display_payload 等）
            list_for_ui = getattr(self.knowledge_manager, "list_documents_for_ui", None)
            if callable(list_for_ui) and (platform_shop_id or "").strip():
                try:
                    raw_list = list_for_ui((platform_shop_id or "").strip())
                except Exception as e:
                    logger.warning(f"list_documents_for_ui 加载失败: {e}")
                    raw_list = []
            else:
                raw_list = None

            getter = getattr(self.knowledge_manager, "get_all_documents", None)
            if raw_list is None and callable(getter):
                try:
                    raw_list = getter()
                    if isinstance(raw_list, list) and raw_list:
                        docs = [
                            SimpleDocument.from_kb_dict(d, i)
                            for i, d in enumerate(raw_list)
                        ]
                        logger.info(f"从 get_all_documents 加载了 {len(docs)} 个文档")
                except Exception as e:
                    logger.warning(f"get_all_documents 加载失败: {e}")

            if not docs:
                try:
                    docs = self._load_from_lancedb()
                    logger.info(f"从 LanceDB 加载了 {len(docs)} 个文档")
                except Exception as lancedb_err:
                    logger.warning(f"LanceDB 直接获取失败: {lancedb_err}")
                    docs = self._load_from_search_api(limit)
                    logger.info(f"从搜索 API 加载了 {len(docs)} 个文档")

            if limit and len(docs) > limit:
                docs = docs[:limit]

            return docs

        except Exception as e:
            logger.error(f"加载文档失败: {e}")
            return []

    def _load_from_lancedb(self) -> List[SimpleDocument]:
        """
        直接从 LanceDB 加载数据

        Returns:
            文档列表
        """
        import lancedb

        db_path = self.knowledge_manager.knowledge.vector_db.uri
        db = lancedb.connect(db_path)
        table = db.open_table("customer_knowledge")

        df = table.to_pandas()

        docs = []
        for idx, row in df.iterrows():
            doc = SimpleDocument.from_lancedb_row(row.to_dict(), idx)
            docs.append(doc)

        return docs

    def _load_from_search_api(self, limit: Optional[int] = None) -> List[SimpleDocument]:
        """
        通过搜索 API 加载数据

        Args:
            limit: 结果数量限制

        Returns:
            文档列表
        """
        search_limit = limit or 1000
        results = self.knowledge_manager.search_knowledge(
            "", limit=search_limit, ignore_shop_filter=True
        )
        return [SimpleDocument.from_agno_doc(doc) for doc in results]
