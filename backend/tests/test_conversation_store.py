from app.conversations.store import Conversation, ConversationStore


def test_conversation_status_lifecycle(tmp_path):
    store = ConversationStore(tmp_path)

    conversation = store.create()
    assert conversation.status == "idle"

    store.set_status(conversation.id, "running")
    running = store.load(conversation.id)
    assert running.status == "running"
    assert running.running_since

    store.set_status(conversation.id, "failed", "boom")
    failed = store.load(conversation.id)
    assert failed.status == "failed"
    assert failed.last_error == "boom"
    assert failed.running_since is None

    [summary] = store.list()
    assert summary.status == "failed"
    assert summary.last_error == "boom"


def test_legacy_conversation_defaults_to_completed():
    legacy = Conversation(
        id="legacy",
        title="旧对话",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        messages=[],
    )

    assert legacy.status == "completed"
