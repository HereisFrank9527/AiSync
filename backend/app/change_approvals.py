from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from app.change_sets import load_change_set
from app.projects.context import ProjectContext

ChangeSetDecision = Literal["applied", "discarded", "deferred", "timed_out"]
ResolvableChangeSetDecision = Literal["applied", "discarded", "deferred"]

_waiters: dict[tuple[str, str], asyncio.Future[ChangeSetDecision]] = {}


def _approval_key(project_root: Path | str, change_set_id: str) -> tuple[str, str]:
    return str(Path(project_root).expanduser().resolve()), change_set_id


def register_change_set_waiter(
    context: ProjectContext,
    change_set_id: str,
) -> asyncio.Future[ChangeSetDecision]:
    key = _approval_key(context.root, change_set_id)
    existing = _waiters.get(key)
    if existing and not existing.done():
        raise RuntimeError(f"change set already has an approval waiter: {change_set_id}")
    future = asyncio.get_running_loop().create_future()
    _waiters[key] = future
    return future


async def wait_for_registered_change_set_decision(
    context: ProjectContext,
    change_set_id: str,
    future: asyncio.Future[ChangeSetDecision],
    *,
    timeout_seconds: float | None = None,
) -> ChangeSetDecision:
    key = _approval_key(context.root, change_set_id)
    try:
        record = await load_change_set(context, change_set_id)
        if record.status in {"applied", "discarded"}:
            return record.status
        if timeout_seconds is None:
            return await future
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=max(0.01, timeout_seconds))
        except asyncio.TimeoutError:
            return "timed_out"
    finally:
        if _waiters.get(key) is future:
            _waiters.pop(key, None)
        if not future.done():
            future.cancel()


async def wait_for_change_set_decision(
    context: ProjectContext,
    change_set_id: str,
    *,
    timeout_seconds: float | None = None,
) -> ChangeSetDecision:
    future = register_change_set_waiter(context, change_set_id)
    return await wait_for_registered_change_set_decision(
        context,
        change_set_id,
        future,
        timeout_seconds=timeout_seconds,
    )


def resolve_change_set_decision(
    project_root: Path | str,
    change_set_id: str,
    decision: ResolvableChangeSetDecision,
) -> bool:
    future = _waiters.get(_approval_key(project_root, change_set_id))
    if not future or future.done():
        return False
    future.set_result(decision)
    return True


def has_change_set_waiter(project_root: Path | str, change_set_id: str) -> bool:
    future = _waiters.get(_approval_key(project_root, change_set_id))
    return bool(future and not future.done())
