"""Unit tests for the `manual_end_date` rejection on the task tools.

These raises fire before any `run_omnijs` call, so they need no live
OmniPlan document — the whole point of the rejection is to fail loudly
instead of silently ignoring the field.
"""
from __future__ import annotations

import pytest

from omniplan_mcp.tasks import create_task, create_tasks, update_task

REASON = "not settable"


@pytest.mark.asyncio
async def test_create_task_rejects_manual_end_date() -> None:
    with pytest.raises(ValueError, match=REASON):
        await create_task(title="__test__med", manual_end_date="2027-04-12")


@pytest.mark.asyncio
async def test_create_tasks_rejects_manual_end_date_in_spec() -> None:
    with pytest.raises(ValueError, match=REASON):
        await create_tasks([{"title": "__test__med", "manual_end_date": "2027-04-12"}])


@pytest.mark.asyncio
async def test_create_tasks_rejects_before_any_side_effect() -> None:
    # A violating spec aborts the whole batch; nothing is created.
    with pytest.raises(ValueError, match=REASON):
        await create_tasks([
            {"title": "__test__med_ok"},
            {"title": "__test__med_bad", "manual_end_date": "2027-04-12"},
        ])


@pytest.mark.asyncio
async def test_update_task_rejects_manual_end_date() -> None:
    with pytest.raises(ValueError, match=REASON):
        await update_task(task_id="1", manual_end_date="2027-04-12")


@pytest.mark.asyncio
async def test_update_task_rejects_empty_string_clear() -> None:
    # "" used to mean "clear"; clearing is also unsupported (OmniPlan
    # derives the field), so it must raise rather than silently drop.
    with pytest.raises(ValueError, match=REASON):
        await update_task(task_id="1", manual_end_date="")
