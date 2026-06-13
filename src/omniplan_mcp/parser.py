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
    set projDur to duration of sce
    set projEff to effort of sce
    set projCost to total cost of sce
    set projViolations to violation count of sce
    try
        set projGran to scheduling granularity of sce
    on error
        set projGran to ""
    end try
    set end of output to "project|" & projTitle & "|" & projStartStr & "|" & projEndStr & "|" & projPct & "|" & projDur & "|" & projEff & "|" & projCost & "|" & projViolations & "|" & projGran

    -- Resources (ALL properties)
    set allResources to every resource of sce
    repeat with r in allResources
        set rid to id of r
        set rname to name of r
        set rtype to resource type of r
        set rdepth to outline depth of r
        set rnum to number of r
        set reff to efficiency of r
        set rcpu to cost per use of r
        set rcph to cost per hour of r
        set rtuses to total uses of r
        set rtsec to total seconds of r
        set rtcost to total cost of r
        try
            set remail to email address of r
        on error
            set remail to ""
        end try
        try
            set rnote to note of r
        on error
            set rnote to ""
        end try
        try
            set rexp to expanded of r
        on error
            set rexp to ""
        end try
        set end of output to "resource|" & rid & "|" & rname & "|" & rtype & "|" & rdepth & "|" & rnum & "|" & reff & "|" & rcpu & "|" & rcph & "|" & rtuses & "|" & rtsec & "|" & rtcost & "|" & remail & "|" & rnote & "|" & rexp
    end repeat

    -- All tasks (ALL properties)
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
        set treff to remaining effort of t
        set tceff to completed effort of t
        set tdepth to outline depth of t
        set tnum to outline number of t

        set tparent to -1
        try
            set tparent to id of parent task of t
        end try

        set tpri to priority of t
        set tstat to task status of t
        set tscost to static cost of t
        set trcost to resource cost of t
        set ttcost to total cost of t
        try
            set tnote to note of t
        on error
            set tnote to ""
        end try

        set tchilds to 0
        try
            set tchilds to count of (every task of t)
        end try
        set tasgns to 0
        try
            set tasgns to count of (every assignment of t)
        end try
        set tpres to 0
        try
            set tpres to count of (every prerequisite of t)
        end try
        set tdep to 0
        try
            set tdep to count of (every dependent of t)
        end try

        -- Constraint dates (from sdef)
        set tstartConst to ""
        set tendConst to ""
        try
            set tstartConst to date string of starting constraint date of t
        end try
        try
            set tendConst to date string of ending constraint date of t
        end try

        set end of output to "task|" & tid & "|" & tname & "|" & ttype & "|" & tstart & "|" & tend & "|" & tdur & "|" & tpct & "|" & teff & "|" & treff & "|" & tceff & "|" & tdepth & "|" & tnum & "|" & tparent & "|" & tpri & "|" & tstat & "|" & tscost & "|" & trcost & "|" & ttcost & "|" & tnote & "|" & tchilds & "|" & tasgns & "|" & tpres & "|" & tdep & "|" & tstartConst & "|" & tendConst
    end repeat

    -- Violations
    try
        set allViolations to every violation of sce
        repeat with v in allViolations
            set vt to violation type of v
            set vdesc to short description of v
            set vhtml to html of v
            try
                set vtid to id of task of v
            on error
                set vtid to -1
            end try
            set end of output to "violation|" & vt & "|" & vdesc & "|" & vhtml & "|" & vtid
        end repeat
    end try

    -- Assignments (sample: only tasks with assignments)
    repeat with t in allTasks
        try
            set assigns to every assignment of t
            if (count of assigns) > 0 then
                repeat with a in assigns
                    set rid_asgn to id of resource of a
                    set end of output to "assignment|" & tid & "|" & rid_asgn
                end repeat
            end if
        end try
    end repeat

    -- Dependencies (sample: only tasks with prerequisites)
    repeat with t in allTasks
        try
            set prereqs to every prerequisite of t
            if (count of prereqs) > 0 then
                repeat with p in prereqs
                    set pid to id of prerequisite task of p
                    set end of output to "dependency|" & tid & "|" & pid
                end repeat
            end if
        end try
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
            "outline_depth": int(parts[4]) if len(parts) > 4 and parts[4] else 0,
            "number": float(parts[5]) if len(parts) > 5 and parts[5] else 1.0,
            "efficiency": float(parts[6]) if len(parts) > 6 and parts[6] else 1.0,
            "cost_per_use": float(parts[7]) if len(parts) > 7 and parts[7] else 0,
            "cost_per_hour": float(parts[8]) if len(parts) > 8 and parts[8] else 0,
            "total_uses": int(parts[9]) if len(parts) > 9 and parts[9] else 0,
            "total_seconds": float(parts[10]) if len(parts) > 10 and parts[10] else 0,
            "total_cost": float(parts[11]) if len(parts) > 11 and parts[11] else 0,
            "email": parts[12] if len(parts) > 12 else "",
            "note": parts[13] if len(parts) > 13 else "",
            "expanded": parts[14] if len(parts) > 14 else "",
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

        result = {
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

        # Optional extra fields from later pipe positions
        if len(parts) > 22:
            result["task_status"] = parts[14] if len(parts) > 14 else ""
            result["static_cost"] = float(parts[15]) if len(parts) > 15 and parts[15] else 0
            result["resource_cost"] = float(parts[16]) if len(parts) > 16 and parts[16] else 0
            result["total_cost"] = float(parts[17]) if len(parts) > 17 and parts[17] else 0
            result["note"] = parts[18] if len(parts) > 18 else ""
            result["child_task_count"] = int(parts[19]) if len(parts) > 19 and parts[19] else 0
            result["assignment_count"] = int(parts[20]) if len(parts) > 20 and parts[20] else 0
            result["prerequisite_count"] = int(parts[21]) if len(parts) > 21 and parts[21] else 0
            result["dependent_count"] = int(parts[22]) if len(parts) > 22 and parts[22] else 0
        if len(parts) > 23:
            result["remaining_effort_hours"] = _seconds_to_hours(float(parts[8]) if parts[8] else 0)
            result["completed_effort_hours"] = _seconds_to_hours(float(parts[9]) if parts[9] else 0)
        if len(parts) > 24:
            result["starting_constraint_date"] = _parse_as_date(parts[24] if len(parts) > 24 else "")
            result["ending_constraint_date"] = _parse_as_date(parts[25] if len(parts) > 25 else "")

        return result

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


def read_mpp(filepath: str) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Read a .mpp file via AppleScript (opens in OmniPlan, reads, closes).

    Uses macOS 'open' command to open the file (which avoids OmniPlan's
    AppleScript 'open' command bug), then reads via AppleScript.

    Returns:
        Tuple of (project_info, resources, tasks, violations, assignments, dependencies).
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


def _parse_lines(
    raw: str,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Parse AppleScript output lines into structured records."""
    projects = []
    resources = []
    tasks = []
    violations = []
    assignments = []
    dependencies = []

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
        elif t == "violation":
            violations.append(record)
        elif t == "assignment":
            assignments.append(record)
        elif t == "dependency":
            dependencies.append(record)

    return projects, resources, tasks, violations, assignments, dependencies


# ── .oplx XML Parsing (kept for files without OmniPlan) ────────────────


def read_oplx(filepath: str) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Read an .oplx file via direct XML parsing.

    Returns:
        Tuple of (project_info, resources, tasks, violations, assignments, dependencies).
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


def _parse_oplx_zip(filepath: str) -> tuple[list[dict], list[dict], list[dict], list, list, list]:
    """Parse .oplx ZIP file."""
    with zipfile.ZipFile(filepath) as z:
        names = z.namelist()
        target = None
        # Always prefer Actual.xml (it contains the latest data).
        # OmniPlan creates backup XML files on save that may be stale.
        if "Actual.xml" in names:
            target = z.read("Actual.xml").decode("utf-8")
        else:
            for n in names:
                if n.endswith(".xml"):
                    content = z.read(n).decode("utf-8")
                    if "<task" in content and "<title>" in content:
                        target = content
                        break

    return _parse_xml_content(target)


def _parse_oplx_dir(dirpath: str) -> tuple[list[dict], list[dict], list[dict], list, list, list]:
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


def _compute_task_status(
    percent_complete: float,
    start_date: str = "",
    end_date: str = "",
    leveled_start: str = "",
    leveled_end: str = "",
) -> str:
    """Compute task status from completion percentage and dates.

    Mimics OmniPlan's logic: 100% → finished, else compare dates to today.
    Falls back to leveled-* dates when start-date/end-date are missing.
    """
    if percent_complete >= 100:
        return "finished"

    # Use leveled dates as fallback
    s = start_date or leveled_start
    e = end_date or leveled_end

    if not s and not e:
        return "ok"

    # Try to parse end date
    if e:
        try:
            end_dt = datetime.fromisoformat(e.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if end_dt < now:
                return "past due"
            # Close to due: within 3 days
            delta = (end_dt - now).days
            if delta <= 3 and delta >= 0:
                return "close to due date"
            if delta == 0:
                return "due now"
        except (ValueError, TypeError):
            pass

    return "ok"


def _parse_xml_content(content: str) -> tuple[list[dict], list[dict], list[dict], list, list, list]:
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

        # Get percent-complete: standard tasks store it directly,
        # group tasks may lack the tag so default to 0
        pct_str = _get_text(t, "percent-complete")
        percent_complete = float(pct_str) if pct_str else 0

        # Fallback: compute from effort-done / effort ratio
        if percent_complete == 0:
            effort_str = _get_text(t, "effort")
            effort_done_str = _get_text(t, "effort-done")
            if effort_str and effort_done_str:
                effort_val = float(effort_str)
                effort_done_val = float(effort_done_str)
                if effort_val > 0:
                    percent_complete = round(effort_done_val / effort_val * 100, 1)

        # Compute task status from dates and completion
        task_status = _compute_task_status(
            percent_complete,
            _get_text(t, "start-date"),
            _get_text(t, "end-date"),
            _get_text(t, "leveled-start"),
            _get_text(t, "leveled-end"),
        )

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
            "percent_complete": percent_complete,
            "effort_hours": _seconds_to_hours(float(_get_text(t, "effort") or 0)),
            "effort_seconds": float(_get_text(t, "effort") or 0),
            "outline_depth": 0,  # Will be computed after parent resolution
            "outline_number": "",
            "parent_id": "",
            "priority": int(_get_text(t, "priority") or 500),
            "task_status": task_status,
        })
        task_map[tid] = tasks[-1]

    # Resolve parent relationships and compute outline depth
    def _set_depth(tid: str, depth: int) -> None:
        """Recursively set outline_depth for a task and its children."""
        if tid not in task_map:
            return
        task_map[tid]["outline_depth"] = depth
        for child in task_map[tid].get("_children", []):
            _set_depth(child, depth + 1)

    for t in root.findall(f".//{NS}task"):
        tid = t.get("id", "")
        if tid in task_map:
            task_map[tid]["_children"] = []
            for child in t:
                clocal = child.tag.split("}")[1] if "}" in child.tag else child.tag
                if clocal == "child-task":
                    cid = child.get("idref", "")
                    task_map[tid]["_children"].append(cid)
                    if cid in task_map:
                        task_map[cid]["parent_id"] = tid

    # Find root tasks (those with no parent or parent is root group)
    # and compute outline_depth recursively
    for tid, tdata in task_map.items():
        if not tdata.get("parent_id") or tdata["parent_id"] == "t-1":
            _set_depth(tid, 0)

    # Compute group task completion from children (bottom-up)
    # Process in reverse depth order so children are computed before parents
    sorted_tasks = sorted(tasks, key=lambda t: t["outline_depth"], reverse=True)
    for t in sorted_tasks:
        if t["task_type"] != "group":
            continue
        # _children is stored in task_map copy, not in the original tasks list
        tid = t["id"]
        if tid not in task_map:
            continue
        children_ids = task_map[tid].get("_children", [])
        children = [task_map.get(cid) for cid in children_ids if cid in task_map]
        if not children:
            continue
        # Average child completion, weighted equally
        child_pcts = [c.get("percent_complete", 0) for c in children]
        t["percent_complete"] = round(sum(child_pcts) / len(child_pcts), 1)
        # Update task_status if all children are finished
        if all(c.get("task_status") == "finished" for c in children):
            t["task_status"] = "finished"
        elif t["percent_complete"] >= 100:
            t["task_status"] = "finished"

    # Remove internal _children helper field from output
    for t in tasks:
        t.pop("_children", None)

    return projects, resources, tasks, [], [], []


# ── Unified API ─────────────────────────────────────────────────────────


def parse_file(
    filepath: str,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Parse a project schedule file (.mpp or .oplx).

    Args:
        filepath: Path to the schedule file.

    Returns:
        Tuple of (project_info, resources, tasks, violations, assignments, dependencies).

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


def evaluate_javascript(script: str) -> str:
    """Evaluate JavaScript in OmniPlan's Omni Automation runtime.

    Uses the 'evaluate javascript' AppleScript command to run any
    Omni Automation JS code directly in the active document context.

    Args:
        script: JavaScript code to evaluate.

    Returns:
        The result string from JavaScript evaluation.

    Raises:
        RuntimeError: If no document is open or execution fails.
    """
    # Escape the script for safe embedding in AppleScript string
    # AppleScript uses \" for escaped quotes within string literals
    escaped_script = script.replace("\\", "\\\\").replace('"', '\\"')

    as_script = (
        'tell application "OmniPlan"\n'
        '    try\n'
        f'        set jsResult to evaluate javascript "{escaped_script}"\n'
        '        if jsResult is missing value then\n'
        '            return "undefined"\n'
        '        end if\n'
        '        return jsResult as string\n'
        '    on error errMsg\n'
        '        return "ERROR: " & errMsg\n'
        '    end try\n'
        'end tell'
    )
    return _run_osascript(as_script)


def export_schedule(filepath: str, format_name: str = "OmniPlan XML", output_path: str | None = None) -> str:
    """Export the active OmniPlan document to a specific format.

    Uses the AppleScript 'export' command on the document.

    Args:
        filepath: Path to open (for context).
        format_name: Export format name. Common options:
            "OmniPlan XML" (.oplx), "OmniPlan Template" (.oplt),
            "HTML", "CSV", "Tab Delimited Text", "iCal",
            "OmniGraffle XML", "Work Breakdown Structure (WBS)"
        output_path: Where to save the exported file.
            If None, saves to a temp location and returns the path.

    Returns:
        Path to the exported file.
    """
    import tempfile

    abs_path = os.path.abspath(filepath)
    if output_path is None:
        suffix = _export_suffix(format_name)
        output_path = os.path.join(tempfile.mkdtemp(), f"export{suffix}")

    # Open file
    subprocess.run(["open", "-a", "OmniPlan", abs_path], capture_output=True, check=True)
    import time
    time.sleep(2)

    try:
        # Escape backslashes and quotes in file paths for safe AppleScript embedding
        safe_path = output_path.replace("\\", "\\\\").replace('"', '\\"')
        safe_format = format_name.replace("\\", "\\\\").replace('"', '\\"')
        as_script = (
            'tell application "OmniPlan"\n'
            '    try\n'
            f'        export document 1 to file "{safe_path}" as "{safe_format}"\n'
            '        return "OK"\n'
            '    on error errMsg\n'
            '        return "ERROR: " & errMsg\n'
            '    end try\n'
            'end tell'
        )
        result = _run_osascript(as_script)
        if result == "OK":
            return output_path
        return result
    finally:
        subprocess.run(
            ["osascript", "-l", "AppleScript", "-e",
             'tell application "OmniPlan" to close document 1 saving no'],
            capture_output=True, timeout=30,
        )


def _export_suffix(format_name: str) -> str:
    """Map export format name to file extension."""
    mapping = {
        "OmniPlan XML": ".oplx",
        "OmniPlan Template": ".oplt",
        "HTML": ".html",
        "CSV": ".csv",
        "Tab Delimited Text": ".txt",
        "iCal": ".ics",
        "OmniGraffle XML": ".graffle",
        "Work Breakdown Structure (WBS)": ".html",
    }
    return mapping.get(format_name, ".txt")


_SCHEDULE_SETTINGS_SCRIPT = r'''
tell application "OmniPlan"
    set docCount to count of documents
    if docCount = 0 then
        return "NO_DOCUMENT"
    end if
    set doc to document 1
    set proj to project of doc
    set sce to frontEditingScenario of proj
    set sched to schedule of sce

    set output to {{}}

    -- Scheduling granularity
    try
        set gran to scheduling granularity of sce
        set end of output to "granularity|" & gran
    end try

    -- Work week schedule
    try
        set wkSched to week day schedule of sched
        repeat with dayNum from 1 to 7
            set dayName to ""
            set dayStart to ""
            set dayEnd to ""
            try
                set dayName to (weekday of (date "Sunday, January 1, 2020" + (dayNum - 1) * days))
            end try
            try
                set {startTime, endTime} to working times of wkSched for weekday dayNum
                set dayStart to startTime
                set dayEnd to endTime
            end try
            set end of output to "weekday|" & dayNum & "|" & dayStart & "|" & dayEnd
        end repeat
    end try

    -- Calendar day schedule
    try
        set calSched to calendar day schedule of sched
        set end of output to "calSchedule|available"
    end try

    set AppleScript's text item delimiters to {return}
    return output as string
end tell
'''


def read_schedule_settings() -> dict[str, Any]:
    """Read schedule/work-time settings from the active OmniPlan document.

    Returns:
        Dict with keys: granularity, weekdays (list of day schedules).

    Raises:
        RuntimeError: If no document is open.
    """
    raw = _run_osascript(_SCHEDULE_SETTINGS_SCRIPT)

    if raw == "NO_DOCUMENT":
        raise RuntimeError(
            "No document is open in OmniPlan. "
            "Please open a project file first."
        )

    result: dict[str, Any] = {
        "granularity": "",
        "weekdays": [],
        "has_calendar_schedule": False,
    }

    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        record_type = parts[0]

        if record_type == "granularity" and len(parts) > 1:
            result["granularity"] = parts[1]
        elif record_type == "weekday" and len(parts) > 3:
            day_num = int(parts[1])
            day_names = ["", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            result["weekdays"].append({
                "day": day_names[day_num] if 1 <= day_num <= 7 else f"Day {day_num}",
                "day_number": day_num,
                "start_time": parts[2],
                "end_time": parts[3],
            })
        elif record_type == "calSchedule":
            result["has_calendar_schedule"] = True

    return result


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
        # Handle both integer (-1, -1) and string ("", "t-1") no-parent indicators
        is_root = False
        if isinstance(parent_id, int) and parent_id <= 0:
            is_root = True
        elif isinstance(parent_id, str) and (parent_id == "" or parent_id == "t-1"):
            is_root = True
        elif parent_id not in task_map:
            is_root = True

        if is_root:
            roots.append(task_map[tid])
        else:
            parent = task_map.get(parent_id)
            if parent:
                parent["children"].append(task_map[tid])

    return roots


def get_resources_staff(resources: list[dict]) -> list[dict]:
    """Filter only person-type resources."""
    return [r for r in resources if r.get("resource_type") == "person"]


# ── Write Operations (AppleScript bridge to OmniPlan) ─────────────────────


def lookup_task(search_name: str) -> str:
    """Find a task by name and return its details (ID, type, etc.).

    Args:
        search_name: Full or partial task name (case-insensitive).

    Returns:
        Formatted list of matching tasks with their IDs.
    """
    safe_name = search_name.replace('"', '\\"')
    script = (
        'tell application "OmniPlan"\n'
        '    set doc to document 1\n'
        '    set proj to project of doc\n'
        '    set sce to frontEditingScenario of proj\n'
        '    set allTasks to every task of sce\n'
        '    set output to {}\n'
        '    repeat with t in allTasks\n'
        '        set tname to name of t\n'
        '        if tname contains "' + safe_name + '" then\n'
        '            set tid to id of t\n'
        '            set end of output to "id=" & tid & " name=" & tname\n'
        '        end if\n'
        '    end repeat\n'
        '    if (count of output) = 0 then\n'
        '        return "No tasks found matching: ' + safe_name + '"\n'
        '    end if\n'
        '    set AppleScript\'s text item delimiters to {return}\n'
        '    return output as string\n'
        'end tell'
    )
    return _run_osascript(script)


def _run_as(script: str) -> str:
    """Run an AppleScript and return stdout, or raise on failure."""
    return _run_osascript(script)




def set_task_completed(task_id: str, include_subtree: bool = True) -> str:
    """Set a task to 100% complete via AppleScript.

    Args:
        task_id: Task ID — XML ID like "t258" or numeric like "258".
        include_subtree: If True, recursively set all descendants to 100%.

    Returns:
        Summary of what was updated.
    """
    # Strip "t" prefix to get the numeric ID AppleScript uses
    tid = task_id.lstrip("t")

    if include_subtree:
        script = f'''
tell application "OmniPlan"
    set doc to document 1
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    set countUpdated to 0
    set resultLines to {{}}
    repeat with t in allTasks
        if id of t = {tid} then
            set tname to name of t
            set completed of t to 1.0
            set countUpdated to countUpdated + 1
            set end of resultLines to "Updated: " & tname & " (GROUP)"
            -- Get all descendants recursively (2 levels deep)
            set children to every task of t
            repeat with child in children
                set completed of child to 1.0
                set countUpdated to countUpdated + 1
                set end of resultLines to "Updated: " & name of child
                set grandchildren to every task of child
                repeat with gc in grandchildren
                    set completed of gc to 1.0
                    set countUpdated to countUpdated + 1
                    set end of resultLines to "Updated: " & name of gc
                end repeat
            end repeat
        end if
    end repeat
    set AppleScript text item delimiters to return
    return (countUpdated as string) & " tasks updated." & return & (resultLines as string)
end tell'''
    else:
        script = f'''
tell application "OmniPlan"
    set doc to document 1
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {tid} then
            set completed of t to 1.0
            return "Updated: " & name of t
        end if
    end repeat
    return "Task not found: {tid}"
end tell'''
    return _run_as(script)


def set_task_completed_by_name(task_name: str, include_subtree: bool = True) -> str:
    """Set a task to 100% complete by name.

    Args:
        task_name: Name of the task to complete (case-sensitive exact match).
        include_subtree: If True, recursively set all descendants to 100%.

    Returns:
        Summary of what was updated.
    """
    # Escape double quotes for AppleScript
    safe_name = task_name.replace('"', '\\"')

    if include_subtree:
        script = f'''
tell application "OmniPlan"
    set doc to document 1
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    set countUpdated to 0
    set resultLines to {{}}
    repeat with t in allTasks
        if name of t = "{safe_name}" then
            set completed of t to 1.0
            set countUpdated to countUpdated + 1
            set end of resultLines to "Updated: " & name of t & " (GROUP)"
            set children to every task of t
            repeat with child in children
                set completed of child to 1.0
                set countUpdated to countUpdated + 1
                set end of resultLines to "Updated: " & name of child
                set grandchildren to every task of child
                repeat with gc in grandchildren
                    set completed of gc to 1.0
                    set countUpdated to countUpdated + 1
                    set end of resultLines to "Updated: " & name of gc
                end repeat
            end repeat
        end if
    end repeat
    set AppleScript text item delimiters to return
    return (countUpdated as string) & " tasks updated." & return & (resultLines as string)
end tell'''
    else:
        script = f'''
tell application "OmniPlan"
    set doc to document 1
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if name of t = "{safe_name}" then
            set completed of t to 1.0
            return "Updated: " & name of t
        end if
    end repeat
    return "Task not found: {safe_name}"
end tell'''
    return _run_as(script)


def add_dependency(dependent_task_id: str, prerequisite_task_id: str) -> str:
    """Add a finish-to-start dependency: dependent ← prerequisite.

    Args:
        dependent_task_id: The task that must wait (AppleScript numeric ID).
        prerequisite_task_id: The task that must finish first.

    Returns:
        Confirmation message.
    """
    dep = dependent_task_id.lstrip("t")
    pre = prerequisite_task_id.lstrip("t")
    script = f'''
tell application "OmniPlan"
    set doc to document 1
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    set depTask to missing value
    set preTask to missing value
    repeat with t in allTasks
        if id of t = {dep} then set depTask to t
        if id of t = {pre} then set preTask to t
    end repeat
    if depTask is missing value then return "Error: dependent task {dep} not found"
    if preTask is missing value then return "Error: prerequisite task {pre} not found"
    depend depTask upon preTask
    return "Added dependency: " & name of preTask & " → " & name of depTask
end tell'''
    return _run_as(script)


def remove_dependency(dependent_task_id: str, prerequisite_task_id: str) -> str:
    """Remove a dependency between two tasks.

    Args:
        dependent_task_id: The dependent task.
        prerequisite_task_id: The prerequisite task to remove.

    Returns:
        Confirmation message.
    """
    dep = dependent_task_id.lstrip("t")
    pre = prerequisite_task_id.lstrip("t")
    script = f'''
tell application "OmniPlan"
    set doc to document 1
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {dep} then
            try
                set prereqs to every prerequisite of t
                repeat with p in prereqs
                    set pTask to prerequisite task of p
                    if id of pTask = {pre} then
                        set pName to name of pTask
                        delete p
                        return "Removed dependency: " & pName & " → " & name of t
                    end if
                end repeat
                return "Dependency not found"
            on error e
                return "Error: " & e
            end try
        end if
    end repeat
    return "Task {dep} not found"
end tell'''
    return _run_as(script)


def set_task_duration(task_id: str, duration_seconds: int) -> str:
    """Set a task's duration.

    Args:
        task_id: AppleScript numeric task ID.
        duration_seconds: Duration in working seconds (28800 = 1 working day).

    Returns:
        Confirmation message.
    """
    tid = task_id.lstrip("t")
    script = f'''
tell application "OmniPlan"
    set doc to document 1
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {tid} then
            set tname to name of t
            set duration of t to {duration_seconds}
            set durDays to round({duration_seconds} / 28800 * 10) / 10
            return "Set " & tname & " duration to " & durDays & " days"
        end if
    end repeat
    return "Task {tid} not found"
end tell'''
    return _run_as(script)


def clear_constraint_date(task_id: str) -> str:
    """Remove the starting constraint (locked start date) from a task.

    Args:
        task_id: AppleScript numeric task ID.

    Returns:
        Confirmation message.
    """
    tid = task_id.lstrip("t")
    # Use evaluate javascript to avoid AppleScript keyword conflicts
    script = f'''
tell application "OmniPlan"
    set doc to document 1
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {tid} then
            set tname to name of t
            try
                -- Use the cocoa key directly
                set startConstraintDate of t to missing value
            end try
            try
                set endConstraintDate of t to missing value
            end try
            return "Cleared constraint dates for: " & tname
        end if
    end repeat
    return "Task {tid} not found"
end tell'''
    return _run_as(script)


def rename_task(task_id: str, new_name: str) -> str:
    """Rename a task.

    Args:
        task_id: AppleScript numeric task ID.
        new_name: New name for the task.

    Returns:
        Confirmation message.
    """
    tid = task_id.lstrip("t")
    safe_name = new_name.replace('"', '\\"')
    script = f'''
tell application "OmniPlan"
    set doc to document 1
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {tid} then
            set oldName to name of t
            set name of t to "{safe_name}"
            return "Renamed: " & oldName & " → {safe_name}"
        end if
    end repeat
    return "Task {tid} not found"
end tell'''
    return _run_as(script)


def delete_task(task_id: str) -> str:
    """Delete a task and all its children.

    Args:
        task_id: AppleScript numeric task ID.

    Returns:
        Confirmation message.
    """
    tid = task_id.lstrip("t")
    script = f'''
tell application "OmniPlan"
    set doc to document 1
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {tid} then
            set tname to name of t
            delete t
            return "Deleted: " & tname
        end if
    end repeat
    return "Task {tid} not found"
end tell'''
    return _run_as(script)


def add_task(parent_task_id: str, task_name: str, duration_seconds: int = 28800) -> str:
    """Add a new task under a parent group.

    Args:
        parent_task_id: AppleScript numeric task ID of the parent group.
        task_name: Name for the new task.
        duration_seconds: Duration in working seconds (default 1 day).

    Returns:
        Confirmation message.
    """
    pid = parent_task_id.lstrip("t")
    safe_name = task_name.replace('"', '\\"')
    script = f'''
tell application "OmniPlan"
    set doc to document 1
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {pid} then
            make new task at end of tasks of t with properties {{name:"{safe_name}", duration:{duration_seconds}}}
            return "Added task: {safe_name} under " & name of t
        end if
    end repeat
    return "Parent task {pid} not found"
end tell'''
    return _run_as(script)


def save_document() -> str:
    """Save the current OmniPlan document.

    Returns:
        Confirmation message.
    """
    script = '''
tell application "OmniPlan"
    try
        save document 1
        return "Document saved"
    on error e
        return "Save error: " & e
    end try
end tell'''
    return _run_as(script)
