from __future__ import annotations

import re
from typing import Any

from app.projects.context import ProjectContext

FORESHADOW_PATH = "plot/foreshadows.json"
CHAPTER_PATH_RE = re.compile(r"chapters/[^\s`'\"，。；、]+?\.md", re.I)
OUTLINE_ID_RE = re.compile(r"outline-[A-Za-z0-9_-]+", re.I)

STATUS_LABELS = {
    "planned": "计划埋",
    "planted": "已埋下",
    "developing": "推进中",
    "paid_off": "已回收",
    "abandoned": "废弃",
}

IMPORTANCE_LABELS = {
    "minor": "轻量",
    "medium": "普通",
    "major": "关键",
}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def normalize_foreshadow_item(value: dict[str, Any], position: int) -> dict[str, Any]:
    return {
        "id": str(value.get("id") or f"foreshadow-{position}"),
        "title": str(value.get("title") or f"伏笔 {position}"),
        "summary": str(value.get("summary") or ""),
        "status": str(value.get("status") or "planned"),
        "importance": str(value.get("importance") or "medium"),
        "plant_chapter": str(value.get("plant_chapter") or ""),
        "payoff_chapter": str(value.get("payoff_chapter") or ""),
        "outline_ids": _string_list(value.get("outline_ids")),
        "related_files": _string_list(value.get("related_files")),
        "tags": _string_list(value.get("tags")),
        "notes": str(value.get("notes") or ""),
    }


async def load_foreshadows(context: ProjectContext) -> list[dict[str, Any]]:
    if not await context.exists(FORESHADOW_PATH):
        return []
    try:
        data = await context.read_json(FORESHADOW_PATH)
    except Exception:
        return []
    raw_items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(raw_items, list):
        return []
    return [
        normalize_foreshadow_item(item, index)
        for index, item in enumerate(raw_items, start=1)
        if isinstance(item, dict)
    ]


def extract_chapter_paths(text: str) -> list[str]:
    return sorted(set(match.group(0).replace("\\", "/") for match in CHAPTER_PATH_RE.finditer(text)))


async def outline_ids_for_chapters(context: ProjectContext, chapter_paths: list[str]) -> set[str]:
    outline_ids: set[str] = set()
    for chapter_path in chapter_paths:
        if "/" not in chapter_path:
            continue
        directory, filename = chapter_path.rsplit("/", 1)
        metadata_path = f"{directory}/ch-meta.yaml"
        slug = filename.removesuffix(".md")
        if not await context.exists(metadata_path):
            continue
        try:
            data = await context.read_yaml(metadata_path) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        chapters = data.get("chapters")
        metadata = chapters.get(slug) if isinstance(chapters, dict) else data.get(slug)
        if isinstance(metadata, dict) and metadata.get("outline_id"):
            outline_ids.add(str(metadata["outline_id"]))
    return outline_ids


def _text_tokens(text: str) -> set[str]:
    normalized = text.lower()
    words = set(re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", normalized))
    cjk = [char for char in normalized if "\u4e00" <= char <= "\u9fff"]
    words.update(f"{cjk[index]}{cjk[index + 1]}" for index in range(len(cjk) - 1))
    return words


def explain_foreshadow_match(
    item: dict[str, Any],
    user_input: str,
    chapter_paths: set[str],
    outline_ids: set[str],
) -> dict[str, Any]:
    score = 0
    reasons: list[str] = []
    action = "参考"
    if item["payoff_chapter"] in chapter_paths:
        score += 120
        reasons.append("目标章节是回收章节")
        action = "优先回收"
    if item["plant_chapter"] in chapter_paths:
        score += 90
        reasons.append("目标章节是埋设章节")
        if action == "参考":
            action = "埋设"
    if chapter_paths.intersection(item["related_files"]):
        score += 70
        reasons.append("相关文件包含目标章节")
    if outline_ids.intersection(item["outline_ids"]):
        score += 65
        reasons.append("关联同一大纲节点")
        if action == "参考" and item["status"] in {"planted", "developing"}:
            action = "推进"

    item_tokens = _text_tokens("\n".join([
        item["title"],
        item["summary"],
        item["notes"],
        " ".join(item["tags"]),
    ]))
    token_hits = item_tokens.intersection(_text_tokens(user_input))
    score += min(len(token_hits) * 8, 40)
    if token_hits:
        reasons.append("标题/摘要/标签关键词命中")

    if item["importance"] == "major":
        score += 10
    if item["status"] in {"planned", "planted", "developing"}:
        score += 8
    if item["status"] == "abandoned":
        score -= 30
        action = "不要主动使用"
        reasons.append("伏笔已废弃")
    if item["status"] == "paid_off":
        action = "避免重复回收"
    return {"score": score, "reasons": reasons, "action": action}


def score_foreshadow(
    item: dict[str, Any],
    user_input: str,
    chapter_paths: set[str],
    outline_ids: set[str],
) -> int:
    return int(explain_foreshadow_match(item, user_input, chapter_paths, outline_ids)["score"])


def foreshadows_with_explanations(
    items: list[dict[str, Any]],
    user_input: str,
    chapter_paths: set[str],
    outline_ids: set[str],
) -> list[dict[str, Any]]:
    explained: list[dict[str, Any]] = []
    for item in items:
        explanation = explain_foreshadow_match(item, user_input, chapter_paths, outline_ids)
        explained.append({**item, "_match": explanation})
    return sorted(explained, key=lambda item: int(item["_match"]["score"]), reverse=True)


def format_foreshadow_context(items: list[dict[str, Any]], limit: int = 8) -> str:
    lines: list[str] = []
    for item in items[:limit]:
        summary = item["summary"].strip() or item["notes"].strip() or "无摘要"
        if len(summary) > 240:
            summary = f"{summary[:240]}..."
        links: list[str] = []
        if item["plant_chapter"]:
            links.append(f"埋设：{item['plant_chapter']}")
        if item["payoff_chapter"]:
            links.append(f"回收：{item['payoff_chapter']}")
        if item["outline_ids"]:
            links.append(f"大纲：{', '.join(item['outline_ids'][:3])}")
        if item["tags"]:
            links.append(f"标签：{', '.join(item['tags'][:5])}")
        status = STATUS_LABELS.get(item["status"], item["status"])
        importance = IMPORTANCE_LABELS.get(item["importance"], item["importance"])
        match = item.get("_match") if isinstance(item.get("_match"), dict) else {}
        reasons = match.get("reasons") if isinstance(match.get("reasons"), list) else []
        action = str(match.get("action") or "")
        action_line = f"\n  建议：{action}" if action else ""
        reasons_line = f"\n  命中：{'；'.join(str(reason) for reason in reasons[:4])}" if reasons else ""
        lines.append(
            f"- {item['title']}（{status} / {importance}）\n"
            f"  摘要：{summary}\n"
            f"  {'；'.join(links) if links else '暂无关联'}"
            f"{action_line}"
            f"{reasons_line}"
        )
    return "\n".join(lines)


async def foreshadow_context_for_prompt(context: ProjectContext, user_input: str, limit: int = 8) -> str:
    items = await load_foreshadows(context)
    if not items:
        return ""

    chapter_paths = set(extract_chapter_paths(user_input))
    outline_ids = set(OUTLINE_ID_RE.findall(user_input))
    outline_ids.update(await outline_ids_for_chapters(context, sorted(chapter_paths)))

    explained = foreshadows_with_explanations(items, user_input, chapter_paths, outline_ids)
    matched = [item for item in explained if int(item["_match"]["score"]) > 0]
    if not matched:
        matched = [
            item for item in items
            if item["status"] in {"planned", "planted", "developing"} and item["importance"] == "major"
        ]
    if not matched:
        return ""

    return format_foreshadow_context(matched, limit=limit)
