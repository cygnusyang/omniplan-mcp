"""Integration tests for `query_tasks` due_before / due_after boundary semantics.

Both filters compare local-midnight calendar dates, so a task whose computed
end_date is exactly D must be EXCLUDED from `due_before=D` (strictly before)
and INCLUDED in `due_before=D+1`. Reading the computed end_date back
dynamically keeps the tests robust to OmniPlan's scheduling calendar.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from omniplan_mcp.tasks import create_task, get_task, query_tasks

pytestmark = pytest.mark.requires_omniplan

START_DATE = "2027-04-12"


async def _make_ending_task(test_root: str, slug: str) -> tuple[str, str]:
    """Create a task with a manual start + effort; return (id, computed end_date)."""
    raw = await create_task(
        title=f"__test__qdf_{slug}",
        parent_id=test_root,
        manual_start_date=START_DATE,
        effort_seconds=28800,
    )
    task = json.loads(raw)
    fresh = json.loads(await get_task(task_id=task["id"]))
    return task["id"], fresh["end_date"]


def _shift(iso: str, days: int) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return (date(y, m, d) + timedelta(days=days)).isoformat()


async def test_due_before_excludes_tasks_ending_on_boundary(test_root: str) -> None:
    task_id, end_date = await _make_ending_task(test_root, "before")
    hits = json.loads(await query_tasks(keyword="__test__qdf_before", due_before=end_date, detail="full"))
    assert all(t["id"] != task_id for t in hits), (
        f"task ending on {end_date} must be EXCLUDED from due_before={end_date} "
        "(strict calendar-date boundary)"
    )


async def test_due_before_includes_tasks_ending_next_day(test_root: str) -> None:
    task_id, end_date = await _make_ending_task(test_root, "before2")
    next_day = _shift(end_date, 1)
    hits = json.loads(await query_tasks(keyword="__test__qdf_before2", due_before=next_day, detail="full"))
    assert any(t["id"] == task_id for t in hits), (
        f"task ending on {end_date} must be INCLUDED in due_before={next_day}"
    )


async def test_due_after_excludes_tasks_ending_before_boundary(test_root: str) -> None:
    task_id, end_date = await _make_ending_task(test_root, "after")
    next_day = _shift(end_date, 1)
    hits = json.loads(await query_tasks(keyword="__test__qdf_after", due_after=next_day, detail="full"))
    assert all(t["id"] != task_id for t in hits), (
        f"task ending on {end_date} must be EXCLUDED from due_after={next_day}"
    )
