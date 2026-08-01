from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ContextWindowMode = Literal["economy", "standard", "long", "maximum"]


@dataclass(frozen=True)
class ContextWindowBudget:
    mode: ContextWindowMode
    label: str
    recent_messages: int
    memory_chars: int
    single_message_chars: int
    vector_top_k: int
    vector_item_chars: int


CONTEXT_WINDOW_BUDGETS: dict[ContextWindowMode, ContextWindowBudget] = {
    "economy": ContextWindowBudget(
        mode="economy",
        label="经济",
        recent_messages=8,
        memory_chars=12000,
        single_message_chars=2500,
        vector_top_k=4,
        vector_item_chars=900,
    ),
    "standard": ContextWindowBudget(
        mode="standard",
        label="标准",
        recent_messages=24,
        memory_chars=24000,
        single_message_chars=4000,
        vector_top_k=8,
        vector_item_chars=1200,
    ),
    "long": ContextWindowBudget(
        mode="long",
        label="长上下文",
        recent_messages=48,
        memory_chars=64000,
        single_message_chars=8000,
        vector_top_k=14,
        vector_item_chars=1800,
    ),
    "maximum": ContextWindowBudget(
        mode="maximum",
        label="最高上下文",
        recent_messages=96,
        memory_chars=160000,
        single_message_chars=16000,
        vector_top_k=24,
        vector_item_chars=2600,
    ),
}


def context_window_budget(mode: str | None) -> ContextWindowBudget:
    if mode in CONTEXT_WINDOW_BUDGETS:
        return CONTEXT_WINDOW_BUDGETS[mode]  # type: ignore[index]
    return CONTEXT_WINDOW_BUDGETS["standard"]
