from app.core.prompt_packs import PromptPackCopy, PromptPackCreate, PromptPackStore, PromptPackUpdate


def test_prompt_pack_store_crud(tmp_path):
    store = PromptPackStore(tmp_path / "prompt_packs.json")

    pack = store.create(
        PromptPackCreate(
            name="冷峻文风",
            category="style",
            stages=["chat", "chapter_draft"],
            content="语言克制，减少解释。",
            description="主线默认文风",
        )
    )

    assert pack.id
    assert pack.category == "style"
    assert pack.stages == ["chat", "chapter_draft"]
    assert store.get(pack.id) is not None

    updated = store.update(
        pack.id,
        PromptPackUpdate(
            enabled=False,
            stages=["chapter_draft", "chapter_draft"],
            content="语言克制，保留留白。",
        ),
    )
    assert updated is not None
    assert updated.enabled is False
    assert updated.stages == ["chapter_draft"]
    assert updated.content == "语言克制，保留留白。"

    copied = store.copy(pack.id, "冷峻文风 副本")
    assert copied is not None
    assert copied.id != pack.id
    assert copied.name == "冷峻文风 副本"

    reloaded = PromptPackStore(tmp_path / "prompt_packs.json")
    assert len(reloaded.list_all()) == 2

    assert reloaded.delete(pack.id) is True
    assert reloaded.get(pack.id) is None
    assert reloaded.delete("missing") is False


def test_prompt_pack_store_filters_enabled_stage(tmp_path):
    store = PromptPackStore(tmp_path / "prompt_packs.json")
    chat_pack = store.create(
        PromptPackCreate(name="对话文风", category="style", stages=["chat"], content="保持克制。")
    )
    store.create(
        PromptPackCreate(name="章节规则", category="writing", stages=["chapter_draft"], content="分场景写。")
    )
    store.create(
        PromptPackCreate(name="空内容", category="custom", stages=["chat"], content="")
    )
    store.create(
        PromptPackCreate(name="已停用", category="style", stages=["chat"], content="不要使用", enabled=False)
    )

    packs = store.enabled_for_stage("chat")

    assert [pack.id for pack in packs] == [chat_pack.id]


def test_prompt_pack_copy_missing_returns_none(tmp_path):
    store = PromptPackStore(tmp_path / "prompt_packs.json")

    assert store.copy("missing", PromptPackCopy(name="x").name) is None
