# 逐行解读：`Message/handler_chain_factory.py`（处理器链组装）

源文件：[handler_chain_factory.py](../../Message/handler_chain_factory.py)（共 108 行）

**功能**：按固定顺序实例化各 `Handler`，返回列表给 `PDDChannel` 注册到 `MessageConsumer`。独立文件是为避免 `Message/__init__.py` 导入顺序导致 `NameError`。

---

## 模块头与缓存变量（第 1–12 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1–3 | docstring | 说明为何从 `__init__` 拆出。 |
| 5 | `from __future__ import annotations` | 允许前向引用类型注解。 |
| 7 | `from .core.handlers import CatchAllHandler` | 链尾兜底，几乎总是 `can_handle=True` 但可能 `handle` 返回 False。 |
| 9–12 | `_cached_*_handler = None` | **单例缓存**：每种 Handler 全进程只 new 一次，省内存、关键词表只加载一次。 |

---

## `_get_image_video_handler`（第 15–26 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 16 | `global _cached_image_video_handler` | 修改模块级变量。 |
| 17–21 | `if None: import ... ImageVideoHumanHandler()` | 懒加载：首次调用才 import，避免循环依赖。 |
| 22–25 | `except ImportError` | 模块缺失时打 warning，返回 None（链上跳过）。 |
| 26 | `return _cached_image_video_handler` | 可能为 None 或实例。 |

`_get_order_logistics_handler`（29–41）、`_get_after_sales_apply_handler`（44–58）、`_get_keyword_handler`（61–73）结构相同，仅类名不同。

---

## `_create_ai_handler`（第 76–79 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 77 | `from .handlers.ai_handler import AIReplyHandler` | 延迟 import AI 模块（会拉 Agno/LanceDB）。 |
| 79 | `return AIReplyHandler(bot)` | `bot` 由 `PDDChannel` 从 DI 取 `CustomerAgent` 传入。 |

---

## `handler_chain`（第 82–107 行）— 顺序即业务优先级

| 行号 | 代码 | 含义 |
|------|------|------|
| 82 | `def handler_chain(use_ai=True, businessHours=None, bot=None)` | `businessHours` 目前多传给 PDDChannel 自身；链构建未直接用。 |
| 84 | `handlers = []` | 空列表。 |
| 86–88 | `OrderLogisticsHandler` | **第 1**：改地址/物流；命中则 AI 不会再跑。 |
| 90–92 | `ImageVideoHumanHandler` | **第 2**：图/视频转人工。 |
| 94–96 | `AfterSalesApplyHandler` | **第 3**：退换货卡片。 |
| 98–100 | `KeywordDetectionHandler` | **第 4**：关键词转人工。 |
| 102–103 | `if use_ai: AIReplyHandler` | **第 5**：AI 自动回复。 |
| 105 | `CatchAllHandler()` | **第 6**：兜底。 |
| 107 | `return handlers` | 交给 `consumer.add_handler` 循环注册。 |

---

## 与 `consumer.py` 的配合

```text
for handler in self.handlers:   # 即此列表顺序
    if handler.can_handle(ctx):
        if await handler.handle(ctx, meta):
            break
```

**设计含义**：越靠前越「硬规则」；AI 放在关键词之后，避免 AI 抢答「转人工」类消息（若关键词未命中才进 AI）。
