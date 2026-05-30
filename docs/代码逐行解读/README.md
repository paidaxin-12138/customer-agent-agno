# 代码逐行解读（按功能拆解）

## 说明

本目录对 **Customer-Agent** 按**功能模块**拆解，对**核心源文件逐行注释**。  

整个仓库约有 **170+ 个 Python 文件、数万行代码**，无法在一份文档里对「每一行」全部讲完。做法是：

1. **先讲主链路**（启动 → 收消息 → 处理器链 → AI / 转人工 → 发回买家）  
2. **每个文件单独一篇**，格式统一为：`行号 | 源码 | 含义`  
3. 未列入的文件，见 [代码架构说明.md](../代码架构说明.md) 的模块索引，可按同样方式自行对照阅读  

## 专题开发文档

| 文档 | 说明 |
|------|------|
| [售后代申请开发说明.md](../售后代申请开发说明.md) | 快捷退款卡策略、协议、配置、排错、统计表 |
| [拼多多退换货卡片-可行性调研.md](../拼多多退换货卡片-可行性调研.md) | 早期调研与 MMS 接口线索 |

## 阅读顺序（推荐）

### 主链路（01–07）

| 序号 | 文档 | 源文件 | 功能 |
|------|------|--------|------|
| 01 | [01-启动入口-app.py.md](./01-启动入口-app.py.md) | `app.py` | 进程入口、Qt、DI、崩溃日志 |
| 02 | [02-消息消费者-consumer.py.md](./02-消息消费者-consumer.py.md) | `Message/core/consumer.py` | 队列消费、Watchdog 启动、Handler 循环 |
| 03 | [03-处理器链-handler_chain_factory.py.md](./03-处理器链-handler_chain_factory.py.md) | `Message/handler_chain_factory.py` | 组装处理器顺序 |
| 04 | [04-150秒兜底-ai_reply_watchdog.py.md](./04-150秒兜底-ai_reply_watchdog.py.md) | `Message/handlers/ai_reply_watchdog.py` | 超时转人工 |
| 05 | [05-AI回复-ai_handler-handle.md](./05-AI回复-ai_handler-handle.md) | `Message/handlers/ai_handler.py` | AI 回复主流程 |
| 06 | [06-人工协助总线-human_assist_bus.py.md](./06-人工协助总线-human_assist_bus.py.md) | `core/human_assist_bus.py` | 弹窗信号、payload |
| 07 | [07-Qt主线程调度-qt_threading.py.md](./07-Qt主线程调度-qt_threading.py.md) | `跨线程 UI` |

### 补充模块（08–16）✅

| 序号 | 文档 | 源文件 | 功能 |
|------|------|--------|------|
| 08 | [08-消息模型-bridge-context.py.md](./08-消息模型-bridge-context.py.md) | `bridge/context.py` | Context / ContextType 全文 |
| 09 | [09-拼多多渠道-pdd_chnnel-核心.md](./09-拼多多渠道-pdd_chnnel-核心.md) | `Channel/pinduoduo/pdd_chnnel.py` | WS、入队、消费者装配 |
| 10 | [10-发送消息-send_message.py.md](./10-发送消息-send_message.py.md) | `utils/API/send_message.py` | MMS 发文本/卡片/转接 |
| 11 | [11-自动回复线程-auto_reply_ui.md](./11-自动回复线程-auto_reply_ui.md) | `ui/auto_reply_ui.py` | AutoReplyThread |
| 12 | [12-Agent-CustomerAgent.md](./12-Agent-CustomerAgent.md) | `Agent/CustomerAgent/agent.py` | Agno、工具、arun |
| 13 | [13-实时聊天-ai_mode-chat_ui.md](./13-实时聊天-ai_mode-chat_ui.md) | `ui/chat_ui.py` | 人工/AI、10 秒、手动发送 |
| 14 | [14-数据库-会话-db_manager.md](./14-数据库-会话-db_manager.md) | `database/db_manager.py` | 会话、ai_mode、结案 |
| 15 | [15-拼多多原始消息-pdd_message.py.md](./15-拼多多原始消息-pdd_message.py.md) | `Channel/pinduoduo/pdd_message.py` | WS JSON 解析 |
| 16 | [16-包导入与模块入口.md](./16-包导入与模块入口.md) | 各包 `__init__.py`、`app.py` 导入顺序、延迟 import | ✅ 补「包导入」 |

## 仍可扩展的模块

| 模块 | 源文件 |
|------|--------|
| HTTP 基类 / Cookie | `Channel/pinduoduo/utils/base_request.py` |
| 会话中枢 UI | `ui/conversation_hub.py` |
| 知识库 LanceDB | `Agent/CustomerAgent/agent_knowledge_lancedb.py` |
| 关键词 Handler | `Message/handlers/keyword_handler.py` |
| 退换货 Handler | `Message/handlers/after_sales_apply_handler.py` |

需要某文件「全文逐行」时，指定路径即可继续追加一篇。

## 一文串起主链路

```text
app.py → MainWindow → AutoReplyThread.run
  → PDDChannel.start_account → _message_loop
  → _process_websocket_message → PDDChatMessage → Context
  → put_message → MessageConsumer (02)
  → start_inbound_watchdog (04) → handler_chain (03)
  → AIReplyHandler (05) → CustomerAgent.arun (12)
  → SendMessage.send_text (10) → notify_outbound_reply (04)
  → 失败/超时 → emit_human_assist (06) → run_on_main_thread (07) → chat_ui 弹窗 (13)
```
