"""Pytest configuration shared by every test layer.

Defines the `requires_omniplan` marker and an autouse skip hook: tests marked
this way only run if the OmniPlan 4 process is alive and its sandbox container
exists on disk. Unit tests never set the marker, so `pytest -m "not requires_omniplan"`
runs the full unit-only matrix without OmniPlan involvement.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest


def _omniplan_running() -> bool:
    pgrep = shutil.which("pgrep")
    if not pgrep:
        return False
    result = subprocess.run(
        [pgrep, "-x", "OmniPlan"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _omniplan_available() -> tuple[bool, str]:
    if not _omniplan_running():
        return False, "OmniPlan 4 is not running (start the app and open a document)"
    # No sandbox-container requirement: non-sandbox installs (direct .app
    # download) run without ~/Library/Containers/com.omnigroup.OmniPlan4, so
    # the old existence check falsely skipped every integration test on those
    # machines. Probe for a responding front document instead.
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e",
             'Application("OmniPlan").documents().length'],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != 0:
            return False, (
                f"osascript front-document probe failed: {result.stderr.strip()[:160]}"
            )
        try:
            count = int(result.stdout.strip())
        except ValueError:
            return False, (
                f"osascript probe returned non-numeric output: "
                f"{result.stdout.strip()[:80]!r}"
            )
        if count < 1:
            return False, "OmniPlan 4 is running but no document is open"
        return True, ""
    except Exception as e:  # osascript missing, timeout, etc.
        return False, f"osascript front-document probe failed: {e}"


@pytest.fixture(scope="session")
def omniplan_available() -> bool:
    ok, _ = _omniplan_available()
    return ok


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    ok, reason = _omniplan_available()
    if ok:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "requires_omniplan" in item.keywords:
            item.add_marker(skip)
