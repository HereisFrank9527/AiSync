from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from app.conversations.store import ConversationMessage

EXPECTED_SECTIONS = ("已确认事实", "用户偏好", "剧情/角色/世界观线索", "未完成事项")
SUMMARY_MESSAGE_TYPES = {"user_message", "agent_final", "message"}
MAX_QUALITY_SOURCE_CHARS = 24000

ANCHOR_PATTERNS = (
    re.compile(r"`([^`]{2,80})`"),
    re.compile(r"[「『《“\"]([^」』》”\"]{2,40})[」』》”\"]"),
    re.compile(r"\b\d+(?:\.\d+)?%?\b"),
    re.compile(r"\b[\w.-]+/[\w./-]+\b"),
)
IMPORTANT_LINE_RE = re.compile(
    r"(设定|世界观|角色|章节|剧情|偏好|必须|不要|不能|需要|继续|下一步|待办|未完成|确认|bug|修复|工具|向量|记忆)"
)


@dataclass
class MemoryQualityReport:
    score: int
    status: str
    issues: list[str]
    missing_sections: list[str]
    missing_anchors: list[str]
    source_messages: int
    summary_chars: int

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_summary_quality(summary: str, source_messages: list[ConversationMessage]) -> MemoryQualityReport:
    source = _source_text(source_messages)
    summary_text = summary.strip()
    missing_sections = [section for section in EXPECTED_SECTIONS if f"## {section}" not in summary_text]
    anchors = _extract_anchors(source)
    missing_anchors = [anchor for anchor in anchors if anchor not in summary_text][:12]
    important_lines = _important_lines(source)
    covered_lines = sum(1 for line in important_lines if _line_is_covered(line, summary_text))

    issues: list[str] = []
    score = 100

    if not summary_text:
        return MemoryQualityReport(
            score=0,
            status="poor",
            issues=["摘要为空"],
            missing_sections=list(EXPECTED_SECTIONS),
            missing_anchors=anchors[:12],
            source_messages=len(source_messages),
            summary_chars=0,
        )

    if missing_sections:
        score -= min(40, len(missing_sections) * 10)
        issues.append(f"缺少摘要章节：{', '.join(missing_sections)}")

    if len(source) > 2500 and len(summary_text) < 220:
        score -= 18
        issues.append("摘要过短，可能无法覆盖旧对话中的关键设定")

    if anchors:
        anchor_coverage = 1 - (len(missing_anchors) / min(len(anchors), 12))
        if anchor_coverage < 0.35:
            score -= 24
            issues.append("关键名词、数值或文件路径覆盖不足")
        elif anchor_coverage < 0.6:
            score -= 12
            issues.append("部分关键名词、数值或文件路径未进入摘要")

    if important_lines:
        line_coverage = covered_lines / len(important_lines)
        if line_coverage < 0.35:
            score -= 18
            issues.append("用户偏好、待办或设定类语句覆盖不足")
        elif line_coverage < 0.6:
            score -= 9
            issues.append("部分用户偏好、待办或设定类语句可能被压缩丢失")

    if important_lines and "未完成事项" in summary_text and re.search(r"未完成事项\s*\n\s*(?:无|暂无|没有)", summary_text):
        score -= 8
        issues.append("源对话存在任务线索，但未完成事项章节为空")

    score = max(0, min(100, score))
    status = "ok" if score >= 75 else "weak" if score >= 50 else "poor"
    return MemoryQualityReport(
        score=score,
        status=status,
        issues=issues,
        missing_sections=missing_sections,
        missing_anchors=missing_anchors,
        source_messages=len([m for m in source_messages if m.type in SUMMARY_MESSAGE_TYPES]),
        summary_chars=len(summary_text),
    )


def _source_text(messages: list[ConversationMessage]) -> str:
    parts = [message.content.strip() for message in messages if message.type in SUMMARY_MESSAGE_TYPES and message.content.strip()]
    text = "\n".join(parts)
    if len(text) > MAX_QUALITY_SOURCE_CHARS:
        return text[-MAX_QUALITY_SOURCE_CHARS:]
    return text


def _extract_anchors(text: str) -> list[str]:
    anchors: list[str] = []
    seen: set[str] = set()
    for pattern in ANCHOR_PATTERNS:
        for match in pattern.finditer(text):
            value = next((group for group in match.groups() if group), match.group(0)).strip()
            if len(value) < 2 or value in seen:
                continue
            seen.add(value)
            anchors.append(value)
            if len(anchors) >= 24:
                return anchors
    return anchors


def _important_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) < 8 or len(line) > 220:
            continue
        if IMPORTANT_LINE_RE.search(line):
            lines.append(line)
        if len(lines) >= 16:
            break
    return lines


def _line_is_covered(line: str, summary: str) -> bool:
    tokens = set(re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", line))
    if not tokens:
        return False
    covered = sum(1 for token in tokens if token in summary)
    return covered / len(tokens) >= 0.45
