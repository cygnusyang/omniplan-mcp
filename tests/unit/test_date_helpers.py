"""Static unit tests for the JS date helpers in `tasks.py`.

These assert on the generated JS text, so they run without OmniPlan and
are timezone-independent — the exact regression class the PR fixes
(east-of-UTC skew that only shows up in a running app on a +8 host).
"""
from __future__ import annotations

import re

from omniplan_mcp.tasks import _fmt_date


def _js() -> str:
    return _fmt_date()


def test_fmt_uses_local_getters_not_utc() -> None:
    js = _js()
    for method in ("getFullYear", "getMonth", "getDate"):
        assert method in js, f"fmtDate must use local {method}"
    for method in ("getUTCFullYear", "getUTCMonth", "getUTCDate"):
        assert method not in js, f"local-getter helper must not use {method}"


def test_datefromiso_guards_against_rollover() -> None:
    # JS Date silently normalizes out-of-range components (2026-13-45 ->
    # 2027-02-14); dateFromISO must reject instead of storing a wrong date.
    js = _js()
    assert "d.getFullYear() !== y" in js, "dateFromISO must round-trip-check components"
    assert "throw new Error('invalid date: ' + iso)" in js


def test_datefromiso_validates_fallback() -> None:
    # Non-YYYY-MM-DD input falls through to new Date(iso); an Invalid Date
    # result must throw, not be silently assigned.
    js = _js()
    assert "isNaN(full.getTime())" in js


def test_fmt_date_defines_both_helpers() -> None:
    js = _js()
    assert "function fmtDate(d)" in js
    assert "function dateFromISO(iso)" in js


def test_no_legacy_raw_date_writes_remain() -> None:
    # Every Python-injected date write must go through dateFromISO, not the
    # old `new Date({json.dumps(...)})` form (which parsed as UTC midnight).
    import inspect
    from omniplan_mcp import tasks as tasks_mod

    src = inspect.getsource(tasks_mod)
    assert "new Date({json.dumps" not in src, (
        "legacy UTC-midnight write form still present; use dateFromISO(...)"
    )
    assert "dateFromISO({json.dumps" in src
