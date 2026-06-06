"""
电商客服 AI 知识库门面。
实现已拆分至 knowledge_storage / knowledge_indexer / knowledge_retriever。
"""

from typing import Any, Dict, List, Optional
import threading

from utils.logger_loguru import get_logger
from config import Config, get_config
from utils.runtime_path import get_temp_path

from Agent.CustomerAgent.knowledge_storage import (
    DocumentLike,
    KnowledgeStorageMixin,
    get_current_platform_shop_id,
    reset_platform_shop_context,
    set_platform_shop_context,
)
from Agent.CustomerAgent.knowledge_fallback import load_knowledge_fallback
from Agent.CustomerAgent.knowledge_indexer import KnowledgeIndexerMixin
from Agent.CustomerAgent.knowledge_retriever import KnowledgeRetrieverMixin

__all__ = [
    "DocumentLike",
    "KnowledgeManager",
    "LanceDBKnowledgeManager",
    "NailLampKnowledgeManager",
    "get_current_platform_shop_id",
    "get_knowledge_manager",
    "get_knowledge_response",
    "get_nail_lamp_response",
    "knowledge_manager",
    "reset_platform_shop_context",
    "set_platform_shop_context",
]


class KnowledgeManager(
    KnowledgeRetrieverMixin, KnowledgeIndexerMixin, KnowledgeStorageMixin
):
    """店铺知识库管理器（向量检索 + 本地 JSON/LanceDB）。"""

    def __init__(self):
        self.knowledge = {}
        self.documents = []
        self.logger = get_logger("KnowledgeManager")
        self._config = Config()
        self._embedder_client = self._init_embedder_client()
        self._embedder_model = (get_config("embedder.model_name", "") or "").strip()
        self._store_file = get_temp_path() / "knowledge_docs.json"

        self._lancedb_path = get_temp_path() / "lancedb"
        self._lancedb_path.mkdir(parents=True, exist_ok=True)
        self._db = None
        self._knowledge_table = None
        self._last_sync_signature: Optional[str] = None
        self._embeddings_ready = False
        self.products, self.faq_templates, self.synonyms = load_knowledge_fallback(
            self._config
        )

        self._store_initialized = False
        self._store_init_started = False
        self._store_init_event = threading.Event()
        self._store_init_lock = threading.Lock()


# 历史类名兼容（旧代码 / 脚本仍可能引用）
NailLampKnowledgeManager = KnowledgeManager
LanceDBKnowledgeManager = KnowledgeManager

_manager_instance: Optional[KnowledgeManager] = None
_manager_lock = threading.Lock()


def get_knowledge_manager() -> KnowledgeManager:
    """延迟初始化知识库，避免 import 时阻塞 LanceDB/embedding。"""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = KnowledgeManager()
                _manager_instance._start_store_init_async()
    return _manager_instance


class _LazyKnowledgeManagerProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_knowledge_manager(), name)

    def __repr__(self) -> str:
        return (
            f"<LazyKnowledgeManagerProxy initialized={_manager_instance is not None}>"
        )


knowledge_manager = _LazyKnowledgeManagerProxy()


def get_knowledge_response(user_message: str, context: Optional[Dict] = None) -> str:
    """根据用户消息与可选上下文生成知识库回复。"""
    return knowledge_manager.answer_question(user_message)


get_nail_lamp_response = get_knowledge_response
