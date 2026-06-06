"""LanceDB 增量同步签名。"""
from unittest.mock import MagicMock, patch


def test_sync_skips_when_signature_unchanged():
    from Agent.CustomerAgent.agent_knowledge import NailLampKnowledgeManager

    mgr = object.__new__(NailLampKnowledgeManager)
    mgr.logger = MagicMock()
    mgr.documents = [{"id": "1", "content": "hello", "platform_shop_id": ""}]
    mgr._knowledge_table = MagicMock()
    mgr._last_sync_signature = mgr._doc_sync_signature()
    mgr._embed_text = MagicMock()

    assert mgr._sync_all_docs_to_lancedb() == 0
    mgr._knowledge_table.delete.assert_not_called()
