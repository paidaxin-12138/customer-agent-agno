import json
from datetime import datetime, timedelta

from core.lifecycle_cleanup import clean_old_vector_docs


def test_clean_old_vector_docs_skips_when_days_zero():
    assert clean_old_vector_docs(0) == 0


def test_clean_old_vector_docs_removes_stale_json_entries(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.runtime_path.get_temp_path", lambda: tmp_path)

    store = tmp_path / "knowledge_docs.json"
    old = (datetime.now() - timedelta(days=200)).isoformat(timespec="seconds")
    docs = [
        {"id": "old1", "content": "x", "created_at": old},
        {
            "id": "keep1",
            "content": "y",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
    ]
    store.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "lancedb").mkdir()

    n = clean_old_vector_docs(180)
    assert n == 1
    remaining = json.loads(store.read_text(encoding="utf-8"))
    assert len(remaining) == 1
    assert remaining[0]["id"] == "keep1"
