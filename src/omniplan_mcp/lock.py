"""
File lock utility for synchronizing OmniPlan access across multiple MCP server instances.

When multiple Claude Code sessions run simultaneously, each has its own MCP server process.
If they all try to call OmniPlan via AppleScript at the same time, conflicts can occur.

This module provides a cross-process file lock so that only one process accesses OmniPlan
at a time. Others will wait (with timeout) for the lock to be released.
"""

import fcntl
import json
import os
import tempfile
import time
from contextlib import contextmanager
from typing import Iterator

LOCK_DIR = os.path.join(tempfile.gettempdir(), "omniplan-mcp-locks")
LOCK_TIMEOUT_SECONDS = 120  # Max wait time for lock


def _ensure_lock_dir() -> str:
    os.makedirs(LOCK_DIR, exist_ok=True)
    return LOCK_DIR


def _lock_path(name: str) -> str:
    """Get the lock file path for a given resource name."""
    safe_name = name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    return os.path.join(_ensure_lock_dir(), f"{safe_name}.lock")


@contextmanager
def omniplan_lock(timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """
    Acquire a cross-process lock for OmniPlan AppleScript access.

    This ensures that only one MCP server instance calls OmniPlan at a time,
    preventing AppleScript conflicts when multiple Claude Code sessions are open.

    Usage:
        with omniplan_lock():
            # Call OmniPlan AppleScript here
            pass

    Args:
        timeout: Maximum seconds to wait for the lock before raising TimeoutError.

    Raises:
        TimeoutError: If the lock cannot be acquired within the timeout period.
    """
    lock_path = _lock_path("omniplan")
    lock_file_path = f"{lock_path}.{os.getpid()}"

    # Create a unique lock file for this process
    fd = os.open(lock_file_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        start_time = time.monotonic()
        acquired = False

        while not acquired:
            try:
                # Try to acquire the lock on the *named* lock file
                # Using LOCK_EX | LOCK_NB for non-blocking attempt
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                # Lock held by another process
                elapsed = time.monotonic() - start_time
                if elapsed > timeout:
                    os.close(fd)
                    raise TimeoutError(
                        f"Could not acquire OmniPlan lock within {timeout}s. "
                        f"Another Claude Code session may be busy with OmniPlan."
                    )
                time.sleep(0.5)

        yield

    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        except Exception:
            pass
        try:
            os.unlink(lock_file_path)
        except FileNotFoundError:
            pass


class LockStats:
    """Track lock usage for debugging."""

    _file = os.path.join(LOCK_DIR, "stats.json")

    @classmethod
    def record_acquisition(cls, wait_seconds: float) -> None:
        """Record a lock acquisition event."""
        _ensure_lock_dir()
        stats = cls._read()
        stats.setdefault("acquisitions", []).append(
            {"wait": round(wait_seconds, 2), "time": time.time()}
        )
        # Keep only last 100 entries
        stats["acquisitions"] = stats["acquisitions"][-100:]
        cls._write(stats)

    @classmethod
    def _read(cls) -> dict:
        try:
            with open(cls._file) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @classmethod
    def _write(cls, data: dict) -> None:
        try:
            with open(cls._file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass
