from app.agent import (
    TASK_PLAN_CHARACTER,
    TASK_PLAN_CONSISTENCY,
    TASK_PLAN_DEFAULT,
    TASK_PLAN_OUTLINE,
    TASK_PLAN_SEARCH,
    TASK_PLAN_WRITING,
    TASK_PLAN_WORLDVIEW,
    build_task_plan,
)


def test_task_plan_uses_writing_template_for_chapter_requests() -> None:
    assert build_task_plan("帮我续写第三章") == TASK_PLAN_WRITING


def test_task_plan_uses_consistency_template_for_conflict_checks() -> None:
    assert build_task_plan("检查世界观有没有矛盾") == TASK_PLAN_CONSISTENCY


def test_task_plan_uses_character_template_for_role_requests() -> None:
    assert build_task_plan("整理角色人设") == TASK_PLAN_CHARACTER


def test_task_plan_uses_outline_template_for_outline_requests() -> None:
    assert build_task_plan("先给我一个剧情大纲") == TASK_PLAN_OUTLINE


def test_task_plan_uses_search_template_for_search_requests() -> None:
    assert build_task_plan("搜索方舟密钥相关资料") == TASK_PLAN_SEARCH


def test_task_plan_uses_worldview_template_for_setting_requests() -> None:
    assert build_task_plan("补充世界观和地理设定") == TASK_PLAN_WORLDVIEW


def test_task_plan_falls_back_to_default_for_generic_requests() -> None:
    assert build_task_plan("随便聊聊") == TASK_PLAN_DEFAULT


def test_task_plan_can_be_refined_by_tool_names() -> None:
    assert build_task_plan("随便聊聊", {"write_chapter"}) == TASK_PLAN_WRITING
