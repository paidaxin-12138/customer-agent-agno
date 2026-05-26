"""
美甲灯客服 AI 知识库集成模块 - LanceDB 向量化版本
使用 LanceDB 向量数据库进行高效检索
"""

from typing import List, Optional, Dict, Any
from pathlib import Path
import json
from contextvars import ContextVar
from dataclasses import dataclass

from openai import OpenAI
from config import Config
from utils.runtime_path import get_temp_path
from utils.logger_loguru import get_logger
import lancedb

# 客服进线时由 CustomerAgent 注入，检索只返回「全店通用 + 本店」文档
_CURRENT_PLATFORM_SHOP_ID: ContextVar[Optional[str]] = ContextVar(
    "current_platform_shop_id", default=None
)


def get_current_platform_shop_id() -> Optional[str]:
    return _CURRENT_PLATFORM_SHOP_ID.get()


def set_platform_shop_context(shop_id: Optional[str]) -> Any:
    """设置当前线程/协程的店铺 ID，返回用于 reset 的 token。"""
    return _CURRENT_PLATFORM_SHOP_ID.set(shop_id)


def reset_platform_shop_context(token: Any) -> None:
    _CURRENT_PLATFORM_SHOP_ID.reset(token)


@dataclass
class DocumentLike:
    """兼容 UI 的轻量文档对象。"""
    id: str
    data: str
    metadata: Dict[str, Any]


class LanceDBKnowledgeManager:
    """美甲灯知识库管理器 - LanceDB 向量化版本"""

    def __init__(self):
        self.logger = get_logger("LanceDBKnowledgeManager")
        self._config = Config()
        self._embedder_client = self._init_embedder_client()
        self._embedder_model = (self._config.get("embedder.model_name", "") or "").strip()
        
        # LanceDB 向量数据库
        self._lancedb_path = get_temp_path() / "lancedb"
        self._lancedb_path.mkdir(parents=True, exist_ok=True)
        self._db = None
        self._knowledge_table = None
        
        # 向后兼容
        self.documents = []
        self._store_file = get_temp_path() / "knowledge_docs.json"
        
        # 初始化（先加载 JSON，再建表以便推断向量维度）
        self._load_documents()
        self._init_lancedb()
        self._sync_to_lancedb()

    def _detect_vector_dimension(self) -> int:
        for doc in self.documents:
            emb = doc.get("embedding")
            if isinstance(emb, list) and emb:
                return len(emb)
        probe = self._embed_text(".")
        if probe:
            return len(probe)
        return 1024

    @staticmethod
    def _lancedb_seed_row(dim: int) -> Dict[str, Any]:
        return {
            "id": "__lancedb_init__",
            "content": "",
            "vector": [0.0] * dim,
            "platform_shop_id": "",
            "inherit_key": "",
            "allow_child_override": False,
            "title": "",
            "filename": "",
            "source": "",
        }

    def _init_lancedb(self):
        """初始化 LanceDB 向量数据库"""
        try:
            self._db = lancedb.connect(str(self._lancedb_path))

            if "knowledge" in self._db.table_names():
                self._knowledge_table = self._db.open_table("knowledge")
                self.logger.info("✅ LanceDB 知识库表已打开")
                return

            dim = self._detect_vector_dimension()
            self._knowledge_table = self._db.create_table(
                "knowledge", [self._lancedb_seed_row(dim)]
            )
            try:
                self._knowledge_table.delete("id = '__lancedb_init__'")
            except Exception:
                pass
            self.logger.info(f"✅ LanceDB 知识库表已创建 (vector_dim={dim})")
        except Exception as e:
            self.logger.error(f"❌ LanceDB 初始化失败：{e}")
            self._db = None
            self._knowledge_table = None
    
    def _init_embedder_client(self) -> Optional[OpenAI]:
        """初始化 embedding 客户端"""
        api_key = (self._config.get("embedder.api_key", "") or "").strip()
        api_base = (self._config.get("embedder.api_base", "") or "").strip()
        if not api_key or not api_base:
            return None
        try:
            return OpenAI(api_key=api_key, base_url=api_base)
        except Exception:
            return None
    
    def _embed_text(self, text: str) -> Optional[List[float]]:
        """生成文本向量"""
        if not self._embedder_client or not self._embedder_model or not text.strip():
            return None
        try:
            sample = text[:8191]  # 限制长度
            resp = self._embedder_client.embeddings.create(
                model=self._embedder_model,
                input=sample
            )
            return list(resp.data[0].embedding)
        except Exception as e:
            self.logger.error(f"Embedding 失败：{e}")
            return None
    
    def _load_documents(self) -> None:
        """从本地 JSON 恢复文档数据"""
        try:
            if not self._store_file.exists():
                return
            raw = self._store_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                self.documents = data
                self.logger.info(f"📚 从 JSON 加载 {len(data)} 条文档")
        except Exception as e:
            self.logger.error(f"加载文档失败：{e}")
            self.documents = []
    
    def _save_documents(self) -> None:
        """保存文档到本地 JSON"""
        try:
            self._store_file.parent.mkdir(parents=True, exist_ok=True)
            self._store_file.write_text(
                json.dumps(self.documents, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            self.logger.error(f"保存文档失败：{e}")
    
    def _sync_to_lancedb(self) -> int:
        """同步所有文档到 LanceDB"""
        if not self._knowledge_table or not self.documents:
            return 0
        
        try:
            # 清空表
            self._knowledge_table.delete("1=1")
            
            # 批量添加
            batch = []
            for doc in self.documents:
                content = str(doc.get("content", ""))
                if not content.strip():
                    continue
                
                # 生成向量
                vector = self._embed_text(content[:2000])
                if not vector:
                    continue
                
                data = {
                    "id": str(doc.get("id", "")),
                    "content": content,
                    "vector": vector,
                    "platform_shop_id": str(doc.get("platform_shop_id", "") or ""),
                    "inherit_key": str(doc.get("inherit_key", "") or ""),
                    "allow_child_override": bool(doc.get("allow_child_override", False)),
                    "title": str(doc.get("title", "") or ""),
                    "filename": str(doc.get("filename", "") or ""),
                    "source": str(doc.get("source", "") or ""),
                }
                batch.append(data)
            
            if batch:
                self._knowledge_table.add(batch)
                self.logger.info(f"✅ LanceDB 同步完成：{len(batch)} 条文档")
                return len(batch)
            else:
                self.logger.warning("⚠️ 没有文档需要同步")
                return 0
                
        except Exception as e:
            self.logger.error(f"LanceDB 同步失败：{e}")
            return 0
    
    def add_document(self, doc: Dict) -> None:
        """添加文档"""
        self.documents.append(doc)
        self._save_documents()
        
        # 同步到 LanceDB
        content = str(doc.get("content", ""))
        if content.strip() and self._knowledge_table:
            vector = self._embed_text(content[:2000])
            if vector:
                data = {
                    "id": str(doc.get("id", "")),
                    "content": content,
                    "vector": vector,
                    "platform_shop_id": str(doc.get("platform_shop_id", "") or ""),
                    "inherit_key": str(doc.get("inherit_key", "") or ""),
                    "allow_child_override": bool(doc.get("allow_child_override", False)),
                    "title": str(doc.get("title", "") or ""),
                    "filename": str(doc.get("filename", "") or ""),
                    "source": str(doc.get("source", "") or ""),
                }
                try:
                    self._knowledge_table.add([data])
                    self.logger.info(f"✅ 添加文档到 LanceDB: {doc.get('id', 'unknown')}")
                except Exception as e:
                    self.logger.error(f"LanceDB 添加失败：{e}")
    
    def remove_document(self, doc_id: str) -> None:
        """删除文档"""
        self.documents = [d for d in self.documents if d.get('id') != doc_id]
        self._save_documents()
        
        # 从 LanceDB 删除
        if self._knowledge_table:
            try:
                self._knowledge_table.delete(f"id = '{doc_id}'")
                self.logger.info(f"✅ 从 LanceDB 删除文档：{doc_id}")
            except Exception as e:
                self.logger.error(f"LanceDB 删除失败：{e}")
    
    def delete_document(self, doc_id: str) -> bool:
        """
        删除文档（兼容旧 UI 接口）
        
        Args:
            doc_id: 文档 ID
            
        Returns:
            bool: 是否删除成功
        """
        try:
            self.remove_document(doc_id)
            return True
        except Exception as e:
            self.logger.error(f"删除文档失败：{e}")
            return False
    
    @staticmethod
    def _doc_visible_for_shop(doc: Dict[str, Any], shop_id: Optional[str]) -> bool:
        """检查文档对店铺是否可见"""
        raw = doc.get("platform_shop_id")
        if raw is None or str(raw).strip() == "":
            return True  # 通用文档
        if shop_id is None or str(shop_id).strip() == "":
            return False
        return str(raw).strip() == str(shop_id).strip()
    
    def search_knowledge(self, query: str, top_k: int = 5, **kwargs) -> List[DocumentLike]:
        """向量检索知识库"""
        limit = kwargs.get("limit", top_k or 5)
        limit = max(1, int(limit))
        explicit_shop = kwargs.get("platform_shop_id")
        eff_shop = explicit_shop if explicit_shop is not None else get_current_platform_shop_id()
        
        # 空查询
        if not query or not query.strip():
            return []
        
        # 使用 LanceDB 向量检索
        if self._knowledge_table and self._embedder_client and self._embedder_model:
            try:
                # 生成查询向量
                query_vec = self._embed_text(query.strip()[:2000])
                
                if query_vec:
                    # 向量检索
                    results = self._knowledge_table.search(query_vec).limit(limit * 3).to_pandas()
                    
                    if not results.empty:
                        # 过滤店铺可见性
                        filtered = []
                        for _, row in results.iterrows():
                            doc = {
                                "id": row["id"],
                                "content": row["content"],
                                "platform_shop_id": row.get("platform_shop_id", ""),
                                "inherit_key": row.get("inherit_key", ""),
                                "allow_child_override": row.get("allow_child_override", False),
                                "title": row.get("title", ""),
                                "filename": row.get("filename", ""),
                                "source": row.get("source", ""),
                            }
                            if self._doc_visible_for_shop(doc, eff_shop):
                                filtered.append(doc)
                        
                        self.logger.debug(f"🔍 LanceDB 检索：'{query[:30]}...' -> {len(filtered)} 条")
                        
                        return [
                            DocumentLike(
                                id=str(d.get("id", "")),
                                data=str(d.get("content", "")),
                                metadata={
                                    "title": d.get("title", ""),
                                    "filename": d.get("filename", ""),
                                    "source": d.get("source", ""),
                                    "platform_shop_id": d.get("platform_shop_id") or "",
                                    "inherit_key": d.get("inherit_key") or "",
                                    "allow_child_override": bool(d.get("allow_child_override", False)),
                                },
                            )
                            for d in filtered[:limit]
                        ]
                        
            except Exception as e:
                self.logger.warning(f"LanceDB 检索失败，返回空结果：{e}")
        
        return []
    
    def get_all_documents(self) -> List[Dict]:
        """获取所有文档"""
        return self.documents
    
    def get_content_count(self) -> int:
        """获取文档数量"""
        return len(self.documents)
    
    def get_document_by_id(self, doc_id: str) -> Optional[Dict]:
        """
        根据 ID 获取文档
        
        Args:
            doc_id: 文档 ID
            
        Returns:
            文档字典，如果不存在则返回 None
        """
        for doc in self.documents:
            if doc.get('id') == doc_id:
                return doc
        return None
    
    def update_document(self, doc_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新文档
        
        Args:
            doc_id: 文档 ID
            updates: 要更新的字段
            
        Returns:
            bool: 是否更新成功
        """
        try:
            # 在 documents 中查找并更新
            for i, doc in enumerate(self.documents):
                if doc.get('id') == doc_id:
                    self.documents[i].update(updates)
                    self._save_documents()
                    
                    # 同步更新到 LanceDB
                    content = str(doc.get('content', ''))
                    if content and self._knowledge_table:
                        vector = self._embed_text(content[:2000])
                        if vector:
                            # 先删除旧的
                            self._knowledge_table.delete(f"id = '{doc_id}'")
                            # 添加新的
                            data = {
                                "id": doc_id,
                                "content": content,
                                "vector": vector,
                                "platform_shop_id": str(doc.get("platform_shop_id", "") or ""),
                                "inherit_key": str(doc.get("inherit_key", "") or ""),
                                "allow_child_override": bool(doc.get("allow_child_override", False)),
                                "title": str(doc.get("title", "") or ""),
                                "filename": str(doc.get("filename", "") or ""),
                                "source": str(doc.get("source", "") or ""),
                            }
                            self._knowledge_table.add([data])
                    
                    self.logger.info(f"✅ 更新文档：{doc_id}")
                    return True
            
            self.logger.warning(f"❌ 文档不存在：{doc_id}")
            return False
            
        except Exception as e:
            self.logger.error(f"更新文档失败：{e}")
            return False
