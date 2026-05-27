"""运营看板相关表结构（与会话库共用 SQLite）。"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text

from database.models import Base, _db_now


class OpsSessionRow(Base):
    """会话看板快照（可与 chat_sessions 关联）。"""

    __tablename__ = "ops_sessions"
    __table_args__ = (
        Index("idx_ops_sessions_updated", "updated_at"),
        Index("idx_ops_sessions_channel", "channel"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_session_id = Column(Integer, nullable=True)
    session_key = Column(String(220), nullable=True)
    user_label = Column(String(200), nullable=False, default="")
    channel = Column(String(50), nullable=False, default="pinduoduo")
    intent = Column(String(100), nullable=True)
    status = Column(String(30), default="active")
    is_resolved = Column(Boolean, default=False)
    transferred_to_human = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=_db_now, onupdate=_db_now)


class OpsTrace(Base):
    """单次 AI 回复链路追踪。"""

    __tablename__ = "ops_traces"
    __table_args__ = (Index("idx_ops_traces_created", "created_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, unique=True)
    session_key = Column(String(200), nullable=True)
    user_label = Column(String(200), nullable=True)
    channel = Column(String(50), nullable=True)
    query_text = Column(Text, nullable=True)
    coreference_json = Column(Text, nullable=True)
    intent_json = Column(Text, nullable=True)
    rewrite_json = Column(Text, nullable=True)
    recall_json = Column(Text, nullable=True)
    rerank_json = Column(Text, nullable=True)
    final_answer = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_db_now)


class OpsKnowledgeRevision(Base):
    """知识库版本与审核流。"""

    __tablename__ = "ops_knowledge_revisions"
    __table_args__ = (Index("idx_ops_kb_doc", "doc_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String(100), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    title = Column(String(300), nullable=True)
    content = Column(Text, nullable=True)
    status = Column(String(30), default="draft")  # draft/review/published/offline
    operator = Column(String(100), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_db_now)


class OpsLowConfidence(Base):
    """低置信度 / 未命中问题池。"""

    __tablename__ = "ops_low_confidence"
    __table_args__ = (Index("idx_ops_lc_status", "review_status"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    repeat_count = Column(Integer, default=1)
    suggested_answer = Column(Text, nullable=True)
    review_status = Column(String(30), default="pending")  # pending/approved/rejected
    channel = Column(String(50), nullable=True)
    updated_at = Column(DateTime, default=_db_now, onupdate=_db_now)


class OpsTicket(Base):
    """工单队列。"""

    __tablename__ = "ops_tickets"
    __table_args__ = (Index("idx_ops_tickets_status", "status"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(300), nullable=False)
    source = Column(String(30), default="ai")  # ai/human
    status = Column(String(30), default="open")  # open/assigned/done/closed
    assignee = Column(String(100), nullable=True)
    result = Column(Text, nullable=True)
    session_key = Column(String(200), nullable=True)
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_db_now)
    updated_at = Column(DateTime, default=_db_now, onupdate=_db_now)


class OpsEvalRun(Base):
    """评测批次。"""

    __tablename__ = "ops_eval_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    test_set_name = Column(String(200), nullable=True)
    model_version = Column(String(100), nullable=True)
    pass_rate = Column(Float, nullable=True)
    failed_count = Column(Integer, default=0)
    total_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_db_now)


class OpsEvalSample(Base):
    """评测失败样本等。"""

    __tablename__ = "ops_eval_samples"
    __table_args__ = (Index("idx_ops_eval_run", "run_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, nullable=False)
    question = Column(Text, nullable=True)
    expected = Column(Text, nullable=True)
    actual = Column(Text, nullable=True)
    passed = Column(Boolean, default=False)
    note = Column(Text, nullable=True)


class OpsCostLog(Base):
    """模型成本明细。"""

    __tablename__ = "ops_cost_logs"
    __table_args__ = (Index("idx_ops_cost_created", "created_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_key = Column(String(200), nullable=True)
    model_name = Column(String(100), nullable=True)
    call_count = Column(Integer, default=1)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cache_hit = Column(Boolean, default=False)
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=_db_now)


class OpsSecurityAudit(Base):
    """安全审计日志。"""

    __tablename__ = "ops_security_audits"
    __table_args__ = (Index("idx_ops_sec_created", "created_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False)
    detail = Column(Text, nullable=True)
    user_label = Column(String(200), nullable=True)
    severity = Column(String(20), default="info")  # info/warn/block
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_db_now)
