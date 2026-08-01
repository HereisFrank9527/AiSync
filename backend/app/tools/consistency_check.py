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
CHINESE_NUMBER_PATTERN = r"[零〇一二两三四五六七八九十百千万亿]+(?:点[零〇一二两三四五六七八九]+)?"
CHINESE_NUMBER_RE = re.compile(
    CHINESE_NUMBER_PATTERN
    + r"(?=\s*(?:岁|年|人|名|个|章|节|级|层|%|％|公里|千米|米|小时|分钟|天|个月|摄氏度|℃))"
)
CHINESE_NUMBER_TOKEN_RE = re.compile(CHINESE_NUMBER_PATTERN)
STRUCTURAL_NUMBER_LINE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:[-*+]\s*)?\d+(?:\.\d+)*[.)、]?\s*")
SENTENCE_SPLIT_RE = re.compile(r"[\n。！？!?；;]+")
GENERIC_TOKENS = {
    "ai",
    "id",
    "json",
    "md",
    "yaml",
    "true",
    "false",
    "none",
    "null",
}
GENERIC_CHINESE_TOKENS = {
    "内容",
    "章节",
    "项目",
    "设定",
    "系统",
    "工具",
    "方案",
    "继续",
    "推进",
    "响应",
    "服务",
    "大纲",
    "角色",
    "正文",
    "相关",
}
STATE_SIGNALS = {
    "life_dead": {"死亡", "死去", "身亡", "dead"},
    "life_alive": {"活着", "存活", "幸存", "alive"},
    "presence_exists": {"仍存在", "依然存在", "确实存在", "exists"},
    "presence_missing": {"不存在", "失踪", "missing"},
    "ruin_destroyed": {"毁灭", "摧毁", "已毁", "destroyed"},
    "ruin_intact": {"完好", "完整保留", "未被摧毁", "intact"},
}
STATE_CONFLICTS = {
    frozenset({"life_dead", "life_alive"}),
    frozenset({"presence_exists", "presence_missing"}),
    frozenset({"ruin_destroyed", "ruin_intact"}),
}
TEMPORAL_TRANSITION_TERMS = {
    "曾经",
    "此前",
    "当时",
    "后来",
    "随后",
    "最终",
    "多年后",
    "年后",
    "年前",
    "过去",
    "如今",
    "现在",
}
NUMERIC_DIMENSIONS = {
    "age": {"年龄", "岁"},
    "ratio": {"%", "％", "比例", "占比", "百分"},
    "population": {"人口", "人数", "成员数量", "幸存者数量"},
    "distance": {"距离", "公里", "千米", "米远"},
    "duration": {"持续", "小时", "分钟", "天后", "个月", "月后"},
    "year": {"年份", "年代", "公元", "纪元"},
    "level": {"等级", "级别", "权限级", "阶段"},
    "capacity": {"容量", "储量", "载重", "上限"},
    "temperature": {"温度", "摄氏", "℃"},
    "speed": {"速度", "时速"},
}
ANCHOR_STOP_TOKENS = GENERIC_CHINESE_TOKENS | {
    "主角",
    "人物",
    "当前",
    "现在",
    "已经",
    "仍然",
    "依然",
    "大约",
    "左右",
    "以上",
    "以下",
    "超过",
    "其中",
    "这个",
    "那个",
    "进行",
    "出现",
    "发生",
    "拥有",
    "获得",
    "成为",
}
MODEL_ISSUE_LIMIT = 3
MODEL_DETAIL_CHARS = 160
MAX_RELATED_CHUNKS = 12
MODE_LABELS = {
    "rules": "保守规则",
    "llm": "LLM 复核",
    "rules_fallback": "LLM 输出异常，规则降级",
    "no_candidates": "未检索到候选",
}
NUMERIC_DIMENSION_LABELS = {
    "age": "年龄",
    "ratio": "比例",
    "population": "人数/人口",
    "distance": "距离",
    "duration": "时长",
    "year": "年份",
    "level": "等级",
    "capacity": "容量",
    "temperature": "温度",
    "speed": "速度",
}


class ConsistencyCheckTool(BaseTool):
    name = "consistency_check"
    description = "将新内容与项目索引设定比对，找出可能的一致性风险。"
    category = "review"
    write_policy = "none"
    uses_agent_llm = True
    agent_boundary = "只做一致性审查和风险提示，不修改项目文件；不要把审查结果当作自动改写。"

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
                "limit": {
                    "type": "integer",
                    "description": "最多检查多少条相关上下文片段。",
                    "default": 8,
                    "minimum": 1,
                    "maximum": MAX_RELATED_CHUNKS,
                },
            },
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        content, path, limit = await self._input_content(params, context)
        related = await self._related_context(content, context, limit)
        issues = self._inspect(content, related, path)
        return self._result(
            issues,
            path,
            len(related),
            mode="rules",
            reviewed_paths=self._reviewed_paths(related, path),
        )

    async def invoke(
        self,
        params: dict[str, Any],
        context: ProjectContext,
        llm: LLMClient,
    ) -> ToolResult | None:
        content, path, limit = await self._input_content(params, context)
        related = await self._related_context(content, context, limit)
        heuristic_issues = self._inspect(content, related, path)
        if not related:
            return self._result([], path, 0, mode="no_candidates", reviewed_paths=[])

        prompt = self._llm_prompt(content, related, heuristic_issues)
        response = await llm.chat(
            ChatRequest(
                messages=[{"role": "user", "content": prompt}],
                tools=[],
                system=(
                    "你是小说创作一致性审校器。只判断给定新内容与候选项目片段是否存在真实冲突。"
                    "输出必须是 JSON，不要使用 Markdown。"
                ),
                max_tokens=2000,
                stream=False,
            )
        )
        parsed, issues = self._parse_llm_issues(response.text, related)
        mode = "llm"
        if not parsed:
            issues = heuristic_issues
            mode = "rules_fallback"
        result = self._result(
            issues,
            path,
            len(related),
            mode=mode,
            reviewed_paths=self._reviewed_paths(related, path),
        )
        result.metadata["llm_usage"] = response.usage or {}
        result.metadata["llm_output_valid"] = parsed
        llm_settings = getattr(llm, "settings", None)
        model_name = str(getattr(llm_settings, "llm_model_name", "") or "").strip()
        provider = str(getattr(llm_settings, "llm_provider", "") or "").strip()
        if model_name:
            result.metadata["llm_model"] = model_name
        if provider:
            result.metadata["llm_provider"] = provider
        return result

    async def _related_context(
        self,
        content: str,
        context: ProjectContext,
        limit: int,
    ) -> list[dict[str, Any]]:
        store = ProjectVectorStore(context)
        exact_terms = self._retrieval_terms(content)
        exact_limit = min(limit, max(2, limit // 2))
        exact = await store.query_exact_terms(exact_terms, top_k=exact_limit)
        semantic = await store.query(content, top_k=limit)

        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in [*exact, *semantic]:
            identity = str(item.get("chunk_id") or f"{item.get('path')}\0{item.get('content')}")
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(item)
            if len(merged) >= limit:
                break
        return merged

    def _reviewed_paths(self, related: list[dict[str, Any]], checked_path: str) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for item in related:
            path = str(item.get("path") or "").strip()
            if not path or path == checked_path or path in seen:
                continue
            seen.add(path)
            paths.append(path)
        return paths

    async def _input_content(
        self,
        params: dict[str, Any],
        context: ProjectContext,
    ) -> tuple[str, str, int]:
        content = str(params.get("content") or "").strip()
        path = str(params.get("path") or "").strip()
        limit = max(1, min(int(params.get("limit") or 8), MAX_RELATED_CHUNKS))
        if path:
            if ".." in path or path.startswith(("/", "\\")):
                raise ValueError("Path must be a project-relative file path")
            content = await context.read_text(path)
        if not content:
            raise ValueError("Either content or path is required")
        return content, path, limit

    def _result(
        self,
        issues: list[dict[str, Any]],
        path: str,
        related_count: int,
        mode: str,
        reviewed_paths: list[str] | None = None,
    ) -> ToolResult:
        mode_label = MODE_LABELS.get(mode, mode)
        reviewed_paths = reviewed_paths or []
        metadata = {
            "checked_path": path or None,
            "related_chunks": related_count,
            "reviewed_paths": reviewed_paths,
            "reviewed_files": len(reviewed_paths),
            "mode": mode,
            "mode_label": mode_label,
        }
        if not issues:
            if mode == "no_candidates":
                content = "未检索到可比对的相关设定，本次无法完成有效一致性审查。"
            elif mode == "rules_fallback":
                content = "LLM 审查结果无法解析；保守规则降级未发现明确冲突。"
            else:
                content = f"未发现明确的一致性冲突（{mode_label}）。"
            return ToolResult(
                content=content,
                ui_hint={"type": "list:issues", "data": []},
                metadata=metadata,
            )

        metadata.update({
            "issue_count": len(issues),
            "model_issue_count": min(len(issues), MODEL_ISSUE_LIMIT),
        })
        return ToolResult(
            content=self._model_issue_summary(issues, related_count, mode),
            ui_hint={"type": "list:issues", "data": issues},
            metadata=metadata,
        )

    def _model_issue_summary(self, issues: list[dict[str, Any]], related_count: int, mode: str) -> str:
        shown = min(len(issues), MODEL_ISSUE_LIMIT)
        mode_label = MODE_LABELS.get(mode, mode)
        lines = [f"一致性审查：发现 {len(issues)} 条提示，相关片段 {related_count} 条，模式 {mode_label}。"]
        lines.append(f"以下仅给模型前 {shown} 条摘要：")
        for index, issue in enumerate(issues[:MODEL_ISSUE_LIMIT], start=1):
            detail = str(issue.get("detail") or "")
            if len(detail) > MODEL_DETAIL_CHARS:
                detail = f"{detail[:MODEL_DETAIL_CHARS].rstrip()}..."
            lines.append(
                f"{index}. [{issue.get('severity')}] {issue.get('title')} · {issue.get('path')}: {detail}"
            )
        if len(issues) > MODEL_ISSUE_LIMIT:
            lines.append("完整问题列表已放入 ui_hint，最终回复只需概括重点，不要逐条复述所有提示。")
        return "\n".join(lines)

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
            "      \"new_snippet\": \"新内容中的冲突原文短摘\",\n"
            "      \"existing_snippet\": \"候选项目片段中的冲突原文短摘\"\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "如果只是主题相关但不冲突，不要输出 issue。\n\n"
            "只有同一实体、同一属性、同一时间范围内出现不兼容事实时才算冲突。\n"
            "人物成长、状态随时间变化、不同对象的不同数值都不算冲突。\n"
            "path 必须原样使用 candidate_context 中已有的路径；无法确认时返回空 issues。\n\n"
            f"输入：\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _parse_llm_issues(
        self,
        text: str,
        related: list[dict[str, Any]],
    ) -> tuple[bool, list[dict[str, Any]]]:
        raw = text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return False, []
        items = data.get("issues") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return False, []
        known_paths = {str(item.get("path")): item for item in related}
        issues: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if path not in known_paths:
                continue
            related_item = known_paths[path]
            severity = str(item.get("severity") or "notice")
            if severity not in {"critical", "potential", "notice"}:
                severity = "notice"
            title = str(item.get("title") or "一致性提示").strip()
            detail = str(item.get("detail") or "").strip()
            signature = (path, title, detail)
            if signature in seen:
                continue
            seen.add(signature)
            issues.append({
                "severity": severity,
                "title": title,
                "path": path,
                "detail": detail,
                "suggestion": str(item.get("suggestion") or ""),
                "new_snippet": str(item.get("new_snippet") or "")[:300],
                "existing_snippet": str(item.get("existing_snippet") or item.get("snippet") or "")[:300],
                "snippet": str(item.get("existing_snippet") or item.get("snippet") or "")[:300],
                "score": related_item.get("score"),
                "collection": related_item.get("collection"),
            })
        return True, issues[:10]

    def _inspect(self, content: str, related: list[dict[str, Any]], checked_path: str) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        content_numeric = self._numeric_statements(content)
        content_states = self._state_statements(content)

        for item in related:
            path = str(item.get("path") or "")
            if checked_path and path == checked_path:
                continue
            text = str(item.get("content") or "")
            snippet = text.replace("\n", " ")
            if len(snippet) > 180:
                snippet = f"{snippet[:180].rstrip()}..."

            numeric_conflict = self._numeric_conflict(content_numeric, self._numeric_statements(text))
            if numeric_conflict:
                issues.append(self._issue(
                    "potential",
                    "数值设定可能不一致",
                    path,
                    numeric_conflict["detail"],
                    snippet,
                    item,
                    new_snippet=numeric_conflict["new_snippet"],
                    existing_snippet=numeric_conflict["existing_snippet"],
                ))
                continue

            state_conflict = self._state_conflict(content_states, self._state_statements(text))
            if state_conflict:
                issues.append(self._issue(
                    "potential",
                    "状态设定可能冲突",
                    path,
                    state_conflict["detail"],
                    snippet,
                    item,
                    new_snippet=state_conflict["new_snippet"],
                    existing_snippet=state_conflict["existing_snippet"],
                ))

        return issues[:10]

    def _numeric_statements(self, text: str) -> list[dict[str, Any]]:
        statements: list[dict[str, Any]] = []
        document_anchors = self._document_anchors(text)
        for sentence in SENTENCE_SPLIT_RE.split(text):
            sentence = STRUCTURAL_NUMBER_LINE_RE.sub("", sentence).strip()
            numbers = self._meaningful_numbers(sentence)
            if not sentence or not numbers:
                continue
            dimensions = {
                name
                for name, terms in NUMERIC_DIMENSIONS.items()
                if self._contains_any(sentence, terms)
            }
            if not dimensions:
                continue
            anchors = self._anchor_tokens(sentence) | document_anchors
            if not anchors:
                continue
            statements.append({
                "numbers": numbers,
                "dimensions": dimensions,
                "anchors": anchors,
                "text": sentence,
            })
        return statements

    def _retrieval_terms(self, text: str) -> list[str]:
        statements = [*self._numeric_statements(text), *self._state_statements(text)]
        anchors = {
            anchor
            for statement in statements
            for anchor in statement.get("anchors", set())
        }
        if not anchors:
            anchors = self._anchor_tokens(text)

        normalized: set[str] = set()
        for anchor in anchors:
            stripped = re.sub(r"(?:的|为|是)$", "", anchor)
            if len(stripped) >= 2:
                normalized.add(stripped)
            if not anchor.endswith(("的", "为", "是")):
                normalized.add(anchor)
        return sorted(normalized, key=lambda token: (len(token), token))[:16]

    def _numeric_conflict(
        self,
        left: list[dict[str, Any]],
        right: list[dict[str, Any]],
    ) -> dict[str, str] | None:
        for new_fact in left:
            for old_fact in right:
                shared_dimensions = new_fact["dimensions"] & old_fact["dimensions"]
                shared_anchors = new_fact["anchors"] & old_fact["anchors"]
                if not shared_dimensions or not shared_anchors:
                    continue
                if new_fact["numbers"] & old_fact["numbers"]:
                    continue
                dimension = sorted(shared_dimensions)[0]
                dimension_label = NUMERIC_DIMENSION_LABELS.get(dimension, dimension)
                anchor = sorted(shared_anchors, key=lambda token: (-len(token), token))[0]
                return {
                    "detail": (
                        f"同一对象“{anchor}”的{dimension_label}数值不同："
                        f"新内容为 {', '.join(sorted(new_fact['numbers']))}，"
                        f"相关片段为 {', '.join(sorted(old_fact['numbers']))}。"
                    ),
                    "new_snippet": str(new_fact["text"])[:300],
                    "existing_snippet": str(old_fact["text"])[:300],
                }
        return None

    def _state_statements(self, text: str) -> list[dict[str, Any]]:
        statements: list[dict[str, Any]] = []
        document_anchors = self._document_anchors(text)
        for sentence in SENTENCE_SPLIT_RE.split(text):
            sentence = sentence.strip()
            if not sentence:
                continue
            states = self._state_signals(sentence)
            anchors = self._anchor_tokens(sentence) | document_anchors
            if not states or not anchors:
                continue
            statements.append({
                "states": states,
                "anchors": anchors,
                "temporal": self._contains_any(sentence, TEMPORAL_TRANSITION_TERMS),
                "text": sentence,
            })
        return statements

    def _state_conflict(
        self,
        left: list[dict[str, Any]],
        right: list[dict[str, Any]],
    ) -> dict[str, str] | None:
        for new_fact in left:
            for old_fact in right:
                if new_fact["temporal"] or old_fact["temporal"]:
                    continue
                shared_anchors = new_fact["anchors"] & old_fact["anchors"]
                if not shared_anchors:
                    continue
                conflicts = [
                    pair
                    for pair in STATE_CONFLICTS
                    if pair <= (new_fact["states"] | old_fact["states"])
                    and pair & new_fact["states"]
                    and pair & old_fact["states"]
                ]
                if not conflicts:
                    continue
                anchor = sorted(shared_anchors, key=lambda token: (-len(token), token))[0]
                new_states = ", ".join(sorted(new_fact["states"]))
                old_states = ", ".join(sorted(old_fact["states"]))
                return {
                    "detail": f"同一对象“{anchor}”出现对立状态：新内容为 {new_states}，相关片段为 {old_states}。",
                    "new_snippet": str(new_fact["text"])[:300],
                    "existing_snippet": str(old_fact["text"])[:300],
                }
        return None

    def _anchor_tokens(self, text: str) -> set[str]:
        dimension_terms = {term for terms in NUMERIC_DIMENSIONS.values() for term in terms}
        state_terms = {term for terms in STATE_SIGNALS.values() for term in terms}
        excluded = ANCHOR_STOP_TOKENS | dimension_terms | state_terms | TEMPORAL_TRANSITION_TERMS
        cleaned = text
        for term in sorted(excluded, key=len, reverse=True):
            cleaned = re.sub(re.escape(term), " ", cleaned, flags=re.IGNORECASE)
        return {
            token
            for token in self._tokens(cleaned)
            if any("\u4e00" <= char <= "\u9fff" for char in token)
            and 2 <= len(token) <= 8
            and not CHINESE_NUMBER_TOKEN_RE.fullmatch(token)
        }

    def _document_anchors(self, text: str) -> set[str]:
        for raw_line in text.splitlines()[:20]:
            line = raw_line.strip()
            if not line:
                continue
            heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if heading:
                return self._anchor_tokens(heading.group(1))
            field = re.match(r"^(?:name|title|姓名|名称)\s*[:：]\s*(.+?)\s*$", line, flags=re.IGNORECASE)
            if field:
                return self._anchor_tokens(field.group(1))
            break
        return set()

    def _tokens(self, text: str) -> list[str]:
        tokens: list[str] = []
        for raw in TOKEN_RE.findall(text):
            token = raw.lower()
            if token in GENERIC_TOKENS:
                continue
            if token.replace(".", "", 1).isdigit():
                continue
            if re.fullmatch(r"[a-z_]{1,2}", token):
                continue
            if all("\u4e00" <= char <= "\u9fff" for char in token):
                tokens.extend(self._chinese_tokens(token))
                continue
            tokens.append(token)
        return tokens

    def _chinese_tokens(self, text: str) -> list[str]:
        if len(text) <= 1:
            return []
        tokens: set[str] = set()
        if len(text) <= 6 and text not in GENERIC_CHINESE_TOKENS:
            tokens.add(text)
        for size in (2, 3, 4):
            if len(text) < size:
                continue
            for index in range(0, len(text) - size + 1):
                token = text[index:index + size]
                if token in GENERIC_CHINESE_TOKENS:
                    continue
                tokens.add(token)
        return list(tokens)

    def _meaningful_numbers(self, text: str) -> set[str]:
        cleaned_lines: list[str] = []
        for line in text.splitlines():
            cleaned_lines.append(STRUCTURAL_NUMBER_LINE_RE.sub("", line))
        cleaned = "\n".join(cleaned_lines)
        numbers = {self._normalize_arabic_number(value) for value in NUMBER_RE.findall(cleaned)}
        for value in CHINESE_NUMBER_RE.findall(cleaned):
            parsed = self._parse_chinese_number(value)
            if parsed is not None:
                numbers.add(self._normalize_arabic_number(str(parsed)))
        return {number for number in numbers if number not in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}}

    def _normalize_arabic_number(self, value: str) -> str:
        if "." not in value:
            return str(int(value))
        return value.rstrip("0").rstrip(".")

    def _parse_chinese_number(self, value: str) -> int | float | None:
        if not value:
            return None
        if "点" in value:
            integer_text, decimal_text = value.split("点", 1)
            integer = self._parse_chinese_integer(integer_text)
            digits = "".join(str(self._chinese_digit(char)) for char in decimal_text)
            if integer is None or not digits:
                return None
            return float(f"{integer}.{digits}")
        return self._parse_chinese_integer(value)

    def _parse_chinese_integer(self, value: str) -> int | None:
        digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        units = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
        if not value or any(char not in digits and char not in units for char in value):
            return None
        if not any(char in units for char in value):
            return int("".join(str(digits[char]) for char in value))

        total = 0
        section = 0
        number = 0
        for char in value:
            if char in digits:
                number = digits[char]
                continue
            unit = units[char]
            if unit < 10000:
                section += (number or 1) * unit
            else:
                section += number
                total += section * unit
                section = 0
            number = 0
        return total + section + number

    def _chinese_digit(self, value: str) -> int:
        return {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}[value]

    def _contains_any(self, text: str, words: set[str]) -> bool:
        lowered = text.lower()
        return any(word.lower() in lowered for word in words)

    def _state_signals(self, text: str) -> set[str]:
        lowered = text.lower()
        signals: set[str] = set()
        for name, phrases in STATE_SIGNALS.items():
            if any(phrase.lower() in lowered for phrase in phrases):
                signals.add(name)
        if "presence_missing" in signals and "presence_exists" in signals:
            signals.discard("presence_exists")
        if "ruin_intact" in signals and "ruin_destroyed" in signals and "未被摧毁" in text:
            signals.discard("ruin_destroyed")
        return signals

    def _issue(
        self,
        severity: str,
        title: str,
        path: str,
        detail: str,
        snippet: str,
        item: dict[str, Any],
        new_snippet: str = "",
        existing_snippet: str = "",
    ) -> dict[str, Any]:
        return {
            "severity": severity,
            "title": title,
            "path": path,
            "detail": detail,
            "suggestion": "",
            "snippet": snippet,
            "new_snippet": new_snippet,
            "existing_snippet": existing_snippet or snippet,
            "score": item.get("score"),
            "collection": item.get("collection"),
        }
