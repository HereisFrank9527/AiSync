from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from app.projects.context import ProjectContext

FACTS_ROOT = "plot/facts"
FACT_CATEGORIES = {
    "identity",
    "state",
    "relationship",
    "location",
    "possession",
    "timeline",
    "world_rule",
    "other",
}
FACT_CERTAINTIES = {"confirmed", "reported", "uncertain"}
MAX_FACTS_PER_CHAPTER = 12


def fact_records_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "description": (
            "本章写入后值得跨章节记住的事实快照，最多 12 条。"
            "只记录人物身份/状态/关系/位置/持有物、明确时间点和世界规则；"
            "不要记录修辞、气氛、普通动作或一次性细节。没有长期事实时传空数组。"
        ),
        "maxItems": MAX_FACTS_PER_CHAPTER,
        "items": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": sorted(FACT_CATEGORIES),
                    "description": "事实类别。",
                },
                "subject": {"type": "string", "description": "事实主体，例如林铎、黑雨城或零号体系。"},
                "predicate": {"type": "string", "description": "稳定属性或关系，例如年龄、当前位置、持有、身份。"},
                "value": {"type": "string", "description": "本章结束时确认的值。"},
                "evidence": {"type": "string", "description": "支持该事实的正文短句，不要整段复制。"},
                "certainty": {
                    "type": "string",
                    "enum": sorted(FACT_CERTAINTIES),
                    "default": "confirmed",
                    "description": "confirmed=叙事确认，reported=角色转述，uncertain=仍存疑。",
                },
                "time": {"type": "string", "description": "可选的故事内时间点或阶段。"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 6,
                    "description": "可选检索标签。",
                },
            },
            "required": ["category", "subject", "predicate", "value", "evidence"],
            "additionalProperties": False,
        },
    }


def chapter_fact_path(chapter_path: str) -> str:
    normalized = chapter_path.replace("\\", "/").strip().lstrip("/")
    path = PurePosixPath(normalized)
    if (
        not normalized.startswith("chapters/")
        or path.suffix.lower() != ".md"
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("fact snapshot requires a chapters/**/*.md path")
    relative = path.relative_to("chapters").with_suffix(".json")
    return str(PurePosixPath(FACTS_ROOT) / relative)


def normalize_fact_records(raw_records: list[Any], chapter_path: str) -> list[dict[str, Any]]:
    if len(raw_records) > MAX_FACTS_PER_CHAPTER:
        raise ValueError(f"单章最多记录 {MAX_FACTS_PER_CHAPTER} 条长期事实")
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for index, raw in enumerate(raw_records, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"fact_records[{index}] must be an object")
        category = _clean_text(raw.get("category"), 32).lower()
        subject = _clean_text(raw.get("subject"), 120)
        predicate = _clean_text(raw.get("predicate"), 80)
        value = _clean_text(raw.get("value"), 240)
        evidence = _clean_text(raw.get("evidence"), 320)
        certainty = _clean_text(raw.get("certainty") or "confirmed", 24).lower()
        time_marker = _clean_text(raw.get("time"), 120)
        if category not in FACT_CATEGORIES:
            raise ValueError(f"fact_records[{index}] has unsupported category: {category}")
        if certainty not in FACT_CERTAINTIES:
            raise ValueError(f"fact_records[{index}] has unsupported certainty: {certainty}")
        if not subject or not predicate or not value or not evidence:
            raise ValueError(f"fact_records[{index}] requires subject, predicate, value and evidence")
        signature = (category, subject, predicate, value)
        if signature in seen:
            continue
        seen.add(signature)
        tags = _string_list(raw.get("tags"), limit=6, item_chars=32)
        digest = hashlib.sha1(
            f"{chapter_path}\0{category}\0{subject}\0{predicate}\0{value}".encode("utf-8")
        ).hexdigest()[:16]
        fact = {
            "id": f"fact-{digest}",
            "category": category,
            "subject": subject,
            "predicate": predicate,
            "value": value,
            "certainty": certainty,
            "source_path": chapter_path,
            "evidence": evidence,
        }
        if time_marker:
            fact["time"] = time_marker
        if tags:
            fact["tags"] = tags
        facts.append(fact)
    return facts


def chapter_fact_document(chapter_path: str, facts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 1,
        "chapter_path": chapter_path,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "facts": facts,
    }


async def load_chapter_facts(context: ProjectContext, chapter_path: str) -> list[dict[str, Any]]:
    path = chapter_fact_path(chapter_path)
    if not await context.exists(path):
        return []
    try:
        data = await context.read_json(path)
    except Exception:
        return []
    raw = data.get("facts") if isinstance(data, dict) else None
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _string_list(value: Any, *, limit: int, item_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for raw in value:
        item = _clean_text(raw, item_chars)
        if item and item not in items:
            items.append(item)
        if len(items) >= limit:
            break
    return items
