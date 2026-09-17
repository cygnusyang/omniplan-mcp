"""Unit tests for the `requires_omniplan` gate in `tests/conftest.py`.

`conftest.py` isn't importable by path normally, so we load it via
`importlib` and exercise `_omniplan_running` / `_omniplan_available` with
mocked `subprocess` / `shutil` boundaries. These functions control whether
the entire integration suite runs or silently skips, so their failure
modes matter.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

CONFTEST_PATH = Path(__file__).resolve().parents[1] / "conftest.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("root_conftest", CONFTEST_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _Proc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_running_when_pgrep_hits(gate, monkeypatch) -> None:
    monkeypatch.setattr(gate.shutil, "which", lambda _: "/usr/bin/pgrep")
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: _Proc(returncode=0))
    assert gate._omniplan_running() is True


def test_not_running_when_pgrep_misses(gate, monkeypatch) -> None:
    monkeypatch.setattr(gate.shutil, "which", lambda _: "/usr/bin/pgrep")
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: _Proc(returncode=1))
    assert gate._omniplan_running() is False


def test_available_reports_app_not_running(gate, monkeypatch) -> None:
    monkeypatch.setattr(gate, "_omniplan_running", lambda: False)
    ok, reason = gate._omniplan_available()
    assert ok is False
    assert "not running" in reason


def test_available_reports_no_document(gate, monkeypatch) -> None:
    monkeypatch.setattr(gate, "_omniplan_running", lambda: True)
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: _Proc(stdout="0"))
    ok, reason = gate._omniplan_available()
    assert ok is False
    assert "no document is open" in reason


def test_available_when_documents_open(gate, monkeypatch) -> None:
    monkeypatch.setattr(gate, "_omniplan_running", lambda: True)
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: _Proc(stdout="2"))
    ok, _ = gate._omniplan_available()
    assert ok is True


def test_available_probe_non_numeric_output(gate, monkeypatch) -> None:
    monkeypatch.setattr(gate, "_omniplan_running", lambda: True)
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: _Proc(stdout="garbage"))
    ok, reason = gate._omniplan_available()
    assert ok is False
    assert "non-numeric" in reason


def test_available_probe_returncode_nonzero(gate, monkeypatch) -> None:
    monkeypatch.setattr(gate, "_omniplan_running", lambda: True)
    monkeypatch.setattr(
        gate.subprocess, "run", lambda *a, **k: _Proc(returncode=1, stderr="boom")
    )
    ok, reason = gate._omniplan_available()
    assert ok is False
    assert "osascript" in reason
    assert "boom" in reason


def test_available_probe_exception(gate, monkeypatch) -> None:
    monkeypatch.setattr(gate, "_omniplan_running", lambda: True)

    def _boom(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(gate.subprocess, "run", _boom)
    ok, reason = gate._omniplan_available()
    assert ok is False
    assert "timed out" in reason
