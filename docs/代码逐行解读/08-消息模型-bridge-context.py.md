# 逐行解读：`bridge/context.py`（统一消息模型）

源文件：[context.py](../../bridge/context.py)（共 96 行）

**功能**：全渠道消息在内存中的**标准形状**。拼多多 WS 解析后都转成 `Context`，后续队列、Handler、Agent 只认这一套。

---

## `ChannelType`（第 8–17 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 8 | `class ChannelType(str, Enum)` | 继承 `str` 的枚举，JSON/配置里可直接用字符串比较。 |
| 10–14 | `PINDUODUO`, `JINGDONG`… | 预留多平台；当前主路径只用 `PINDUODUO`。 |
| 16–17 | `__str__` 返回 `self.value` | 打印时显示 `pinduoduo` 而非 `ChannelType.PINDUODUO`。 |

---

## `ContextType`（第 19–39 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 19–36 | 各枚举成员 | 决定 `can_handle`、是否入队、是否立即处理。 |
| 21–28 | TEXT / IMAGE / VIDEO / EMOTION / GOODS_* / ORDER_INFO | **会入队** 的业务消息（见 `pdd_chnnel._should_queue_message`）。 |
| 29–36 | SYSTEM_* / MALL_CS / WITHDRAW / AUTH / TRANSFER | 多为**系统或立即处理**，通常不走 AI 队列。 |

---

## `PinduoduoKwargs`（第 41–58 行）

| 行号 | 字段 | 含义 |
|------|------|------|
| 43 | `msg_id` | 平台消息 ID，去重/持久化。 |
| 44 | `shop_name` | 展示用店铺名。 |
| 45–48 | `from_user` / `from_uid` | 发送方；买家消息时 `from_uid` 为买家 UID。 |
| 46–48 | `to_user` / `to_uid` | 接收方。 |
| 49 | `nickname` | 买家昵称，弹窗/列表显示。 |
| 50 | `timestamp` | 平台时间戳字符串。 |
| 51 | `user_msg_type` | 原始类型，可与 `Context.type` 一致。 |
| 52–54 | `shop_id`, `user_id`, `username` | **卖家侧**账号维度，发消息、查 DB 必需。 |
| 55 | `raw_data` | 原始 JSON 片段，调试或扩展用。 |
| 57–58 | `Config.arbitrary_types_allowed` | Pydantic 允许 kwargs 里嵌复杂类型。 |

---

## `Context`（第 60–94 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 60–65 | 类字段 | `type` 必填；`content` 多为 str，订单/商品有时序列化为 JSON 字符串；`kwargs` 实际常为 `PinduoduoKwargs` 实例；`channel_type` 渠道。 |
| 67–94 | `create_pinduoduo_context` 工厂 | 由 `PDDChannel._convert_to_context` 调用：组装 kwargs → `Context(type=user_msg_type or TEXT, ...)`。 |
| 90 | `type=user_msg_type or ContextType.TEXT` | 未指定类型时当作文本。 |

---

## 在链路中的位置

```text
WebSocket JSON → PDDChatMessage → Context.create_pinduoduo_context(...)
  → put_message(queue) → MessageConsumer → Handler.can_handle(context.type)
```

`metadata` 里的 `shop_id`/`from_uid` 多从 `context.kwargs` 拷贝，与 kwargs 字段一一对应。
