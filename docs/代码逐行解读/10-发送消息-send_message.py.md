# 逐行解读：`Channel/pinduoduo/utils/API/send_message.py`

源文件：[send_message.py](../../Channel/pinduoduo/utils/API/send_message.py)

**功能**：封装拼多多商家后台 MMS HTTP API。所有「发给买家」的自动回复、人工回复、卡片、转接，最终都依赖本类（继承 `BaseRequest` 带 Cookie）。

---

## 类构造（第 7–14 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 7 | `class SendMessage(BaseRequest)` | 父类负责 cookies、headers、post 重试、登录过期刷新。 |
| 8 | `__init__(shop_id, user_id, channel_name="pinduoduo")` | 从 DB 加载该账号 cookies。 |
| 12–14 | 无 `account_name` 则 `raise ValueError` | 构造失败，上层应提示重新登录。 |

---

## `send_text`（第 16–53 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 20 | URL `plateau/chat/send_message` | MMS 统一发送接口。 |
| 21–41 | `data` 结构 | `cmd: send_message`；`to.role=user` + `to.uid=recipient_uid`；`from.role=mall_cs`；`content` 文本；`type: 0` 文本；`manual_reply: 1` 标记人工/客服侧发送。 |
| 24 | `generate_request_id()` | 请求唯一 ID，防重放/对齐平台协议。 |
| 43 | `self.post(url, json_data=data)` | 同步 HTTP；Handler 里用 `asyncio.to_thread` 包装。 |
| 44–50 | `success` 且 `error_code==10002` | 平台业务错误，返回 error 字符串而非 dict。 |
| 50 | `return result` | 成功时为 dict，含 `success: True`。 |
| 52–53 | 失败 | 记日志，返回 `None`。 |

**调用方**：`AIReplyHandler._send_reply`、`ai_reply_watchdog._send_buyer_text`、`keyword_handler`、`chat_ui.SendHumanMessageThread`。

---

## `send_image`（第 57–88 行）

| 行号 | 含义 |
|------|------|
| 74 | `content` 为图片 URL | |
| 77 | `type: 1` | 图片类型。 |
| 其余 | 与 `send_text` 同 URL，不同 type/content。 |

---

## `send_mallGoodsCard`（第 91–116 行）

| 行号 | 含义 |
|------|------|
| 100 | 独立 URL `send/mallGoodsCard` | |
| 102–105 | `uid`, `goods_id`, `biz_type` | 客服推荐商品卡片。 |
| 107–108 | `_chat_mms_headers` | 聊天专用请求头。 |

---

## `send_ask_refund_apply`（第 118–170 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 139–144 | `ChatOrdersAPI.get_order_pickup_info` | 拉取订单退货相关信息，填入 `reposeInfo`。 |
| 146 | URL `ask_refund_apply/send` | 申请退换货卡片（非公开文档接口）。 |
| 147–156 | `order_sn`, `after_sales_type`, `refund_amount`（分）等 | 与 `config chat.after_sales_apply_*` 对应。 |
| 160–170 | post 结果 | `AfterSalesApplyHandler` 根据 success 决定是否冷却、跟发文案。 |

---

## `getAssignCsList` / `move_conversation`（第 173–211 行）

| 方法 | 含义 |
|------|------|
| `getAssignCsList` | 获取可转接客服列表；`keyword_handler` 转人工用。 |
| `move_conversation` | `plateau/chat/move_conversation`，把买家会话转给 `cs_uid`。 |

---

## 与 Watchdog 的关系

任意 `send_text` 返回 `success` 后，上层应调用 `notify_outbound_reply()`，否则 150s 兜底仍会弹窗。
