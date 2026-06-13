"""
OmniPlan project file parser.

Two modes:
  - .mpp files: Uses AppleScript to read directly from OmniPlan's in-memory data.
  - .oplx files: Direct XML parsing (no OmniPlan needed).
"""

import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from typing import Any

# OmniPlan XML namespace (for .oplx parsing)
NS = "{http://www.omnigroup.com/namespace/OmniPlan/v2}"

# ── AppleScript Bridge ──────────────────────────────────────────────────


def _run_osascript(script: str) -> str:
    """Run an AppleScript and return stdout, or raise on failure."""
    result = subprocess.run(
        ["osascript", "-l", "AppleScript", "-e", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"AppleScript failed: {result.stderr}\n"
            f"Make sure OmniPlan is installed and you have granted "
            f"Accessibility/Automation permissions in "
            f"System Settings → Privacy & Security → Automation."
        )
    return result.stdout.strip()


def _parse_as_date(d: str) -> str:
    """Parse AppleScript date string to YYYY-MM-DD format.
    AppleScript dates look like: '2025年11月28日 星期五' or 'Friday, November 28, 2025'
    """
    if not d:
        return ""
    # Try parsing with known formats
    for fmt in [
        "%Y年%m月%d日 %A",
        "%A, %B %d, %Y",
        "%A %B %d %Y",
    ]:
        try:
            dt = datetime.strptime(d, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Fallback: extract date digits
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", d)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return d[:10]


def _seconds_to_hours(s: float) -> str:
    """Convert seconds to hours."""
    if not s:
        return "0"
    return str(round(s / 3600, 1))


def _seconds_to_days(s: float) -> str:
    """Convert seconds to days (8h workday)."""
    if not s:
        return "0"
    return str(round(s / 28800, 1))


# ── AppleScript Templates ───────────────────────────────────────────────

_READ_OPEN_DOC = r'''
tell application "OmniPlan"
    set docCount to count of documents
    if docCount = 0 then
        return "NO_DOCUMENT"
    end if
    set doc to document 1
    set proj to project of doc
    set sce to frontEditingScenario of proj

    set output to {{}}

    -- Project metadata
    set projTitle to title of proj
    try
        set projStart to starting date of sce
        set projStartStr to date string of projStart
    on error
        set projStartStr to ""
    end try
    try
        set projEnd to ending date of sce
        set projEndStr to date string of projEnd
    on error
        set projEndStr to ""
    end try
    set projPct to completed of sce
    set end of output to "project|" & projTitle & "|" & projStartStr & "|" & projEndStr & "|" & projPct

    -- Resources
    set allResources to every resource of sce
    repeat with r in allResources
        set rid to id of r
        set rname to name of r
        set rtype to resource type of r
        set end of output to "resource|" & rid & "|" & rname & "|" & rtype
    end repeat

    -- All tasks (full hierarchy)
    set allTasks to every task of sce
    repeat with t in allTasks
        set tid to id of t
        set tname to name of t
        set ttype to task type of t

        set tstart to ""
        set tend to ""
        try
            set tstart to date string of starting date of t
        end try
        try
            set tend to date string of ending date of t
        end try

        set tdur to duration of t
        set tpct to completed of t
        set teff to effort of t
        set tdepth to outline depth of t
        set tnum to outline number of t

        set tparent to -1
        try
            set tparent to id of parent task of t
        end try

        set tpri to priority of t

        set end of output to "task|" & tid & "|" & tname & "|" & ttype & "|" & tstart & "|" & tend & "|" & tdur & "|" & tpct & "|" & teff & "|" & tdepth & "|" & tnum & "|" & tparent & "|" & tpri
    end repeat

    set AppleScript's text item delimiters to {return}
    return output as string
end tell
'''

def _parse_as_record(line: str) -> dict[str, Any]:
    """Parse a pipe-delimited line from AppleScript output into a dict."""
    parts = line.split("|")
    record_type = parts[0]

    if record_type == "project":
        return {
            "type": "project",
            "title": parts[1] if len(parts) > 1 else "",
            "start_date": _parse_as_date(parts[2] if len(parts) > 2 else ""),
            "end_date": _parse_as_date(parts[3] if len(parts) > 3 else ""),
            "percent_complete": float(parts[4]) * 100 if len(parts) > 4 and parts[4] else 0,
        }

    elif record_type == "resource":
        return {
            "type": "resource",
            "id": int(parts[1]) if len(parts) > 1 and parts[1] else 0,
            "name": parts[2] if len(parts) > 2 else "",
            "resource_type": parts[3] if len(parts) > 3 else "",
        }

    elif record_type == "task":
        ttype_raw = parts[3] if len(parts) > 3 else ""
        # Map AppleScript task type to readable form
        if ttype_raw == "standard task":
            task_type = "task"
        elif ttype_raw == "milestone task":
            task_type = "milestone"
        elif ttype_raw == "group task":
            task_type = "group"
        elif ttype_raw == "hammock task":
            task_type = "hammock"
        else:
            task_type = ttype_raw

        dur_sec = float(parts[6]) if len(parts) > 6 and parts[6] else 0
        pct_raw = float(parts[7]) if len(parts) > 7 and parts[7] else 0
        effort_sec = float(parts[8]) if len(parts) > 8 and parts[8] else 0

        return {
            "type": "task",
            "id": int(parts[1]) if len(parts) > 1 and parts[1] else 0,
            "name": parts[2] if len(parts) > 2 else "",
            "task_type": task_type,
            "start_date": _parse_as_date(parts[4] if len(parts) > 4 else ""),
            "end_date": _parse_as_date(parts[5] if len(parts) > 5 else ""),
            "duration_days": _seconds_to_days(dur_sec),
            "duration_hours": _seconds_to_hours(dur_sec),
            "duration_seconds": dur_sec,
            "percent_complete": round(pct_raw * 100, 1),
            "effort_hours": _seconds_to_hours(effort_sec),
            "effort_seconds": effort_sec,
            "outline_depth": int(parts[9]) if len(parts) > 9 and parts[9] else 0,
            "outline_number": parts[10] if len(parts) > 10 else "",
            "parent_id": int(parts[11]) if len(parts) > 11 and parts[11] else -1,
            "priority": int(parts[12]) if len(parts) > 12 and parts[12] else 0,
        }

    return {"type": "unknown", "raw": line}


# ── Main Parse Functions ────────────────────────────────────────────────


def read_apple_data() -> tuple[list[dict], list[dict], list[dict]]:
    """Read project data from currently open OmniPlan document via AppleScript.

    Returns:
        Tuple of (project_info, resources, tasks).
    """
    raw = _run_osascript(_READ_OPEN_DOC)

    if raw == "NO_DOCUMENT":
        raise RuntimeError(
            "No document is open in OmniPlan. "
            "Please open a project file first."
        )

    return _parse_lines(raw)


def read_mpp(filepath: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Read a .mpp file via AppleScript (opens in OmniPlan, reads, closes).

    Uses macOS 'open' command to open the file (which avoids OmniPlan's
    AppleScript 'open' command bug), then reads via AppleScript.

    Returns:
        Tuple of (project_info, resources, tasks).
    """
    abs_path = os.path.abspath(filepath)

    # Open the file using macOS open command (more reliable than AppleScript)
    import subprocess as _sp
    _sp.run(["open", "-a", "OmniPlan", abs_path], capture_output=True, check=True)
    import time
    time.sleep(2)  # Give OmniPlan time to load

    try:
        raw = _run_osascript(_READ_OPEN_DOC)
        if raw == "NO_DOCUMENT":
            raise RuntimeError("Failed to open document in OmniPlan")
        return _parse_lines(raw)
    finally:
        # Close the document
        _sp.run(
            ["osascript", "-l", "AppleScript", "-e",
             'tell application "OmniPlan" to close document 1 saving no'],
            capture_output=True, timeout=30,
        )


def _parse_lines(raw: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Parse AppleScript output lines into structured records."""
    projects = []
    resources = []
    tasks = []

    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        record = _parse_as_record(line)
        t = record["type"]
        if t == "project":
            projects.append(record)
        elif t == "resource":
            resources.append(record)
        elif t == "task":
            tasks.append(record)

    return projects, resources, tasks


# ── .oplx XML Parsing (kept for files without OmniPlan) ────────────────


def read_oplx(filepath: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Read an .oplx file via direct XML parsing.

    Returns:
        Tuple of (project_info, resources, tasks).
    """
    if os.path.isdir(filepath):
        return _parse_oplx_dir(filepath)
    return _parse_oplx_zip(filepath)


def _get_text(elem: ET.Element | None, tag: str) -> str:
    if elem is None:
        return ""
    el = elem.find(f"{NS}{tag}")
    return el.text.strip() if el is not None and el.text else ""


def _convert_iso_date(d: str) -> str:
    if not d:
        return ""
    try:
        dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return d[:10] if len(d) >= 10 else d


def _parse_oplx_zip(filepath: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Parse .oplx ZIP file."""
    with zipfile.ZipFile(filepath) as z:
        names = z.namelist()
        target = None
        for n in names:
            if n.endswith(".xml"):
                content = z.read(n).decode("utf-8")
                if "<task" in content and "<title>" in content:
                    target = content
                    break
        if target is None:
            target = z.read("Actual.xml").decode("utf-8")

    return _parse_xml_content(target)


def _parse_oplx_dir(dirpath: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Parse .oplx directory export."""
    candidates = []
    for f in os.listdir(dirpath):
        if f.endswith(".xml") and f not in ("__TOC.xml", "__changelog.xml"):
            fp = os.path.join(dirpath, f)
            candidates.append((os.path.getsize(fp), fp))

    if not candidates:
        raise RuntimeError(f"No XML data file found in {dirpath}")

    candidates.sort(reverse=True)
    with open(candidates[0][1]) as f:
        return _parse_xml_content(f.read())


def _parse_xml_content(content: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Parse XML content into structured records."""
    root = ET.fromstring(content)

    projects = []
    resources = []
    tasks = []

    # Project info
    start_date = _get_text(root, "start-date")
    projects.append({
        "type": "project",
        "title": "",
        "start_date": _convert_iso_date(start_date),
        "end_date": "",
        "percent_complete": 0,
    })

    # Resources
    for r in root.findall(f".//{NS}resource"):
        rtype = _get_text(r, "type")
        if rtype == "Staff":
            resources.append({
                "type": "resource",
                "id": r.get("id", ""),
                "name": _get_text(r, "name"),
                "resource_type": "person",
            })

    # Tasks
    task_map = {}
    for t in root.findall(f".//{NS}task"):
        tid = t.get("id", "")
        ttype = _get_text(t, "type")
        if ttype == "milestone":
            task_type = "milestone"
        elif ttype == "group":
            task_type = "group"
        else:
            task_type = "task"

        dur = _get_text(t, "duration")
        dur_sec = float(dur) if dur else 0

        tasks.append({
            "type": "task",
            "id": tid,
            "name": _get_text(t, "title"),
            "task_type": task_type,
            "start_date": _convert_iso_date(_get_text(t, "start-date")),
            "end_date": _convert_iso_date(_get_text(t, "end-date")),
            "duration_days": _seconds_to_days(dur_sec),
            "duration_hours": _seconds_to_hours(dur_sec),
            "duration_seconds": dur_sec,
            "percent_complete": float(_get_text(t, "percent-complete") or 0),
            "effort_hours": _seconds_to_hours(float(_get_text(t, "effort") or 0)),
            "effort_seconds": float(_get_text(t, "effort") or 0),
            "outline_depth": int(_get_text(t, "indentLevel") or 0),
            "outline_number": "",
            "parent_id": "",
            "priority": int(_get_text(t, "priority") or 500),
        })
        task_map[tid] = tasks[-1]

    # Resolve parent relationships
    for t in root.findall(f".//{NS}task"):
        tid = t.get("id", "")
        if tid in task_map:
            # Find parent by checking if this task is a child of another
            for parent in root.findall(f".//{NS}task"):
                for child in parent:
                    clocal = child.tag.split("}")[1] if "}" in child.tag else child.tag
                    if clocal == "child-task" and child.get("idref", "") == tid:
                        task_map[tid]["parent_id"] = parent.get("id", "")
                        break

    return projects, resources, tasks


# ── Unified API ─────────────────────────────────────────────────────────


def parse_file(filepath: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Parse a project schedule file (.mpp or .oplx).

    Args:
        filepath: Path to the schedule file.

    Returns:
        Tuple of (project_info, resources, tasks).

    Raises:
        ValueError: If file format is unsupported.
        RuntimeError: If parsing fails.
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".mpp":
        return read_mpp(filepath)
    elif ext == ".oplx":
        return read_oplx(filepath)
    else:
        raise ValueError(
            f"Unsupported file format: {ext}. "
            f"Supported: .mpp, .oplx"
        )


def build_task_tree(tasks: list[dict]) -> list[dict]:
    """Build a hierarchical task tree from flat task list.

    Tasks are nested based on parent_id relationships.
    Returns tasks sorted by outline_depth and ordered as a tree.
    """
    task_map = {}
    for t in tasks:
        tid = t["id"]
        task_map[tid] = dict(t)
        task_map[tid]["children"] = []

    roots = []
    for t in tasks:
        tid = t["id"]
        parent_id = t["parent_id"]
        if parent_id == -1 or parent_id == "" or parent_id not in task_map:
            roots.append(task_map[tid])
        else:
            parent = task_map.get(parent_id)
            if parent:
                parent["children"].append(task_map[tid])

    return roots


def get_resources_staff(resources: list[dict]) -> list[dict]:
    """Filter only person-type resources."""
    return [r for r in resources if r.get("resource_type") == "person"]
