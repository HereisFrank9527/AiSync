from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from app.projects.context import ProjectContext


OUTLINE_HISTORY_DIR = ".aisync/outline_history"
OUTLINE_MARKDOWN_PATH = "plot/outline.md"
OUTLINE_INDEX_PATH = "plot/outline.json"
OUTLINE_INDEX_VERSION = 3

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CHAPTER_HEADING_RE = re.compile(
    r"^(?:第\s*([0-9一二三四五六七八九十百零〇Xx]+)\s*[章节回]|chapter\s*(\d+)|ch[-_\s]*(\d+))\s*[：:.\-\s]*(.*)$",
    re.I,
)
BARE_CHAPTER_HEADING_RE = re.compile(
    r"^(?:第\s*([0-9一二三四五六七八九十百零〇Xx]+)\s*[章节回]|chapter\s*(\d+)|ch[-_\s]*(\d+))"
    r"(?=$|[\s：:.\-])[\s：:.\-]*(.*)$",
    re.I,
)
VOLUME_HEADING_RE = re.compile(
    r"^(?:第\s*[0-9一二三四五六七八九十百零〇Xx]+\s*卷|卷\s*[0-9一二三四五六七八九十百零〇Xx]+)\b",
    re.I,
)


async def snapshot_outline_markdown(
    context: ProjectContext,
    *,
    reason: str,
) -> str | None:
    path = "plot/outline.md"
    if not await context.exists(path):
        return None

    content = await context.read_text(path)
    if not content:
        return None

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    safe_reason = re.sub(r"[^a-z0-9_-]+", "-", reason.strip().lower()).strip("-") or "update"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = f"{OUTLINE_HISTORY_DIR}/{timestamp}-{safe_reason}-{digest}.md"
    if not await context.exists(snapshot_path):
        await context.write_text(snapshot_path, content)
    return snapshot_path


def _normalized_heading(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _outline_node_id(kind: str, heading: str, ordinal: int, chapter_number: str = "") -> str:
    if kind == "chapter" and chapter_number.isdigit():
        return f"outline-{int(chapter_number)}"
    digest = hashlib.sha1(
        f"{kind}\n{_normalized_heading(heading)}\n{ordinal}".encode("utf-8")
    ).hexdigest()[:12]
    return f"outline-{kind}-{digest}"


def _previous_outline_nodes(previous: Any) -> list[dict[str, Any]]:
    if not isinstance(previous, dict):
        return []
    raw_nodes = previous.get("nodes") or previous.get("items") or previous.get("chapters") or []
    if not isinstance(raw_nodes, list):
        return []
    return [dict(item) for item in raw_nodes if isinstance(item, dict)]


def _match_previous_node(
    previous_nodes: list[dict[str, Any]],
    used_ids: set[str],
    *,
    kind: str,
    heading: str,
    chapter_number: str,
    kind_position: int,
) -> dict[str, Any] | None:
    normalized = _normalized_heading(heading)
    for item in previous_nodes:
        item_id = str(item.get("id") or "")
        item_kind = str(item.get("kind") or "chapter")
        item_heading = str(item.get("heading") or item.get("title") or item.get("raw") or "")
        if item_id and item_id not in used_ids and item_kind == kind and _normalized_heading(item_heading) == normalized:
            return item

    if kind == "chapter" and chapter_number:
        for item in previous_nodes:
            item_id = str(item.get("id") or "")
            item_number = str(item.get("chapter_number") or item.get("index") or "")
            if item_id and item_id not in used_ids and item_number == chapter_number:
                return item

    same_kind = [
        item
        for item in previous_nodes
        if str(item.get("kind") or "chapter") == kind and str(item.get("id") or "") not in used_ids
    ]
    if 0 <= kind_position - 1 < len(same_kind):
        return same_kind[kind_position - 1]
    return None


def build_outline_index(content: str, previous: Any = None) -> dict[str, Any]:
    lines = content.splitlines()
    headings: list[dict[str, Any]] = []
    in_fence = False
    for offset, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(stripped)
        if match:
            headings.append(
                {
                    "offset": offset,
                    "line": offset + 1,
                    "level": len(match.group(1)),
                    "heading": match.group(2).strip(),
                    "raw": raw_line,
                    "explicit_heading": True,
                }
            )
            continue
        if BARE_CHAPTER_HEADING_RE.match(stripped):
            headings.append(
                {
                    "offset": offset,
                    "line": offset + 1,
                    "level": 6,
                    "heading": stripped,
                    "raw": raw_line,
                    "explicit_heading": False,
                }
            )

    title = "大纲"
    document_heading_index: int | None = None
    if headings and headings[0]["level"] == 1:
        title = str(headings[0]["heading"] or "大纲")
        document_heading_index = 0

    previous_nodes = _previous_outline_nodes(previous)
    used_ids: set[str] = set()
    kind_counts: dict[str, int] = {}
    chapter_index = 0
    nodes: list[dict[str, Any]] = []
    hierarchy: list[tuple[int, str]] = []

    first_content_offset = 1 if document_heading_index == 0 else 0
    if document_heading_index == 0:
        first_node_offset = int(headings[1]["offset"]) if len(headings) > 1 else len(lines)
    else:
        first_node_offset = int(headings[0]["offset"]) if headings else len(lines)
    intro_body = "\n".join(lines[first_content_offset:first_node_offset]).strip("\n")
    if intro_body.strip():
        intro_id = _outline_node_id("markdown", "开篇说明", 1)
        nodes.append(
            {
                "id": intro_id,
                "kind": "markdown",
                "level": 1,
                "parent_id": None,
                "title": "开篇说明",
                "heading": "",
                "body": intro_body,
                "raw_markdown": intro_body,
                "source_start_line": first_content_offset + 1,
                "source_end_line": first_node_offset,
            }
        )
        used_ids.add(intro_id)

    visible_headings = headings[1:] if document_heading_index == 0 else headings
    for position, heading_info in enumerate(visible_headings):
        start_offset = int(heading_info["offset"])
        end_offset = (
            int(visible_headings[position + 1]["offset"])
            if position + 1 < len(visible_headings)
            else len(lines)
        )
        heading = str(heading_info["heading"])
        level = int(heading_info["level"])
        body = "\n".join(lines[start_offset + 1:end_offset]).strip("\n")
        chapter_pattern = (
            CHAPTER_HEADING_RE
            if bool(heading_info.get("explicit_heading"))
            else BARE_CHAPTER_HEADING_RE
        )
        chapter_match = chapter_pattern.match(heading)
        chapter_number = ""
        if chapter_match:
            kind = "chapter"
            chapter_number = str(chapter_match.group(1) or chapter_match.group(2) or chapter_match.group(3) or "")
            node_title = chapter_match.group(4).strip() or heading
            chapter_index += 1
        elif VOLUME_HEADING_RE.match(heading):
            kind = "volume"
            node_title = heading
        else:
            kind = "section"
            node_title = heading

        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        previous_node = _match_previous_node(
            previous_nodes,
            used_ids,
            kind=kind,
            heading=heading,
            chapter_number=chapter_number,
            kind_position=kind_counts[kind],
        )
        node_id = str(previous_node.get("id") or "") if previous_node else ""
        if not node_id:
            node_id = _outline_node_id(kind, heading, kind_counts[kind], chapter_number)
        unique_id = node_id
        suffix = 2
        while unique_id in used_ids:
            unique_id = f"{node_id}-{suffix}"
            suffix += 1
        node_id = unique_id
        used_ids.add(node_id)

        while hierarchy and hierarchy[-1][0] >= level:
            hierarchy.pop()
        parent_id = hierarchy[-1][1] if hierarchy else None
        hierarchy.append((level, node_id))

        node: dict[str, Any] = {
            "id": node_id,
            "kind": kind,
            "level": level,
            "parent_id": parent_id,
            "title": node_title,
            "heading": heading,
            "body": body,
            "raw_markdown": "\n".join(lines[start_offset:end_offset]).strip("\n"),
            "source_start_line": start_offset + 1,
            "source_end_line": max(start_offset + 1, end_offset),
        }
        if kind == "chapter":
            node.update(
                {
                    "index": chapter_index,
                    "chapter_number": chapter_number,
                    "summary": body,
                    "status": str((previous_node or {}).get("status") or "planned"),
                    "raw": str(heading_info["raw"]),
                }
            )
        nodes.append(node)

    chapter_items = [
        {
            "id": node["id"],
            "index": node["index"],
            "title": node["title"],
            "summary": node["summary"],
            "status": node["status"],
            "raw": node["raw"],
            "kind": "chapter",
            "parent_id": node["parent_id"],
            "source_start_line": node["source_start_line"],
            "source_end_line": node["source_end_line"],
        }
        for node in nodes
        if node["kind"] == "chapter"
    ]
    return {
        "version": OUTLINE_INDEX_VERSION,
        "source": OUTLINE_MARKDOWN_PATH,
        "source_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "title": title,
        "nodes": nodes,
        "items": chapter_items,
    }


async def refresh_outline_index(context: ProjectContext) -> dict[str, Any]:
    if await context.exists(OUTLINE_MARKDOWN_PATH):
        content = await context.read_text(OUTLINE_MARKDOWN_PATH)
    else:
        content = "# 大纲\n"
        await context.write_text(OUTLINE_MARKDOWN_PATH, content)

    previous: Any = None
    if await context.exists(OUTLINE_INDEX_PATH):
        try:
            previous = await context.read_json(OUTLINE_INDEX_PATH)
        except (OSError, ValueError):
            previous = None
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if (
        isinstance(previous, dict)
        and previous.get("version") == OUTLINE_INDEX_VERSION
        and previous.get("source_hash") == source_hash
        and isinstance(previous.get("nodes"), list)
    ):
        return previous
    data = build_outline_index(content, previous)
    await context.write_json(OUTLINE_INDEX_PATH, data)
    return data


def outline_items_from_markdown(content: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        chapter = (
            CHAPTER_HEADING_RE.match(heading.group(2).strip())
            if heading
            else BARE_CHAPTER_HEADING_RE.match(line)
        )
        if chapter or heading:
            if current:
                items.append(current)
            title = ""
            index = len(items) + 1
            if chapter:
                number = chapter.group(1) or chapter.group(2) or chapter.group(3)
                title = chapter.group(4).strip() or line.lstrip("#").strip()
                if number and number.isdigit():
                    index = int(number)
            elif heading:
                title = heading.group(2).strip()
            current = {"index": index, "title": title, "summary": "", "raw": line}
            continue

        if current:
            current["summary"] = f"{current['summary']}\n{line}".strip()

    if current:
        items.append(current)
    return items


def chapter_outline_items_from_markdown(content: str) -> list[dict[str, Any]]:
    """Strict importer: only explicit chapter headings become outline nodes."""
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    stop_section = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:卷[一二三四五六七八九十0-9]+|核心问题|双线推进|[A-ZＡ-Ｚ]\s*线|关键转折)\b",
        re.I,
    )

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        chapter = (
            CHAPTER_HEADING_RE.match(heading.group(2).strip())
            if heading
            else BARE_CHAPTER_HEADING_RE.match(line)
        )
        if chapter:
            if current:
                items.append(current)
            number = chapter.group(1) or chapter.group(2) or chapter.group(3)
            title = chapter.group(4).strip() or line.lstrip("#").strip()
            index = int(number) if number and number.isdigit() else len(items) + 1
            current = {
                "id": f"outline-{index}",
                "index": index,
                "title": title,
                "summary": "",
                "status": "planned",
                "raw": line,
            }
            continue
        if current:
            if stop_section.match(line) or re.match(r"^#{1,6}\s+", line):
                items.append(current)
                current = None
                continue
            current["summary"] = f"{current['summary']}\n{line}".strip()

    if current:
        items.append(current)
    return [
        {**item, "index": position}
        for position, item in enumerate(items, start=1)
    ]
