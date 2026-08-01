from __future__ import annotations

from app.core.prompt_packs import PromptPackCreate


def prompt_pack_examples() -> list[dict[str, object]]:
    return [
        {
            "id": "style_semi_classical",
            "name": "半文半白叙事",
            "category": "style",
            "stages": ["chat", "chapter_draft", "revision"],
            "description": "适合古风、仙侠、权谋或庄重叙事；保留现代可读性。",
            "content": (
                "文风要求：\n"
                "1. 采用半文半白，不写纯古文，保证读者能顺畅阅读。\n"
                "2. 叙述句可用“却、遂、只道、未料、不过、终究”等词增加古意。\n"
                "3. 人物对白允许略古，但不要堆砌生僻字，不用过度拗口的骈文。\n"
                "4. 动作描写克制，少用网络化感叹和现代口头禅。\n"
                "5. 情绪不直接喊出来，优先通过眼神、停顿、衣袖、灯火、风声等细节表现。\n"
                "6. 输出正文时只写正文，不解释本提示词。"
            ),
        },
        {
            "id": "style_wasteland_cold",
            "name": "废土冷峻文风",
            "category": "style",
            "stages": ["chat", "chapter_draft", "revision"],
            "description": "适合废土、末世、硬科幻场景。",
            "content": (
                "文风要求：\n"
                "1. 语言冷峻、具体，减少抒情和空泛形容。\n"
                "2. 环境描写突出尘、锈、干渴、机械残骸、旧世界标识等可见物。\n"
                "3. 战斗和危机段落用短句推进，避免解释过多。\n"
                "4. 科技设定只在角色需要理解或使用时露出，不大段科普。\n"
                "5. 主角判断要体现生存经验：先观察风险，再行动。\n"
                "6. 输出正文时保持章节连续性，不写创作说明。"
            ),
        },
        {
            "id": "writing_chapter_goal",
            "name": "章节草稿约束",
            "category": "writing",
            "stages": ["chapter_plan", "chapter_draft"],
            "description": "让章节计划和草稿更像可落地章节。",
            "content": (
                "章节写作规则：\n"
                "1. 每章必须有清晰的开场钩子、推进事件、转折或余味。\n"
                "2. 不要在一章内解决所有问题，至少保留一个自然牵引下一章的悬念。\n"
                "3. 角色行动必须有动机，不让角色只为解释设定而说话。\n"
                "4. 新设定第一次出现时只露出必要部分，后续再展开。\n"
                "5. 如果引用了伏笔，标出它在本章是“埋设、推进、回收、暂不处理”中的哪一种。"
            ),
        },
        {
            "id": "check_consistency_strict",
            "name": "设定一致性复核",
            "category": "check",
            "stages": ["check", "revision"],
            "description": "用于润色或检查步骤，减少设定漂移。",
            "content": (
                "检查规则：\n"
                "1. 优先检查人物姓名、阵营、年龄、能力边界、地理位置、时间顺序。\n"
                "2. 区分真正矛盾和只是信息相关；没有明确冲突时不要夸大问题。\n"
                "3. 对每个问题给出引用位置、冲突原因、建议修正方式。\n"
                "4. 不因章节编号、列表编号或普通数字相同就判定冲突。"
            ),
        },
    ]


def prompt_pack_create_from_example(example_id: str) -> PromptPackCreate | None:
    for item in prompt_pack_examples():
        if item["id"] != example_id:
            continue
        return PromptPackCreate(
            name=str(item["name"]),
            category=item["category"],  # type: ignore[arg-type]
            scope="global",
            stages=item["stages"],  # type: ignore[arg-type]
            content=str(item["content"]),
            enabled=True,
            description=str(item["description"]),
        )
    return None
