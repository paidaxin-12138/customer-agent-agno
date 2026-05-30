# 逐行解读：`Agent/CustomerAgent/agent.py`（AI 核心）

源文件：[agent.py](../../Agent/CustomerAgent/agent.py)（约 328 行；文件头含大段 `_NATURAL_STYLE_*`、`_KNOWLEDGE_GROUNDING` 常量，为提示词规则，此处不逐字展开）

**功能**：实现 `Bot` 接口，用 **Agno** `Agent` 调用 OpenAI 兼容 API，挂载知识检索与拼多多工具。

---

## 知识检索适配（第 92–165 行，摘要）

| 符号 | 含义 |
|------|------|
| `_customer_agno_knowledge_retriever(km)` | 返回 Agno 要求的 `knowledge_retriever` 闭包。 |
| 闭包内 | 调 `KnowledgeManager.search_knowledge`，店铺隔离靠 `set_platform_shop_context(shop_id)`。 |
| 原因 | Agno 传空 `knowledge={}` 时不检索；必须自定义 retriever。 |

---

## `CustomerAgent.__init__`（第 168–182 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 168 | `class CustomerAgent(Bot)` | `AIReplyHandler` 通过 DI 或 `CustomerAgent()` 注入。 |
| 169–179 | `knowledge_manager` | 优先 DI 的 `KnowledgeManager`，否则 `KnowledgeManager()`。 |
| 180 | `self._agent: Optional[Agent] = None` | Agno Agent **延迟创建**。 |
| 181–182 | `logger`, `_is_initialized` | |

---

## `_build_input_with_transcript`（第 184–188 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 186 | `from conversation_memory import build_layered_prompt` | |
| 188 | `return build_layered_prompt(query, context)` | 拼装【长期摘要】【任务状态】【短期记忆】+ 当前买家句。 |

---

## `initialize_async`（第 190–270 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 192–193 | 已初始化则直接 True | 避免重复建 Agent。 |
| 197–217 | `get_config` 读 llm、prompt | `model_name`, `api_key`, `api_base`, `max_tokens`, `temperature`, `description`, `instructions`。 |
| 219–227 | `append_natural_style` | True 时拼接 `_NATURAL_STYLE_INSTRUCTIONS`、`_KNOWLEDGE_GROUNDING`、`_NATURAL_STYLE_CONTEXT`。 |
| 230–231 | 无 api_key 抛错 | |
| 234–241 | `OpenAILike(**model_kw)` | 兼容 DashScope/DeepSeek 等。 |
| 243–263 | `Agent(...)` 构造 | |
| 244 | `db=SqliteDb(db_file=db_path)` | Agno 运行历史/会话存储（与业务 `customer.db` 不同路径）。 |
| 245 | `knowledge=None` | 检索走 retriever，不用内置 knowledge 对象。 |
| 246 | `knowledge_retriever=...` | 接 LanceDB。 |
| 248–253 | `tools=[...]` | 转接、发商品链接、拉商品列表/SKU。 |
| 254 | `search_knowledge=True` | 允许 Agent 触发检索。 |
| 255–257 | `description`, `instructions`, `additional_context` | 角色与人设。 |
| 259 | `add_history_to_context=not memory.enabled` | 开启三层记忆时关闭 Agno 自带历史，避免重复。 |
| 260–262 | `add_dependencies_to_context`, 上海时区 | `dependencies` 在 `arun` 时传入 shop_id 等。 |
| 265–270 | 成功/失败日志 | |

---

## `async_reply`（第 272–328 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 272 | `async def async_reply(self, query, context)` | `AIReplyHandler._call_bot_once` 优先走此路径。 |
| 274–276 | `_agent` 为空则 `initialize_async` | 失败返回 `Reply(TEXT, "AI客服初始化失败")`。 |
| 279 | `_agno_memory_scope(context)` | 生成 Agno 的 `session_id` / `user_id`（买家维度）。 |
| 280–283 | `__no_buyer__` 警告 | kwargs 缺 `from_uid` 时记忆串会话。 |
| 285–291 | `dependencies` dict | 工具内可读 shop_name、shop_id、from_uid。 |
| 293–294 | `set_platform_shop_context(shop_scope)` | ContextVar，检索仅本店知识。 |
| 296 | `_build_input_with_transcript` | 带记忆的完整 prompt。 |
| 298–303 | `enrich_from_agent_input` | 运营看板遥测。 |
| 305–310 | `await self._agent.arun(...)` | **单次** LLM 调用；同步重试在 Handler 层。 |
| 306–308 | `user_id`, `session_id`, `input`, `dependencies` | Agno 会话隔离。 |
| 311+ | `record_llm_usage`, 解析 `RunOutput` 为 `Reply` | 取 `response.content` 等返回给 Handler。 |

---

## 与 Handler 的分工

| 层级 | 职责 |
|------|------|
| `AIReplyHandler` | ai_mode、排队降级、watchdog、发送 MMS、`to_thread` 调 bot |
| `CustomerAgent` | 提示词、知识检索、工具调用、Agno `arun` |
| `SendMessage` | 真正把文本发到拼多多 |

---

## 相关文件

- `Agent/CustomerAgent/agent_knowledge_lancedb.py` — 向量检索实现  
- `Agent/CustomerAgent/tools/*.py` — 各 `@tool` 函数  
- `Agent/CustomerAgent/conversation_memory.py` — `build_layered_prompt`
