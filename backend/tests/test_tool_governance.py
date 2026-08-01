from app.tools.factory import create_tool_registry


def test_all_tools_expose_governance_descriptor():
    registry = create_tool_registry()
    descriptors = registry.get_all_descriptors()

    assert descriptors
    for descriptor in descriptors:
        governance = descriptor.get("governance")
        assert isinstance(governance, dict), descriptor["name"]
        assert governance["category"] in {"generate", "edit", "search", "review", "manage", "patch", "workspace", "other"}
        assert governance["write_policy"] in {"none", "direct", "proposal", "workspace_only"}
        assert isinstance(governance["requires_confirmation"], bool)
        assert isinstance(governance["agent_boundary"], str)


def test_tool_schemas_include_governance_boundaries_for_agent():
    registry = create_tool_registry()
    schemas = {schema["name"]: schema for schema in registry.get_all_schemas()}

    assert "工具治理：category=generate; write_policy=direct" in schemas["outline_generate"]["description"]
    assert "局部增删改必须先读取区块 ID" in schemas["outline_generate"]["description"]
    assert "工具治理：category=patch; write_policy=proposal" in schemas["file_change_proposal"]["description"]
    assert "补丁式修改" in schemas["file_change_proposal"]["description"]
    assert "replace_outline_node" in schemas["file_change_proposal"]["description"]
    assert "insert_before_outline_node" in schemas["file_change_proposal"]["description"]
    assert "insert_after_outline_node" in schemas["file_change_proposal"]["description"]


def test_tool_governance_expected_core_categories():
    registry = create_tool_registry()
    descriptors = {descriptor["name"]: descriptor for descriptor in registry.get_all_descriptors()}

    assert descriptors["search_project"]["governance"]["category"] == "search"
    assert descriptors["consistency_check"]["governance"]["category"] == "review"
    assert descriptors["file_change_proposal"]["governance"]["write_policy"] == "proposal"
    assert descriptors["outline_generate"]["governance"]["category"] == "generate"
    assert descriptors["foreshadow_manage"]["governance"]["category"] == "manage"
    assert descriptors["foreshadow_manage"]["governance"]["write_policy"] == "none"
