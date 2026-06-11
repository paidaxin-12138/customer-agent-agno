"""ignore_shop_filter=True 时应检索全库（公共 + 全部店铺子库）。"""
from Agent.CustomerAgent.knowledge_retriever import KnowledgeRetrieverMixin
from Agent.CustomerAgent.knowledge_storage import KnowledgeStorageMixin


class _StubKM(KnowledgeRetrieverMixin, KnowledgeStorageMixin):
    def __init__(self, documents):
        self.documents = documents
        self.logger = type("L", (), {"debug": staticmethod(lambda *a, **k: None)})()


def test_documents_for_retrieval_ignore_shop_returns_all():
    km = _StubKM(
        [
            {"id": "pub", "content": "公共", "platform_shop_id": ""},
            {"id": "a", "content": "店A", "platform_shop_id": "shop_a"},
            {"id": "b", "content": "店B", "platform_shop_id": "shop_b"},
        ]
    )
    scoped = km._documents_for_retrieval(ignore_shop_filter=False, platform_shop_id=None)
    assert [d["id"] for d in scoped] == ["pub"]

    all_docs = km._documents_for_retrieval(ignore_shop_filter=True)
    assert {d["id"] for d in all_docs} == {"pub", "a", "b"}


def test_apply_parent_override_skipped_when_ignore_shop_filter():
    km = _StubKM(
        [
            {
                "id": "parent",
                "platform_shop_id": "",
                "inherit_key": "policy",
                "allow_child_override": True,
                "content": "父",
            },
            {
                "id": "child",
                "platform_shop_id": "shop_a",
                "inherit_key": "policy",
                "content": "子",
            },
        ]
    )
    ranked = [(0.1, km.documents[0]), (0.2, km.documents[1])]
    scoped = km._apply_parent_override_filter(ranked, km.documents, "shop_a")
    assert [d["id"] for _, d in scoped] == ["child"]

    # ignore_shop_filter 路径不调用覆盖过滤，父子条目均保留
    assert [d["id"] for _, d in ranked] == ["parent", "child"]
