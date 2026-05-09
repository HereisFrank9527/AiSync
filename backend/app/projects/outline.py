from __future__ import annotations

import re
from typing import Any


def outline_items_from_markdown(content: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    chapter_pattern = re.compile(
        r"^\s*(?:#{1,4}\s*)?(?:第\s*(\d+)\s*[章节回]|chapter\s*(\d+)|ch[-_\s]*(\d+))\s*[：:.\-\s]*(.*)$",
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
                if number:
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
