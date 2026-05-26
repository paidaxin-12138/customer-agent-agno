"""
运营看板：会话、链路、知识、低置信度、工单、评测、成本、安全审计。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CaptionLabel, PushButton, SubtitleLabel

from database.ops_repository import get_ops_repository
from ui.ops_dashboard.table_panel import OpsTablePanel
from utils.logger_loguru import get_logger

logger = get_logger(__name__)


class OpsDashboardUI(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("运营看板")
        self._repo = get_ops_repository()
        self._trace_cache: List[Dict[str, Any]] = []
        self._init_ui()
        self.refresh_all()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        head = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.addWidget(SubtitleLabel("运营看板"))
        title_col.addWidget(
            CaptionLabel(
                "会话列表 · 链路追踪 · 知识管理 · 低置信度池 · 工单 · 评测 · 成本 · 安全审计"
            )
        )
        head.addLayout(title_col)
        head.addStretch()
        sync_btn = PushButton("全量同步")
        sync_btn.clicked.connect(self.refresh_all)
        head.addWidget(sync_btn)
        layout.addLayout(head)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self._build_sessions_tab()
        self._build_trace_tab()
        self._build_knowledge_tab()
        self._build_low_conf_tab()
        self._build_tickets_tab()
        self._build_eval_tab()
        self._build_cost_tab()
        self._build_security_tab()

    def _build_sessions_tab(self) -> None:
        self.sessions_panel = OpsTablePanel(
            "会话列表",
            ["user_label", "channel", "intent", "status", "is_resolved", "transferred_to_human", "updated_at"],
            {
                "user_label": "用户",
                "channel": "渠道",
                "intent": "意图",
                "status": "状态",
                "is_resolved": "是否解决",
                "transferred_to_human": "转人工",
                "updated_at": "更新时间",
            },
        )
        self.sessions_panel.set_refresh_callback(self._load_sessions)
        self.sessions_panel.set_detail_formatter(
            lambda r: f"用户 {r.get('user_label')} | 渠道 {r.get('channel')} | 意图 {r.get('intent') or '-'} | 状态 {r.get('status')}"
        )
        self.tabs.addTab(self.sessions_panel, "会话列表")

    def _build_trace_tab(self) -> None:
        self.trace_panel = OpsTablePanel(
            "链路追踪",
            ["trace_id", "user_label", "channel", "query_text", "final_answer", "created_at"],
            {
                "trace_id": "追踪ID",
                "user_label": "用户",
                "channel": "渠道",
                "query_text": "用户问题",
                "final_answer": "最终答案",
                "created_at": "时间",
            },
        )
        self.trace_panel.set_refresh_callback(self._load_traces)
        self.trace_panel.set_detail_formatter(self._format_trace_detail)
        self.tabs.addTab(self.trace_panel, "链路追踪")

    def _format_trace_detail(self, row: Dict[str, Any]) -> str:
        tid = row.get("trace_id", "")
        full = next((t for t in self._trace_cache if t.get("trace_id") == tid), row)
        parts = [
            f"指代消解: {json.dumps(full.get('coreference', {}), ensure_ascii=False)[:200]}",
            f"意图识别: {json.dumps(full.get('intent', {}), ensure_ascii=False)[:200]}",
            f"查询改写: {json.dumps(full.get('rewrite', {}), ensure_ascii=False)[:200]}",
            f"召回: {json.dumps(full.get('recall', []), ensure_ascii=False)[:400]}",
            f"Rerank: {json.dumps(full.get('rerank', []), ensure_ascii=False)[:300]}",
        ]
        return "\n".join(parts)

    def _build_knowledge_tab(self) -> None:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        bar = QHBoxLayout()
        add_btn = PushButton("新增草稿")
        add_btn.clicked.connect(self._kb_add_draft)
        seed_btn = PushButton("从知识库同步版本")
        seed_btn.clicked.connect(self._seed_knowledge_revisions)
        pub_btn = PushButton("发布选中")
        pub_btn.clicked.connect(lambda: self._kb_action("published"))
        off_btn = PushButton("下线选中")
        off_btn.clicked.connect(lambda: self._kb_action("offline"))
        rollback_btn = PushButton("版本回滚")
        rollback_btn.clicked.connect(self._kb_rollback)
        bar.addWidget(add_btn)
        bar.addWidget(seed_btn)
        bar.addWidget(pub_btn)
        bar.addWidget(off_btn)
        bar.addWidget(rollback_btn)
        bar.addStretch()
        v.addLayout(bar)

        self.kb_panel = OpsTablePanel(
            "知识管理",
            ["id", "doc_id", "version", "title", "status", "operator", "created_at"],
            {
                "id": "ID",
                "doc_id": "文档ID",
                "version": "版本",
                "title": "标题",
                "status": "状态",
                "operator": "操作人",
                "created_at": "时间",
            },
        )
        self.kb_panel.set_refresh_callback(self._load_knowledge)
        v.addWidget(self.kb_panel, 1)
        self.tabs.addTab(wrap, "知识管理")

    def _build_low_conf_tab(self) -> None:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        bar = QHBoxLayout()
        approve_btn = PushButton("审核通过")
        approve_btn.clicked.connect(lambda: self._lc_review("approved"))
        reject_btn = PushButton("驳回")
        reject_btn.clicked.connect(lambda: self._lc_review("rejected"))
        bar.addWidget(approve_btn)
        bar.addWidget(reject_btn)
        bar.addStretch()
        v.addLayout(bar)

        self.lc_panel = OpsTablePanel(
            "低置信度问题池",
            ["id", "question", "repeat_count", "suggested_answer", "review_status", "channel", "updated_at"],
            {
                "id": "ID",
                "question": "未命中问题",
                "repeat_count": "重复次数",
                "suggested_answer": "建议答案",
                "review_status": "审核状态",
                "channel": "渠道",
                "updated_at": "更新时间",
            },
        )
        self.lc_panel.set_refresh_callback(self._load_low_confidence)
        v.addWidget(self.lc_panel, 1)
        self.tabs.addTab(wrap, "低置信度池")

    def _build_tickets_tab(self) -> None:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        bar = QHBoxLayout()
        assign_btn = PushButton("标记已接手")
        assign_btn.clicked.connect(self._ticket_assign)
        done_btn = PushButton("标记已完成")
        done_btn.clicked.connect(self._ticket_done)
        bar.addWidget(assign_btn)
        bar.addWidget(done_btn)
        bar.addStretch()
        v.addLayout(bar)

        self.ticket_panel = OpsTablePanel(
            "工单队列",
            ["id", "title", "source", "status", "assignee", "result", "session_key", "updated_at"],
            {
                "id": "ID",
                "title": "标题",
                "source": "来源",
                "status": "状态",
                "assignee": "接手人",
                "result": "处理结果",
                "session_key": "会话键",
                "updated_at": "更新时间",
            },
        )
        self.ticket_panel.set_refresh_callback(self._load_tickets)
        v.addWidget(self.ticket_panel, 1)
        self.tabs.addTab(wrap, "工单队列")

    def _build_eval_tab(self) -> None:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        bar = QHBoxLayout()
        demo_btn = PushButton("导入演示评测批次")
        demo_btn.clicked.connect(self._seed_demo_eval)
        bar.addWidget(demo_btn)
        bar.addStretch()
        v.addLayout(bar)

        self.eval_run_panel = OpsTablePanel(
            "评测中心 · 测试集/回归",
            ["id", "name", "test_set_name", "model_version", "pass_rate", "failed_count", "total_count", "created_at"],
            {
                "id": "ID",
                "name": "批次",
                "test_set_name": "测试集",
                "model_version": "模型版本",
                "pass_rate": "通过率",
                "failed_count": "失败数",
                "total_count": "总数",
                "created_at": "时间",
            },
        )
        self.eval_run_panel.set_refresh_callback(self._load_eval)
        self.eval_sample_panel = OpsTablePanel(
            "失败样本",
            ["id", "run_id", "question", "expected", "actual", "passed", "note"],
            {
                "id": "ID",
                "run_id": "批次",
                "question": "问题",
                "expected": "期望",
                "actual": "实际",
                "passed": "通过",
                "note": "备注",
            },
        )
        self.eval_run_panel.table.clicked.connect(self._load_eval_samples_for_run)
        v.addWidget(self.eval_run_panel, 2)
        v.addWidget(self.eval_sample_panel, 1)
        self.tabs.addTab(wrap, "评测中心")

    def _build_cost_tab(self) -> None:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        self.cost_summary_label = CaptionLabel("")
        self.cost_summary_label.setWordWrap(True)
        v.addWidget(self.cost_summary_label)

        self.cost_panel = OpsTablePanel(
            "成本明细",
            [
                "session_key",
                "model_name",
                "call_count",
                "prompt_tokens",
                "completion_tokens",
                "cache_hit",
                "cost_usd",
                "created_at",
            ],
            {
                "session_key": "会话",
                "model_name": "模型",
                "call_count": "调用次数",
                "prompt_tokens": "Prompt Token",
                "completion_tokens": "Completion Token",
                "cache_hit": "缓存命中",
                "cost_usd": "成本(USD)",
                "created_at": "时间",
            },
        )
        self.cost_panel.set_refresh_callback(self._load_cost)
        v.addWidget(self.cost_panel, 1)
        self.tabs.addTab(wrap, "成本看板")

    def _build_security_tab(self) -> None:
        self.sec_panel = OpsTablePanel(
            "安全审计",
            ["id", "event_type", "detail", "user_label", "severity", "created_at"],
            {
                "id": "ID",
                "event_type": "类型",
                "detail": "详情",
                "user_label": "用户",
                "severity": "级别",
                "created_at": "时间",
            },
        )
        self.sec_panel.set_refresh_callback(self._load_security)
        self.sec_panel.set_detail_formatter(lambda r: str(r.get("detail", ""))[:800])
        self.tabs.addTab(self.sec_panel, "安全审计")

    def refresh_all(self) -> None:
        self._repo.sync_sessions_from_chat()
        self._load_sessions()
        self._load_traces()
        self._load_knowledge()
        self._load_low_confidence()
        self._load_tickets()
        self._load_eval()
        self._load_cost()
        self._load_security()

    def _load_sessions(self) -> None:
        self.sessions_panel.set_rows(self._repo.list_sessions())

    def _load_traces(self) -> None:
        self._trace_cache = self._repo.list_traces()
        self.trace_panel.set_rows(self._trace_cache)

    def _load_knowledge(self) -> None:
        self.kb_panel.set_rows(self._repo.list_knowledge_revisions())

    def _load_low_confidence(self) -> None:
        self.lc_panel.set_rows(self._repo.list_low_confidence())

    def _load_tickets(self) -> None:
        self.ticket_panel.set_rows(self._repo.list_tickets())

    def _load_eval(self) -> None:
        self.eval_run_panel.set_rows(self._repo.list_eval_runs())

    def _load_eval_samples_for_run(self) -> None:
        row = self.eval_run_panel.selected_row()
        if not row:
            return
        self.eval_sample_panel.set_rows(self._repo.list_eval_samples(int(row["id"])))

    def _load_cost(self) -> None:
        s = self._repo.cost_summary()
        self.cost_summary_label.setText(
            f"模型调用 {s.get('total_calls', 0)} 次 | "
            f"Token {s.get('total_tokens', 0)} (P{s.get('prompt_tokens', 0)}+C{s.get('completion_tokens', 0)}) | "
            f"缓存命中率 {s.get('cache_hit_rate', 0)}% | "
            f"总成本 ${s.get('total_cost_usd', 0)} | "
            f"单会话成本 ${s.get('cost_per_session_usd', 0)}"
        )
        self.cost_panel.set_rows(self._repo.list_cost_logs())

    def _load_security(self) -> None:
        self.sec_panel.set_rows(self._repo.list_security_audits())

    def _kb_add_draft(self) -> None:
        from PyQt6.QtWidgets import QInputDialog, QTextEdit, QDialog, QVBoxLayout

        title, ok1 = QInputDialog.getText(self, "新增知识", "标题：")
        if not ok1 or not title.strip():
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("知识正文")
        dlg.resize(520, 360)
        lay = QVBoxLayout(dlg)
        edit = QTextEdit()
        lay.addWidget(edit)
        from qfluentwidgets import PrimaryPushButton

        btn = PrimaryPushButton("保存为草稿")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        content = edit.toPlainText().strip()
        if not content:
            return
        import uuid

        doc_id = f"kb_{uuid.uuid4().hex[:10]}"
        self._repo.add_knowledge_revision(
            doc_id, title.strip(), content, status="draft", operator="ops_ui"
        )
        QMessageBox.information(self, "已保存", "草稿已写入版本表，审核后可点「发布选中」上线")
        self._load_knowledge()

    def _seed_knowledge_revisions(self) -> None:
        try:
            from Agent.CustomerAgent.agent_knowledge import knowledge_manager

            docs = knowledge_manager.get_all_documents()
            n = 0
            for d in docs:
                ok = self._repo.add_knowledge_revision(
                    str(d.get("id", "")),
                    str(d.get("title", d.get("filename", "未命名"))),
                    str(d.get("content", ""))[:8000],
                    status="published",
                    operator="sync",
                    note="从当前知识库同步",
                )
                if ok:
                    n += 1
            QMessageBox.information(self, "同步完成", f"已写入 {n} 条知识版本记录")
            self._load_knowledge()
        except Exception as e:
            QMessageBox.warning(self, "同步失败", str(e))

    def _kb_action(self, status: str) -> None:
        row = self.kb_panel.selected_row()
        if not row:
            return
        self._repo.update_knowledge_status(int(row["id"]), status)
        self._load_knowledge()

    def _kb_rollback(self) -> None:
        row = self.kb_panel.selected_row()
        if not row:
            return
        self._repo.rollback_knowledge(int(row["id"]))
        self._load_knowledge()

    def _lc_review(self, status: str) -> None:
        row = self.lc_panel.selected_row()
        if not row:
            return
        self._repo.update_low_confidence_status(int(row["id"]), status)
        self._load_low_confidence()

    def _ticket_assign(self) -> None:
        row = self.ticket_panel.selected_row()
        if not row:
            return
        name, ok = QInputDialog.getText(self, "接手人", "请输入客服名称：")
        if ok and name:
            self._repo.update_ticket(int(row["id"]), status="assigned", assignee=name.strip())

        self._load_tickets()

    def _ticket_done(self) -> None:
        row = self.ticket_panel.selected_row()
        if not row:
            return
        result, ok = QInputDialog.getText(self, "处理结果", "请输入处理结果：")
        if ok:
            self._repo.update_ticket(
                int(row["id"]),
                status="done",
                result=(result or "").strip() or "已处理",
            )
        self._load_tickets()

    def _seed_demo_eval(self) -> None:
        run_id = self._repo.add_eval_run(
            "回归演示",
            "美甲灯FAQ",
            "v1",
            0.85,
            2,
            20,
        )
        if not run_id:
            return
        samples = [
            ("功率多少", "24W/48W", "72W", False),
            ("有没有白色", "以知识库为准", "只有黑色", False),
            ("发货多久", "24小时内", "24小时内", True),
        ]
        for q, exp, act, passed in samples:
            self._repo.add_eval_sample(
                run_id, q, exp, act, passed, note="" if passed else "需核对知识库"
            )
        self._load_eval()
        self.eval_sample_panel.set_rows(self._repo.list_eval_samples(run_id))
