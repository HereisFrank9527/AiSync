from __future__ import annotations

from app.conversations.quality import evaluate_summary_quality
from app.conversations.store import ConversationMessage


def msg(role: str, content: str, type_: str = "message") -> ConversationMessage:
    return ConversationMessage(role=role, content=content, type=type_)


def sample_source() -> list[ConversationMessage]:
    return [
        msg(
            "user",
            (
                "世界观设定：灾变被称为「灰烬潮」，三个月内全球 95% 以上人口死亡。"
                "请把核心设定写进 world/overview.md。"
            ),
            "user_message",
        ),
        msg(
            "agent",
            (
                "已确认事实：灰烬区约占陆地 60%，净区约占 40%。"
                "待办：继续完善地理设定，补齐净区、灰河和幸存者聚落。"
            ),
            "agent_final",
        ),
        msg(
            "user",
            "用户偏好：不要写成科技术语堆砌，保持废土感和可读性。",
            "user_message",
        ),
    ]


def test_quality_accepts_summary_covering_facts_preferences_and_todos() -> None:
    summary = """## 已确认事实
- 灾变名为「灰烬潮」，三个月内全球 95% 以上人口死亡。
- 核心设定写入 world/overview.md。

## 用户偏好
- 不要写成科技术语堆砌，保持废土感和可读性。

## 剧情/角色/世界观线索
- 灰烬区约占陆地 60%，净区约占 40%，存在灰河和幸存者聚落。

## 未完成事项
- 继续完善地理设定，补齐净区、灰河和幸存者聚落。
"""
    report = evaluate_summary_quality(summary, sample_source())

    assert report.status == "ok"
    assert report.score >= 75
    assert report.missing_sections == []
    assert "灰烬潮" not in report.missing_anchors
    assert "95%" not in report.missing_anchors
    assert "world/overview.md" not in report.missing_anchors


def test_quality_rejects_empty_summary() -> None:
    report = evaluate_summary_quality("", sample_source())

    assert report.status == "poor"
    assert report.score == 0
    assert "摘要为空" in report.issues
    assert report.missing_sections == ["已确认事实", "用户偏好", "剧情/角色/世界观线索", "未完成事项"]


def test_quality_downgrades_summary_missing_key_anchors() -> None:
    summary = """## 已确认事实
- 用户讨论了一个末世题材项目。

## 用户偏好
- 需要保持可读性。

## 剧情/角色/世界观线索
- 存在灾变后的地理设定。

## 未完成事项
- 继续完善。
"""
    report = evaluate_summary_quality(summary, sample_source())

    assert report.status in {"weak", "poor"}
    assert report.score < 75
    assert "灰烬潮" in report.missing_anchors
    assert any("关键名词" in issue for issue in report.issues)


def test_quality_ignores_non_memory_message_types() -> None:
    source = [
        msg("user", "世界观设定：必须保留「方舟密钥」。", "user_message"),
        msg("agent", "这条工具状态不该参与摘要质量。", "tool_call_start"),
    ]
    summary = """## 已确认事实
- 必须保留「方舟密钥」。

## 用户偏好
- 暂无。

## 剧情/角色/世界观线索
- 方舟密钥是关键设定。

## 未完成事项
- 暂无。
"""
    report = evaluate_summary_quality(summary, source)

    assert report.source_messages == 1
    assert "工具状态" not in report.missing_anchors
