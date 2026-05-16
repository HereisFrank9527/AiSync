import pytest

from app.conversations.memory import RECENT_MEMORY_MESSAGES, ConversationMemory
from app.conversations.store import ConversationStore


@pytest.mark.asyncio
async def test_memory_context_exposes_operational_stats(tmp_path):
    store = ConversationStore(tmp_path)
    conversation = store.create()
    for index in range(15):
        role = "user" if index % 2 == 0 else "agent"
        message_type = "user_message" if role == "user" else "agent_final"
        conversation = store.append(conversation.id, role, f"消息 {index}", message_type)

    memory = ConversationMemory(tmp_path)
    context = await memory.context_for(conversation)

    assert context.total_message_count == 15
    assert context.old_message_count == 15 - RECENT_MEMORY_MESSAGES
    assert context.recent_window == RECENT_MEMORY_MESSAGES
    assert len(context.recent_messages) == RECENT_MEMORY_MESSAGES
    assert context.summary_chars == 0
    assert context.summary_updated_at is None


@pytest.mark.asyncio
async def test_memory_context_reports_summary_metadata(tmp_path):
    store = ConversationStore(tmp_path)
    conversation = store.create()
    for index in range(20):
        role = "user" if index % 2 == 0 else "agent"
        message_type = "user_message" if role == "user" else "agent_final"
        conversation = store.append(conversation.id, role, f"世界观设定：方舟密钥 {index}", message_type)

    memory = ConversationMemory(tmp_path)
    memory.save_summary(conversation.id, "## 已确认事实\n- 方舟密钥很重要。\n")

    context = await memory.context_for(conversation)

    assert context.summary_chars > 0
    assert context.summary_updated_at is not None
    assert context.summary_quality is not None
