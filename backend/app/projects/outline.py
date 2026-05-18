from __future__ import annotations

import re
from typing import Any


def outline_items_from_markdown(content: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    chapter_pattern = re.compile(
        r"^\s*(?:#{1,4}\s*)?(?:第\s*([0-9一二三四五六七八九十百零〇Xx]+)\s*[章节回]|chapter\s*(\d+)|ch[-_\s]*(\d+))\s*[：:.\-\s]*(.*)$",
        re.I,
    )

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        chapter = chapter_pattern.match(line)
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
    chapter_pattern = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:第\s*([0-9一二三四五六七八九十百零〇Xx]+)\s*[章节回]|chapter\s*(\d+)|ch[-_\s]*(\d+))\s*[：:.\-\s]*(.+)$",
        re.I,
    )
    stop_section = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:卷[一二三四五六七八九十0-9]+|核心问题|双线推进|[A-ZＡ-Ｚ]\s*线|关键转折)\b",
        re.I,
    )

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        chapter = chapter_pattern.match(line)
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
