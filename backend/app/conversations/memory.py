from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.conversations.store import Conversation, ConversationMessage
from app.llm.types import ChatRequest, LLMClient
from app.conversations.quality import MemoryQualityReport, evaluate_summary_quality

SUMMARY_TRIGGER_MESSAGES = 18
RECENT_MEMORY_MESSAGES = 12
MAX_SUMMARY_SOURCE_CHARS = 18000

SUMMARY_SYSTEM_PROMPT = """你是 AiSync 的会话记忆压缩器。
你的任务是把旧对话压缩成稳定、可复用的小说创作记忆。
保留：
- 用户明确提出的偏好、约束、命名、设定
- 已确认的剧情、角色、世界观、工具操作结果
- 未完成的任务、待确认问题、重要决策
删除：
- 寒暄、重复表达、失败重试细节
- 与项目无关的过程性废话

输出 Markdown，使用以下结构：
## 已确认事实
## 用户偏好
## 剧情/角色/世界观线索
## 未完成事项
"""


@dataclass
class MemoryContext:
    summary: str
    recent_messages: list[dict[str, str]]
    summary_pending: bool = False
    summary_quality: dict[str, object] | None = None
    summary_updated_at: str | None = None
    summary_chars: int = 0
    recent_window: int = RECENT_MEMORY_MESSAGES
    old_message_count: int = 0
    total_message_count: int = 0


class ConversationMemory:
    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.root = self.project_root / ".aisync" / "conversations"

    def load_summary(self, conversation_id: str) -> str:
        path = self._summary_path(conversation_id)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def save_summary(self, conversation_id: str, summary: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._summary_path(conversation_id).write_text(summary.strip() + "\n", encoding="utf-8")

    def summary_updated_at(self, conversation_id: str) -> str | None:
        path = self._summary_path(conversation_id)
        if not path.exists():
            return None
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()

    def save_summary_quality(self, conversation_id: str, report: MemoryQualityReport) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._summary_quality_path(conversation_id)
        path.write_text(
            "\n".join(
                [
                    f"score: {report.score}",
                    f"status: {report.status}",
                    f"source_messages: {report.source_messages}",
                    f"summary_chars: {report.summary_chars}",
                    "issues:",
                    *[f"- {issue}" for issue in report.issues],
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    async def context_for(
        self,
        conversation: Conversation,
    ) -> MemoryContext:
        summary = self.load_summary(conversation.id)
        recent_source = conversation.messages[-RECENT_MEMORY_MESSAGES:]
        old_messages = conversation.messages[:-RECENT_MEMORY_MESSAGES]

        return MemoryContext(
            summary=summary,
            recent_messages=self._messages_to_history(recent_source),
            summary_pending=len(old_messages) >= SUMMARY_TRIGGER_MESSAGES,
            summary_quality=evaluate_summary_quality(summary, old_messages).model_dump() if summary and old_messages else None,
            summary_updated_at=self.summary_updated_at(conversation.id),
            summary_chars=len(summary),
            recent_window=RECENT_MEMORY_MESSAGES,
            old_message_count=len(old_messages),
            total_message_count=len(conversation.messages),
        )

    async def update_after_turn(
        self,
        conversation: Conversation,
        llm_client: LLMClient,
    ) -> bool:
        if len(conversation.messages) <= SUMMARY_TRIGGER_MESSAGES + RECENT_MEMORY_MESSAGES:
            return False
        summary = self.load_summary(conversation.id)
        old_messages = conversation.messages[:-RECENT_MEMORY_MESSAGES]
        await self._summarize(conversation.id, summary, old_messages, llm_client)
        return True

    async def _summarize(
        self,
        conversation_id: str,
        existing_summary: str,
        messages: list[ConversationMessage],
        llm_client: LLMClient,
    ) -> str:
        source = self._format_messages(messages)
        if len(source) > MAX_SUMMARY_SOURCE_CHARS:
            source = source[-MAX_SUMMARY_SOURCE_CHARS:]
            source = "[较早内容已按字符预算截断]\n\n" + source

        user_content = (
            "现有摘要：\n"
            f"{existing_summary or '（暂无）'}\n\n"
            "需要压缩进摘要的旧对话：\n"
            f"{source}\n\n"
            "请输出更新后的完整摘要。"
        )
        response = await llm_client.chat(
            ChatRequest(
                messages=[{"role": "user", "content": user_content}],
                system=SUMMARY_SYSTEM_PROMPT,
                max_tokens=2000,
                stream=False,
            )
        )
        summary = response.text.strip()
        if summary:
            self.save_summary(conversation_id, summary)
            report = evaluate_summary_quality(summary, messages)
            self.save_summary_quality(conversation_id, report)
        return summary or existing_summary

    def _messages_to_history(self, messages: list[ConversationMessage]) -> list[dict[str, str]]:
        return [
            {"role": message.role, "content": message.content}
            for message in messages
            if message.type in {"user_message", "agent_final", "message"} and message.content.strip()
        ]

    def _format_messages(self, messages: list[ConversationMessage]) -> str:
        lines: list[str] = []
        for message in messages:
            if message.type not in {"user_message", "agent_final", "message"}:
                continue
            role = self._role_label(message.role)
            lines.append(f"{role}（{message.created_at}）:\n{message.content.strip()}")
        return "\n\n---\n\n".join(lines)

    def _role_label(self, role: Literal["user", "agent"]) -> str:
        return "用户" if role == "user" else "Agent"

    def _summary_path(self, conversation_id: str) -> Path:
        if not conversation_id or "/" in conversation_id or "\\" in conversation_id or ".." in conversation_id:
            raise ValueError("Invalid conversation id")
        return self.root / f"{conversation_id}.summary.md"

    def _summary_quality_path(self, conversation_id: str) -> Path:
        if not conversation_id or "/" in conversation_id or "\\" in conversation_id or ".." in conversation_id:
            raise ValueError("Invalid conversation id")
        return self.root / f"{conversation_id}.summary.quality.txt"
