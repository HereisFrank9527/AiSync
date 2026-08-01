from __future__ import annotations

from typing import Any

from app.change_sets import ProposedFileChange, create_change_set, hash_text, normalize_editable_path
from app.projects.context import ProjectContext
from app.projects.outline import OUTLINE_INDEX_PATH, OUTLINE_MARKDOWN_PATH, build_outline_index
from app.tools.base import BaseTool, ToolFileAccess, ToolPresentation, ToolResult


MAX_OUTLINE_NODE_OPERATIONS = 24
MAX_LINE_OPERATIONS_PER_FILE = 24
OUTLINE_NODE_OPERATIONS = (
    "replace_outline_node",
    "insert_before_outline_node",
    "insert_after_outline_node",
)


class FileChangeProposalTool(BaseTool):
    name = "file_change_proposal"
    description = (
        "提出一组待用户确认的项目文件改动，并生成差异预览。"
        "已有文件的局部修改支持 replace_text、replace_lines、append_text 和 prepend_text，避免重发完整文件。"
        "大纲支持按区块 ID 替换、删除，以及在指定区块前后插入局部 Markdown。"
        "可用于修改项目根目录 AGENT.md 中的长期工作习惯和当前文风。"
        "清理 temp/ 目录时支持 delete_directory，并自动展开为逐文件删除。"
        "此工具默认不会直接写入正式文件，用户确认后才会应用。"
    )
    category = "patch"
    write_policy = "proposal"
    requires_confirmation = True
    agent_boundary = (
        "用于清理、删除、替换、跨文件修补等补丁式修改。"
        "用户要求长期记住工作习惯或文风时，也用于更新 AGENT.md。"
        "当任务是改掉某段既有正式文件内容时，优先使用此工具，而不是生成类工具。"
        "大纲局部修改使用 replace_outline_node、insert_before_outline_node 或 insert_after_outline_node，"
        "其他局部修改优先使用 replace_text；如果已通过 read_project_files 读取行范围，优先使用带 source_hash 的 replace_lines；"
        "只有新建文件或整体重写时才使用 write。"
    )

    def file_access(self) -> ToolFileAccess:
        return ToolFileAccess(
            read=["**/*.md", "**/*.txt", "**/*.json", "**/*.yaml", "**/*.yml", "**/*.csv"],
            write=["仅在用户确认改动包后写入"],
            generate=[".aisync/change_sets/*.json"],
        )

    def presentation(self) -> ToolPresentation:
        return ToolPresentation(type="changeset:proposal", description="文件改动差异预览")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "这组改动的简短标题，例如：清理旧权限来源残留。",
                },
                "summary": {
                    "type": "string",
                    "description": "说明为什么要做这些改动，以及影响范围。",
                },
                "changes": {
                    "type": "array",
                    "description": "需要用户确认后再应用的文件改动列表。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "项目内相对路径，只支持 md/txt/json/yaml/yml/csv。",
                            },
                            "operation": {
                                "type": "string",
                                "enum": [
                                    "write",
                                    "replace_text",
                                    "replace_lines",
                                    "replace_outline_node",
                                    "insert_before_outline_node",
                                    "insert_after_outline_node",
                                    "append_text",
                                    "prepend_text",
                                    "delete",
                                    "delete_directory",
                                ],
                                "default": "write",
                                "description": (
                                    "write 表示写入完整新内容；replace_text 精确替换唯一旧文本；"
                                    "replace_lines 按读取时的文件哈希替换指定行，避免文本漂移时误改；"
                                    "replace_outline_node 按大纲区块 ID 替换 plot/outline.md 中的完整区块；"
                                    "insert_before_outline_node/insert_after_outline_node 在指定大纲区块前后插入内容；"
                                    "append_text/prepend_text 追加或前置文本；delete 表示删除整个文件；"
                                    "delete_directory 仅允许清理 temp/ 下的目录，并会在差异预览中展开为逐文件删除。"
                                ),
                            },
                            "new_content": {
                                "type": "string",
                                "description": "operation=write 时必填，必须是该文件应用后的完整内容。",
                            },
                            "old_text": {
                                "type": "string",
                                "description": "operation=replace_text 时必填，必须在当前或前序补丁结果中恰好出现一次。",
                            },
                            "start_line": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "replace_lines 的起始行（包含，行号从 1 开始）。",
                            },
                            "end_line": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "replace_lines 的结束行（包含）。",
                            },
                            "source_hash": {
                                "type": "string",
                                "description": "read_project_files 返回的文件 SHA-256；文件变化时拒绝生成改动包。",
                            },
                            "node_id": {
                                "type": "string",
                                "description": (
                                    "大纲区块替换或插入操作时必填。先用 read_project_files inspect "
                                    "plot/outline.md 获取区块 ID。"
                                ),
                            },
                            "new_text": {
                                "type": "string",
                                "description": (
                                    "文本替换、大纲区块替换/插入及追加操作使用的局部新文本；"
                                    "replace_text 或 replace_outline_node 可传空字符串删除目标，"
                                    "大纲插入操作必须提供非空 Markdown。"
                                ),
                            },
                            "reason": {
                                "type": "string",
                                "description": "这个文件为什么要改。",
                            },
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                },
            },
            "required": ["title", "changes"],
            "additionalProperties": False,
        }

    async def execute(self, params: dict[str, Any], context: ProjectContext) -> ToolResult:
        raw_changes = params.get("changes")
        if not isinstance(raw_changes, list):
            raise ValueError("changes must be a list")

        staged: dict[str, dict[str, Any]] = {}
        ordered_paths: list[str] = []
        expanded_directories: list[str] = []
        operation_counts: dict[str, int] = {}

        def remember_operation(path: str, operation: str, reason: str) -> None:
            state = staged[path]
            state["source_operations"].append(operation)
            if reason and reason not in state["reasons"]:
                state["reasons"].append(reason)
            operation_counts[operation] = operation_counts.get(operation, 0) + 1

        for item in raw_changes:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            operation = str(item.get("operation") or "write")
            reason = str(item.get("reason") or "")
            if operation == "delete_directory":
                directory = self._normalize_temp_directory(path)
                files = await context.list_files(directory)
                editable_files: list[str] = []
                for file_path in files:
                    try:
                        normalized = normalize_editable_path(file_path)
                    except ValueError:
                        continue
                    if normalized == "temp/.aisync-temp.json" or not normalized.startswith("temp/"):
                        continue
                    editable_files.append(normalized)
                if not editable_files:
                    raise ValueError(f"目录没有可清理的文本文件：{directory}")
                if len(editable_files) > 200:
                    raise ValueError("单个目录清理最多支持 200 个文本文件")
                expanded_directories.append(directory)
                for file_path in sorted(editable_files):
                    if file_path in staged:
                        raise ValueError(f"同一文件不能同时执行目录删除和其他改动：{file_path}")
                    staged[file_path] = {
                        "operation": "delete",
                        "content": None,
                        "source_operations": [],
                        "reasons": [],
                        "mode": "delete",
                    }
                    ordered_paths.append(file_path)
                    remember_operation(file_path, "delete_directory", reason or f"清理 {directory}")
                continue
            if operation not in {
                "write",
                "replace_text",
                "replace_lines",
                *OUTLINE_NODE_OPERATIONS,
                "append_text",
                "prepend_text",
                "delete",
            }:
                raise ValueError(f"unsupported operation: {operation}")
            path = normalize_editable_path(path)

            if operation in OUTLINE_NODE_OPERATIONS:
                if path != OUTLINE_MARKDOWN_PATH:
                    raise ValueError(f"大纲区块操作仅支持 {OUTLINE_MARKDOWN_PATH}")
                if "new_text" not in item or item.get("new_text") is None:
                    raise ValueError(f"{operation} operation requires new_text: {path}")
                node_id = str(item.get("node_id") or "").strip()
                if not node_id:
                    raise ValueError(f"{operation} operation requires node_id")
                new_text = str(item.get("new_text"))
                if operation != "replace_outline_node" and not new_text:
                    raise ValueError(f"{operation} operation requires non-empty new_text")

                state = staged.get(path)
                if state is None:
                    if not await context.exists(path):
                        raise ValueError(f"大纲文件不存在：{path}")
                    content = await context.read_text(path)
                    previous: Any = None
                    if await context.exists(OUTLINE_INDEX_PATH):
                        try:
                            previous = await context.read_json(OUTLINE_INDEX_PATH)
                        except (OSError, ValueError):
                            previous = None
                    outline_index = build_outline_index(content, previous)
                    state = {
                        "operation": "write",
                        "content": content,
                        "source_operations": [],
                        "reasons": [],
                        "mode": "outline_patch",
                        "outline_nodes": {
                            str(node.get("id") or ""): dict(node)
                            for node in outline_index.get("nodes") or []
                            if isinstance(node, dict) and node.get("id")
                        },
                        "outline_operations": [],
                        "outline_node_ids": [],
                    }
                    staged[path] = state
                    ordered_paths.append(path)
                elif state["mode"] != "outline_patch":
                    raise ValueError(f"大纲区块补丁不能与同一文件的其他操作混用：{path}")

                if len(state["outline_operations"]) >= MAX_OUTLINE_NODE_OPERATIONS:
                    raise ValueError(f"一次最多执行 {MAX_OUTLINE_NODE_OPERATIONS} 个大纲区块操作")
                if node_id in state["outline_node_ids"]:
                    raise ValueError(f"同一大纲区块不能重复修改：{node_id}")
                node = state["outline_nodes"].get(node_id)
                if not node:
                    raise ValueError(f"大纲区块不存在或已变化：{node_id}")
                state["outline_operations"].append(
                    {
                        "operation": operation,
                        "node_id": node_id,
                        "start_line": int(node.get("source_start_line") or 0),
                        "end_line": int(node.get("source_end_line") or 0),
                        "new_text": new_text,
                        "order": len(state["outline_operations"]),
                    }
                )
                state["outline_node_ids"].append(node_id)
                remember_operation(path, operation, reason)
                continue

            if operation == "write":
                if path in staged:
                    raise ValueError(f"完整写入不能与同一文件的其他操作混用：{path}")
                if "new_content" not in item or item.get("new_content") is None:
                    raise ValueError(f"write operation requires new_content: {path}")
                staged[path] = {
                    "operation": "write",
                    "content": str(item.get("new_content")),
                    "source_operations": [],
                    "reasons": [],
                    "mode": "write",
                    "outline_node_ids": [],
                }
                ordered_paths.append(path)
                remember_operation(path, operation, reason)
                continue

            if operation == "delete":
                if path in staged:
                    raise ValueError(f"删除不能与同一文件的其他操作混用：{path}")
                if not await context.exists(path):
                    raise ValueError(f"cannot delete missing file: {path}")
                staged[path] = {
                    "operation": "delete",
                    "content": None,
                    "source_operations": [],
                    "reasons": [],
                    "mode": "delete",
                    "outline_node_ids": [],
                }
                ordered_paths.append(path)
                remember_operation(path, operation, reason)
                continue

            state = staged.get(path)
            if state is None:
                if not await context.exists(path):
                    raise ValueError(f"局部补丁目标文件不存在：{path}")
                current_content = await context.read_text(path)
                state = {
                    "operation": "write",
                    "content": current_content,
                    "source_operations": [],
                    "reasons": [],
                    "mode": "patch",
                    "source_hash": hash_text(current_content),
                    "line_operations": [],
                    "outline_node_ids": [],
                }
                staged[path] = state
                ordered_paths.append(path)
            elif state["mode"] != "patch":
                raise ValueError(f"局部补丁不能与同一文件的完整写入或删除混用：{path}")

            raw_new_text = item.get("new_text")
            if operation == "replace_lines" and raw_new_text is None:
                raw_new_text = item.get("new_content")
            if raw_new_text is None:
                raise ValueError(f"{operation} operation requires new_text: {path}")
            new_text = str(raw_new_text)
            content = str(state["content"])
            if operation == "replace_lines":
                if any(source_operation != "replace_lines" for source_operation in state["source_operations"]):
                    raise ValueError(f"replace_lines 不能与同一文件的其他局部操作混用：{path}")
                line_operations = state["line_operations"]
                if len(line_operations) >= MAX_LINE_OPERATIONS_PER_FILE:
                    raise ValueError(f"同一文件一次最多执行 {MAX_LINE_OPERATIONS_PER_FILE} 个 replace_lines 操作：{path}")
                source_hash = str(item.get("source_hash") or "").strip().lower()
                if not source_hash:
                    raise ValueError(f"replace_lines operation requires source_hash: {path}")
                if source_hash != state.get("source_hash") or source_hash != hash_text(content):
                    raise ValueError(f"文件内容已变化，请重新读取后再生成行范围改动：{path}")
                try:
                    start_line = int(item.get("start_line") or 0)
                    end_line = int(item.get("end_line") or 0)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"replace_lines 行号无效：{path}") from exc
                lines = content.splitlines(keepends=True)
                if start_line < 1 or end_line < start_line or end_line > len(lines):
                    raise ValueError(f"replace_lines 行号超出范围：{path}")
                if any(
                    not (end_line < existing["start_line"] or start_line > existing["end_line"])
                    for existing in line_operations
                ):
                    raise ValueError(f"replace_lines 行范围不能重叠：{path} 第 {start_line}-{end_line} 行")
                line_operations.append(
                    {
                        "start_line": start_line,
                        "end_line": end_line,
                        "new_text": new_text,
                    }
                )
            elif operation == "replace_text":
                if state["line_operations"]:
                    raise ValueError(f"replace_lines 不能与同一文件的其他局部操作混用：{path}")
                old_text = str(item.get("old_text") or "")
                if not old_text:
                    raise ValueError(f"replace_text operation requires non-empty old_text: {path}")
                matches = content.count(old_text)
                if matches != 1:
                    raise ValueError(f"replace_text 必须唯一匹配：{path}，实际匹配 {matches} 处")
                state["content"] = content.replace(old_text, new_text, 1)
            elif operation == "append_text":
                if state["line_operations"]:
                    raise ValueError(f"replace_lines 不能与同一文件的其他局部操作混用：{path}")
                if not new_text:
                    raise ValueError(f"append_text requires non-empty new_text: {path}")
                state["content"] = content + new_text
            else:
                if state["line_operations"]:
                    raise ValueError(f"replace_lines 不能与同一文件的其他局部操作混用：{path}")
                if not new_text:
                    raise ValueError(f"prepend_text requires non-empty new_text: {path}")
                state["content"] = new_text + content
            remember_operation(path, operation, reason)

        for state in staged.values():
            if state["mode"] == "outline_patch":
                state["content"] = self._apply_outline_operations(
                    str(state["content"]),
                    list(state["outline_operations"]),
                )
            elif state["mode"] == "patch" and state["line_operations"]:
                state["content"] = self._apply_line_operations(
                    str(state["content"]),
                    list(state["line_operations"]),
                )

        changes = [
            ProposedFileChange(
                path=path,
                operation=staged[path]["operation"],
                new_content=staged[path]["content"],
                reason="；".join(staged[path]["reasons"]),
                source_operations=list(staged[path]["source_operations"]),
                outline_node_ids=list(staged[path].get("outline_node_ids") or []),
            )
            for path in ordered_paths
        ]
        if not changes:
            raise ValueError("changes must not be empty")
        record = await create_change_set(
            context,
            title=str(params.get("title") or ""),
            summary=str(params.get("summary") or ""),
            changes=changes,
        )
        data = record.model_dump()
        data["changes"] = [
            {
                "path": change.path,
                "operation": change.operation,
                "old_hash": change.old_hash,
                "diff": change.diff,
                "reason": change.reason,
                "old_length": len(change.old_content),
                "new_length": len(change.new_content or ""),
                "source_operations": list(change.source_operations),
                "outline_node_ids": list(change.outline_node_ids),
            }
            for change in record.changes
        ]
        return ToolResult(
            content=(
                f"已生成待确认改动：{record.title}，共 {len(record.changes)} 个文件。"
                "请在前端差异预览中选择应用或丢弃。"
            ),
            ui_hint={"type": "changeset:proposal", "data": data},
            metadata={
                "changeset_id": record.id,
                "change_count": len(record.changes),
                "paths": [change.path for change in record.changes],
                "expanded_directories": expanded_directories,
                "operation_counts": operation_counts,
                "outline_node_ids": {
                    path: list(staged[path].get("outline_node_ids") or [])
                    for path in ordered_paths
                    if staged[path].get("outline_node_ids")
                },
            },
        )

    def _apply_outline_operations(
        self,
        content: str,
        operations: list[dict[str, Any]],
    ) -> str:
        lines = content.splitlines(keepends=True)
        line_ending = "\r\n" if "\r\n" in content else "\n"
        preserve_final_newline = content.endswith(("\n", "\r"))
        ordered = sorted(
            operations,
            key=lambda item: (
                int(item["end_line"] if item["operation"] == "insert_after_outline_node" else item["start_line"] - 1),
                1 if item["operation"] == "replace_outline_node" else 0,
                int(item["order"]),
            ),
            reverse=True,
        )
        for item in ordered:
            operation = str(item["operation"])
            start_line = int(item["start_line"])
            end_line = int(item["end_line"])
            if start_line < 1 or end_line < start_line or end_line > len(lines):
                raise ValueError(f"大纲区块行号已失效：{item['node_id']}")
            normalized = self._normalize_outline_text(str(item["new_text"]), line_ending)
            if operation == "replace_outline_node":
                has_following_line = end_line < len(lines)
                if normalized and (has_following_line or preserve_final_newline) and not normalized.endswith(line_ending):
                    normalized += line_ending
                lines[start_line - 1:end_line] = [normalized] if normalized else []
                continue

            insert_at = start_line - 1 if operation == "insert_before_outline_node" else end_line
            if insert_at > 0 and not lines[insert_at - 1].endswith(("\n", "\r")) and not normalized.startswith(("\n", "\r")):
                normalized = line_ending + normalized
            has_following_line = insert_at < len(lines)
            if (has_following_line or preserve_final_newline) and not normalized.endswith(line_ending):
                normalized += line_ending
            lines[insert_at:insert_at] = [normalized]
        return "".join(lines)

    def _apply_line_operations(
        self,
        content: str,
        operations: list[dict[str, Any]],
    ) -> str:
        lines = content.splitlines(keepends=True)
        original_line_count = len(lines)
        line_ending = "\r\n" if "\r\n" in content else "\n"
        for item in sorted(operations, key=lambda operation: int(operation["start_line"]), reverse=True):
            start_line = int(item["start_line"])
            end_line = int(item["end_line"])
            replacement = (
                str(item["new_text"])
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .replace("\n", line_ending)
            )
            if replacement and end_line < original_line_count and not replacement.endswith(line_ending):
                replacement += line_ending
            lines[start_line - 1:end_line] = [replacement] if replacement else []
        return "".join(lines)

    def _normalize_outline_text(self, content: str, line_ending: str) -> str:
        return content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", line_ending)

    def _normalize_temp_directory(self, path: str) -> str:
        normalized = path.replace("\\", "/").strip().strip("/")
        parts = normalized.split("/")
        if (
            not normalized
            or any(part in {"", ".", ".."} for part in parts)
            or any(part.startswith(".") for part in parts)
            or parts[0] != "temp"
        ):
            raise ValueError("delete_directory 仅允许清理 temp/ 下的目录")
        return normalized
