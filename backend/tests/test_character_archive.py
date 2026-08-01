import pytest

from app.projects.characters import (
    CHARACTER_ID_RE,
    CHARACTER_SCHEMA_VERSION,
    CharacterConflictError,
    archive_character,
    list_character_archives,
    list_characters,
    normalize_character_slug,
    restore_character,
    save_character,
)
from app.projects.context import ProjectContext


async def test_archive_character_moves_profile_files_to_temp_archive(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text("characters/lu-chen/profile.md", "# 陆沉\n")
    await context.write_yaml("characters/lu-chen/profile.yaml", {"slug": "lu-chen", "name": "陆沉"})

    result = await archive_character(context, "lu-chen", "旧名残留")

    assert result["status"] == "archived"
    assert result["archive_path"].startswith("temp/archive/characters/lu-chen-")
    assert not await context.exists("characters/lu-chen/profile.md")
    assert not await context.exists("characters/lu-chen/profile.yaml")
    assert await context.exists(f"{result['archive_path']}/profile.md")
    assert await context.exists(f"{result['archive_path']}/profile.yaml")
    assert await context.exists(f"{result['archive_path']}/archive.json")


async def test_save_character_updates_structured_fields_and_preserves_custom_metadata(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_yaml(
        "characters/lin-duo/profile.yaml",
        {
            "slug": "lin-duo",
            "name": "林铎",
            "role": "主角",
            "custom_note": "保留字段",
        },
    )
    await context.write_text("characters/lin-duo/profile.md", "# 林铎\n\n旧档案。\n")

    record = await save_character(
        context,
        slug="lin-duo",
        name="林铎",
        role="主角",
        summary="灰烬平原拾荒者。",
        profile="# 林铎\n\n新档案。",
        aliases=["零号", "零号"],
        status="active",
        faction="赤砂镇",
        tags=["权限持有者", "拾荒者"],
        first_appearance="第一章",
    )

    metadata = await context.read_yaml("characters/lin-duo/profile.yaml")
    assert metadata["schema_version"] == CHARACTER_SCHEMA_VERSION
    assert CHARACTER_ID_RE.fullmatch(metadata["character_id"])
    assert metadata["custom_note"] == "保留字段"
    assert metadata["aliases"] == ["零号"]
    assert record["faction"] == "赤砂镇"
    assert await context.read_text("characters/lin-duo/profile.md") == "# 林铎\n\n新档案。\n"


async def test_save_character_rejects_duplicate_name_or_alias(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_yaml(
        "characters/lin-duo/profile.yaml",
        {"slug": "lin-duo", "name": "林铎", "aliases": ["零号"]},
    )
    await context.write_text("characters/lin-duo/profile.md", "# 林铎\n")
    await context.write_yaml(
        "characters/xia-he/profile.yaml",
        {"slug": "xia-he", "name": "夏禾"},
    )
    await context.write_text("characters/xia-he/profile.md", "# 夏禾\n")

    with pytest.raises(CharacterConflictError) as exc_info:
        await save_character(
            context,
            slug="xia-he",
            name="夏禾",
            aliases=["零 号"],
            create=False,
        )

    assert exc_info.value.conflicts[0]["slug"] == "lin-duo"


async def test_character_archive_can_be_listed_and_restored(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_text("characters/lu-chen/profile.md", "# 陆沉\n")
    await context.write_yaml(
        "characters/lu-chen/profile.yaml",
        {"slug": "lu-chen", "name": "陆沉", "role": "旧主角"},
    )
    archived = await archive_character(context, "lu-chen", "旧名残留")

    archives = await list_character_archives(context)
    assert archives == [
        {
            "archive_id": archived["archive_id"],
            "character_id": archives[0]["character_id"],
            "slug": "lu-chen",
            "name": "陆沉",
            "role": "旧主角",
            "aliases": [],
            "reason": "旧名残留",
            "archived_at": archives[0]["archived_at"],
            "archive_path": archived["archive_path"],
        }
    ]

    restored = await restore_character(context, archived["archive_id"])
    characters, warnings = await list_characters(context)
    assert restored["status"] == "restored"
    assert characters[0]["name"] == "陆沉"
    assert characters[0]["character_id"] == archives[0]["character_id"]
    assert warnings == []
    assert not await context.exists(f"{archived['archive_path']}/archive.json")


async def test_list_characters_tolerates_invalid_schema_version(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_yaml(
        "characters/lin-duo/profile.yaml",
        {"schema_version": "unknown", "slug": "lin-duo", "name": "林铎"},
    )

    characters, warnings = await list_characters(context)

    assert characters[0]["schema_version"] == 1
    assert warnings == [
        {
            "path": "characters/lin-duo/profile.yaml",
            "message": "schema_version 无效，已按版本 1 兼容读取",
        }
    ]


def test_character_slug_rejects_unsafe_windows_names():
    assert normalize_character_slug("lin-duo_01") == "lin-duo_01"
    with pytest.raises(ValueError):
        normalize_character_slug("林铎")
    with pytest.raises(ValueError):
        normalize_character_slug("lin:duo")
