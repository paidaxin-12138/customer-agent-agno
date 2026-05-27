"""运营看板数据访问层。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

RevisionAddResult = Literal["created", "unchanged", "error"]

from sqlalchemy.exc import SQLAlchemyError

from database.models import Account, ChatSession
from database.ops_models import (
    OpsCostLog,
    OpsEvalRun,
    OpsEvalSample,
    OpsKnowledgeRevision,
    OpsLowConfidence,
    OpsSecurityAudit,
    OpsSessionRow,
    OpsTicket,
    OpsTrace,
)
from utils.chat_time import format_display_datetime, now_for_db
from utils.logger_loguru import get_logger

logger = get_logger("OpsRepository")


def _row_to_dict(obj, fields: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for f in fields:
        v = getattr(obj, f, None)
        if isinstance(v, datetime):
            v = format_display_datetime(v)
        out[f] = v
    return out


class OpsRepository:
    def __init__(self, db_manager):
        self._db = db_manager
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        from database.models import Base
        from database import ops_models  # noqa: F401 — register tables
        from database.ops_migrate import migrate_ops_schema

        path = self._db.engine.url.database
        if path:
            migrate_ops_schema(path)

        Base.metadata.create_all(self._db.engine, tables=[
            OpsSessionRow.__table__,
            OpsTrace.__table__,
            OpsKnowledgeRevision.__table__,
            OpsLowConfidence.__table__,
            OpsTicket.__table__,
            OpsEvalRun.__table__,
            OpsEvalSample.__table__,
            OpsCostLog.__table__,
            OpsSecurityAudit.__table__,
        ])

    def sync_sessions_from_chat(self) -> int:
        """从 chat_sessions 同步会话列表到看板表。"""
        session = self._db.get_session()
        n = 0
        try:
            rows = session.query(ChatSession).order_by(ChatSession.updated_at.desc()).limit(500).all()
            for cs in rows:
                existing = (
                    session.query(OpsSessionRow)
                    .filter(OpsSessionRow.chat_session_id == cs.id)
                    .first()
                )
                acc = session.query(Account).filter(Account.id == cs.account_id).first()
                seller_uid = acc.user_id if acc else ""
                channel = "pinduoduo"
                user_label = cs.buyer_nickname or cs.buyer_uid or ""
                transferred = cs.status == "transferred" or not bool(cs.ai_mode)
                intent = getattr(cs, "last_intent", None) or ""
                sk = f"pinduoduo:{cs.platform_shop_id}:{seller_uid}:{cs.buyer_uid}"
                payload = dict(
                    session_key=sk,
                    user_label=user_label,
                    channel=channel,
                    intent=intent or None,
                    status=cs.status or "active",
                    is_resolved=cs.status == "closed",
                    transferred_to_human=transferred,
                    updated_at=cs.updated_at or now_for_db(),
                )
                if existing:
                    for k, v in payload.items():
                        setattr(existing, k, v)
                else:
                    session.add(OpsSessionRow(chat_session_id=cs.id, **payload))
                n += 1
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"sync_sessions_from_chat: {e}")
        finally:
            session.close()
        return n

    def list_sessions(self, limit: int = 200) -> List[Dict[str, Any]]:
        session = self._db.get_session()
        try:
            rows = (
                session.query(OpsSessionRow)
                .order_by(OpsSessionRow.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [
                _row_to_dict(
                    r,
                    [
                        "id",
                        "user_label",
                        "channel",
                        "intent",
                        "status",
                        "is_resolved",
                        "transferred_to_human",
                        "updated_at",
                    ],
                )
                for r in rows
            ]
        finally:
            session.close()

    def insert_trace(self, data: Dict[str, Any]) -> None:
        session = self._db.get_session()
        try:
            session.add(OpsTrace(**data))
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"insert_trace: {e}")
        finally:
            session.close()

    def list_traces(self, limit: int = 100) -> List[Dict[str, Any]]:
        session = self._db.get_session()
        try:
            rows = (
                session.query(OpsTrace)
                .order_by(OpsTrace.created_at.desc())
                .limit(limit)
                .all()
            )
            out = []
            for r in rows:
                d = _row_to_dict(
                    r,
                    [
                        "id",
                        "trace_id",
                        "user_label",
                        "channel",
                        "query_text",
                        "final_answer",
                        "created_at",
                    ],
                )
                for key in (
                    "coreference_json",
                    "intent_json",
                    "rewrite_json",
                    "recall_json",
                    "rerank_json",
                ):
                    raw = getattr(r, key, None)
                    if raw:
                        try:
                            d[key.replace("_json", "")] = json.loads(raw)
                        except json.JSONDecodeError:
                            d[key.replace("_json", "")] = raw
                out.append(d)
            return out
        finally:
            session.close()

    def list_knowledge_revisions(self, limit: int = 200) -> List[Dict[str, Any]]:
        session = self._db.get_session()
        try:
            rows = (
                session.query(OpsKnowledgeRevision)
                .order_by(OpsKnowledgeRevision.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                _row_to_dict(
                    r,
                    ["id", "doc_id", "version", "title", "status", "operator", "created_at"],
                )
                for r in rows
            ]
        finally:
            session.close()

    @staticmethod
    def _revision_content_fingerprint(title: str, content: str) -> str:
        """标题 + 正文一致则视为同一版本内容（用于去重）。"""
        t = (title or "").strip()
        c = content or ""
        return hashlib.sha256(f"{t}\n---\n{c}".encode("utf-8")).hexdigest()

    def _latest_revision_matches(
        self, last: Optional[OpsKnowledgeRevision], title: str, content: str
    ) -> bool:
        if last is None:
            return False
        fp = self._revision_content_fingerprint(title, content)
        last_fp = self._revision_content_fingerprint(
            str(last.title or ""), str(last.content or "")
        )
        return fp == last_fp

    def add_knowledge_revision(
        self,
        doc_id: str,
        title: str,
        content: str,
        status: str = "draft",
        operator: str = "admin",
        note: str = "",
        *,
        skip_if_unchanged: bool = False,
    ) -> RevisionAddResult:
        session = self._db.get_session()
        try:
            last = (
                session.query(OpsKnowledgeRevision)
                .filter(OpsKnowledgeRevision.doc_id == doc_id)
                .order_by(OpsKnowledgeRevision.version.desc())
                .first()
            )
            if skip_if_unchanged and self._latest_revision_matches(last, title, content):
                return "unchanged"
            ver = (last.version + 1) if last else 1
            session.add(
                OpsKnowledgeRevision(
                    doc_id=doc_id,
                    version=ver,
                    title=title,
                    content=content,
                    status=status,
                    operator=operator,
                    note=note,
                )
            )
            session.commit()
            return "created"
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"add_knowledge_revision: {e}")
            return "error"
        finally:
            session.close()

    def update_knowledge_status(self, rev_id: int, status: str) -> bool:
        session = self._db.get_session()
        try:
            row = session.query(OpsKnowledgeRevision).filter(OpsKnowledgeRevision.id == rev_id).first()
            if not row:
                return False
            row.status = status
            session.commit()
            if status == "published":
                self._apply_revision_to_live_knowledge(row)
            return True
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"update_knowledge_status: {e}")
            return False
        finally:
            session.close()

    def _apply_revision_to_live_knowledge(self, row: OpsKnowledgeRevision) -> None:
        """发布：把审核通过的版本写回线上知识库（NailLampKnowledgeManager）。"""
        try:
            from Agent.CustomerAgent.agent_knowledge import knowledge_manager

            doc_id = str(row.doc_id)
            content = str(row.content or "")
            title = str(row.title or doc_id)
            existing = None
            for d in knowledge_manager.get_all_documents():
                if str(d.get("id")) == doc_id:
                    existing = d
                    break
            if existing:
                knowledge_manager.update_document(
                    doc_id,
                    {
                        "title": title,
                        "content": content,
                        "import_format": existing.get("import_format") or "text",
                    },
                )
            else:
                knowledge_manager.add_document(
                    {
                        "id": doc_id,
                        "title": title,
                        "content": content,
                        "filename": f"{title}.txt",
                        "source": "ops_publish",
                        "import_format": "text",
                    }
                )
            logger.info(f"已发布知识到线上库: {doc_id} v{row.version}")
        except Exception as e:
            logger.error(f"发布知识到线上库失败: {e}")

    def update_session_intent(
        self, session_key: str, user_label: str, intent: str
    ) -> None:
        """更新看板会话行的意图标签。"""
        if not intent:
            return
        session = self._db.get_session()
        try:
            row = None
            if session_key:
                row = (
                    session.query(OpsSessionRow)
                    .filter(OpsSessionRow.session_key == session_key)
                    .first()
                )
            if not row and user_label:
                row = (
                    session.query(OpsSessionRow)
                    .filter(OpsSessionRow.user_label == user_label)
                    .order_by(OpsSessionRow.updated_at.desc())
                    .first()
                )
            if row:
                row.intent = intent
                session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            logger.debug(f"update_session_intent: {e}")
        finally:
            session.close()

    def rollback_knowledge(self, rev_id: int) -> bool:
        session = self._db.get_session()
        try:
            row = session.query(OpsKnowledgeRevision).filter(OpsKnowledgeRevision.id == rev_id).first()
            if not row:
                return False
            new_rev = OpsKnowledgeRevision(
                doc_id=row.doc_id,
                version=row.version + 1,
                title=row.title,
                content=row.content,
                status="published",
                operator=row.operator,
                note=f"rollback from v{row.version}",
            )
            session.add(new_rev)
            session.flush()
            self._apply_revision_to_live_knowledge(new_rev)
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"rollback_knowledge: {e}")
            return False
        finally:
            session.close()

    def upsert_low_confidence(self, question: str, suggested: str = "", channel: str = "") -> None:
        q = (question or "").strip()
        if not q:
            return
        session = self._db.get_session()
        try:
            row = (
                session.query(OpsLowConfidence)
                .filter(OpsLowConfidence.question == q)
                .first()
            )
            if row:
                row.repeat_count = int(row.repeat_count or 0) + 1
                if suggested:
                    row.suggested_answer = suggested
                row.updated_at = now_for_db()
            else:
                session.add(
                    OpsLowConfidence(
                        question=q,
                        repeat_count=1,
                        suggested_answer=suggested or None,
                        channel=channel or None,
                    )
                )
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"upsert_low_confidence: {e}")
        finally:
            session.close()

    def list_low_confidence(self, limit: int = 200) -> List[Dict[str, Any]]:
        session = self._db.get_session()
        try:
            rows = (
                session.query(OpsLowConfidence)
                .order_by(OpsLowConfidence.repeat_count.desc())
                .limit(limit)
                .all()
            )
            return [
                _row_to_dict(
                    r,
                    [
                        "id",
                        "question",
                        "repeat_count",
                        "suggested_answer",
                        "review_status",
                        "channel",
                        "updated_at",
                    ],
                )
                for r in rows
            ]
        finally:
            session.close()

    def update_low_confidence_status(self, row_id: int, status: str) -> bool:
        session = self._db.get_session()
        try:
            row = session.query(OpsLowConfidence).filter(OpsLowConfidence.id == row_id).first()
            if not row:
                return False
            row.review_status = status
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            return False
        finally:
            session.close()

    def create_ticket(
        self,
        title: str,
        source: str = "ai",
        session_key: str = "",
        payload: Optional[Dict] = None,
    ) -> int:
        session = self._db.get_session()
        try:
            t = OpsTicket(
                title=title,
                source=source,
                session_key=session_key or None,
                payload_json=json.dumps(payload or {}, ensure_ascii=False),
            )
            session.add(t)
            session.commit()
            return int(t.id)
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"create_ticket: {e}")
            return 0
        finally:
            session.close()

    def list_tickets(self, limit: int = 200) -> List[Dict[str, Any]]:
        session = self._db.get_session()
        try:
            rows = (
                session.query(OpsTicket)
                .order_by(OpsTicket.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [
                _row_to_dict(
                    r,
                    [
                        "id",
                        "title",
                        "source",
                        "status",
                        "assignee",
                        "result",
                        "session_key",
                        "created_at",
                        "updated_at",
                    ],
                )
                for r in rows
            ]
        finally:
            session.close()

    def update_ticket(self, ticket_id: int, **fields) -> bool:
        session = self._db.get_session()
        try:
            row = session.query(OpsTicket).filter(OpsTicket.id == ticket_id).first()
            if not row:
                return False
            for k, v in fields.items():
                if hasattr(row, k):
                    setattr(row, k, v)
            row.updated_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            return False
        finally:
            session.close()

    def list_eval_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        session = self._db.get_session()
        try:
            rows = (
                session.query(OpsEvalRun)
                .order_by(OpsEvalRun.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                _row_to_dict(
                    r,
                    [
                        "id",
                        "name",
                        "test_set_name",
                        "model_version",
                        "pass_rate",
                        "failed_count",
                        "total_count",
                        "created_at",
                    ],
                )
                for r in rows
            ]
        finally:
            session.close()

    def list_eval_samples(self, run_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        session = self._db.get_session()
        try:
            rows = (
                session.query(OpsEvalSample)
                .filter(OpsEvalSample.run_id == run_id)
                .order_by(OpsEvalSample.id.desc())
                .limit(limit)
                .all()
            )
            return [
                _row_to_dict(
                    r,
                    ["id", "run_id", "question", "expected", "actual", "passed", "note"],
                )
                for r in rows
            ]
        finally:
            session.close()

    def add_eval_sample(
        self,
        run_id: int,
        question: str,
        expected: str,
        actual: str,
        passed: bool,
        note: str = "",
    ) -> None:
        session = self._db.get_session()
        try:
            session.add(
                OpsEvalSample(
                    run_id=run_id,
                    question=question,
                    expected=expected,
                    actual=actual,
                    passed=passed,
                    note=note,
                )
            )
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"add_eval_sample: {e}")
        finally:
            session.close()

    def add_eval_run(
        self,
        name: str,
        test_set_name: str,
        model_version: str,
        pass_rate: float,
        failed_count: int,
        total_count: int,
    ) -> int:
        session = self._db.get_session()
        try:
            run = OpsEvalRun(
                name=name,
                test_set_name=test_set_name,
                model_version=model_version,
                pass_rate=pass_rate,
                failed_count=failed_count,
                total_count=total_count,
            )
            session.add(run)
            session.commit()
            return int(run.id)
        except SQLAlchemyError as e:
            session.rollback()
            return 0
        finally:
            session.close()

    def insert_cost(self, data: Dict[str, Any]) -> None:
        session = self._db.get_session()
        try:
            session.add(OpsCostLog(**data))
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"insert_cost: {e}")
        finally:
            session.close()

    def cost_summary(self) -> Dict[str, Any]:
        session = self._db.get_session()
        try:
            rows = session.query(OpsCostLog).all()
            total_calls = sum(int(r.call_count or 0) for r in rows)
            prompt_t = sum(int(r.prompt_tokens or 0) for r in rows)
            completion_t = sum(int(r.completion_tokens or 0) for r in rows)
            cost = sum(float(r.cost_usd or 0) for r in rows)
            hits = sum(1 for r in rows if r.cache_hit)
            cache_rate = (hits / len(rows) * 100) if rows else 0.0
            sessions = len({r.session_key for r in rows if r.session_key})
            per_session = cost / sessions if sessions else 0.0
            return {
                "total_calls": total_calls,
                "prompt_tokens": prompt_t,
                "completion_tokens": completion_t,
                "total_tokens": prompt_t + completion_t,
                "cache_hit_rate": round(cache_rate, 1),
                "total_cost_usd": round(cost, 4),
                "session_count": sessions,
                "cost_per_session_usd": round(per_session, 4),
            }
        finally:
            session.close()

    def list_cost_logs(self, limit: int = 200) -> List[Dict[str, Any]]:
        session = self._db.get_session()
        try:
            rows = (
                session.query(OpsCostLog)
                .order_by(OpsCostLog.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                _row_to_dict(
                    r,
                    [
                        "id",
                        "session_key",
                        "model_name",
                        "call_count",
                        "prompt_tokens",
                        "completion_tokens",
                        "cache_hit",
                        "cost_usd",
                        "created_at",
                    ],
                )
                for r in rows
            ]
        finally:
            session.close()

    def insert_security_audit(self, data: Dict[str, Any]) -> None:
        session = self._db.get_session()
        try:
            session.add(OpsSecurityAudit(**data))
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"insert_security_audit: {e}")
        finally:
            session.close()

    def list_security_audits(self, limit: int = 200) -> List[Dict[str, Any]]:
        session = self._db.get_session()
        try:
            rows = (
                session.query(OpsSecurityAudit)
                .order_by(OpsSecurityAudit.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                _row_to_dict(
                    r,
                    ["id", "event_type", "detail", "user_label", "severity", "created_at"],
                )
                for r in rows
            ]
        finally:
            session.close()


_ops_repo: Optional[OpsRepository] = None


def get_ops_repository() -> OpsRepository:
    global _ops_repo
    if _ops_repo is None:
        from database.db_manager import db_manager

        _ops_repo = OpsRepository(db_manager)
    return _ops_repo
