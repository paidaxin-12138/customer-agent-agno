import asyncio
import errno

from agno import tools
from Agent.bot import Bot
from agno.agent import Agent, RunOutput

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from agno.models.openai import OpenAILike
from agno.db.sqlite import SqliteDb
from Agent.CustomerAgent.agent_knowledge_lancedb import (
    LanceDBKnowledgeManager as KnowledgeManager,
    reset_platform_shop_context,
    set_platform_shop_context,
)
from Agent.CustomerAgent.tools.move_conversation import transfer_conversation
from Agent.CustomerAgent.tools.get_product_list import get_shop_products, get_product_skus
from Agent.CustomerAgent.tools.send_goods_link import send_goods_link
from config import get_config
from typing import Any, Dict, List, Optional
from utils.logger_loguru import get_logger
from pydantic import BaseModel, Field

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

def _is_transient_llm_transport_error(exc: BaseException) -> bool:
    """
    判定是否为可重试的瞬时网络/传输错误（如 EPIPE、连接被重置、httpx 读超时等）。
    日志中常见：[Errno 32] Broken pipe。
    """
    seen: set[int] = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, asyncio.TimeoutError)):
            return True
        if isinstance(cur, OSError):
            en = getattr(cur, "errno", None)
            if en in (errno.EPIPE, errno.ECONNRESET, errno.ETIMEDOUT, errno.ECONNABORTED):
                return True
        name = type(cur).__name__
        if name in (
            "ReadError",
            "WriteError",
            "RemoteProtocolError",
            "LocalProtocolError",
            "ConnectError",
            "ReadTimeout",
            "WriteTimeout",
            "ConnectTimeout",
        ):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


_KNOWLEDGE_GROUNDING: List[str] = [
    "本店主营以知识库检索到的「美甲灯/光疗灯」及其中明确写明的配件为准；不得编造未在检索结果中出现的在售 SKU、库存、价格或规格。",
    "知识库里若只出现美甲步骤中的底胶/色胶/封层/光疗胶等通用概念，仅代表美甲流程说明，不等同于本店在售甲油胶商品；买家问「有没有美甲胶/甲油胶/胶类」时，若检索片段未列出可发货的胶类产品，应如实说明本店以美甲灯为主、胶类需确认或引导其选购灯适用类型，禁止用「都有」「有货」等空泛承诺。",
    "若用户问题与检索内容无关或检索为空：简短说明本店当前可查到的上架范围，并给出可执行下一步（如「我去问问产品经理」「稍后回复」）；不要凭想象补全商品信息。",
    "若检索未覆盖买家问的商品（如打磨机、胶类等）：明确说明知识库/在售链接里暂未查到，应说「我去问问产品经理」「稍后由产品经理确认」；禁止使用「转人工客服」「转人工」「问老板」「找老板」「问店主」「转同事」等话术。",
    "不要引导买家「再发图」「发照片」来辨认商品：本链路中 AI 无法查看聊天图片；识图需求应说「我去问问产品经理」，话术上避免让顾客重复发图给机器人。",
    "当买家询问商品相关信息（价格、规格、库存、款式、颜色等）时，必须优先使用 get_shop_products（实时列表含 SKU）或 get_product_skus(goods_id) 查询，再基于工具返回回答；无需先同步知识库。禁止凭空猜测或编造商品信息。",
    "如果知识库检索结果为空，但买家询问具体商品，应使用 get_shop_products 工具查询店铺在售商品，然后根据查询结果推荐合适的商品给买家。",
    "推荐商品时：优先从 get_shop_products 返回的商品列表中选择 1-2 款最匹配的，提供商品名称、价格、核心卖点；不要一次性推荐超过 2 款。",
    "当买家询问「有没有 XX 款」「有没有 XX 功能」「有什么颜色」「有哪些款式」时：先用 get_shop_products 查询商品列表，确认有货后再推荐；若无此商品，如实告知「知识库暂未收录这款，我去问问产品经理」并推荐相似款。",
    "【语言匹配】自动检测买家使用的语言（中文/英文/泰语/越南语等），并用相同语言回复；买家说中文就用中文回答，买家说英文就用英文回答，保持语言一致。",
    "【禁止话术】禁止使用以下表述：「转人工」「转人工客服」「人工客服」「问老板」「找老板」「问店主」「转同事」「转其他客服」；统一改为「我去问问产品经理」「这边跟产品经理确认下」「稍后产品经理回复您」。",
    "【禁止编造】严禁编造以下信息：商品颜色（如「只有黑色」「有白色」）、商品款式、库存状态、商品名称；如知识库和商品列表中都未找到，必须如实说明「暂未查到」并主动提出「我去问问产品经理」。",
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
        q = (query or "").strip()
        if not q:
            return None
        limit = 5
        if num_documents is not None:
            try:
                n = int(num_documents)
                if n > 0:
                    limit = n
            except (TypeError, ValueError):
                pass
        try:
            hits = km.search_knowledge(q, top_k=limit)
        except Exception as e:
            log.warning(f"knowledge_retriever 检索失败: {e}")
            return None
        if not hits:
            try:
                from core.ops_telemetry import set_recall_results
                set_recall_results([])
            except Exception:
                pass
            return None
        try:
            from core.ops_telemetry import set_recall_results
            set_recall_results(hits)
        except Exception:
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
                knowledge_manager = KnowledgeManager()
        self.knowledge_manager = knowledge_manager
        self._agent: Optional[Agent] = None  # 延迟初始化
        self.logger = get_logger("CustomerAgent")
        self._is_initialized = False

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
            db_path = get_config("db_path", "./temp/agent.db")
            model_name = get_config("llm.model_name", "gpt-3.5-turbo")
            api_key = get_config("llm.api_key", "")
            api_base = get_config("llm.api_base", "")
            max_tokens = get_config("llm.max_tokens", None)
            temperature = get_config("llm.temperature", 0.7)
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
            }
            # 知识检索按拼多多店铺 ID 隔离（与 platform_shop_id 字段对齐）
            shop_scope = str(context.kwargs.shop_id or "").strip() or None
            tok = set_platform_shop_context(shop_scope)
            try:
                ar_input = self._build_input_with_transcript(query, context)
                try:
                    from core.ops_telemetry import enrich_from_agent_input

                    tlines = ar_input.count("\n") if ar_input else 0
                    enrich_from_agent_input(query, ar_input, transcript_lines=tlines)
                except Exception:
                    pass
                # v2：链路内同步重试由 AIReplyHandler 负责；此处单次 arun
                response: RunOutput = await self._agent.arun(
                    user_id=agent_user_id,
                    session_id=session_id,
                    input=ar_input,
                    dependencies=dependencies,
                )
                try:
                    from core.ops_telemetry import get_current_turn, record_llm_usage

                    turn = get_current_turn()
                    if turn:
                        turn.final_answer = str(response.content or "")
                    record_llm_usage(
                        response,
                        model_name=str(get_config("llm.model_name", "") or ""),
                    )
                except Exception:
                    pass
                return Reply(ReplyType.TEXT, response.content)
            finally:
                reset_platform_shop_context(tok)
        except Exception as e:
            self.logger.error(f"CustomerAgent异步回复失败: {e}")
            raise