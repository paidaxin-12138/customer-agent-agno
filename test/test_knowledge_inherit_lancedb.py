"""LanceDB 检索路径的父子店 inherit 覆盖。"""
from Agent.CustomerAgent.knowledge_retriever import KnowledgeRetrieverMixin


class _StubKM(KnowledgeRetrieverMixin):
    def __init__(self, documents):
        self.documents = documents

    @staticmethod
    def _inherit_key(doc):
        return str(doc.get("inherit_key") or "").strip()

    @staticmethod
    def _parent_allows_child_override(doc):
        return bool(doc.get("allow_child_override", False))

    def _shop_override_inherit_keys(self, pool, shop_id):
        keys = set()
        sid = (shop_id or "").strip()
        for d in pool:
            ps = (d.get("platform_shop_id") or "").strip()
            if ps == sid:
                ik = self._inherit_key(d)
                if ik:
                    keys.add(ik)
        return keys


def test_lancedb_ranked_applies_parent_override_filter():
    km = _StubKM(
        [
            {
                "id": "parent",
                "platform_shop_id": "",
                "inherit_key": "ship_policy",
                "allow_child_override": True,
                "content": "父",
            },
            {
                "id": "child",
                "platform_shop_id": "shop_a",
                "inherit_key": "ship_policy",
                "content": "子",
            },
        ]
    )
    ranked = [
        (0.1, km.documents[0]),
        (0.2, km.documents[1]),
    ]
    out = km._apply_parent_override_filter(ranked, km.documents, "shop_a")
    ids = [d["id"] for _, d in out]
    assert ids == ["child"]
