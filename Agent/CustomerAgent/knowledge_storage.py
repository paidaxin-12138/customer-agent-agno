# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""LanceDB 与 JSON 文档持久化。"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import lancedb
from openai import OpenAI

from config import Config, get_config
from utils.runtime_path import get_temp_path
from utils.logger_loguru import get_logger

_CURRENT_PLATFORM_SHOP_ID: ContextVar[Optional[str]] = ContextVar(
    "current_platform_shop_id", default=None
)

_LANCEDB_INIT_ID = "__lancedb_init__"


def lancedb_escape_id(doc_id: str) -> str:
    """转义 LanceDB 过滤表达式中的文档 ID（防注入/引号破坏）。"""
    return str(doc_id or "").replace("'", "''")


def lancedb_delete_filter(doc_id: str) -> str:
    """生成 LanceDB delete 过滤条件。"""
    return f"id = '{lancedb_escape_id(doc_id)}'"


def get_current_platform_shop_id() -> Optional[str]:
    return _CURRENT_PLATFORM_SHOP_ID.get()


def set_platform_shop_context(shop_id: Optional[str]) -> Any:
    """设置当前线程/协程的店铺 ID，返回用于 reset 的 token。"""
    return _CURRENT_PLATFORM_SHOP_ID.set(shop_id)


def reset_platform_shop_context(token: Any) -> None:
    _CURRENT_PLATFORM_SHOP_ID.reset(token)


def _tabular_sheet_payload(df: Any, name: str, max_rows: int = 1000) -> Dict[str, Any]:
    """将 pandas DataFrame 转为可 JSON 序列化的表格（供 UI 按表格展示）。"""
    columns = [str(c) for c in df.columns]
    truncated = len(df) > max_rows
    sub = df.head(max_rows)
    rows = sub.fillna("").astype(str).values.tolist()
    return {
        "name": name,
        "columns": columns,
        "rows": rows,
        "truncated": truncated,
        "total_rows": int(len(df)),
    }


def _excel_display_payload_json(path: Path) -> Optional[str]:
    try:
        import pandas as pd
    except ImportError:
        return None
    try:
        excel_file = pd.ExcelFile(str(path))
        sheets = []
        for sheet_name in excel_file.sheet_names:
            df = pd.read_excel(excel_file, sheet_name=sheet_name)
            sheets.append(_tabular_sheet_payload(df, str(sheet_name)))
        return json.dumps({"type": "excel", "sheets": sheets}, ensure_ascii=False)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        get_logger("KnowledgeManager").debug("Excel 展示载荷解析失败: {}", exc)
        return None


def _csv_display_payload_json(content: str, label: str) -> Optional[str]:
    try:
        import io
        import pandas as pd

        df = pd.read_csv(io.StringIO(content))
        sheet = _tabular_sheet_payload(df, label)
        return json.dumps({"type": "csv", "sheets": [sheet]}, ensure_ascii=False)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        get_logger("KnowledgeManager").debug("CSV 展示载荷解析失败: {}", exc)
        return None


@dataclass
class DocumentLike:
    """兼容 UI 的轻量文档对象。"""

    id: str
    data: str
    metadata: Dict[str, Any]


class KnowledgeStorageMixin:
    """LanceDB 连接、JSON 落盘与向量表同步。"""

    # UI 线程与商品同步线程共用，避免 LanceDB/JSON 并发写导致卡死
    _global_io_lock = threading.RLock()

    def _detect_vector_dimension(self) -> int:
        """推断向量维度（已有 embedding > 探针请求 > 配置/默认 1024）。"""
        for doc in self.documents:
            emb = doc.get("embedding")
            if isinstance(emb, list) and emb:
                return len(emb)
            for chunk in doc.get("chunks") or []:
                if not isinstance(chunk, dict):
                    continue
                ce = chunk.get("embedding")
                if isinstance(ce, list) and ce:
                    return len(ce)
        probe = self._embed_text(".")
        if probe:
            return len(probe)
        cfg_dim = self._config.get("embedder.dimensions")
        if cfg_dim is not None:
            try:
                return max(1, int(cfg_dim))
            except (TypeError, ValueError):
                pass
        return 1024

    @staticmethod
    def _lancedb_seed_row(dim: int) -> Dict[str, Any]:
        """创建空表时用的占位行（创建后立即删除）。"""
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

    def _init_lancedb(self) -> None:
        """初始化 LanceDB 向量数据库（损坏或缺失表时自动重建）。"""
        with self._global_io_lock:
            try:
                self._db = lancedb.connect(str(self._lancedb_path))
                table_names = list(self._db.table_names())
                if "knowledge" in table_names:
                    try:
                        self._knowledge_table = self._db.open_table("knowledge")
                        self.logger.info("LanceDB 知识库表打开成功")
                        return
                    except (OSError, RuntimeError, ValueError) as open_err:
                        self.logger.warning(
                            f"LanceDB knowledge 表打开失败，将重建：{open_err}"
                        )
                        try:
                            self._db.drop_table("knowledge")
                        except (OSError, RuntimeError, ValueError) as drop_err:
                            self.logger.debug(f"drop_table 跳过：{drop_err}")

                dim = self._detect_vector_dimension()
                self._knowledge_table = self._db.create_table(
                    "knowledge", [self._lancedb_seed_row(dim)]
                )
                try:
                    self._knowledge_table.delete("id = '__lancedb_init__'")
                except (OSError, RuntimeError, ValueError) as del_err:
                    self.logger.debug(f"删除 LanceDB 占位行失败（可忽略）：{del_err}")

                self.logger.info(f"LanceDB 知识库表创建成功 (vector_dim={dim})")
                if self.documents:
                    synced = self._sync_all_docs_to_lancedb()
                    self.logger.info(f"LanceDB 已同步历史文档：{synced} 条")
            except (OSError, RuntimeError, ValueError) as exc:
                self.logger.error(f"LanceDB 初始化失败：{exc}")
                self._db = None
                self._knowledge_table = None

    @staticmethod
    def _doc_visible_for_shop(doc: Dict[str, Any], shop_id: Optional[str]) -> bool:
        """
        未设置 platform_shop_id（或空）→ 父知识库（全店通用）；设置了则仅匹配该拼多多店铺 ID（子知识库）。
        shop_id 为空且需要过滤时：非通用文档不可见（避免串店）。
        """
        raw = doc.get("platform_shop_id")
        if raw is None or str(raw).strip() == "":
            return True
        if shop_id is None or str(shop_id).strip() == "":
            return False
        return str(raw).strip() == str(shop_id).strip()

    @staticmethod
    def _inherit_key(doc: Dict[str, Any]) -> str:
        """同一业务键下，子库可覆盖父库；未设置则每条文档独立（不参与覆盖合并）。"""
        ik = (doc.get("inherit_key") or "").strip()
        return ik

    @staticmethod
    def _parent_allows_child_override(doc: Dict[str, Any]) -> bool:
        """父库条目是否显式允许被子店同 inherit_key 覆盖（默认否，兼容旧数据）。"""
        v = doc.get("allow_child_override")
        if v is True:
            return True
        if v is False or v is None:
            return False
        s = str(v).strip().lower()
        return s in ("1", "true", "yes", "on")

    def _shop_override_inherit_keys(
        self, pool: List[Dict[str, Any]], shop_id: Optional[str]
    ) -> set:
        """当前店铺下、带 inherit_key 的子库文档所声明的键（仅用于与「允许被覆盖」的父条配对）。"""
        if not shop_id or not str(shop_id).strip():
            return set()
        sid = str(shop_id).strip()
        keys: set = set()
        for d in pool:
            ps = (d.get("platform_shop_id") or "").strip()
            if ps != sid:
                continue
            ik = self._inherit_key(d)
            if ik:
                keys.add(ik)
        return keys

    def _start_store_init_async(self) -> None:
        """后台加载 JSON + LanceDB 索引，不阻塞主线程。"""
        with self._store_init_lock:
            if self._store_initialized or self._store_init_started:
                return
            self._store_init_started = True

        def _work() -> None:
            try:
                self._load_documents()
                self._init_lancedb()
                self._sync_all_docs_to_lancedb()
            except Exception as exc:
                self.logger.error(f"知识库索引后台加载失败：{exc}")
            finally:
                self._store_initialized = True
                self._store_init_event.set()

        threading.Thread(target=_work, daemon=True, name="kb-index-init").start()

    def _ensure_store_initialized(
        self, *, wait: bool = True, timeout: float = 60.0
    ) -> bool:
        """首次检索前确保索引就绪；wait=False 时不阻塞调用方。"""
        if self._store_initialized:
            return True
        self._start_store_init_async()
        if not wait:
            return False
        return self._store_init_event.wait(timeout)

    def _load_documents(self) -> None:
        """从本地 JSON 恢复文档数据。"""
        try:
            self._store_file.parent.mkdir(parents=True, exist_ok=True)
            if not self._store_file.exists():
                return
            raw = self._store_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                self.documents = data
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            # 持久化恢复失败不应阻断应用启动
            self.logger.warning("知识库 JSON 恢复失败，使用内存列表: {}", exc)
            self.documents = self.documents or []

    def reload_documents_from_disk(self) -> int:
        """子进程写入 JSON 后，主进程重新加载内存文档供 UI 增量展示。"""
        with self._global_io_lock:
            before = len(self.documents)
            self._load_documents()
            return len(self.documents) - before

    @staticmethod
    def _ensure_doc_created_at(doc: Dict[str, Any]) -> None:
        """为文档打上 created_at，供生命周期向量清理使用。"""
        if not isinstance(doc, dict):
            return
        if doc.get("created_at"):
            return
        meta = doc.get("metadata")
        if isinstance(meta, dict) and meta.get("created_at"):
            doc["created_at"] = meta["created_at"]
            return
        doc["created_at"] = datetime.now().isoformat(timespec="seconds")

    def _save_documents(self) -> None:
        """将文档数据持久化到本地 JSON（原子 replace）。"""
        with self._global_io_lock:
            tmp_path = None
            try:
                for d in self.documents:
                    self._ensure_doc_created_at(d)
                self._store_file.parent.mkdir(parents=True, exist_ok=True)
                payload = json.dumps(self.documents, ensure_ascii=False, indent=2)
                tmp_path = self._store_file.with_suffix(
                    self._store_file.suffix + ".tmp"
                )
                tmp_path.write_text(payload, encoding="utf-8")
                import os

                os.replace(tmp_path, self._store_file)
            except OSError as exc:
                if tmp_path is not None:
                    with suppress(OSError):
                        tmp_path.unlink(missing_ok=True)
                self.logger.warning("知识库 JSON 保存失败: {}", exc)

    def _init_embedder_client(self) -> Optional[OpenAI]:
        """初始化 embedding 客户端（可选）。"""
        api_key = (get_config("embedder.api_key", "") or "").strip()
        api_base = (get_config("embedder.api_base", "") or "").strip()
        if not api_key or not api_base:
            return None
        try:
            return OpenAI(api_key=api_key, base_url=api_base)
        except (TypeError, ValueError) as exc:
            self.logger.debug("embedding 客户端初始化失败: {}", exc)
            return None

    def _embed_text(self, text: str) -> Optional[List[float]]:
        """生成文本向量，失败时返回 None。"""
        if not self._embedder_client or not self._embedder_model or not text.strip():
            return None
        try:
            # 限制长度避免超限
            sample = text[:4000]
            resp = self._embedder_client.embeddings.create(
                model=self._embedder_model, input=sample
            )
            return list(resp.data[0].embedding)
        except (OSError, KeyError, TypeError, ValueError, IndexError) as exc:
            self.logger.debug("embedding 请求失败: {}", exc)
            return None

    @staticmethod
    def _embedding_text_for_doc(doc: Dict[str, Any]) -> str:
        """建索引用正文（标题 + 内容），不经过查询同义词扩展。"""
        content = str(doc.get("content", "")).strip()
        if not content:
            return ""
        title = str(doc.get("title") or "").strip()
        filename = str(doc.get("filename") or "").strip()
        header = " ".join(x for x in (title, filename) if x)
        body = f"{header}\n{content}" if header else content
        return body[:4000]

    def _lancedb_delete_by_id(self, doc_id: str) -> None:
        if not self._knowledge_table or not doc_id:
            return
        try:
            self._knowledge_table.delete(lancedb_delete_filter(doc_id))
        except Exception as exc:
            self.logger.debug("LanceDB 删除文档跳过 id={}: {}", doc_id, exc)

    def _add_doc_to_lancedb(self, doc: Dict) -> bool:
        """将文档添加到 LanceDB"""
        if not self._knowledge_table:
            return False

        try:
            content = str(doc.get("content", ""))
            if not content.strip():
                return False

            embed_text = self._embedding_text_for_doc(doc)
            vector = self._embed_text(embed_text) if embed_text else None

            if not vector:
                self.logger.warning(f"文档 {doc.get('id', 'unknown')} 无法生成向量")
                return False

            # 准备数据
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

            # 添加到 LanceDB
            self._knowledge_table.add([data])
            self.logger.debug(
                f"LanceDB 添加文档：id={data['id']}, content_len={len(content)}"
            )
            return True

        except Exception as e:
            self.logger.error(f"LanceDB 添加文档失败：{e}")
            return False

    def _doc_sync_signature(self) -> str:
        parts = []
        for doc in self.documents:
            doc_id = str(doc.get("id", "") or "")
            content = str(doc.get("content", "") or "")[:500]
            shop = str(doc.get("platform_shop_id", "") or "")
            parts.append(f"{doc_id}:{shop}:{hash(content)}")
        raw = "|".join(sorted(parts))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _existing_lancedb_ids(self) -> set[str]:
        ids: set[str] = set()
        if not self._knowledge_table:
            return ids
        try:
            df = self._knowledge_table.to_pandas()
            if df is not None and not df.empty and "id" in df.columns:
                ids = {str(x) for x in df["id"].tolist() if str(x) != _LANCEDB_INIT_ID}
        except Exception:
            pass
        return ids

    def _sync_all_docs_to_lancedb(self, *, force: bool = False) -> int:
        """增量同步 JSON 文档到 LanceDB（签名未变则跳过）。"""
        if not self._knowledge_table:
            return 0
        if not self.documents:
            for doc_id in self._existing_lancedb_ids():
                self._lancedb_delete_by_id(doc_id)
            self._last_sync_signature = self._doc_sync_signature()
            return 0

        signature = self._doc_sync_signature()
        if not force and signature == self._last_sync_signature:
            return 0

        try:
            json_ids = {
                str(doc.get("id", "") or "").strip()
                for doc in self.documents
                if str(doc.get("id", "") or "").strip()
            }
            existing_ids = self._existing_lancedb_ids()
            for stale_id in existing_ids - json_ids:
                self._lancedb_delete_by_id(stale_id)

            count = 0
            for doc in self.documents:
                doc_id = str(doc.get("id", "") or "").strip()
                if doc_id:
                    self._lancedb_delete_by_id(doc_id)
                if self._add_doc_to_lancedb(doc):
                    count += 1
            self._last_sync_signature = signature
            if count:
                self.logger.info(f"LanceDB 增量同步：{count} 条文档")
            return count
        except Exception as e:
            self.logger.error(f"LanceDB 同步失败：{e}")
            return 0

    def get_content_count(self) -> int:
        """向后兼容 - 旧 UI 代码使用 - 返回内容数量"""
        return len(self.documents)

    def get_knowledge_count(self) -> int:
        """向后兼容 - 旧 UI 代码使用 - 返回知识数量"""
        return len(self.documents)

    def get_all_documents(self) -> List[Dict]:
        """向后兼容 - 旧 UI 代码使用 - 返回所有文档"""
        self._ensure_store_initialized(wait=True)
        return self.documents

    def get_all_contents(self) -> List[Dict]:
        """向后兼容 - 旧 UI 代码使用 - 返回所有内容"""
        return self.documents
