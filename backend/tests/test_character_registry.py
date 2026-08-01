from app.projects.characters import (
    CHARACTER_ID_RE,
    CHARACTER_SCHEMA_VERSION,
    migrate_character_registry,
    resolve_character_references,
)
from app.projects.context import ProjectContext


async def test_character_registry_migrates_legacy_profiles_without_touching_markdown(tmp_path):
    context = ProjectContext(tmp_path)
    original_profile = "# 林铎\n\n不可改写的人物档案。\n"
    await context.write_yaml(
        "characters/lin-duo/profile.yaml",
        {"slug": "lin-duo", "name": "林铎", "custom_note": "保留"},
    )
    await context.write_text("characters/lin-duo/profile.md", original_profile)
    await context.write_text("characters/xia-he/profile.md", "# 夏禾\n\n旧项目只有 Markdown。\n")

    migrated = await migrate_character_registry(context)

    assert migrated["status"] == "migrated"
    assert migrated["changed"] == 2
    assert migrated["created_metadata"] == 1
    assert migrated["snapshot_path"]
    assert await context.exists(migrated["snapshot_path"])
    assert await context.read_text("characters/lin-duo/profile.md") == original_profile

    lin_duo = await context.read_yaml("characters/lin-duo/profile.yaml")
    xia_he = await context.read_yaml("characters/xia-he/profile.yaml")
    assert lin_duo["schema_version"] == CHARACTER_SCHEMA_VERSION
    assert lin_duo["custom_note"] == "保留"
    assert CHARACTER_ID_RE.fullmatch(lin_duo["character_id"])
    assert xia_he["name"] == "夏禾"
    assert CHARACTER_ID_RE.fullmatch(xia_he["character_id"])
    assert lin_duo["character_id"] != xia_he["character_id"]

    index = await context.read_yaml("characters/index.yaml")
    assert {item["name"] for item in index["characters"]} == {"林铎", "夏禾"}

    repeated = await migrate_character_registry(context)
    assert repeated["status"] == "current"
    assert repeated["changed"] == 0
    assert (await context.read_yaml("characters/lin-duo/profile.yaml"))["character_id"] == lin_duo["character_id"]
    assert len(await context.list_files(".aisync/migration_backups")) == 1


async def test_character_reference_resolution_uses_names_aliases_and_reports_ambiguity(tmp_path):
    context = ProjectContext(tmp_path)
    await context.write_yaml(
        "characters/lin-duo/profile.yaml",
        {"slug": "lin-duo", "name": "林铎", "aliases": ["零号", "拾荒者"]},
    )
    await context.write_text("characters/lin-duo/profile.md", "# 林铎\n")
    await context.write_yaml(
        "characters/lu-chen/profile.yaml",
        {"slug": "lu-chen", "name": "陆沉", "aliases": ["拾荒者"]},
    )
    await context.write_text("characters/lu-chen/profile.md", "# 陆沉\n")

    result = await resolve_character_references(context, ["林铎", "零 号", "拾荒者", "不存在"])

    assert [(item["input"], item["name"]) for item in result["resolved"]] == [
        ("林铎", "林铎"),
        ("零 号", "林铎"),
    ]
    assert result["unresolved"] == ["不存在"]
    assert result["ambiguous"][0]["input"] == "拾荒者"
    assert {item["name"] for item in result["ambiguous"][0]["candidates"]} == {"林铎", "陆沉"}


async def test_character_registry_replaces_duplicate_ids_deterministically(tmp_path):
    context = ProjectContext(tmp_path)
    duplicate_id = "char_1234567890abcdef1234"
    for slug, name in [("alpha", "甲"), ("beta", "乙")]:
        await context.write_yaml(
            f"characters/{slug}/profile.yaml",
            {"character_id": duplicate_id, "slug": slug, "name": name},
        )

    report = await migrate_character_registry(context)
    alpha = await context.read_yaml("characters/alpha/profile.yaml")
    beta = await context.read_yaml("characters/beta/profile.yaml")

    assert report["changed"] == 2
    assert alpha["character_id"] == duplicate_id
    assert beta["character_id"] != duplicate_id
    assert CHARACTER_ID_RE.fullmatch(beta["character_id"])
    assert any("重复" in item["message"] for item in report["warnings"])


async def test_archived_character_keeps_id_in_registry_and_name_resolution(tmp_path):
    context = ProjectContext(tmp_path)
    character_id = "char_abcdef1234567890abcd"
    archive_dir = "temp/archive/characters/lin-duo-20260731010101"
    await context.write_yaml(
        f"{archive_dir}/profile.yaml",
        {
            "schema_version": CHARACTER_SCHEMA_VERSION,
            "character_id": character_id,
            "slug": "lin-duo",
            "name": "林铎",
            "aliases": ["零号"],
        },
    )
    await context.write_text(f"{archive_dir}/profile.md", "# 林铎\n")
    await context.write_json(
        f"{archive_dir}/archive.json",
        {
            "type": "character_archive",
            "character_id": character_id,
            "slug": "lin-duo",
            "files": [],
        },
    )

    await migrate_character_registry(context)
    index = await context.read_yaml("characters/index.yaml")
    resolved = await resolve_character_references(context, ["零号"])

    assert index["characters"][0]["character_id"] == character_id
    assert index["characters"][0]["archived"] is True
    assert resolved["resolved"][0] == {
        "input": "零号",
        "character_id": character_id,
        "name": "林铎",
        "slug": "lin-duo",
        "archived": True,
    }
