from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.projects.characters import normalize_character_ids
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


def _normalize_verification(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    status = str(value.get("status") or "unknown").strip()
    if status not in {"unknown", "verified", "review", "confirmed"}:
        status = "review"
    result: dict[str, Any] = {"status": status}
    for key in ("checked_at", "confirmed_at", "action", "chapter_path", "note"):
        text = str(value.get(key) or "").strip()
        if text:
            result[key] = text
    if "evidence_match" in value:
        result["evidence_match"] = bool(value.get("evidence_match"))
    result["issues"] = _string_list(value.get("issues"))
    return result


def normalize_foreshadow_item(value: dict[str, Any], position: int) -> dict[str, Any]:
    item = {
        "id": str(value.get("id") or f"foreshadow-{position}"),
        "title": str(value.get("title") or f"伏笔 {position}"),
        "summary": str(value.get("summary") or ""),
        "status": str(value.get("status") or "planned"),
        "importance": str(value.get("importance") or "medium"),
        "plant_chapter": str(value.get("plant_chapter") or ""),
        "payoff_chapter": str(value.get("payoff_chapter") or ""),
        "character_ids": normalize_character_ids(value.get("character_ids")),
        "outline_ids": _string_list(value.get("outline_ids")),
        "related_files": _string_list(value.get("related_files")),
        "tags": _string_list(value.get("tags")),
        "notes": str(value.get("notes") or ""),
    }
    verification = _normalize_verification(value.get("verification"))
    if verification is not None:
        item["verification"] = verification
    return item


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


async def verify_foreshadow_actions(
    context: ProjectContext,
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items = await load_foreshadows(context)
    by_id = {item["id"]: item for item in items}
    verification: list[dict[str, Any]] = []

    for action in actions:
        if not isinstance(action, dict):
            continue
        foreshadow_id = str(action.get("foreshadow_id") or "")
        chapter_path = str(action.get("chapter_path") or "")
        action_name = str(action.get("action") or "")
        evidence = str(action.get("evidence") or "").strip()
        issues: list[str] = []
        evidence_match = False

        item = by_id.get(foreshadow_id)
        if item is None:
            issues.append("伏笔记录未找到")
        if not chapter_path or not await context.exists(chapter_path):
            issues.append("章节文件不存在")
        else:
            chapter_content = await context.read_text(chapter_path)
            if evidence:
                normalized_content = re.sub(r"\s+", "", chapter_content)
                normalized_evidence = re.sub(r"\s+", "", evidence)
                evidence_match = bool(normalized_evidence and normalized_evidence in normalized_content)
                if not evidence_match:
                    evidence_tokens = _text_tokens(evidence)
                    content_tokens = _text_tokens(chapter_content)
                    matched_tokens = evidence_tokens.intersection(content_tokens)
                    evidence_match = bool(
                        evidence_tokens
                        and len(matched_tokens) / len(evidence_tokens) >= 0.6
                    )
                if not evidence_match:
                    issues.append("正文中未找到足够匹配的证据")
            else:
                issues.append("没有提供正文证据")

        if item is not None:
            if chapter_path not in item["related_files"]:
                issues.append("伏笔记录未关联当前章节")
            if action_name == "plant" and item["plant_chapter"] != chapter_path:
                issues.append("埋设章节记录不一致")
            if action_name == "payoff" and (
                item["payoff_chapter"] != chapter_path or item["status"] != "paid_off"
            ):
                issues.append("回收章节或状态记录不一致")

        verification.append(
            {
                "action": action_name,
                "foreshadow_id": foreshadow_id,
                "chapter_path": chapter_path,
                "status": "verified" if not issues else "review",
                "evidence_match": evidence_match,
                "issues": issues,
            }
        )

    return verification


async def persist_foreshadow_verification(
    context: ProjectContext,
    verification: list[dict[str, Any]],
) -> None:
    if not verification:
        return
    items = await load_foreshadows(context)
    by_id = {item["id"]: item for item in items}
    checked_at = datetime.now(timezone.utc).isoformat()
    changed = False
    for result in verification:
        if not isinstance(result, dict):
            continue
        item = by_id.get(str(result.get("foreshadow_id") or ""))
        if item is None:
            continue
        item["verification"] = _normalize_verification(
            {
                **result,
                "checked_at": checked_at,
            }
        ) or {"status": "review", "checked_at": checked_at, "issues": ["复核结果无效"]}
        changed = True
    if changed:
        await context.write_json(FORESHADOW_PATH, {"items": items})


async def confirm_foreshadow_verification(
    context: ProjectContext,
    foreshadow_id: str,
    note: str = "",
) -> list[dict[str, Any]]:
    items = await load_foreshadows(context)
    item = next((candidate for candidate in items if candidate["id"] == foreshadow_id), None)
    if item is None:
        raise ValueError(f"伏笔记录未找到：{foreshadow_id}")
    current = item.get("verification") if isinstance(item.get("verification"), dict) else {}
    now = datetime.now(timezone.utc).isoformat()
    item["verification"] = _normalize_verification(
        {
            **current,
            "status": "confirmed",
            "confirmed_at": now,
            "note": note,
        }
    ) or {"status": "confirmed", "confirmed_at": now, "issues": []}
    await context.write_json(FORESHADOW_PATH, {"items": items})
    return items


def apply_foreshadow_actions(
    items: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    chapter_path: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply model-declared chapter actions to a copy of the foreshadow ledger."""
    records = [normalize_foreshadow_item(item, index) for index, item in enumerate(items, start=1)]
    by_id = {item["id"]: item for item in records}
    applied: list[dict[str, Any]] = []

    def add_unique(values: list[str], value: str) -> list[str]:
        return [*values, value] if value and value not in values else values

    def append_evidence(item: dict[str, Any], evidence: str) -> None:
        if not evidence:
            return
        note = f"{chapter_path}: {evidence}"
        notes = item.get("notes") or ""
        if note not in notes:
            item["notes"] = f"{notes}\n{note}".strip()

    for raw in actions:
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action") or "none").strip().lower()
        if action == "none":
            continue
        if action not in {"plant", "advance", "payoff"}:
            raise ValueError(f"unsupported foreshadow action: {action}")

        foreshadow_id = str(raw.get("foreshadow_id") or "").strip()
        title = str(raw.get("title") or "").strip()
        summary = str(raw.get("summary") or "").strip()
        evidence = str(raw.get("evidence") or "").strip()
        payoff_chapter = str(raw.get("payoff_chapter") or "").strip()
        importance = str(raw.get("importance") or "medium").strip()
        tags = _string_list(raw.get("tags"))

        if action == "plant":
            if foreshadow_id:
                raise ValueError("plant action must not provide an existing foreshadow_id")
            if not title or not summary:
                raise ValueError("plant action requires title and summary")
            if importance not in IMPORTANCE_LABELS:
                importance = "medium"
            foreshadow_id = f"foreshadow-{uuid4().hex[:12]}"
            item = normalize_foreshadow_item(
                {
                    "id": foreshadow_id,
                    "title": title,
                    "summary": summary,
                    "status": "planted",
                    "importance": importance,
                    "plant_chapter": chapter_path,
                    "payoff_chapter": payoff_chapter,
                    "related_files": [chapter_path],
                    "tags": tags,
                    "notes": evidence,
                },
                len(records) + 1,
            )
            records.append(item)
            by_id[foreshadow_id] = item
        else:
            if not foreshadow_id or foreshadow_id not in by_id:
                raise ValueError(f"{action} action requires an existing foreshadow_id")
            item = by_id[foreshadow_id]
            if item["status"] == "abandoned":
                raise ValueError(f"cannot use abandoned foreshadow: {foreshadow_id}")
            item["related_files"] = add_unique(item["related_files"], chapter_path)
            if tags:
                item["tags"] = list(dict.fromkeys([*item["tags"], *tags]))
            append_evidence(item, evidence)
            if action == "advance":
                item["status"] = "developing"
            else:
                item["status"] = "paid_off"
                item["payoff_chapter"] = chapter_path

        applied.append(
            {
                "action": action,
                "foreshadow_id": foreshadow_id,
                "title": item["title"],
                "status": item["status"],
                "chapter_path": chapter_path,
                "evidence": evidence,
            }
        )

    return records, applied


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

    matched = bool(reasons)

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
    return {"score": score, "reasons": reasons, "action": action, "matched": matched}


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
    matched = [item for item in explained if item["_match"]["matched"]]
    if not matched:
        return ""

    return format_foreshadow_context(matched, limit=limit)
