# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
from agno import tools
from Agent.bot import Bot
from agno.agent import Agent, RunOutput

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from agno.models.openai import OpenAILike
from agno.db.sqlite import SqliteDb
from Agent.CustomerAgent.agent_knowledge import (
    KnowledgeManager,
    get_knowledge_manager,
    reset_platform_shop_context,
    set_platform_shop_context,
)
from Agent.CustomerAgent.tools.move_conversation import transfer_conversation
from Agent.CustomerAgent.tools.get_product_list import get_shop_products, get_product_skus
from Agent.CustomerAgent.tools.send_goods_link import send_goods_link
from config import get_config
import asyncio
import concurrent.futures
from contextlib import suppress
from contextvars import ContextVar, Token
from functools import partial
from typing import Any, Dict, List, Optional
from utils.logger_loguru import get_logger
from pydantic import BaseModel, Field

from core.turn_abort import (
    TurnAborted,
    get_current_turn_abort,
    reset_current_turn_abort,
    set_current_turn_abort,
    turn_abort_registry,
)
from core.turn_abort_loop import run_coroutine_on_private_loop_abortable

# 与 config 里长「角色+示例」并存时，用于压过「每条都自我介绍」的仿写倾向
_NATURAL_STYLE_INSTRUCTIONS: List[str] = [
    "像真实店主用手机回微信：口语、短句，少用公文和客服报告腔。",
    "同一会话里：只在整条对话的首次回复可简短问候一次；从第二条买家消息起，禁止再自我介绍、报花名工号、说「欢迎光临」「我是xx客服」「亲您好呀开场」等任何开场套话，直接接问题回答。",
    "对方追问、补一句话时：不要用新的一轮欢迎语或重复你是谁；接过话头就说重点。",
    "不要先复述用户的问题再回答（少用「关于您说的xxx」）；非必要不列举 markdown、少用 emoji。",
    "不重复上一轮已经讲过的信息；能一句说清楚就不用两三句。",
    "单条回复务必短：总字数控制在约 120 字以内（手机聊天气泡约 6～8 行）；能用两三句说完就不要长段落，禁止长篇营销软文或把全店 SKU 铺开。",
    "推荐款式时最多点名 1～2 个价位/系列，少堆叠形容词；不要假想买家这句里没有的词（对方没提的英文、缩写不要单独纠「是不是打错」），紧扣对方当前这句回应。",
    "买家可能把一句话拆成多条或单字连发；系统会把短时间内的连续买家消息合并成一句——请按合并后的整句理解，不要只盯最后一个字。",
    "电商平台对话里禁止「问老板」「找老板」「问店主」等表述——买家不知道指谁、也无法操作；无货/无链接/需核实时应说「帮您转接人工客服确认」「我们向店铺同事核实后回复您」等明确动作。",
]

_NATURAL_STYLE_CONTEXT = (
    "【最高优先级·回复习惯】忽略提示词里教你「每条欢迎、自我介绍」的示例话术——那是错误示范。"
    "真实场景要像熟人接力聊天：后续消息默认零寒暄，直奔答案。"
    "篇幅硬约束：单条输出宁可短一半也不要写长；买家连发多条时更要一句点破，不要铺陈。"
)

_knowledge_retrieval_enabled: ContextVar[bool] = ContextVar(
    "knowledge_retrieval_enabled", default=True
)

_RAG_MAX_DOCUMENTS = 3


def _llm_arun_timeout_sec() -> float:
    """LLM arun 硬超时，默认 120s（应小于 watchdog 默认 150s）。"""
    try:
        raw = get_config("chat.llm_arun_timeout_sec", 120)
        v = float(raw if raw is not None else 120)
        return max(10.0, min(v, 600.0))
    except (TypeError, ValueError):
        return 120.0


from core.arun_executor import ARUN_EXECUTOR as _ARUN_EXECUTOR


def _run_coroutine_on_private_loop(coro):
    """在独立 event loop 中执行 coroutine（供 asyncio.to_thread 调用，释放 WS loop）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()


def set_knowledge_retrieval_enabled(enabled: bool) -> Token:
    return _knowledge_retrieval_enabled.set(bool(enabled))


def reset_knowledge_retrieval_enabled(token: Token) -> None:
    _knowledge_retrieval_enabled.reset(token)


def is_knowledge_retrieval_enabled() -> bool:
    return _knowledge_retrieval_enabled.get()


_KNOWLEDGE_GROUNDING: List[str] = [
    "本店主营以知识库检索到的「美甲灯/光疗灯」及其中明确写明的配件为准；不得编造未在检索结果中出现的在售 SKU、库存、价格或规格。",
    "知识库里若只出现美甲步骤中的底胶/色胶/封层/光疗胶等通用概念，仅代表美甲流程说明，不等同于本店在售甲油胶商品；买家问「有没有美甲胶/甲油胶/胶类」时，若检索片段未列出可发货的胶类产品，应如实说明本店以美甲灯为主、胶类需确认或引导其选购灯适用类型，禁止用「都有」「有货」等空泛承诺。",
    "若用户问题与检索内容无关或检索为空：简短说明本店当前可查到的上架范围，并引导买家补充描述；"
    "不要编造商品信息，可说「我暂时还不清楚，您可以更详细描述，或者我帮您转人工客服」。",
    "若检索未覆盖买家问的商品（如打磨机、胶类等）：明确说明知识库/在售链接里暂未查到，"
    "引导买家补充需求或转人工；禁止使用「转人工客服」「问老板」「找老板」等含糊表述。",
    "不要引导买家「再发图」「发照片」来辨认商品：本链路中 AI 无法查看聊天图片；"
    "识图需求应引导买家转人工或补充文字描述。",
    "当买家询问商品相关信息（价格、规格、库存、款式、颜色等）时，必须优先使用 get_shop_products（实时列表含 SKU）或 get_product_skus(goods_id) 查询，再基于工具返回回答；无需先同步知识库。禁止凭空猜测或编造商品信息。",
    "如果知识库检索结果为空，但买家询问具体商品，应使用 get_shop_products 工具查询店铺在售商品，然后根据查询结果推荐合适的商品给买家。",
    "推荐商品时：优先从 get_shop_products 返回的商品列表中选择 1-2 款最匹配的，提供商品名称、价格、核心卖点；不要一次性推荐超过 2 款。",
    "当买家询问「有没有 XX 款」「有没有 XX 功能」「有什么颜色」「有哪些款式」时：先用 get_shop_products 查询商品列表，确认有货后再推荐；若无此商品，如实告知暂未查到并推荐相似款或引导转人工。",
    "【语言匹配】自动检测买家使用的语言（中文/英文/泰语/越南语等），并用相同语言回复；买家说中文就用中文回答，买家说英文就用英文回答，保持语言一致。",
    "【禁止话术】禁止频繁使用「产品经理」作为兜底；知识库未覆盖时使用「我暂时还不清楚，您可以更详细描述，或者我帮您转人工客服」。",
    "【禁止编造】严禁编造以下信息：商品颜色（如「只有黑色」「有白色」）、商品款式、库存状态、商品名称；如知识库和商品列表中都未找到，必须如实说明「暂未查到」并引导补充描述或转人工。",
    "【转人工】买家明确要求转人工时，或仅靠文字无法安全、准确处理时（过敏、红肿、身体不适、纠纷投诉、工商/平台介入、索赔/特殊退款、需查看聊天图片或订单后台、改址/改单已超出自动流程等），"
    "先一句简短安抚（如「我马上帮您转同事处理」），再调用 transfer_conversation 工具完成转接；禁止对医疗风险、赔偿金额等自行承诺或拖延不转。"
    "同一买家连续两轮仍属弱高风险（如过敏/投诉未缓解），第二轮起不再自行解答，直接调用 transfer_conversation。",
    "【三层记忆】输入中含【长期摘要】【任务状态】【短期记忆】：长期摘要用于更早事实；任务状态中的意图/槽位/待确认/流程节点必须遵守；短期记忆为最近几轮原文，指代词（这个/那款）优先对照短期与任务状态理解。",
]


def _customer_agno_knowledge_retriever(km: "KnowledgeManager"):
    """
    Agno 的 knowledge 传空 dict 时会被判定为「无向量库」，检索恒为 None。
    通过官方 knowledge_retriever 接入本地 NailLampKnowledgeManager.search_knowledge。
    店铺隔离依赖 async_reply 里 set_platform_shop_context（ContextVar）。
    """

    def _retriever(
        agent: Any,
        query: str,
        num_documents: Optional[int] = None,
        **kwargs: Any,
    ) -> Optional[List[Dict[str, Any]]]:
        log = get_logger("CustomerAgent")
        if not is_knowledge_retrieval_enabled():
            return None
        q = (query or "").strip()
        if not q:
            return None
        limit = _RAG_MAX_DOCUMENTS
        if num_documents is not None:
            try:
                n = int(num_documents)
                if n > 0:
                    limit = min(n, _RAG_MAX_DOCUMENTS)
            except (TypeError, ValueError):
                pass
        try:
            timeout_sec = 5.0
            try:
                from config import get_config

                timeout_sec = float(
                    get_config("chat.knowledge_retrieval_timeout_sec", 5) or 5
                )
            except (TypeError, ValueError):
                pass
            timeout_sec = max(0.5, min(timeout_sec, 30.0))

            async def _search_async() -> Any:
                return await asyncio.wait_for(
                    asyncio.to_thread(km.search_knowledge, q, top_k=limit),
                    timeout=timeout_sec,
                )

            def _run_search() -> Any:
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    return asyncio.run(_search_async())
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, _search_async()).result(
                        timeout=timeout_sec + 1.0
                    )

            if timeout_sec > 0:
                try:
                    hits = _run_search()
                except (asyncio.TimeoutError, TimeoutError):
                    log.warning(
                        "knowledge_retriever 超时 {:.1f}s，跳过 RAG: {}",
                        timeout_sec,
                        q[:80],
                    )
                    return None
            else:
                hits = km.search_knowledge(q, top_k=limit)
        except (ImportError, AttributeError, RuntimeError, TimeoutError, OSError) as e:
            log.warning(f"knowledge_retriever 检索失败: {e}")
            return None
        if not hits:
            try:
                from core.ops_telemetry import set_recall_results
                set_recall_results([])
            except ImportError:
                pass
            return None
        try:
            from core.ops_telemetry import set_recall_results
            set_recall_results(hits)
        except ImportError:
            pass
        out: List[Dict[str, Any]] = []
        for r in hits:
            if hasattr(r, "id"):
                meta = getattr(r, "metadata", None)
                out.append(
                    {
                        "id": str(r.id),
                        "content": str(r.data),
                        "metadata": dict(meta) if isinstance(meta, dict) else {},
                    }
                )
            elif isinstance(r, dict):
                out.append(r)
        return out if out else None

    return _retriever


def _agno_memory_scope(context: Context) -> tuple[str, str]:
    """
    Agno SqliteDb 中的会话隔离键：每个买家一条上下文，不与同店其他买家串台。
    返回 (session_id, user_id)，二者在本项目中一致，避免底层按 user_id 合并不同会话。
    """
    ch = str(context.channel_type.value if context.channel_type else "unknown")
    seller_uid = str(getattr(context.kwargs, "user_id", None) or "").strip()
    buyer_uid = str(getattr(context.kwargs, "from_uid", None) or "").strip()
    if buyer_uid:
        scope = f"{ch}:{seller_uid}:{buyer_uid}"
        return scope, scope
    # 无买家 UID 时（异常或测试），单独一桶，避免与真实买家混写
    fallback = f"{ch}:{seller_uid}:__no_buyer__"
    return fallback, fallback


class CustomerAgent(Bot):
    def __init__(self, knowledge_manager: 'KnowledgeManager' = None):
        super().__init__()
        # 从 DI 容器获取 KnowledgeManager（如果未传入）
        if knowledge_manager is None:
            from core.di_container import container
            try:
                knowledge_manager = container.get(KnowledgeManager)
            except ValueError:
                # 容器中未注册时直接创建
                knowledge_manager = get_knowledge_manager()
        self.knowledge_manager = knowledge_manager
        self._agent: Optional[Agent] = None  # 延迟初始化
        self.logger = get_logger("CustomerAgent")
        self._is_initialized = False
        self._arun_locks: Dict[int, asyncio.Lock] = {}

    def _arun_lock_for_current_loop(self) -> asyncio.Lock:
        """单例 Agent 按 event loop 串行 arun，避免多 Worker 并发 corrupt 内部状态。"""
        loop = asyncio.get_running_loop()
        key = id(loop)
        lock = self._arun_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._arun_locks[key] = lock
        return lock

    def _run_agent_arun_blocking(
        self,
        user_id: str,
        session_id: str,
        ar_input: str,
        dependencies: Dict[str, str],
        signal: Optional[Any] = None,
    ) -> RunOutput:
        """在 worker 线程的独立 event loop 中运行 Agno arun（含 sync tools）。"""
        abort_token = set_current_turn_abort(signal) if signal else None
        try:
            if signal and signal.is_aborted():
                raise TurnAborted(signal.reason(), signal.turn_id)

            async def _do() -> RunOutput:
                if signal and signal.is_aborted():
                    raise TurnAborted(signal.reason(), signal.turn_id)
                return await self._agent.arun(
                    user_id=user_id,
                    session_id=session_id,
                    input=ar_input,
                    dependencies=dependencies,
                )

            result = run_coroutine_on_private_loop_abortable(_do, signal)
            if signal and signal.is_aborted():
                turn_abort_registry.record_stale_dropped()
                raise TurnAborted(signal.reason(), signal.turn_id)
            return result
        finally:
            if abort_token is not None:
                reset_current_turn_abort(abort_token)

    def _build_input_with_transcript(self, query: str, context: Optional[Context]) -> str:
        """三层记忆组装：短期原文 + 任务状态 + 长期摘要。"""
        from Agent.CustomerAgent.conversation_memory import build_layered_prompt

        return build_layered_prompt(query, context)

    async def initialize_async(self) -> bool:
        """初始化CustomerAgent"""
        if self._is_initialized:
            return True

        try:
            # 获取配置
            from utils.runtime_path import resolve_writable_path

            agno_db_raw = (get_config("chat.agno_db_path") or "").strip()
            if agno_db_raw:
                db_path = str(resolve_writable_path(agno_db_raw))
            else:
                # 与 customer.db 分离，避免 Agno 会话写入与聊天库争抢锁导致 UI 卡顿
                db_path = str(resolve_writable_path("./temp/agno_sessions.db"))
            model_name = get_config("llm.model_name", "gpt-3.5-turbo")
            api_key = get_config("llm.api_key", "")
            api_base = get_config("llm.api_base", "")
            max_tokens = get_config("llm.max_tokens", None)
            temperature = get_config("llm.temperature", 0.7)
            chat_max = get_config("chat.ai_max_tokens", None)
            chat_temp = get_config("chat.ai_temperature", None)
            if chat_max is not None:
                max_tokens = chat_max
            if chat_temp is not None:
                temperature = chat_temp
            try:
                if max_tokens is not None:
                    max_tokens = int(max_tokens)
            except (TypeError, ValueError):
                max_tokens = None
            try:
                temperature = float(temperature)
            except (TypeError, ValueError):
                temperature = 0.7
            description = get_config("prompt.description", "")
            raw_instr = get_config("prompt.instructions", [])
            if not isinstance(raw_instr, list):
                raw_instr = []
            instructions: List[str] = [str(x) for x in raw_instr if str(x).strip()]
            additional_context = (get_config("prompt.additional_context", "") or "").strip()

            if get_config("prompt.append_natural_style", True):
                instructions = _NATURAL_STYLE_INSTRUCTIONS + instructions
                instructions = _KNOWLEDGE_GROUNDING + instructions
                if additional_context:
                    additional_context = _NATURAL_STYLE_CONTEXT + "\n\n" + additional_context
                else:
                    additional_context = _NATURAL_STYLE_CONTEXT
            else:
                instructions = _KNOWLEDGE_GROUNDING + instructions

            # 验证必要配置
            if not api_key:
                raise ValueError("LLM API密钥未配置")

            # 创建Agent实例
            model_kw: Dict[str, Any] = {
                "id": model_name,
                "api_key": api_key,
                "base_url": api_base,
                "temperature": temperature,
            }
            if max_tokens is not None and max_tokens > 0:
                model_kw["max_tokens"] = max_tokens

            self._agent = Agent(
                db=SqliteDb(db_file=db_path),
                knowledge=None,
                knowledge_retriever=_customer_agno_knowledge_retriever(self.knowledge_manager),
                model=OpenAILike(**model_kw),
                tools=[
                    transfer_conversation,
                    send_goods_link,
                    get_shop_products,
                    get_product_skus,
                ],
                search_knowledge= True,
                description=description,
                instructions=instructions,
                additional_context=additional_context,
                # 三层记忆由 build_layered_prompt 注入，避免与 Agno 内置历史重复
                add_history_to_context=not bool(get_config("chat.memory.enabled", True)),
                add_dependencies_to_context=True,
                add_datetime_to_context=True,
                timezone_identifier="Asia/Shanghai"
            )

            self.logger.info("CustomerAgent初始化成功")
            return True

        except Exception as e:
            self.logger.error(f"CustomerAgent初始化失败: {e}")
            return False

    async def async_reply(self, query: str, context:Context = None) -> Reply:
        """异步回复接口 - 确保返回Reply对象"""
        if not self._agent:
            if not await self.initialize_async():
                return Reply(ReplyType.TEXT, "AI客服初始化失败")

        try:
            session_id, agent_user_id = _agno_memory_scope(context)
            if "__no_buyer__" in session_id:
                self.logger.warning(
                    "当前消息缺少买家 from_uid，Agno 记忆将写入占位会话 __no_buyer__，请检查渠道上下文"
                )
            # 确保dependencies中的值是安全的类型
            dependencies = {
                "shop_name": str(context.kwargs.shop_name),
                "channel_type": str(context.channel_type.value),
                "shop_id": str(context.kwargs.shop_id),
                "user_id": str(context.kwargs.user_id),
                "from_uid": str(context.kwargs.from_uid),
                "buyer_message": str(query or "").strip(),
            }
            # 知识检索按拼多多店铺 ID 隔离（与 platform_shop_id 字段对齐）
            shop_scope = str(context.kwargs.shop_id or "").strip() or None
            tok = set_platform_shop_context(shop_scope)
            try:
                ar_input = await asyncio.to_thread(
                    self._build_input_with_transcript, query, context
                )
                try:
                    from core.ops_telemetry import enrich_from_agent_input

                    tlines = ar_input.count("\n") if ar_input else 0
                    enrich_from_agent_input(query, ar_input, transcript_lines=tlines)
                except ImportError:
                    pass
                # v2：链路内同步重试由 AIReplyHandler 负责；arun 在 worker 线程执行，避免阻塞 WS loop
                timeout_sec = _llm_arun_timeout_sec()
                loop = asyncio.get_running_loop()
                signal = get_current_turn_abort()
                if signal and signal.is_aborted():
                    turn_abort_registry.record_stale_dropped()
                    raise TurnAborted(signal.reason(), signal.turn_id)
                async with self._arun_lock_for_current_loop():
                    try:
                        response: RunOutput = await asyncio.wait_for(
                            loop.run_in_executor(
                                _ARUN_EXECUTOR,
                                partial(
                                    self._run_agent_arun_blocking,
                                    agent_user_id,
                                    session_id,
                                    ar_input,
                                    dependencies,
                                    signal,
                                ),
                            ),
                            timeout=timeout_sec,
                        )
                    except asyncio.TimeoutError:
                        if signal:
                            signal.abort("arun_timeout")
                        self.logger.error(
                            "CustomerAgent arun 超时 ({:.0f}s)",
                            timeout_sec,
                        )
                        raise TurnAborted(
                            "arun_timeout",
                            signal.turn_id if signal else "",
                        ) from None
                if signal and signal.is_aborted():
                    turn_abort_registry.record_stale_dropped()
                    raise TurnAborted(signal.reason(), signal.turn_id)
                try:
                    from core.ops_telemetry import get_current_turn, record_llm_usage

                    turn = get_current_turn()
                    if turn:
                        turn.final_answer = str(response.content or "")
                    record_llm_usage(
                        response,
                        model_name=str(get_config("llm.model_name", "") or ""),
                    )
                except ImportError:
                    pass
                return Reply(ReplyType.TEXT, response.content)
            finally:
                reset_platform_shop_context(tok)
        except Exception as e:
            self.logger.error(f"CustomerAgent异步回复失败: {e}")
            raise