"""Integration tests for constraint date round-trips on `update_task`.

Verified omniJS surface (probed live 2026-05-01, OmniPlan 4.10.2 build 232.5.0,
matched against omni-automation.com class docs):

  - `task.startNoEarlierThanDate` (Date or null)  read/write, persistent
  - `task.startNoLaterThanDate`   (Date or null)  read/write, persistent
  - `task.endNoEarlierThanDate`   (Date or null)  read/write, persistent
  - `task.endNoLaterThanDate`     (Date or null)  read/write, persistent

These are the documented omniJS names for what the AppleScript SDEF calls
`start constraint date` / `start before date` / `end after date` /
`end before date`. An earlier draft of this fork's docs claimed these were
broken — that was us probing under the SDEF names, which don't exist on the
omniJS Task class. With the correct names they round-trip across JXA calls
the same way `task.manualStartDate` does. See `dev-docs/omnijs-persistence-gaps.md`
for the post-mortem.

Test methodology: each constraint setter is asserted to round-trip the same
value as the existing `manual_start_date` setter when given the same input.
This isolates "does the new field persist" from the wider date-format /
timezone round-trip behaviour of the codebase. Dates are written through the
`dateFromISO` helper (local-midnight construction, not `new Date('YYYY-MM-DD')`
which parses as UTC midnight) and read back with local getters (`fmtDate`), so
round-trips are timezone-independent — see `tasks.py _fmt_date`.
"""
from __future__ import annotations

import json

import pytest

from omniplan_mcp.tasks import create_task, get_task, update_task

pytestmark = pytest.mark.requires_omniplan

TARGET_DATE = "2027-04-12"


async def _round_trip_field(test_root: str, slug: str, **update_kwargs: str) -> tuple[str, str]:
    """Set the manual_start_date AND the given constraint field to the same
    target and return both round-tripped values. They should match exactly,
    proving the constraint setter persists the way the manual setter does.
    """
    raw = await create_task(title=f"__test__constraint__{slug}", parent_id=test_root)
    task = json.loads(raw)

    await update_task(task_id=task["id"], manual_start_date=TARGET_DATE, **update_kwargs)

    fresh = json.loads(await get_task(task_id=task["id"]))
    constraint_field = next(iter(update_kwargs))
    return fresh["manual_start_date"], fresh[constraint_field]


async def test_set_start_no_earlier_than_persists(test_root: str) -> None:
    manual, constraint = await _round_trip_field(
        test_root, "sne", start_no_earlier_than=TARGET_DATE
    )
    assert constraint == manual
    assert constraint == TARGET_DATE, (
        f"start_no_earlier_than read back as {constraint!r} but input was "
        f"{TARGET_DATE!r} — timezone skew regression (see tasks.py fmtDate)"
    )


async def test_set_start_no_later_than_persists(test_root: str) -> None:
    manual, constraint = await _round_trip_field(
        test_root, "snl", start_no_later_than=TARGET_DATE
    )
    assert constraint == manual
    assert constraint == TARGET_DATE, (
        f"start_no_later_than read back as {constraint!r} but input was "
        f"{TARGET_DATE!r} — timezone skew regression (see tasks.py fmtDate)"
    )


async def test_set_end_no_earlier_than_persists(test_root: str) -> None:
    manual, constraint = await _round_trip_field(
        test_root, "ene", end_no_earlier_than=TARGET_DATE
    )
    assert constraint == manual
    assert constraint == TARGET_DATE, (
        f"end_no_earlier_than read back as {constraint!r} but input was "
        f"{TARGET_DATE!r} — timezone skew regression (see tasks.py fmtDate)"
    )


async def test_set_end_no_later_than_persists(test_root: str) -> None:
    manual, constraint = await _round_trip_field(
        test_root, "enl", end_no_later_than=TARGET_DATE
    )
    assert constraint == manual
    assert constraint == TARGET_DATE, (
        f"end_no_later_than read back as {constraint!r} but input was "
        f"{TARGET_DATE!r} — timezone skew regression (see tasks.py fmtDate)"
    )


async def test_manual_start_date_persists_without_timezone_skew(test_root: str) -> None:
    """Regression for the same timezone bug applied to manual_start_date.

    Earlier four tests had `assert constraint == manual` only. That passed
    even when both fields were silently shifted by one day west of UTC.
    This test pins manual_start_date itself to the input string so the
    skew can't hide.
    """
    raw = await create_task(title="__test__constraint__mn", parent_id=test_root)
    task = json.loads(raw)
    await update_task(task_id=task["id"], manual_start_date=TARGET_DATE)
    fresh = json.loads(await get_task(task_id=task["id"]))
    assert fresh["manual_start_date"] == TARGET_DATE, (
        f"manual_start_date read back as {fresh['manual_start_date']!r} but "
        f"input was {TARGET_DATE!r} — timezone skew regression"
    )
