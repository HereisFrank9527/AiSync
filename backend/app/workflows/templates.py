from __future__ import annotations

from typing import Any


def workflow_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": "chapter_draft_safe",
            "name": "安全章节草稿",
            "description": "检索上下文、生成计划、人工确认、生成草稿，默认输出到 temp/drafts。",
            "workflow_type": "chapter_draft",
            "input_summary": "写一章正文草稿：先规划，再确认，再写作，草稿先放入 temp/drafts。",
            "steps": [
                {
                    "name": "检索章节上下文",
                    "kind": "context",
                    "context_pack_ids": ["outline_node", "related_characters", "related_foreshadows", "world_rules"],
                },
                {
                    "name": "生成章节计划",
                    "kind": "plan",
                },
                {
                    "name": "用户确认计划",
                    "kind": "user_confirm",
                },
                {
                    "name": "生成章节草稿",
                    "kind": "draft",
                    "output_path": "temp/drafts/",
                },
            ],
        },
        {
            "id": "chapter_draft_to_formal",
            "name": "草稿转正式章节",
            "description": "先生成草稿，再经人工确认写入 chapters 目录。",
            "workflow_type": "chapter_draft",
            "input_summary": "写一章正文草稿，确认后写入正式章节文件。",
            "steps": [
                {"name": "检索章节上下文", "kind": "context"},
                {"name": "生成章节计划", "kind": "plan"},
                {"name": "确认计划", "kind": "user_confirm"},
                {"name": "生成章节草稿", "kind": "draft", "output_path": "temp/drafts/"},
                {
                    "name": "确认写入正式章节",
                    "kind": "user_confirm",
                    "input": {"note": "确认草稿内容和目标章节路径后再继续。"},
                },
                {
                    "name": "写入正式章节",
                    "kind": "write_file",
                    "input": {
                        "source_path": "",
                        "target_path": "chapters/vol-01/ch-001.md",
                    },
                },
            ],
        },
        {
            "id": "revise_existing_chapter",
            "name": "章节修订草稿",
            "description": "检索上下文后按额外要求修订，先输出修订草稿，不直接覆盖正式章节。",
            "workflow_type": "chapter_revision",
            "input_summary": "修订指定章节，保留原剧情事实，输出到 temp/drafts。",
            "steps": [
                {"name": "检索修订上下文", "kind": "context"},
                {
                    "name": "生成修订方案",
                    "kind": "plan",
                    "input": {"extra_prompt": "指出需要保留、增强、删除的内容。"},
                },
                {"name": "确认修订方案", "kind": "user_confirm"},
                {"name": "生成修订草稿", "kind": "revise", "output_path": "temp/drafts/"},
            ],
        },
    ]


def workflow_template(template_id: str) -> dict[str, Any] | None:
    for template in workflow_templates():
        if template["id"] == template_id:
            return template
    return None
