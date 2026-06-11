# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""Pydantic 配置模型、默认值与校验（与 config.Config 运行时分离）。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.models.openai import OpenAILike
from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.logger_loguru import get_logger


class ModelType(str, Enum):
    """模型类型枚举"""
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    KIMI = "kimi"
    CLAUDE = "claude"

class EmbedderConfig(OpenAIEmbedder):
    """嵌入器配置模型"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    pass
class LLMConfig(OpenAILike):
    """LLM配置模型"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    pass

class KnowledgeConfig(BaseModel):
    """知识库配置模型"""
    contents_db_path: str = Field(default="", description="内容数据库路径")
    vector_db_path: str = Field(default="", description="向量数据库路径")
    goods_sync_ocr_enabled: bool = Field(
        default=True,
        description="同步商品到知识库时是否 OCR 主图/详情图",
    )
    goods_sync_ocr_max_main_images: int = Field(default=3, description="OCR 主图张数上限")
    goods_sync_ocr_max_detail_images: int = Field(default=6, description="OCR 详情图张数上限")
    goods_sync_ocr_max_lines_per_image: int = Field(default=40, description="单张图 OCR 行数上限")
    goods_sync_ocr_download_timeout_sec: int = Field(default=15, description="下载商品图超时秒")
    goods_sync_ocr_summarize_with_llm: bool = Field(
        default=False,
        description="OCR 后是否用 LLM 整理参数摘要（默认关，避免改写价格）",
    )
    goods_sync_ocr_summarize_max_tokens: int = Field(default=800, description="OCR 摘要 LLM max_tokens")
    goods_sync_ocr_include_raw: bool = Field(default=True, description="是否保留过滤后的 OCR 原文")
    goods_sync_ocr_min_rec_score: float = Field(default=0.45, description="OCR 识别置信度下限")
    goods_sync_ocr_det_limit_side_len: int = Field(default=1920, description="OCR 检测边长")
    goods_sync_ocr_cpu_threads: int = Field(
        default=2,
        description="OCR/Paddle 占用 CPU 线程上限，避免界面卡死",
    )
    goods_sync_use_browser: bool = Field(
        default=True,
        description="同步商品时用 Playwright 走商家后台页面上下文（绕过 goodsList 54001 风控）",
    )
    goods_sync_browser_headless: bool = Field(
        default=True,
        description="商品同步 Playwright 是否无头运行",
    )

class BusinessHoursConfig(BaseModel):
    """营业时间配置模型"""
    start: str = Field(default="08:00", description="开始时间")
    end: str = Field(default="23:00", description="结束时间")

    @field_validator('start', 'end')
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        """验证时间格式 HH:MM"""
        try:
            datetime.strptime(v, '%H:%M')
            return v
        except ValueError:
            raise ValueError('时间格式必须为HH:MM，例如08:00')

class PromptConfig(BaseModel):
    """提示词配置模型"""
    description: str = Field(default="", description="角色描述")
    instructions: list[str] = Field(default=[], description="指令")
    additional_context: str = Field(default="", description="额外提示词")


class PinduoduoOpenConfig(BaseModel):
    """拼多多开放平台配置"""
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(default=True, description="是否启用开放平台")
    client_id: str = Field(default="", description="应用 client_id")
    client_secret: str = Field(default="", description="应用 client_secret")
    access_token: str = Field(default="", description="店铺 access_token")


class ChatConfig(BaseModel):
    """
    chat 段配置：数值/开关字段强类型校验；文案类键允许 extra（兼容长提示语）。
    """
    model_config = ConfigDict(extra="allow")
    manual_mode_send_notice: bool = False
    buyer_burst_merge_gap_sec: float = 45
    buyer_burst_merge_max_parts: int = 40
    message_consumer_max_concurrent: int = 16
    ws_message_max_concurrent: int = 16
    ai_watchdog_enabled: bool = True
    ai_watchdog_escalate_sec: int = 150
    ai_watchdog_retry_sec: Optional[int] = None
    image_video_forward_human: bool = True
    image_video_buyer_notice: str = ""
    after_sales_apply_return_refund_hours: Optional[float] = None
    queue_degrade_enabled: bool = True
    queue_degrade_threshold_sec: float = 120
    queue_degrade_emit_assist: bool = True
    queue_p95_cap_sec: float = 30
    queue_stats_window_size: int = 100
    queue_stats_recent_size: int = 20
    queue_prior_duration_sec: float = 8
    queue_stats_min_samples: int = 10
    llm_sync_retry_enabled: bool = True
    llm_sync_retry_delay_sec: float = 1.5
    llm_arun_timeout_sec: float = 120.0
    agno_tool_timeout_sec: float = 90.0
    turn_abort_enabled: bool = True
    turn_abort_supersede_on_new_inbound: bool = True
    turn_abort_registry_max_sessions: int = 5000
    turn_abort_loop_stop_grace_ms: int = 500
    turn_abort_arun_backlog_watch_enabled: bool = True
    turn_abort_arun_backlog_warn_sec: float = 30.0
    turn_abort_arun_backlog_poll_sec: float = 5.0
    after_sales_apply_enabled: bool = True
    session_idle_resolve_enabled: bool = True
    session_idle_resolve_minutes: int = 5
    session_idle_resolve_check_interval_sec: int = 60
    address_change_enabled: bool = True
    human_transfer_semantic_enabled: bool = True
    human_transfer_notice: str = "稍等下 这边上报一下呢亲亲"
    # 转接：售后专用子账号 seller_user_id 列表，AI/规则转人工时优先转给这些号
    preferred_transfer_seller_user_ids: List[str] = Field(default_factory=list)
    inbound_transfer_system_notice: str = (
        "[会话已转接] 售前/其他客服已将买家转给您，请关注后续消息"
    )
    inbound_transfer_buyer_notice: str = ""
    inbound_transfer_default_manual: bool = False
    inbound_transfer_force_takeover: bool = True
    inbound_transfer_takeover_ai_mode: bool = True
    inbound_transfer_enqueue_unreplied: bool = True
    inbound_transfer_gate_until_received: bool = True
    weak_supervision_enabled: bool = False
    inbound_transfer_stage: str = "after_sales"
    ai_allow_after_sales_stage: bool = True
    transfer_auto_rose_enabled: bool = False
    buyer_emotion_alert_enabled: bool = True
    buyer_emotion_escalate_threshold: int = 2
    ai_pm_escalation_enabled: bool = True
    ai_max_tokens: int = 500
    ai_temperature: float = 0.5
    ai_fallback_to_human_on_unknown: bool = False
    ai_unknown_fallback_notice: str = (
        "亲，我暂时还不清楚，您可以描述得更详细些，或者我帮您转人工客服？"
    )
    queue_force_enqueue: bool = False
    ui_page_size: int = 50
    message_write_batch_enabled: bool = True
    message_write_batch_interval_sec: float = 0.5
    message_write_batch_size: int = 10
    mms_session_sync_enabled: bool = False
    mms_session_sync_interval_ms: int = 15000
    mms_session_sync_page_size: int = 50
    mms_session_sync_browser_headless: bool = True
    mms_session_sync_enqueue_new: bool = False
    ws_reconnect_reconcile_enabled: bool = True
    ws_reconnect_enqueue_unreplied: bool = True
    ws_reconnect_reconcile_cooldown_sec: int = 120
    knowledge_retrieval_timeout_sec: float = 5.0
    unhandled_fallback_enabled: bool = True
    unhandled_fallback_notice: str = (
        "亲，消息已收到，客服稍后会回复您；如需人工请回复「人工」。"
    )
    catchall_comfort_enabled: bool = True
    catchall_comfort_notice: str = (
        "亲，消息已收到，客服稍后会回复您；如需人工请回复「人工」。"
    )
    ai_mode_check_retries: int = 3
    ai_mode_check_retry_delay_sec: float = 0.12
    ai_mode_check_fail_open: bool = False
    ws_auto_reconnect_enabled: bool = True
    ws_reconnect_delay_sec: float = 5.0
    ws_reconnect_max_attempts: int = 0


class RetentionConfig(BaseModel):
    """数据保留与清理"""
    chat_history_days: int = 30
    audit_log_days: int = 90
    temp_files_days: int = 7
    vacuum_interval_days: int = 30
    temp_dir: str = "temp"
    lifecycle_hour: int = 3
    lifecycle_minute: int = 0
    vector_days: int = 0
    stage_idle_timeout_sec: int = 1800


class ProductionConfig(BaseModel):
    """生产运维：健康检查、备份"""
    health_enabled: bool = True
    health_host: str = "127.0.0.1"
    health_port: int = 8080
    health_token: str = ""
    backup_enabled: bool = True
    backup_hour: int = 2
    backup_minute: int = 0
    backup_retention_days: int = 7
    backup_dir: str = "backup"
    db_path: str = ""
    log_level: str = "INFO"


class ConfigModel(BaseModel):
    """配置模型"""
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    business_hours: BusinessHoursConfig = Field(
        default_factory=BusinessHoursConfig,
        description="营业时间配置"
    )
    llm: LLMConfig = Field(
        default_factory=LLMConfig,
        description="LLM配置"
    )
    embedder: EmbedderConfig = Field(
        default_factory=EmbedderConfig,
        description="嵌入器配置"
    )
    knowledge_base: KnowledgeConfig = Field(
        default_factory=KnowledgeConfig,
        description="知识库配置"
    )
    prompt: PromptConfig = Field(
        default_factory=PromptConfig,
        description="提示词配置"
    )
    chat: ChatConfig = Field(
        default_factory=ChatConfig,
        description="会话/处理器/chat 业务配置",
    )
    pinduoduo_open: PinduoduoOpenConfig = Field(
        default_factory=PinduoduoOpenConfig,
        description="拼多多开放平台",
    )
    db_path: str = Field(default="", description="数据库路径")
    retention: RetentionConfig = Field(
        default_factory=RetentionConfig,
        description="数据保留策略",
    )
    production: ProductionConfig = Field(
        default_factory=ProductionConfig,
        description="生产运维",
    )


def _known_section_keys(section: str, base: Dict[str, Any]) -> set:
    """合并 config_base 与 Pydantic 模型字段，减少误报未知键。"""
    known = set((base.get(section) or {}).keys())
    model_map = {
        "chat": ChatConfig,
        "pinduoduo_open": PinduoduoOpenConfig,
    }
    model_cls = model_map.get(section)
    if model_cls is not None:
        known |= set(model_cls.model_fields.keys())
    return known


def warn_unknown_config_keys(
    config_data: Dict[str, Any],
    defaults: Optional[Dict[str, Any]] = None,
) -> None:
    """对 chat / pinduoduo_open 中未知键打 warning，帮助发现拼写错误。"""
    base = defaults if defaults is not None else config_base
    log = get_logger("config")
    for section in ("chat", "pinduoduo_open"):
        block = config_data.get(section)
        if not isinstance(block, dict):
            continue
        unknown = set(block.keys()) - _known_section_keys(section, base)
        if unknown:
            log.warning(
                "config.json 的 [{}] 含未知键（可能是拼写错误）: {}",
                section,
                sorted(unknown),
            )



# 默认配置基础数据
config_base = {
    "business_hours": {
        "start": "08:00",
        "end": "23:00"
    },
    "llm": {
        "model_name": "",
        "api_key": "",
        "api_base": "",
        "max_tokens": 256,
        "temperature": 0.5,
        "transport_retry_max": 1,
        "transport_retry_backoff_sec": 0.45,
        "request_timeout_sec": 35,
    },
    "embedder": {
        "model_name": "",
        "api_key": "",
        "api_base": ""
    },
    "knowledge_base": {
        "contents_db_path": "",
        "vector_db_path": "",
        "goods_sync_ocr_enabled": True,
        "goods_sync_ocr_max_main_images": 3,
        "goods_sync_ocr_max_detail_images": 6,
        "goods_sync_ocr_max_lines_per_image": 40,
        "goods_sync_ocr_download_timeout_sec": 15,
        "goods_sync_ocr_summarize_with_llm": False,
        "goods_sync_ocr_summarize_max_tokens": 800,
        "goods_sync_ocr_include_raw": True,
        "goods_sync_ocr_min_rec_score": 0.45,
        "goods_sync_ocr_det_limit_side_len": 1920,
        "goods_sync_ocr_cpu_threads": 2,
        "goods_sync_use_browser": True,
        "goods_sync_browser_headless": True,
    },
    "prompt": {
        "append_natural_style": True,
    },
    "chat": {
        "manual_mode_send_notice": False,
        "buyer_burst_merge_gap_sec": 45,
        "buyer_burst_merge_max_parts": 40,
        # LLM 压测约 30 并发无限流；应用侧留余量，默认 16 路
        "message_consumer_max_concurrent": 16,
        "ws_message_max_concurrent": 16,
        "ai_watchdog_enabled": True,
        "ai_watchdog_escalate_sec": 150,
        "ai_watchdog_retry_sec": None,
        "ai_watchdog_escalate_notice": "不好意思亲亲，让你久等了",
        "image_video_forward_human": True,
        "image_video_buyer_notice": "",
        "after_sales_apply_return_refund_hours": None,
        "queue_degrade_enabled": True,
        "queue_degrade_threshold_sec": 120,
        "queue_degrade_notice": (
            "感谢亲亲选择我们的产品，当前咨询较多请耐心等待；如需人工请直接回复「人工」。"
        ),
        "queue_degrade_emit_assist": True,
        "queue_p95_cap_sec": 30,
        "queue_stats_window_size": 100,
        "queue_stats_recent_size": 20,
        "queue_prior_duration_sec": 8,
        "queue_stats_min_samples": 10,
        "queue_force_enqueue": False,
        "ui_page_size": 50,
        "message_write_batch_enabled": True,
        "message_write_batch_interval_sec": 0.5,
        "message_write_batch_size": 10,
        "mms_session_sync_enabled": False,
        "mms_session_sync_interval_ms": 15000,
        "mms_session_sync_page_size": 50,
        "mms_session_sync_browser_headless": True,
        "mms_session_sync_enqueue_new": False,
        "ws_reconnect_reconcile_enabled": True,
        "ws_reconnect_enqueue_unreplied": True,
        "ws_reconnect_reconcile_cooldown_sec": 120,
        "llm_sync_retry_enabled": True,
        "llm_sync_retry_delay_sec": 1.5,
        "llm_arun_timeout_sec": 120,
        "agno_tool_timeout_sec": 90,
        "turn_abort_enabled": True,
        "turn_abort_supersede_on_new_inbound": True,
        "turn_abort_registry_max_sessions": 5000,
        "turn_abort_loop_stop_grace_ms": 500,
        "turn_abort_arun_backlog_watch_enabled": True,
        "turn_abort_arun_backlog_warn_sec": 30,
        "turn_abort_arun_backlog_poll_sec": 5,
        "after_sales_apply_enabled": True,
        "after_sales_apply_return_refund_days": 7,
        "after_sales_apply_card_valid_hours": 48,
        "after_sales_apply_send_card_valid_time": True,
        "after_sales_apply_exchange_max_days": 90,
        "after_sales_apply_after_sales_type": 3,
        "after_sales_apply_question_type": 1,
        "after_sales_apply_question_type_unshipped": 0,
        "after_sales_apply_refund_amount_fen": 0,
        "after_sales_apply_card_message": None,
        "after_sales_apply_follow_text": (
            "亲，请点击上方卡片，在弹出的页面中【手动填写退款理由】，"
            "点击【提交】后我们才能收到申请，否则卡片会因超时而失效哦。"
        ),
        "after_sales_apply_cooldown_sec": 300,
        "after_sales_apply_order_cache_ttl_sec": 3600,
        "session_idle_resolve_enabled": True,
        "session_idle_resolve_minutes": 5,
        "session_idle_resolve_check_interval_sec": 60,
        "preferred_transfer_seller_user_ids": [],
        "inbound_transfer_system_notice": (
            "[会话已转接] 售前/其他客服已将买家转给您，请关注后续消息"
        ),
        "inbound_transfer_buyer_notice": "",
        "inbound_transfer_default_manual": False,
        "inbound_transfer_force_takeover": True,
        "inbound_transfer_takeover_ai_mode": True,
        "inbound_transfer_enqueue_unreplied": True,
        "inbound_transfer_gate_until_received": True,
        "weak_supervision_enabled": False,
        "inbound_transfer_stage": "after_sales",
        "ai_allow_after_sales_stage": True,
        "transfer_auto_rose_enabled": False,
        "after_sales_apply_check_orders_by_uid": True,
        "after_sales_apply_no_orders_notice": (
            "亲，暂未查到您在本店的订单记录，请确认是否用下单账号咨询，"
            "或从订单页进入客服后再申请售后~"
        ),
        "after_sales_apply_order_not_eligible_notice": (
            "亲，查到您的订单已完成退款或正在售后处理中，暂无法再次发送申请卡片；"
            "如有疑问请回复「人工」为您处理~"
        ),
        "after_sales_apply_orders_query_fail_notice": (
            "亲，订单查询暂时失败，请稍后再试或回复「人工」协助处理~"
        ),
        "after_sales_apply_need_order_notice": (
            "亲，麻烦发一下订单号（订单详情可复制，格式类似 250105-xxxxxxxx），"
            "或从订单页进聊天发订单卡片，我这边给您发退换货申请~"
        ),
        "after_sales_apply_fail_notice": (
            "亲，退换货申请卡片发送未成功，请您在订单里点击「申请售后」，或回复「人工」为您处理~"
        ),
        "after_sales_apply_quota_notice": (
            "亲，该订单今日代申请售后次数已满，请您在订单详情页自行申请售后，"
            "或回复「人工」为您处理~"
        ),
        "after_sales_apply_fail_cooldown_sec": 300,
        "after_sales_apply_quota_cooldown_sec": 86400,
        "after_sales_apply_card_expired_notice": (
            "亲，刚才的快捷退款卡片已失效，请您打开订单详情点击「申请售后」自行提交，"
            "或回复「人工」为您处理~"
        ),
        "after_sales_apply_merchant_window_expired_notice": (
            "亲，该订单商家代申请退款的有效期已过或次数已满，无法再次发送快捷退款卡。"
            "请您在订单详情点击「申请售后」，或回复「人工」为您处理~"
        ),
        "after_sales_apply_pending_notice": (
            "亲，已经为您提交了退款申请，请耐心等待。"
        ),
        "after_sales_apply_record_expired_notice": (
            "亲，该订单的快捷退款申请已超时。请到拼多多APP订单详情页点击「申请售后」"
            "手动操作，或回复「人工」。"
        ),
        "after_sales_apply_already_in_progress_notice": (
            "亲，看到您这笔订单已在售后处理中，请在订单详情查看进度；有疑问可回复「人工」。"
        ),
        "after_sales_apply_amount_unknown_notice": (
            "亲，暂未获取到订单金额，请您在订单详情页直接申请售后，或回复「人工」协助处理~"
        ),
        "after_sales_apply_refund_only_human_notice": (
            "亲，仅退款需要人工为您核实处理，这边马上为您转接人工客服~"
        ),
        "after_sales_apply_unknown_order_time_notice": (
            "亲，暂未查到该订单的购买时间，为您转接人工客服协助处理退换货~"
        ),
        "after_sales_apply_over_90_human_notice": (
            "亲，您的订单已超过可在线申请售后的期限，为您转接人工客服进一步处理~"
        ),
        "after_sales_apply_unshipped_exchange_notice": (
            "亲，您的订单尚未发货，换货需人工为您处理，这边为您转接人工客服~"
        ),
        "after_sales_apply_mid_window_human_notice": (
            "亲，您的订单已超过 7 天无理由退货退款期限，退货退款需人工为您办理，"
            "这边为您转接人工客服~"
        ),
        "address_change_enabled": True,
        "address_change_mms_url": "",
        "address_change_shipped_first_text": (
            "亲，您的订单已发货，平台可能不允许修改地址。若您确认仍要修改，请点击【确认改址】按钮（操作后无法撤销），并告知新的收货地址。"
        ),
        "address_change_ask_full_address_text": (
            "亲，请提供完整的收货地址（省市区街道门牌号+收件人+电话），我会帮您尝试修改。"
        ),
        "address_change_multi_order_text": (
            "亲，您在我店有多个订单，请告知需要修改哪个订单的地址？提供订单号或商品名称即可。"
        ),
        "address_change_ask_complete_text": (
            "亲，您提供的地址好像不完整（缺少省/市/区），请重新提供完整地址，以免发错哦。"
        ),
        "address_change_success_text": (
            "亲，已为您提交地址修改申请，请留意物流更新。如有问题可随时联系我们。"
        ),
        "address_change_fail_text": (
            "亲，很抱歉，平台当前不允许修改该订单的地址。建议您联系快递公司或收货人主动沟通，也可回复「人工」由客服协助。"
        ),
        "address_change_shipped_confirm_hint": (
            "该订单已发货，平台可能不允许改址。操作后无法撤销，是否仍尝试修改？"
        ),
        "address_change_no_orders_text": (
            "亲，暂未查到与您账号关联的本店订单，请确认是否用下单账号咨询，或提供订单号~"
        ),
        "address_change_order_not_found_text": (
            "亲，未找到您提供的订单号，请核对后重新发送~"
        ),
        "address_change_order_not_eligible_text": (
            "亲，该订单当前状态暂不支持在线改地址，请回复「人工」为您处理~"
        ),
        "human_transfer_semantic_enabled": True,
        "human_transfer_notice": "稍等下 这边上报一下呢亲亲",
        "buyer_emotion_alert_enabled": True,
        "buyer_emotion_escalate_threshold": 2,
        "ai_pm_escalation_enabled": True,
        "ai_max_tokens": 500,
        "ai_temperature": 0.5,
        "ai_fallback_to_human_on_unknown": False,
        "ai_unknown_fallback_notice": (
            "亲，我暂时还不清楚，您可以描述得更详细些，或者我帮您转人工客服？"
        ),
        "knowledge_retrieval_timeout_sec": 5.0,
        "intent_reset_enabled": True,
        "intent_reset_stages": [
            "address_change",
            "logistics",
            "after_sales",
            "await_confirm",
        ],
        "unhandled_fallback_enabled": True,
        "unhandled_fallback_notice": (
            "亲，消息已收到，客服稍后会回复您；如需人工请回复「人工」。"
        ),
        "catchall_comfort_enabled": True,
        "catchall_comfort_notice": (
            "亲，消息已收到，客服稍后会回复您；如需人工请回复「人工」。"
        ),
        "ai_mode_check_retries": 3,
        "ai_mode_check_retry_delay_sec": 0.12,
        "ai_mode_check_fail_open": False,
        "ws_auto_reconnect_enabled": True,
        "ws_reconnect_delay_sec": 5.0,
        "ws_reconnect_max_attempts": 0,
    },
    "pinduoduo_open": {
        "enabled": True,
        "client_id": "",
        "client_secret": "",
        "access_token": ""
    },
    "db_path": "data/customer_agent.db",
    "retention": {
        "chat_history_days": 30,
        "audit_log_days": 90,
        "temp_files_days": 7,
        "vacuum_interval_days": 30,
        "temp_dir": "temp",
        "lifecycle_hour": 3,
        "lifecycle_minute": 0,
        "vector_days": 0,
        "stage_idle_timeout_sec": 1800,
    },
    "production": {
        "health_enabled": True,
        "health_host": "127.0.0.1",
        "health_port": 8080,
        "health_token": "",
        "backup_enabled": True,
        "backup_hour": 2,
        "backup_minute": 0,
        "backup_retention_days": 7,
        "backup_dir": "backup",
        "db_path": "",
        "log_level": "INFO",
    },
}


def merge_missing_config_defaults(
    user: Dict[str, Any], defaults: Dict[str, Any]
) -> tuple[Dict[str, Any], bool]:
    """
    将 defaults 中缺失的键递归补入 user，不覆盖已有键值。
    用于旧版 config.json 自动出现新版占位键（如 pinduoduo_open）。
    """
    changed = False
    out = deepcopy(user)
    for key, default_val in defaults.items():
        if key not in out:
            out[key] = deepcopy(default_val)
            changed = True
        elif isinstance(default_val, dict) and isinstance(out.get(key), dict):
            sub_merged, sub_changed = merge_missing_config_defaults(out[key], default_val)
            out[key] = sub_merged
            if sub_changed:
                changed = True
    return out, changed
