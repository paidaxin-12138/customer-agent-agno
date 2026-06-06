# Customer-Agent 架构说明

本文描述桌面端 AI 客服的核心数据流与模块依赖，便于 onboarding 与二次开发。

---

## 1. 系统总览

```mermaid
flowchart TB
    subgraph Desktop["桌面进程 (app.py)"]
        UI["PyQt6 UI\nui/main_ui.py"]
        Agent["CustomerAgent\nAgno + LLM"]
        KB["知识库\nknowledge_*"]
        Core["core/\n健康检查 · 指标 · 会话同步"]
        DB["database/\nSQLite"]
    end

    subgraph Channel["渠道层 Channel/pinduoduo"]
        WS["WebSocket\nws_* 模块"]
        HTTP["MMS HTTP\nsend_message 等"]
        PW["Playwright\nCookie 登录"]
    end

    subgraph External["外部服务"]
        PDD_WS["拼多多 WS"]
        PDD_MMS["mms.pinduoduo.com"]
        PDD_OPEN["开放平台 Router"]
        LLM["OpenAI 兼容 LLM"]
        EMB["Embedding API"]
    end

    UI --> Agent
    UI --> DB
    Agent --> KB
    Agent --> LLM
    KB --> EMB
    WS --> PDD_WS
    HTTP --> PDD_MMS
    PW --> PDD_MMS
    Core --> WS
    Message["Message/\n队列 · 处理器链"] --> Agent
    WS --> Message
    Message --> HTTP
    Message --> DB
    OrderLogistics["OrderLogisticsHandler"] --> PDD_OPEN
```

---

## 2. 买家消息数据流

```mermaid
sequenceDiagram
    participant Buyer as 买家
    participant PDD as 拼多多 WS
    participant Ch as PDDChannel
    participant Q as MessageQueue
    participant C as MessageConsumer
    participant H as HandlerChain
    participant AI as AIReplyHandler
    participant MMS as send_message
    participant DB as SQLite

    Buyer->>PDD: 文本/卡片消息
    PDD->>Ch: WebSocket 帧
    Ch->>Ch: pdd_message 解析 Context
    Ch->>Q: enqueue(metadata)
    Q->>C: dequeue
    C->>H: 顺序执行处理器
    alt 关键词/改址/物流等命中
        H->>H: 专用 Handler 处理
    else 进入 AI
        H->>AI: AIReplyHandler
        AI->>AI: 知识检索 + Agent.reply
        AI->>MMS: SendMessage.send_text
        AI->>DB: persist_ai_message
    end
    MMS->>PDD: 商家回复
    PDD->>Buyer: 展示回复
```

### 处理器链顺序

```mermaid
flowchart LR
    A[AddressChangeHandler] --> B[OrderLogisticsHandler]
    B --> C[ImageVideoHumanHandler]
    C --> D[AfterSalesApplyHandler]
    D --> E[BuyerEmotionHandler]
    E --> F[KeywordDetectionHandler]
    F --> G[AIReplyHandler]
    G --> H[CatchAllHandler]
```

任一 Handler 返回「已处理」则链条终止；未处理则由 Consumer 触发 `fallback_reply` 安抚。

---

## 3. 知识库模块依赖

知识库自 `agent_knowledge.py` 拆分为三层（门面仍从原路径 import）：

```mermaid
flowchart TB
    Facade["agent_knowledge.py\nNailLampKnowledgeManager 门面"]
    Retriever["knowledge_retriever.py\n检索 · FAQ · search_knowledge"]
    Indexer["knowledge_indexer.py\n分块 · 向量化 · 导入/商品同步"]
    Storage["knowledge_storage.py\nJSON 落盘 · LanceDB 表"]

    Facade --> Retriever
    Facade --> Indexer
    Facade --> Storage
    Retriever --> Storage
    Indexer --> Storage
    Storage --> LanceDB[(LanceDB)]
    Storage --> JSON[(knowledge_docs.json)]
    Indexer --> EmbedAPI[Embedding API]
    Retriever --> EmbedAPI
```

| 模块 | 职责 |
|------|------|
| `knowledge_storage.py` | 店铺上下文、`knowledge_docs.json` 读写、LanceDB 连接与全量/增量同步 |
| `knowledge_indexer.py` | 长文分块、embedding 补齐、文件导入、`goods_sync` 批量写入 |
| `knowledge_retriever.py` | 向量检索 + 本地打分兜底、父/子库 inherit_key 覆盖、FAQ 直答 |
| `agent_knowledge.py` | 单例 `get_knowledge_manager()`、内置产品兜底数据、向后兼容别名 |

**存储层约定**：LanceDB 按 ID 删除统一走 `lancedb_delete_filter()`（转义单引号）；建索引向量用 `_embedding_text_for_doc()`（标题+正文），检索侧仍用 `_build_embedding_query_text()`（含同义词扩展）。

---

## 4. UI 与会话状态

```mermaid
flowchart LR
    Hub["ConversationHub\n内存索引"]
    Store["session_store.py"]
    DB2[(chat_sessions\nchat_messages)]
    ChatUI["ChatLiveWidget"]
    MainUI["MainWindow"]

    MainUI --> ChatUI
    ChatUI --> Hub
    Hub --> Store
    Store --> DB2
    Consumer["MessageConsumer"] --> Store
    Consumer --> Hub
```

- **权威数据源**：SQLite 中的 `chat_sessions` / `chat_messages`。
- **Hub**：UI 列表、未读数、预览的内存加速层；持久化后通过 `session_store` 回刷。
- **离开聊天页**：`main_ui` 仅在「从聊天页切到其他页」时调用 `_restore_ai_for_current_if_manual()`，避免 stackedWidget 初始化误触发。

---

## 5. 可观测性

| 端点 | 含义 |
|------|------|
| `GET /health` | 进程存活 |
| `GET /ready` | WebSocket 已连接且消费者在跑 |
| `GET /metrics` | `app_metrics`：处理量、队列深度、`cache_sizes`（Hub / 图片 LRU / 买家锁）等 |

生产部署见 [生产部署说明.md](生产部署说明.md)。

---

## 6. 主要包依赖（逻辑层）

```mermaid
flowchart TD
    app[app.py] --> ui[ui/]
    app --> core[core/]
    ui --> Message[Message/]
    ui --> database[database/]
    ui --> Agent[Agent/]
    Message --> bridge[bridge/]
    Message --> Channel[Channel/]
    Message --> utils[utils/]
    Agent --> utils
    Agent --> database
    Channel --> utils
    core --> Message
    core --> Channel
    database --> utils
```

**原则**：`bridge` 仅放 Context/Reply 等轻量类型；避免 `Message` ↔ `Agent` 循环 import（阶段常量放在 `core/session_stages.py`）。
