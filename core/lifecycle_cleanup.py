"""数据保留与临时文件清理。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from utils.logger_loguru import get_logger

_logger = get_logger("LifecycleCleanup")


def _retention_cfg() -> Dict[str, Any]:
    try:
        from config import config

        block = config.get("retention") or {}
        if isinstance(block, dict):
            return block
    except Exception:
        pass
    return {}


def _db_path() -> Path:
    from scripts.backup_db import resolve_db_path

    return resolve_db_path()


def _app_meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
    return str(row[0]) if row else None


def _app_meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)",
        (key, value),
    )


def _parse_created_at(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text.replace(" ", "T")[:26])
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text[:19], fmt)
            except ValueError:
                continue
    return None


def _doc_created_at(doc: Dict[str, Any]) -> datetime | None:
    meta = doc.get("metadata")
    if isinstance(meta, dict):
        dt = _parse_created_at(meta.get("created_at"))
        if dt:
            return dt
    return _parse_created_at(doc.get("created_at"))


def clean_old_vector_docs(days: int) -> int:
    """
    清理超期 LanceDB 向量与 knowledge_docs.json 中对应条目。
    days <= 0 时不执行。
    """
    if days <= 0:
        return 0

    from utils.runtime_path import get_temp_path

    json_path = get_temp_path() / "knowledge_docs.json"
    lancedb_path = get_temp_path() / "lancedb"
    if not json_path.exists():
        _logger.debug("向量清理跳过：{} 不存在", json_path)
        return 0

    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("读取知识库 JSON 失败: {}", e)
        return 0

    docs: List[Dict[str, Any]] = raw if isinstance(raw, list) else raw.get("documents", [])
    if not isinstance(docs, list):
        return 0

    cutoff = datetime.now() - timedelta(days=days)
    remove_ids: List[str] = []
    kept: List[Dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        doc_id = str(doc.get("id") or "")
        if doc_id == "__lancedb_init__":
            kept.append(doc)
            continue
        created = _doc_created_at(doc)
        if created is not None and created < cutoff:
            if doc_id:
                remove_ids.append(doc_id)
            continue
        kept.append(doc)

    if not remove_ids:
        return 0

    deleted = 0
    if lancedb_path.exists():
        try:
            import lancedb

            db = lancedb.connect(str(lancedb_path))
            if "knowledge" in db.table_names():
                table = db.open_table("knowledge")
                for doc_id in remove_ids:
                    safe_id = doc_id.replace("'", "''")
                    try:
                        table.delete(f"id = '{safe_id}'")
                        deleted += 1
                    except Exception as e:
                        _logger.debug("LanceDB 删除 {} 跳过: {}", doc_id, e)
        except Exception as e:
            _logger.warning("LanceDB 向量清理失败: {}", e)

    try:
        payload = kept if isinstance(raw, list) else {**raw, "documents": kept}
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        _logger.error("写回 knowledge_docs.json 失败: {}", e)

    _logger.info("向量文档清理: 删除 {} 条 (保留期 {} 天)", len(remove_ids), days)
    return len(remove_ids)


def run_lifecycle_cleanup() -> Dict[str, int]:
    cfg = _retention_cfg()
    chat_days = int(cfg.get("chat_history_days", 30) or 30)
    audit_days = int(cfg.get("audit_log_days", 90) or 90)
    temp_days = int(cfg.get("temp_files_days", 7) or 7)
    vacuum_days = int(cfg.get("vacuum_interval_days", 30) or 30)
    temp_dir = Path(str(cfg.get("temp_dir", "temp")))
    if not temp_dir.is_absolute():
        temp_dir = Path(__file__).resolve().parents[1] / temp_dir

    vector_days = int(cfg.get("vector_days", 0) or 0)
    stats = {
        "chat_messages_deleted": 0,
        "audits_deleted": 0,
        "temp_files_deleted": 0,
        "vacuum": 0,
        "vector_docs_deleted": 0,
    }
    db = _db_path()
    if not db.exists():
        _logger.warning("生命周期清理跳过：数据库不存在 {}", db)
        return stats

    conn = sqlite3.connect(db)
    try:
        cutoff_chat = (datetime.now() - timedelta(days=chat_days)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            cur = conn.execute(
                "DELETE FROM chat_messages WHERE created_at < ?",
                (cutoff_chat,),
            )
            stats["chat_messages_deleted"] = cur.rowcount
        except sqlite3.OperationalError as e:
            _logger.warning("清理 chat_messages 跳过: {}", e)

        cutoff_audit = (datetime.now() - timedelta(days=audit_days)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            cur = conn.execute(
                "DELETE FROM ops_security_audits WHERE created_at < ?",
                (cutoff_audit,),
            )
            stats["audits_deleted"] = cur.rowcount
        except sqlite3.OperationalError as e:
            _logger.debug("清理 ops_security_audits 跳过: {}", e)

        last_vacuum = _app_meta_get(conn, "last_vacuum_at")
        do_vacuum = True
        if last_vacuum:
            try:
                last_dt = datetime.fromisoformat(last_vacuum)
                if datetime.now() - last_dt < timedelta(days=vacuum_days):
                    do_vacuum = False
            except ValueError:
                pass
        if do_vacuum:
            conn.execute("VACUUM")
            _app_meta_set(conn, "last_vacuum_at", datetime.now().isoformat(timespec="seconds"))
            stats["vacuum"] = 1
        conn.commit()
    finally:
        conn.close()

    if vector_days > 0:
        try:
            stats["vector_docs_deleted"] = clean_old_vector_docs(vector_days)
        except Exception as e:
            _logger.warning("向量文档清理跳过: {}", e)

    if temp_dir.exists():
        cutoff_temp = datetime.now() - timedelta(days=temp_days)
        for f in temp_dir.rglob("*"):
            if not f.is_file():
                continue
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff_temp:
                    f.unlink(missing_ok=True)
                    stats["temp_files_deleted"] += 1
            except OSError as e:
                _logger.error("删除临时文件失败 {}: {}", f, e)

    _logger.info("生命周期清理完成: {}", stats)
    return stats
