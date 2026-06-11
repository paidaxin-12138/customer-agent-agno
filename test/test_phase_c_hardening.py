"""Phase C 生产硬化 TDD。"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from Agent.CustomerAgent.knowledge_indexer import KnowledgeIndexerMixin
from Agent.CustomerAgent.knowledge_storage import KnowledgeStorageMixin
from database.schema_migrations import migrate_message_dead_letters_table
from sqlalchemy import create_engine


class _KbProbe(KnowledgeIndexerMixin, KnowledgeStorageMixin):
    pass


def test_save_documents_atomic_replace(tmp_path):
    probe = _KbProbe()
    probe._store_file = tmp_path / "docs.json"
    probe.documents = [{"id": "d1", "content": "hello", "title": "t"}]

    with patch("os.replace") as mock_replace:
        probe._save_documents()
        mock_replace.assert_called_once()
    tmp_file = tmp_path / "docs.json.tmp"
    assert tmp_file.exists()
    data = json.loads(tmp_file.read_text(encoding="utf-8"))
    assert data[0]["id"] == "d1"


def test_add_document_under_io_lock(tmp_path):
    probe = _KbProbe()
    probe._store_file = tmp_path / "docs.json"
    probe.documents = []
    probe._add_doc_to_lancedb = MagicMock(return_value=True)
    probe._lancedb_delete_by_id = MagicMock()
    probe.add_document({"id": "x", "content": "c"})
    assert len(probe.documents) == 1
    assert probe._store_file.exists()


def test_audit_log_redacts_extra_secrets():
    from utils.audit_log import audit_log

    captured = {}

    def _insert(row):
        captured.update(row)

    with patch(
        "database.ops_repository.get_ops_repository",
        return_value=MagicMock(insert_security_audit=_insert),
    ):
        audit_log(
            "test_event",
            "user1",
            "detail",
            extra={"password": "secret123", "note": "ok"},
        )

    payload = json.loads(captured["payload_json"])
    assert payload["password"] == "***"
    assert payload["note"] == "ok"


def test_ui_log_handler_uses_redact_filter():
    from utils.logger_loguru import UILogHandler

    handler = UILogHandler()
    with patch("utils.logger_loguru.logger.add", return_value=1) as mock_add, patch(
        "utils.logger_loguru.logger.remove"
    ):
        handler.install()
        kwargs = mock_add.call_args.kwargs
        assert kwargs.get("filter") is not None
        handler.uninstall()


def test_strict_handlers_default_in_production(monkeypatch):
    from Message import handler_chain_factory as hcf

    monkeypatch.delenv("STRICT_HANDLERS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert hcf._strict_handlers_enabled() is True
    monkeypatch.setenv("STRICT_HANDLERS", "0")
    assert hcf._strict_handlers_enabled() is False


def test_audit_handler_chain_raises_when_strict_and_missing(monkeypatch):
    from Message.handler_chain_factory import HandlerChainError, audit_handler_chain

    monkeypatch.setenv("STRICT_HANDLERS", "1")

    def _boom(_module, _cls):
        raise ImportError("missing handler")

    with patch("Message.handler_chain_factory._import_handler", side_effect=_boom):
        with pytest.raises(HandlerChainError):
            audit_handler_chain()


@pytest.mark.asyncio
async def test_message_loop_drains_inflight_before_exit():
    from Channel.pinduoduo.ws_message_loop import run_message_loop

    class _FakeWebSocket:
        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._msgs:
                raise StopAsyncIteration
            return self._msgs.pop(0)

        _msgs = ["one"]

    started = asyncio.Event()
    done = asyncio.Event()

    async def _on_message(_msg):
        started.set()
        await asyncio.sleep(0.05)
        done.set()

    tasks: set = set()
    stop = asyncio.Event()
    ws = _FakeWebSocket()
    await run_message_loop(
        ws,
        shop_id="s",
        user_id="u",
        username="cs",
        stop_event=stop,
        on_message=_on_message,
        processing_tasks=tasks,
    )
    assert done.is_set()
    assert len(tasks) == 0


@pytest.mark.asyncio
async def test_cancel_task_set_persists_cancelled_ws_frame(temp_db=None):
    from Channel.pinduoduo.ws_task_cleanup import cancel_task_set

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "t.db")
        engine = create_engine(f"sqlite:///{db_path}")
        migrate_message_dead_letters_table(engine)

        tasks: set = set()
        payloads: dict = {}
        blocker = asyncio.Event()

        async def _slow():
            await blocker.wait()

        t = asyncio.create_task(_slow())
        tasks.add(t)
        payloads[t] = '{"type":"test"}'

        with patch("Message.dead_letter._db_path", return_value=db_path):
            await cancel_task_set(
                tasks,
                drain_wait_sec=0,
                task_payloads=payloads,
                queue_name="pdd_s_u",
            )

        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM message_dead_letters WHERE reason = ?",
                ("ws_inflight_cancel",),
            ).fetchone()[0]
        finally:
            conn.close()
        assert int(count) == 1
