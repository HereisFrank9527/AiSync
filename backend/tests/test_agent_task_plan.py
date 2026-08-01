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


def test_task_plan_starts_generic_without_tool_evidence() -> None:
    assert build_task_plan() == TASK_PLAN_DEFAULT


def test_task_plan_uses_writing_template_for_writing_tools() -> None:
    assert build_task_plan({"write_chapter"}) == TASK_PLAN_WRITING


def test_task_plan_uses_consistency_template_for_review_tool() -> None:
    assert build_task_plan({"consistency_check"}) == TASK_PLAN_CONSISTENCY


def test_task_plan_uses_character_template_for_character_tool() -> None:
    assert build_task_plan({"character_manage"}) == TASK_PLAN_CHARACTER


def test_task_plan_uses_outline_template_for_outline_tool() -> None:
    assert build_task_plan({"outline_generate"}) == TASK_PLAN_OUTLINE


def test_task_plan_uses_search_template_for_search_tool() -> None:
    assert build_task_plan({"search_project"}) == TASK_PLAN_SEARCH


def test_task_plan_uses_worldview_template_for_worldview_tool() -> None:
    assert build_task_plan({"update_worldview"}) == TASK_PLAN_WORLDVIEW
