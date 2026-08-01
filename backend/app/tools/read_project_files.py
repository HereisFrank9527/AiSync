from __future__ import annotations

import re
from typing import Any

from app.change_sets import hash_text, normalize_editable_path
from app.projects.context import ProjectContext
from app.projects.outline import OUTLINE_INDEX_PATH, OUTLINE_MARKDOWN_PATH, build_outline_index
from app.tools.base import BaseTool, ToolFileAccess, ToolResult

MAX_FILES = 12
MAX_SELECTIONS = 12
MAX_LINES_PER_SELECTION = 800
DEFAULT_FILE_CHARS = 20_000
MAX_FILE_CHARS = 80_000
MAX_TOTAL_CHARS = 160_000
MAX_OUTLINE_NODES_INSPECTED = 160
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")


class ReadProjectFilesTool(BaseTool):
    name = "read_project_files"
    description = (
        "按项目内相对路径精确读取文本文件。长文件可先 inspect 查看总行数和 Markdown 标题行，"
        "再用 selections 自选起止行读取局部；检查 plot/outline.md 时还会返回可用于局部补丁的"
        "大纲区块 ID、类型和源行范围。整体重写时仍可通过 paths 读取全文。"
    )
    category = "search"
    write_policy = "none"
    has_frontend_ui = False
    agent_boundary = (
        "只读取明确指定的项目文本文件，不搜索、不修改文件。长文件优先先 inspect 后分段读取；"
        "只有整体重写或全局核对时才读取全文。"
    )

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(read=["**/*.md", "**/*.txt", "**/*.json", "**/*.yaml", "**/*.yml", "**/*.csv"])

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["content", "inspect"],
                    "default": "content",
                    "description": "inspect 只返回行数、字符数和 Markdown 标题行；content 返回正文。",
                },
                "paths": {
                    "type": "array",
                    "description": (
                        f"要读取全文的项目相对路径，或 inspect 时要检查的路径，最多 {MAX_FILES} 个。"
                        "长文件不要默认全文读取。"
                    ),
                    "items": {"type": "string"},
                    "maxItems": MAX_FILES,
                },
                "selections": {
                    "type": "array",
                    "description": (
                        f"按行读取的文件范围，最多 {MAX_SELECTIONS} 段，每段最多 {MAX_LINES_PER_SELECTION} 行。"
                        "建议先 inspect，再根据标题行选择范围。"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "start_line": {"type": "integer", "minimum": 1},
                            "end_line": {"type": "integer", "minimum": 1},
                        },
                        "required": ["path", "start_line", "end_line"],
                        "additionalProperties": False,
                    },
                    "maxItems": MAX_SELECTIONS,
                },
                "max_chars_per_file": {
                    "type": "integer",
                    "description": "每个全文文件或单个行范围最多返回字符数。",
                    "default": DEFAULT_FILE_CHARS,
                    "minimum": 1000,
                    "maximum": MAX_FILE_CHARS,
                },
            },
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        mode = str(params.get("mode") or "content").strip().lower()
        if mode not in {"content", "inspect"}:
            raise ValueError("mode must be content or inspect")
        paths = self._normalize_paths(params.get("paths"))
        selections = self._normalize_selections(params.get("selections"))
        if mode == "inspect":
            inspect_paths = list(paths)
            for selection in selections:
                if selection["path"] not in inspect_paths:
                    inspect_paths.append(selection["path"])
            if not inspect_paths:
                raise ValueError("inspect mode requires paths or selections")
            return await self._inspect_files(inspect_paths, context)
        if not paths and not selections:
            raise ValueError("content mode requires paths or selections")

        max_chars = max(1000, min(int(params.get("max_chars_per_file") or DEFAULT_FILE_CHARS), MAX_FILE_CHARS))
        sections: list[str] = []
        read_paths: list[str] = []
        missing_paths: list[str] = []
        truncated_paths: list[str] = []
        range_metadata: list[dict[str, Any]] = []
        total_chars = 0

        for path in paths:
            if not await context.exists(path):
                missing_paths.append(path)
                continue
            content = await context.read_text(path)
            remaining = MAX_TOTAL_CHARS - total_chars
            if remaining <= 0:
                truncated_paths.append(path)
                continue
            limit = min(max_chars, remaining)
            shown = content[:limit]
            if len(shown) < len(content):
                shown += "\n[文件内容已截断]"
                truncated_paths.append(path)
            sections.append(f"## {path}\n\n文件 SHA-256：{hash_text(content)}\n\n{shown}")
            read_paths.append(path)
            total_chars += len(shown)

        for selection in selections:
            path = selection["path"]
            if not await context.exists(path):
                if path not in missing_paths:
                    missing_paths.append(path)
                continue
            content = await context.read_text(path)
            lines = content.splitlines()
            line_count = len(lines)
            start_line = selection["start_line"]
            requested_end = selection["end_line"]
            if start_line > line_count and line_count > 0:
                raise ValueError(f"起始行超出文件范围：{path} 共有 {line_count} 行")
            if line_count == 0:
                shown = "[空文件]"
                returned_end = 0
                truncated = False
            else:
                end_line = min(requested_end, line_count)
                remaining = MAX_TOTAL_CHARS - total_chars
                if remaining <= 0:
                    truncated_paths.append(path)
                    continue
                shown, returned_end, truncated = self._numbered_range(
                    lines,
                    start_line,
                    end_line,
                    min(max_chars, remaining),
                )
                if truncated:
                    shown += "\n[所选行范围已截断]"
                    truncated_paths.append(path)
            sections.append(
                f"## {path}（第 {start_line}～{returned_end} 行 / 共 {line_count} 行）\n"
                f"文件 SHA-256：{hash_text(content)}\n\n{shown}"
            )
            if path not in read_paths:
                read_paths.append(path)
            total_chars += len(shown)
            range_metadata.append(
                {
                    "path": path,
                    "source_hash": hash_text(content),
                    "requested_start_line": start_line,
                    "requested_end_line": requested_end,
                    "returned_end_line": returned_end,
                    "line_count": line_count,
                    "truncated": truncated,
                }
            )

        if not read_paths:
            raise ValueError("指定文件均不存在或无法读取")
        if missing_paths:
            sections.append("## 未找到\n\n" + "\n".join(f"- {path}" for path in missing_paths))
        return ToolResult(
            content="\n\n".join(sections),
            metadata={
                "mode": "content",
                "read_count": len(read_paths),
                "paths": read_paths,
                "missing_paths": missing_paths,
                "truncated_paths": list(dict.fromkeys(truncated_paths)),
                "returned_chars": total_chars,
                "selections": range_metadata,
            },
        )

    async def _inspect_files(self, paths: list[str], context: ProjectContext) -> ToolResult:
        sections: list[str] = []
        files: list[dict[str, Any]] = []
        missing_paths: list[str] = []
        for path in paths:
            if not await context.exists(path):
                missing_paths.append(path)
                continue
            content = await context.read_text(path)
            lines = content.splitlines()
            headings = []
            for line_number, line in enumerate(lines, start=1):
                match = HEADING_RE.match(line)
                if not match:
                    continue
                headings.append(
                    {
                        "line": line_number,
                        "level": len(match.group(1)),
                        "title": match.group(2).strip()[:160],
                    }
                )
                if len(headings) >= 60:
                    break
            lines_out = [
                f"- 总行数：{len(lines)}",
                f"- 字符数：{len(content)}",
                f"- 文件 SHA-256：{hash_text(content)}",
            ]
            if headings:
                lines_out.append("- Markdown 标题：")
                lines_out.extend(
                    f"  - L{item['line']} {'#' * item['level']} {item['title']}"
                    for item in headings
                )
            else:
                lines_out.append("- Markdown 标题：无")
            outline_nodes: list[dict[str, Any]] = []
            outline_source_hash = ""
            if path == OUTLINE_MARKDOWN_PATH:
                previous: Any = None
                if await context.exists(OUTLINE_INDEX_PATH):
                    try:
                        previous = await context.read_json(OUTLINE_INDEX_PATH)
                    except (OSError, ValueError):
                        previous = None
                outline_index = build_outline_index(content, previous)
                outline_source_hash = str(outline_index.get("source_hash") or "")
                for node in (outline_index.get("nodes") or [])[:MAX_OUTLINE_NODES_INSPECTED]:
                    if not isinstance(node, dict):
                        continue
                    outline_nodes.append(
                        {
                            "id": str(node.get("id") or ""),
                            "kind": str(node.get("kind") or "section"),
                            "title": str(node.get("heading") or node.get("title") or ""),
                            "source_start_line": int(node.get("source_start_line") or 0),
                            "source_end_line": int(node.get("source_end_line") or 0),
                            "parent_id": node.get("parent_id"),
                        }
                    )
                lines_out.append("- 大纲区块（局部修改时使用区块 ID 和行范围）：")
                lines_out.extend(
                    (
                        f"  - {node['id']} | {node['kind']} | "
                        f"L{node['source_start_line']}-L{node['source_end_line']} | {node['title']}"
                    )
                    for node in outline_nodes
                )
                total_nodes = len(outline_index.get("nodes") or [])
                if total_nodes > len(outline_nodes):
                    lines_out.append(f"  - [仅显示前 {len(outline_nodes)} / {total_nodes} 个区块]")
            sections.append(f"## {path}\n\n" + "\n".join(lines_out))
            files.append(
                {
                    "path": path,
                    "line_count": len(lines),
                    "characters": len(content),
                    "source_hash": hash_text(content),
                    "headings": headings,
                    "outline_source_hash": outline_source_hash,
                    "outline_nodes": outline_nodes,
                }
            )
        if not files:
            raise ValueError("指定文件均不存在或无法检查")
        if missing_paths:
            sections.append("## 未找到\n\n" + "\n".join(f"- {path}" for path in missing_paths))
        return ToolResult(
            content="\n\n".join(sections),
            metadata={
                "mode": "inspect",
                "read_count": len(files),
                "paths": [item["path"] for item in files],
                "missing_paths": missing_paths,
                "files": files,
            },
        )

    def _normalize_paths(self, raw_paths: Any) -> list[str]:
        if raw_paths is None:
            return []
        if not isinstance(raw_paths, list):
            raise ValueError("paths must be a list")
        if len(raw_paths) > MAX_FILES:
            raise ValueError(f"一次最多读取 {MAX_FILES} 个文件")
        paths: list[str] = []
        for raw_path in raw_paths:
            path = normalize_editable_path(str(raw_path or ""))
            if path not in paths:
                paths.append(path)
        return paths

    def _normalize_selections(self, raw_selections: Any) -> list[dict[str, Any]]:
        if raw_selections is None:
            return []
        if not isinstance(raw_selections, list):
            raise ValueError("selections must be a list")
        if len(raw_selections) > MAX_SELECTIONS:
            raise ValueError(f"一次最多读取 {MAX_SELECTIONS} 个行范围")
        selections: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()
        for raw in raw_selections:
            if not isinstance(raw, dict):
                raise ValueError("each selection must be an object")
            path = normalize_editable_path(str(raw.get("path") or ""))
            start_line = int(raw.get("start_line") or 0)
            end_line = int(raw.get("end_line") or 0)
            if start_line < 1 or end_line < start_line:
                raise ValueError("selection line range is invalid")
            if end_line - start_line + 1 > MAX_LINES_PER_SELECTION:
                raise ValueError(f"单个行范围最多 {MAX_LINES_PER_SELECTION} 行")
            signature = (path, start_line, end_line)
            if signature in seen:
                continue
            seen.add(signature)
            selections.append({"path": path, "start_line": start_line, "end_line": end_line})
        return selections

    def _numbered_range(
        self,
        lines: list[str],
        start_line: int,
        end_line: int,
        char_limit: int,
    ) -> tuple[str, int, bool]:
        rendered: list[str] = []
        total = 0
        returned_end = start_line - 1
        truncated = False
        for line_number in range(start_line, end_line + 1):
            item = f"{line_number:>6} | {lines[line_number - 1]}"
            additional = len(item) + (1 if rendered else 0)
            if rendered and total + additional > char_limit:
                truncated = True
                break
            if not rendered and len(item) > char_limit:
                item = item[:char_limit]
                truncated = True
            rendered.append(item)
            total += len(item) + (1 if len(rendered) > 1 else 0)
            returned_end = line_number
            if truncated:
                break
        return "\n".join(rendered), returned_end, truncated
