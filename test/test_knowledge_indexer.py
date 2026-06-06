"""知识库索引层单元测试（分块、LanceDB ID 转义）。"""
from __future__ import annotations

from Agent.CustomerAgent.knowledge_storage import (
    KnowledgeStorageMixin,
    lancedb_delete_filter,
    lancedb_escape_id,
)
from Agent.CustomerAgent.knowledge_indexer import KnowledgeIndexerMixin


class _IndexerProbe(KnowledgeIndexerMixin, KnowledgeStorageMixin):
    """测试用最小组合（与 NailLampKnowledgeManager MRO 子集一致）。"""

    _CHUNK_TARGET = 480


def test_lancedb_escape_id_quotes():
    assert lancedb_escape_id("doc_1") == "doc_1"
    assert lancedb_escape_id("a'b") == "a''b"
    assert lancedb_delete_filter("x'y") == "id = 'x''y'"


def test_split_content_chunks_short_text():
    probe = _IndexerProbe()
    parts = probe._split_content_chunks("短文本")
    assert parts == ["短文本"]


def test_split_content_chunks_long_paragraphs():
    probe = _IndexerProbe()
    long_para = "段落内容。" * 200
    parts = probe._split_content_chunks(long_para)
    assert len(parts) >= 2
    assert all(len(p) <= probe._CHUNK_TARGET + probe._CHUNK_OVERLAP for p in parts)


def test_embedding_text_for_doc_includes_title():
    text = KnowledgeStorageMixin._embedding_text_for_doc(
        {"title": "标题", "content": "正文"}
    )
    assert "标题" in text
    assert "正文" in text
