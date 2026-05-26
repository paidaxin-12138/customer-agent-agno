import pytest

from bridge.context import Context, ContextType, ChannelType
from bridge.reply import Reply
from Message.handlers.ai_handler import AIReplyHandler


class SyncBot:
    def reply(self, query, context):
        return Reply(content=f"echo:{query}")


@pytest.fixture
def text_context() -> Context:
    return Context(
        type=ContextType.TEXT,
        content="hello",
        channel_type=ChannelType.PINDUODUO,
        kwargs={},
    )


@pytest.mark.asyncio
async def test_call_bot_once_uses_sync_bot_reply(text_context: Context):
    handler = AIReplyHandler(bot=SyncBot())
    res = await handler._call_bot_once("hello", text_context)
    assert res == "echo:hello"


@pytest.mark.asyncio
async def test_get_ai_reply_with_sync_retry(text_context: Context, monkeypatch):
    handler = AIReplyHandler(bot=SyncBot())
    monkeypatch.setattr(
        "Message.handlers.ai_handler.config.get",
        lambda key, default=None: False if key == "chat.llm_sync_retry_enabled" else default,
    )
    res = await handler._get_ai_reply_with_sync_retry("hello", text_context)
    assert res == "echo:hello"
