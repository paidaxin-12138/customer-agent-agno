"""知识库延迟初始化。"""
from unittest.mock import MagicMock, patch


def test_knowledge_manager_lazy_singleton():
    import Agent.CustomerAgent.agent_knowledge as ak

    ak._manager_instance = None
    mock_mgr = MagicMock()
    mock_mgr.get_content_count.return_value = 7

    with patch.object(ak, "NailLampKnowledgeManager", return_value=mock_mgr) as cls:
        assert ak.knowledge_manager.get_content_count() == 7
        assert ak.knowledge_manager.get_content_count() == 7
        cls.assert_called_once()
