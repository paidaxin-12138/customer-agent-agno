# 逐行解读：`Channel/pinduoduo/pdd_message.py`（WS JSON → ContextType）

源文件：[pdd_message.py](../../Channel/pinduoduo/pdd_message.py)

**功能**：把 WebSocket 一条 JSON 解析为内部类型 + content，供 `PDDChannel._convert_to_context` 使用。

---

## `BaseMessageHandler`（第 7–21 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 8–10 | `__init__(msg)` | `msg` 为顶层 WS 对象；`self.data = msg.get("message",{})`。 |
| 11–21 | `get_basic_info()` | 提取 msg_id、nickname、from/to role/uid、timestamp。 |

---

## `MessageTypeHandler` 静态方法（第 24–80+ 行）

每种平台 `type` 对应一个 `handle_*`，返回 `(ContextType, content)`：

| 方法 | 行号 | 返回类型 | content 形态 |
|------|------|----------|----------------|
| `handle_text` | 27–29 | TEXT | 字符串 |
| `handle_image` | 32–35 | IMAGE | 图片 URL |
| `handle_video` | 38–41 | VIDEO | 视频 URL |
| `handle_emotion` | 44–47 | EMOTION | 表情描述 |
| `handle_withdraw` | 50–53 | WITHDRAW | 撤回提示 |
| `handle_goods_inquiry` | 56–65 | GOODS_INQUIRY | dict：goods_id, name, price… |
| `handle_goods_spec` | 68–76 | GOODS_SPEC | dict 含 spec |
| `handle_order_info` | 79+ | ORDER_INFO | 订单结构 dict |

后续 Handler 若收到 dict 内容，可能 `json.dumps` 再送 LLM 或专用解析（如退换货 Handler）。

---

## `PDDChatMessage` 类（文件后半，摘要）

典型逻辑（具体行号以源文件为准）：

| 步骤 | 含义 |
|------|------|
| 读 `message.type` 或类似字段 | 映射到 `MessageTypeHandler` 方法名 |
| 调对应 `handle_*` | 得到 `user_msg_type` 与 `content` |
| 暴露属性 | `msg_id`, `from_uid`, `nickname`, `content`, `user_msg_type` 等 |

`_convert_to_context` 使用：

```python
context_type = pdd_message.user_msg_type
content = ... # str 或 json.dumps(dict)
Context.create_pinduoduo_context(..., user_msg_type=context_type, ...)
```

---

## 类型 → 是否进 AI 队列

| ContextType | 通常路径 |
|-------------|----------|
| TEXT, IMAGE, … | `put_message` → Consumer |
| WITHDRAW, AUTH, … | `_handle_immediate_message` |
| 未识别 | 忽略 debug |

详见 [09-拼多多渠道](./09-拼多多渠道-pdd_chnnel-核心.md) 中 `_should_queue_message`。

---

## 调试建议

在 `pdd_chnnel._process_websocket_message` 第 810 行附近已 `debug` 打印完整 JSON；对照 `MessageTypeHandler` 看平台新类型是否需新增 `handle_*` 与 `ContextType` 枚举。
