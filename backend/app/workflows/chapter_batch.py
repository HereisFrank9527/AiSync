from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator

from app.workflows.runs import WorkflowRunCreate, WorkflowStepRecord


MAX_CHAPTERS_PER_BATCH = 20
DEFAULT_TARGET_CHARACTERS = 3000


class ChapterBatchCreate(BaseModel):
    start_chapter: int = Field(ge=1, le=9999)
    end_chapter: int = Field(ge=1, le=9999)
    volume: str = Field(default="vol-01", min_length=1, max_length=80)
    requirements: str = Field(default="", max_length=4000)
    preset_id: str | None = None
    prompt_pack_ids: list[str] = Field(default_factory=list, max_length=20)
    target_characters: int = Field(default=DEFAULT_TARGET_CHARACTERS, ge=500, le=20000)
    overwrite_existing: bool = False
    title: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_range_and_volume(self) -> "ChapterBatchCreate":
        if self.end_chapter < self.start_chapter:
            raise ValueError("结束章节不能小于起始章节")
        if self.end_chapter - self.start_chapter + 1 > MAX_CHAPTERS_PER_BATCH:
            raise ValueError(f"单次最多连续写 {MAX_CHAPTERS_PER_BATCH} 章")
        self.volume = normalize_volume(self.volume)
        self.preset_id = (self.preset_id or "").strip() or None
        self.prompt_pack_ids = list(dict.fromkeys(item.strip() for item in self.prompt_pack_ids if item.strip()))
        self.requirements = self.requirements.strip()
        self.title = (self.title or "").strip() or None
        return self


def build_chapter_batch_workflow(data: ChapterBatchCreate) -> WorkflowRunCreate:
    chapter_count = data.end_chapter - data.start_chapter + 1
    steps = [
        WorkflowStepRecord(
            name=f"写作第 {chapter_number} 章",
            kind="chapter",
            preset_id=data.preset_id,
            prompt_pack_ids=list(data.prompt_pack_ids),
            input={
                "chapter_number": chapter_number,
                "volume": data.volume,
                "target_path": chapter_path(data.volume, chapter_number),
                "requirements": data.requirements,
                "target_characters": data.target_characters,
                "overwrite_existing": data.overwrite_existing,
            },
        )
        for chapter_number in range(data.start_chapter, data.end_chapter + 1)
    ]
    range_text = (
        f"第 {data.start_chapter} 章"
        if chapter_count == 1
        else f"第 {data.start_chapter}-{data.end_chapter} 章"
    )
    input_summary = f"连续写作{range_text}，每章约 {data.target_characters} 字。"
    if data.requirements:
        input_summary = f"{input_summary}\n{data.requirements}"
    return WorkflowRunCreate(
        workflow_type="chapter_batch",
        title=data.title or f"连续写作 {range_text}",
        input_summary=input_summary,
        steps=steps,
        metadata={
            "source": "chapter_batch",
            "version": 1,
            "start_chapter": data.start_chapter,
            "end_chapter": data.end_chapter,
            "chapter_count": chapter_count,
            "volume": data.volume,
            "target_characters": data.target_characters,
            "overwrite_existing": data.overwrite_existing,
        },
    )


def chapter_path(volume: str, chapter_number: int) -> str:
    if chapter_number < 1 or chapter_number > 9999:
        raise ValueError("章节号超出范围")
    return f"chapters/{normalize_volume(volume)}/ch-{chapter_number:03d}.md"


def normalize_volume(value: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[\w.\-\u4e00-\u9fff]+", normalized, re.UNICODE):
        raise ValueError("卷目录只能包含文字、数字、下划线、点和短横线")
    if normalized in {".", ".."}:
        raise ValueError("卷目录无效")
    return normalized
