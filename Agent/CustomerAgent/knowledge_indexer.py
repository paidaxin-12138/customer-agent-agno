# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""分块、向量化与文档索引写入。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from Agent.CustomerAgent.knowledge_storage import (
    _csv_display_payload_json,
    _excel_display_payload_json,
)


class KnowledgeIndexerMixin:
    _CHUNK_LONG_DOC_THRESHOLD = 520
    _CHUNK_TARGET = 480
    _CHUNK_OVERLAP = 96
    _CHUNK_MIN_MERGE = 72

    def ensure_embeddings_ready(self) -> int:
        """
        启动时补齐缺失 embedding。
        返回本次补齐数量。
        """
        if not self.documents:
            return 0
        if not self._embedder_client or not self._embedder_model:
            self.logger.warning("embedding 配置不完整，跳过启动向量补齐")
            return 0

        updated = 0
        for d in self.documents:
            if self._ensure_doc_chunks_and_embeddings(d):
                updated += 1

        if updated > 0:
            self._save_documents()
            self.logger.info(f"启动补齐 embedding 完成: {updated} 条")
        return updated

    def _split_content_chunks(self, text: str) -> List[str]:
        """按段落与长度切分，适合中文长文检索。"""
        text = (text or "").strip()
        if not text:
            return []
        if len(text) <= self._CHUNK_TARGET:
            return [text]

        paras = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
        if not paras:
            return [text[: self._CHUNK_TARGET]]

        chunks: List[str] = []
        buf = ""
        for p in paras:
            if len(p) > self._CHUNK_TARGET:
                if buf:
                    chunks.append(buf)
                    buf = ""
                start = 0
                while start < len(p):
                    end = min(start + self._CHUNK_TARGET, len(p))
                    chunks.append(p[start:end])
                    if end >= len(p):
                        break
                    start = end - self._CHUNK_OVERLAP
                    if start < 0:
                        start = 0
                continue
            if not buf:
                buf = p
            elif len(buf) + 2 + len(p) <= self._CHUNK_TARGET:
                buf = buf + "\n\n" + p
            else:
                chunks.append(buf)
                buf = p
        if buf:
            chunks.append(buf)

        merged: List[str] = []
        for c in chunks:
            if merged and len(c) < self._CHUNK_MIN_MERGE:
                merged[-1] = merged[-1] + "\n\n" + c
            else:
                merged.append(c)
        return merged if merged else [text[: self._CHUNK_TARGET]]

    def _build_chunk_entries(self, content: str) -> List[Dict[str, Any]]:
        """为长文档生成带向量的分块列表。"""
        parts = self._split_content_chunks(content)
        out: List[Dict[str, Any]] = []
        for part in parts:
            emb = self._embed_text(part)
            out.append({"text": part, "embedding": emb})
        return out

    @staticmethod
    def _header_for_doc(doc: Dict[str, Any]) -> str:
        parts = [str(doc.get("title") or ""), str(doc.get("filename") or "")]
        return " ".join(x.strip() for x in parts if x and str(x).strip()).strip()

    def _document_should_use_chunks(self, content: str) -> bool:
        return len((content or "").strip()) > self._CHUNK_LONG_DOC_THRESHOLD

    def _ensure_doc_chunks_and_embeddings(self, doc: Dict[str, Any]) -> bool:
        """
        长文档补全 chunks；短文档保证顶层 embedding。
        若内容已变更需调用方自行处理；此处仅补齐缺失结构。
        返回是否修改了 doc（需写盘）。
        """
        content = str(doc.get("content", "")).strip()
        if not content:
            return False
        changed = False
        if self._document_should_use_chunks(content):
            raw_chunks = doc.get("chunks")
            need_rebuild = not isinstance(raw_chunks, list) or len(raw_chunks) == 0
            if not need_rebuild:
                for c in raw_chunks:
                    if not isinstance(c, dict) or not str(c.get("text", "")).strip():
                        need_rebuild = True
                        break
            if need_rebuild:
                doc["chunks"] = self._build_chunk_entries(content)
                ce = doc["chunks"][0].get("embedding") if doc["chunks"] else None
                if isinstance(ce, list) and ce:
                    doc["embedding"] = ce
                changed = True
            else:
                for c in doc["chunks"]:
                    if not isinstance(c, dict):
                        continue
                    txt = str(c.get("text", "")).strip()
                    if not txt:
                        continue
                    if not (
                        isinstance(c.get("embedding"), list) and c.get("embedding")
                    ):
                        vec = self._embed_text(txt)
                        if vec:
                            c["embedding"] = vec
                            changed = True
                ch0 = doc["chunks"][0] if doc["chunks"] else None
                e0 = ch0.get("embedding") if isinstance(ch0, dict) else None
                if (
                    isinstance(e0, list)
                    and e0
                    and not (
                        isinstance(doc.get("embedding"), list) and doc.get("embedding")
                    )
                ):
                    doc["embedding"] = e0
                    changed = True
        else:
            if not (isinstance(doc.get("embedding"), list) and doc.get("embedding")):
                vec = self._embed_text(content)
                if vec:
                    doc["embedding"] = vec
                    changed = True
        return changed

    def add_document(self, doc: Dict) -> None:
        """向后兼容 - 旧 UI 代码使用"""
        with self._global_io_lock:
            self.documents.append(doc)
            self._save_documents()
            self._last_sync_signature = None
            doc_id = str(doc.get("id", "") or "").strip()
            if doc_id:
                self._lancedb_delete_by_id(doc_id)
            self._add_doc_to_lancedb(doc)

    def remove_document(self, doc_id: str) -> None:
        """向后兼容 - 旧 UI 代码使用"""
        with self._global_io_lock:
            self.documents = [d for d in self.documents if d.get("id") != doc_id]
            self._save_documents()
            self._last_sync_signature = None
            self._lancedb_delete_by_id(str(doc_id))

    def update_document(self, doc_id: str, updates: Dict[str, Any]) -> bool:
        """更新文档（UI 编辑）；正文变更时清除表格类 display_payload。"""
        doc_id = str(doc_id)
        with self._global_io_lock:
            for i, doc in enumerate(self.documents):
                if str(doc.get("id")) != doc_id:
                    continue
                merged = dict(doc)
                for k, v in (updates or {}).items():
                    if k == "display_payload" and v is None:
                        merged.pop("display_payload", None)
                        continue
                    merged[k] = v
                if "content" in (updates or {}):
                    merged.pop("display_payload", None)
                self.documents[i] = merged
                self._save_documents()
                self._lancedb_delete_by_id(doc_id)
                self._add_doc_to_lancedb(merged)
                self._last_sync_signature = None
                return True
        return False

    async def add_content_from_file(
        self,
        file_path: str,
        platform_shop_id: Optional[str] = None,
        inherit_key: Optional[str] = None,
        allow_child_override: bool = False,
    ) -> int:
        """
        向后兼容 - UI 导入入口（异步）。
        返回新增记录数。
        """
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        suffix = path.suffix.lower()
        content = ""
        title = path.stem

        if suffix in {".txt", ".text", ".md", ".markdown", ".csv"}:
            content = path.read_text(encoding="utf-8", errors="ignore")
        elif suffix == ".json":
            raw = path.read_text(encoding="utf-8", errors="ignore")
            try:
                obj = json.loads(raw)
                content = json.dumps(obj, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                content = raw
        elif suffix in {".xlsx", ".xls"}:
            # Excel 文件解析
            try:
                import pandas as pd

                if suffix == ".xlsx":
                    df = pd.read_excel(str(path), engine="openpyxl")
                else:  # .xls
                    df = pd.read_excel(str(path), engine="xlrd")

                # 将所有列的内容合并
                content_parts = []
                for col in df.columns:
                    col_content = df[col].dropna().astype(str).tolist()
                    if col_content:
                        content_parts.append(f"## {col}\n" + "\n".join(col_content))

                content = "\n\n".join(content_parts).strip()

                if not content:
                    # 尝试读取所有 sheet
                    excel_file = pd.ExcelFile(str(path))
                    all_parts = []
                    for sheet_name in excel_file.sheet_names:
                        df_sheet = pd.read_excel(excel_file, sheet_name=sheet_name)
                        sheet_parts = []
                        for col in df_sheet.columns:
                            col_content = df_sheet[col].dropna().astype(str).tolist()
                            if col_content:
                                sheet_parts.append(
                                    f"### {sheet_name} - {col}\n"
                                    + "\n".join(col_content)
                                )
                        all_parts.extend(sheet_parts)
                    content = "\n\n".join(all_parts).strip()

            except ImportError as ie:
                raise RuntimeError(
                    f"Excel 解析失败：缺少依赖库 - {ie}. 请运行 `uv add openpyxl xlrd`"
                ) from ie
            except Exception as e:
                raise RuntimeError(f"Excel 解析失败：{e}") from e
        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(path))
                parts = []
                for p in reader.pages:
                    t = (p.extract_text() or "").strip()
                    if t:
                        parts.append(t)
                content = "\n\n".join(parts).strip()
            except Exception as e:
                raise RuntimeError(f"PDF 解析失败: {e}") from e
        else:
            # 其它类型先尝试文本方式兜底读取
            content = path.read_text(encoding="utf-8", errors="ignore")

        if not content.strip():
            raise ValueError("导入完成，但文件未提取到可用文本内容")

        import_format_map: Dict[str, str] = {
            ".md": "markdown",
            ".markdown": "markdown",
            ".txt": "text",
            ".text": "text",
            ".csv": "csv",
            ".json": "json",
            ".xlsx": "excel",
            ".xls": "excel",
            ".pdf": "pdf",
        }
        import_format = import_format_map.get(suffix, "text")
        display_payload: Optional[str] = None
        if import_format == "excel":
            display_payload = _excel_display_payload_json(path)
        elif import_format == "csv":
            display_payload = _csv_display_payload_json(content, path.name)

        doc_id = f"doc_{len(self.documents)+1}"
        ps = (platform_shop_id or "").strip() or None
        ik = (inherit_key or "").strip() or None
        allow_ov = bool(allow_child_override) if (not ps and ik) else False
        rec: Dict[str, Any] = {
            "id": doc_id,
            "title": title,
            "filename": path.name,
            "content": content,
            "source": "import_file",
            "import_format": import_format,
            "platform_shop_id": ps,
            "inherit_key": ik,
            "allow_child_override": allow_ov,
        }
        if display_payload:
            rec["display_payload"] = display_payload
        if self._document_should_use_chunks(content):
            rec["chunks"] = self._build_chunk_entries(content)
            rec["embedding"] = (
                rec["chunks"][0].get("embedding")
                if rec["chunks"]
                else self._embed_text(content[:4000])
            )
        else:
            rec["embedding"] = self._embed_text(content)

        self.documents.append(rec)
        self._save_documents()
        self._add_doc_to_lancedb(rec)
        return 1

    async def add_text_content(
        self,
        title: str,
        content: str,
        platform_shop_id: Optional[str] = None,
        inherit_key: Optional[str] = None,
        allow_child_override: bool = False,
    ) -> bool:
        """向后兼容 - 添加文本内容（异步）。"""
        if not title or not content:
            return False
        doc_id = f"doc_{len(self.documents)+1}"
        psid = (platform_shop_id or "").strip() or None
        ik = (inherit_key or "").strip() or None
        allow_ov = bool(allow_child_override) if (not psid and ik) else False
        row: Dict[str, Any] = {
            "id": doc_id,
            "title": title,
            "filename": f"{title}.txt",
            "content": content,
            "source": "manual_input",
            "import_format": "manual",
            "platform_shop_id": psid,
            "inherit_key": ik,
            "allow_child_override": allow_ov,
        }
        if self._document_should_use_chunks(content):
            row["chunks"] = self._build_chunk_entries(content)
            row["embedding"] = (
                row["chunks"][0].get("embedding")
                if row["chunks"]
                else self._embed_text(content[:4000])
            )
        else:
            row["embedding"] = self._embed_text(content)
        self.documents.append(row)
        self._save_documents()
        self._add_doc_to_lancedb(row)
        return True

    def list_documents_for_ui(
        self, platform_shop_id: Optional[str] = None
    ) -> List[Dict]:
        """知识库 UI：仅展示全店通用 + 指定店铺子库，并隐藏已被子库覆盖的父条。"""
        sid = (platform_shop_id or "").strip() or None
        if not sid:
            return list(self.documents)
        visible = [d for d in self.documents if self._doc_visible_for_shop(d, sid)]
        return self._drop_overridden_parents_from_list(visible, sid)

    def delete_goods_sync_documents(self, platform_shop_id: str) -> int:
        """删除某店铺此前 goods_sync 写入的文档（全量同步前清理）。"""
        with self._global_io_lock:
            sid = str(platform_shop_id or "").strip()
            if not sid:
                return 0
            remove_ids: List[str] = []
            kept: List[Dict[str, Any]] = []
            for d in self.documents:
                ps = (d.get("platform_shop_id") or "").strip()
                src = (d.get("source") or "").strip()
                if src == "goods_sync" and ps == sid:
                    remove_ids.append(str(d.get("id")))
                else:
                    kept.append(d)
            if not remove_ids:
                return 0
            self.documents = kept
            for doc_id in remove_ids:
                self._lancedb_delete_by_id(doc_id)
            self._save_documents()
            return len(remove_ids)

    def _build_goods_sync_row(
        self,
        *,
        platform_shop_id: str,
        goods_id: str,
        title: str,
        content: str,
        compute_embedding: bool = True,
    ) -> Optional[Dict[str, Any]]:
        sid = str(platform_shop_id or "").strip()
        gid = str(goods_id or "").strip()
        if not sid or not gid or not title or not content:
            return None
        doc_id = f"goods_sync_{sid}_{gid}"
        row: Dict[str, Any] = {
            "id": doc_id,
            "title": title,
            "filename": f"{title}.md",
            "content": content,
            "source": "goods_sync",
            "import_format": "markdown",
            "platform_shop_id": sid,
            "inherit_key": f"goods:{gid}",
            "allow_child_override": False,
        }
        if compute_embedding:
            if self._document_should_use_chunks(content):
                row["chunks"] = self._build_chunk_entries(content)
                row["embedding"] = (
                    row["chunks"][0].get("embedding")
                    if row["chunks"]
                    else self._embed_text(content[:4000])
                )
            else:
                row["embedding"] = self._embed_text(content)
        return row

    def upsert_goods_sync_row(self, row: Dict[str, Any]) -> bool:
        """写入/更新已构建好的商品同步文档行。"""
        if not row:
            return False
        doc_id = str(row.get("id") or "")
        if not doc_id:
            return False
        with self._global_io_lock:
            updated = False
            for i, doc in enumerate(self.documents):
                if str(doc.get("id")) == doc_id:
                    self.documents[i] = row
                    updated = True
                    break
            if not updated:
                self.documents.append(row)
            self._lancedb_delete_by_id(doc_id)
            self._add_doc_to_lancedb(row)
            self._save_documents()
        return True

    def upsert_goods_sync_document(
        self,
        *,
        platform_shop_id: str,
        goods_id: str,
        title: str,
        content: str,
    ) -> bool:
        """
        写入/更新店铺商品子知识库。
        inherit_key=goods:{id} 与父库同键时，父条需 allow_child_override 才会在检索中被隐藏。
        """
        row = self._build_goods_sync_row(
            platform_shop_id=platform_shop_id,
            goods_id=goods_id,
            title=title,
            content=content,
        )
        if not row:
            return False
        return self.upsert_goods_sync_row(row)

    def bulk_upsert_goods_sync_documents(
        self,
        rows: List[Dict[str, Any]],
    ) -> int:
        """批量写入商品同步文档（单次落盘 + 向量索引）。"""
        if not rows:
            return 0
        written = 0
        with self._global_io_lock:
            for row in rows:
                doc_id = str(row.get("id") or "")
                if not doc_id:
                    continue
                updated = False
                for i, doc in enumerate(self.documents):
                    if str(doc.get("id")) == doc_id:
                        self.documents[i] = row
                        updated = True
                        break
                if not updated:
                    self.documents.append(row)
                written += 1
            for row in rows:
                doc_id = str(row.get("id") or "")
                if doc_id:
                    self._lancedb_delete_by_id(doc_id)
            for row in rows:
                self._add_doc_to_lancedb(row)
            self._save_documents()
            self._last_sync_signature = None
        return written

    def delete_document(self, doc_id: str) -> bool:
        """向后兼容 - 删除文档。"""
        before = len(self.documents)
        self.documents = [d for d in self.documents if str(d.get("id")) != str(doc_id)]
        changed = len(self.documents) < before
        if changed:
            self._save_documents()
            self._last_sync_signature = None
            self._lancedb_delete_by_id(str(doc_id))
        return changed
