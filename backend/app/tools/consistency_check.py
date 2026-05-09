from __future__ import annotations

import json
import re
from typing import Any

from app.llm.types import ChatRequest, LLMClient
from app.projects.context import ProjectContext
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult
from app.vector.store import ProjectVectorStore

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
STRUCTURAL_NUMBER_LINE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:[-*+]\s*)?\d+(?:\.\d+)*[.)、]?\s*")
NEGATION_PHRASES = {
    "没有",
    "不会",
    "不能",
    "不再",
    "不可",
    "不许",
    "不允许",
    "禁止",
    "尚未",
    "未曾",
    "从未",
    "never",
    "no",
    "not",
    "without",
}
STATE_SIGNALS = {
    "life_dead": {"死亡", "死", "dead"},
    "life_alive": {"活着", "存活", "alive"},
    "presence_exists": {"存在"},
    "presence_missing": {"不存在", "失踪", "missing"},
    "ruin_destroyed": {"毁灭", "摧毁", "destroyed"},
}


class ConsistencyCheckTool(BaseTool):
    name = "consistency_check"
    description = "将新内容与项目索引设定比对，找出可能的一致性风险。"

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(read=["**/*.md", "**/*.txt", "**/*.yaml", "**/*.yml", "**/*.json"])

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="list:issues", description="一致性问题列表")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要检查的新内容或设定。"},
                "path": {"type": "string", "description": "可选的项目文件路径，用于读取并检查。"},
                "limit": {"type": "integer", "description": "最多检查多少条相关上下文片段。", "default": 8},
            },
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        content, path, limit = await self._input_content(params, context)
        related = await ProjectVectorStore(context).query(content, top_k=limit)
        issues = self._inspect(content, related, path)
        return self._result(issues, path, len(related), mode="rules")

    async def invoke(
        self,
        params: dict[str, Any],
        context: ProjectContext,
        llm: LLMClient,
    ) -> ToolResult | None:
        content, path, limit = await self._input_content(params, context)
        related = await ProjectVectorStore(context).query(content, top_k=limit)
        heuristic_issues = self._inspect(content, related, path)
        if not related:
            return self._result([], path, 0, mode="llm")

        prompt = self._llm_prompt(content, related, heuristic_issues)
        response = await llm.chat(
            ChatRequest(
                messages=[{"role": "user", "content": prompt}],
                tools=[],
                system=(
                    "你是小说创作一致性审校器。只判断给定新内容与候选项目片段是否存在真实冲突。"
                    "输出必须是 JSON，不要使用 Markdown。"
                ),
                max_tokens=4000,
                stream=False,
            )
        )
        issues = self._parse_llm_issues(response.text, related)
        if not issues and heuristic_issues:
            issues = heuristic_issues
        result = self._result(issues, path, len(related), mode="llm")
        if not issues and response.text.strip():
            result.content = response.text.strip()
        return result

    async def _input_content(
        self,
        params: dict[str, Any],
        context: ProjectContext,
    ) -> tuple[str, str, int]:
        content = str(params.get("content") or "").strip()
        path = str(params.get("path") or "").strip()
        limit = int(params.get("limit") or 8)
        if path:
            if ".." in path or path.startswith(("/", "\\")):
                raise ValueError("Path must be a project-relative file path")
            content = await context.read_text(path)
        if not content:
            raise ValueError("Either content or path is required")
        return content, path, limit

    def _result(self, issues: list[dict[str, Any]], path: str, related_count: int, mode: str) -> ToolResult:
        if not issues:
            return ToolResult(
                content="未发现明显的一致性问题。",
                ui_hint={"type": "list:issues", "data": []},
                metadata={"checked_path": path or None, "related_chunks": related_count, "mode": mode},
            )

        rendered = "\n".join(
            f"- [{issue['severity']}] {issue['title']} ({issue['path']}): {issue['detail']}"
            for issue in issues
        )
        return ToolResult(
            content=rendered,
            ui_hint={"type": "list:issues", "data": issues},
            metadata={"checked_path": path or None, "related_chunks": related_count, "mode": mode},
        )

    def _llm_prompt(
        self,
        content: str,
        related: list[dict[str, Any]],
        heuristic_issues: list[dict[str, Any]],
    ) -> str:
        candidates = []
        for index, item in enumerate(related[:10], start=1):
            text = str(item.get("content") or "")
            if len(text) > 1200:
                text = f"{text[:1200]}\n[片段已截断]"
            candidates.append({
                "id": index,
                "path": item.get("path"),
                "collection": item.get("collection"),
                "score": item.get("score"),
                "content": text,
            })
        payload = {
            "new_content": content[:6000],
            "candidate_context": candidates,
            "heuristic_issues": heuristic_issues,
        }
        return (
            "请根据 JSON 输入判断新内容与候选项目片段是否存在真实一致性问题。\n"
            "只输出 JSON，格式如下：\n"
            "{\n"
            "  \"issues\": [\n"
            "    {\n"
            "      \"severity\": \"critical|potential|notice\",\n"
            "      \"title\": \"简短标题\",\n"
            "      \"path\": \"相关文件路径\",\n"
            "      \"detail\": \"为什么冲突或为什么需要复核\",\n"
            "      \"suggestion\": \"建议如何修改新内容或旧设定\",\n"
            "      \"snippet\": \"相关原文短摘\"\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "如果只是主题相关但不冲突，不要输出 issue。\n\n"
            f"输入：\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _parse_llm_issues(self, text: str, related: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raw = text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        items = data.get("issues") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        known_paths = {str(item.get("path")): item for item in related}
        issues: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            related_item = known_paths.get(path, {})
            issues.append({
                "severity": str(item.get("severity") or "notice"),
                "title": str(item.get("title") or "一致性提示"),
                "path": path,
                "detail": str(item.get("detail") or ""),
                "suggestion": str(item.get("suggestion") or ""),
                "snippet": str(item.get("snippet") or "")[:300],
                "score": related_item.get("score"),
                "collection": related_item.get("collection"),
            })
        return issues[:10]

    def _inspect(self, content: str, related: list[dict[str, Any]], checked_path: str) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        content_tokens = set(self._tokens(content))
        content_numbers = self._meaningful_numbers(content)
        content_negations = self._contains_any(content, NEGATION_PHRASES)
        content_states = self._state_signals(content)

        for item in related:
            path = str(item.get("path") or "")
            if checked_path and path == checked_path:
                continue
            text = str(item.get("content") or "")
            overlap = content_tokens & set(self._tokens(text))
            if len(overlap) < 2:
                continue
            snippet = text.replace("\n", " ")
            if len(snippet) > 180:
                snippet = f"{snippet[:180].rstrip()}..."

            text_numbers = self._meaningful_numbers(text)
            if content_numbers and text_numbers and not (content_numbers & text_numbers):
                issues.append(self._issue(
                    "potential",
                    "数值设定可能不一致",
                    path,
                    f"新内容出现 {', '.join(sorted(content_numbers))}，相关片段出现 {', '.join(sorted(text_numbers))}。",
                    snippet,
                    item,
                ))
                continue

            text_negations = self._contains_any(text, NEGATION_PHRASES)
            if content_negations != text_negations:
                issues.append(self._issue(
                    "notice",
                    "规则或否定表述需要复核",
                    path,
                    "新内容与相关片段在明确否定短语上存在差异。",
                    snippet,
                    item,
                ))
                continue

            text_states = self._state_signals(text)
            if content_states and text_states and content_states != text_states:
                issues.append(self._issue(
                    "potential",
                    "状态设定可能冲突",
                    path,
                    f"新内容状态标签 {', '.join(sorted(content_states))}，相关片段状态标签 {', '.join(sorted(text_states))}。",
                    snippet,
                    item,
                ))
                continue

            issues.append(self._issue(
                "notice",
                "存在高相关设定，请人工复核",
                path,
                f"与新内容共享关键词：{', '.join(sorted(overlap)[:8])}。",
                snippet,
                item,
            ))

        return issues[:10]

    def _tokens(self, text: str) -> list[str]:
        return [token.lower() for token in TOKEN_RE.findall(text)]

    def _meaningful_numbers(self, text: str) -> set[str]:
        cleaned_lines: list[str] = []
        for line in text.splitlines():
            cleaned_lines.append(STRUCTURAL_NUMBER_LINE_RE.sub("", line))
        cleaned = "\n".join(cleaned_lines)
        numbers = set(NUMBER_RE.findall(cleaned))
        return {number for number in numbers if number not in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}}

    def _contains_any(self, text: str, words: set[str]) -> bool:
        lowered = text.lower()
        return any(word.lower() in lowered for word in words)

    def _state_signals(self, text: str) -> set[str]:
        lowered = text.lower()
        signals: set[str] = set()
        for name, phrases in STATE_SIGNALS.items():
            if any(phrase.lower() in lowered for phrase in phrases):
                signals.add(name)
        return signals

    def _issue(
        self,
        severity: str,
        title: str,
        path: str,
        detail: str,
        snippet: str,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "severity": severity,
            "title": title,
            "path": path,
            "detail": detail,
            "suggestion": "",
            "snippet": snippet,
            "score": item.get("score"),
            "collection": item.get("collection"),
        }
