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


def _normalize_task_id(task_id: str) -> str:
    """Return an AppleScript-safe numeric task ID."""
    normalized = str(task_id).removeprefix("t")
    if not normalized.isdigit():
        raise ValueError(f"Invalid task ID: {task_id!r}")
    return normalized


def _escape_applescript_string(value: str) -> str:
    """Escape a value for use inside an AppleScript string literal."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _validate_nonnegative_seconds(value: int | float, field_name: str) -> int | float:
    """Validate numeric second values before interpolating into AppleScript."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative number")
    return value


def _open_document_paths() -> set[str]:
    """Return normalized paths for saved documents currently open in OmniPlan."""
    script = r'''
tell application "OmniPlan"
    set output to {}
    repeat with d in every document
        try
            set end of output to POSIX path of ((file of d) as alias)
        end try
    end repeat
    set AppleScript's text item delimiters to {return}
    return output as string
end tell
'''
    raw = _run_osascript(script)
    return {
        os.path.realpath(path)
        for path in raw.splitlines()
        if path.strip()
    }


def _document_prelude(
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Build AppleScript that selects one document without relying on document 1."""
    if filepath and document_id:
        raise ValueError("Specify either filepath or document_id, not both")

    if filepath:
        wanted_path = _escape_applescript_string(
            os.path.realpath(os.path.abspath(filepath))
        )
        return f'''
    set doc to missing value
    repeat with candidate in every document
        try
            if POSIX path of ((file of candidate) as alias) is "{wanted_path}" then
                set doc to candidate
                exit repeat
            end if
        end try
    end repeat
    if doc is missing value then return "Error: document is not open: {wanted_path}"
'''

    if document_id:
        wanted_id = _escape_applescript_string(document_id)
        return f'''
    set doc to missing value
    repeat with candidate in every document
        if (id of candidate as string) is "{wanted_id}" then
            set doc to candidate
            exit repeat
        end if
    end repeat
    if doc is missing value then return "Error: document ID is not open: {wanted_id}"
'''

    return '''
    set docCount to count of documents
    if docCount = 0 then return "Error: no OmniPlan document is open"
    if docCount > 1 then return "Error: multiple OmniPlan documents are open; specify filepath or document_id"
    set doc to item 1 of documents
'''


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
            set tid to id of t
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
            set tid to id of t
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
        resource_type_raw = parts[3] if len(parts) > 3 else ""
        resource_type_map = {
            "staff resource": "person",
            "equipment resource": "equipment",
            "material resource": "material",
            "group resource": "group",
        }
        return {
            "type": "resource",
            "id": int(parts[1]) if len(parts) > 1 and parts[1] else 0,
            "name": parts[2] if len(parts) > 2 else "",
            "resource_type": resource_type_map.get(resource_type_raw, resource_type_raw),
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
            "remaining_effort_hours": _seconds_to_hours(float(parts[9])) if len(parts) > 9 and parts[9] else 0,
            "completed_effort_hours": _seconds_to_hours(float(parts[10])) if len(parts) > 10 and parts[10] else 0,
            "outline_depth": int(parts[11]) if len(parts) > 11 and parts[11] else 0,
            "outline_number": parts[12] if len(parts) > 12 else "",
            "parent_id": int(parts[13]) if len(parts) > 13 and parts[13] else -1,
            "priority": int(parts[14]) if len(parts) > 14 and parts[14] else 0,
        }

        result["task_status"] = parts[15] if len(parts) > 15 else ""
        result["static_cost"] = float(parts[16]) if len(parts) > 16 and parts[16] else 0
        result["resource_cost"] = float(parts[17]) if len(parts) > 17 and parts[17] else 0
        result["total_cost"] = float(parts[18]) if len(parts) > 18 and parts[18] else 0
        result["note"] = parts[19] if len(parts) > 19 else ""
        result["child_task_count"] = int(parts[20]) if len(parts) > 20 and parts[20] else 0
        result["assignment_count"] = int(parts[21]) if len(parts) > 21 and parts[21] else 0
        result["prerequisite_count"] = int(parts[22]) if len(parts) > 22 and parts[22] else 0
        result["dependent_count"] = int(parts[23]) if len(parts) > 23 and parts[23] else 0
        result["starting_constraint_date"] = _parse_as_date(parts[24] if len(parts) > 24 else "")
        result["ending_constraint_date"] = _parse_as_date(parts[25] if len(parts) > 25 else "")

        return result

    elif record_type == "violation":
        return {
            "type": "violation",
            "violation_type": parts[1] if len(parts) > 1 else "",
            "description": parts[2] if len(parts) > 2 else "",
            "html": parts[3] if len(parts) > 3 else "",
            "task_id": int(parts[4]) if len(parts) > 4 and parts[4] else -1,
        }

    elif record_type == "assignment":
        return {
            "type": "assignment",
            "task_id": int(parts[1]) if len(parts) > 1 and parts[1] else 0,
            "resource_id": int(parts[2]) if len(parts) > 2 and parts[2] else 0,
        }

    elif record_type == "dependency":
        return {
            "type": "dependency",
            "task_id": int(parts[1]) if len(parts) > 1 and parts[1] else 0,
            "prerequisite_task_id": int(parts[2]) if len(parts) > 2 and parts[2] else 0,
        }

    return {"type": "unknown", "raw": line}


# ── Main Parse Functions ────────────────────────────────────────────────


def _read_document_script(
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Return the live-read script with a deterministic document selector."""
    old_prelude = '''    set docCount to count of documents
    if docCount = 0 then
        return "NO_DOCUMENT"
    end if
    set doc to document 1
'''
    return _READ_OPEN_DOC.replace(
        old_prelude,
        _document_prelude(filepath, document_id),
        1,
    )


def _close_document(filepath: str, saving: str = "no") -> str:
    """Close a specific open document by path."""
    prelude = _document_prelude(filepath=filepath)
    script = f'''
tell application "OmniPlan"
{prelude}
    close doc saving {saving}
    return "Document closed"
end tell'''
    return _run_osascript(script)


def read_apple_data(
    filepath: str | None = None,
    document_id: str | None = None,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Read project data from currently open OmniPlan document via AppleScript.

    Returns:
        Tuple of (project_info, resources, tasks).
    """
    raw = _run_osascript(_read_document_script(filepath, document_id))

    if raw.startswith("Error:"):
        raise RuntimeError(raw)

    return _parse_lines(raw)


def read_mpp(filepath: str) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Read a .mpp file via AppleScript (opens in OmniPlan, reads, closes).

    Uses macOS 'open' command to open the file (which avoids OmniPlan's
    AppleScript 'open' command bug), then reads via AppleScript.

    Returns:
        Tuple of (project_info, resources, tasks, violations, assignments, dependencies).
    """
    abs_path = os.path.realpath(os.path.abspath(filepath))
    was_open = abs_path in _open_document_paths()

    # Open the file using macOS open command (more reliable than AppleScript)
    import subprocess as _sp
    _sp.run(["open", "-a", "OmniPlan", abs_path], capture_output=True, check=True)
    import time
    for _ in range(20):
        if abs_path in _open_document_paths():
            break
        time.sleep(0.25)
    else:
        raise RuntimeError(f"Failed to open document in OmniPlan: {abs_path}")

    try:
        return read_apple_data(filepath=abs_path)
    finally:
        if not was_open and abs_path in _open_document_paths():
            _close_document(abs_path)


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
        changelog = None
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
        if "__changelog.xml" in names:
            changelog = z.read("__changelog.xml").decode("utf-8")

    return _parse_xml_content(target, changelog)


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
        content = f.read()

    changelog_path = os.path.join(dirpath, "__changelog.xml")
    changelog = None
    if os.path.exists(changelog_path):
        with open(changelog_path) as f:
            changelog = f.read()

    return _parse_xml_content(content, changelog)


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


def _parse_xml_content(
    content: str,
    changelog_content: str | None = None,
) -> tuple[list[dict], list[dict], list[dict], list, list, list]:
    """Parse XML content into structured records."""
    root = ET.fromstring(content)

    projects = []
    resources = []
    tasks = []
    assignments = []
    dependencies = []

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
                "note": _get_text(r, "note") or "",
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
        if not dur:
            dur = _get_text(t, "fixed-duration")
        dur_sec = float(dur) if dur else 0
        start_date = _get_text(t, "start-date") or _get_text(t, "leveled-start")
        end_date = _get_text(t, "end-date") or _get_text(t, "leveled-end")

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
            start_date,
            end_date,
            _get_text(t, "leveled-start"),
            _get_text(t, "leveled-end"),
        )

        tasks.append({
            "type": "task",
            "id": tid,
            "name": _get_text(t, "title"),
            "task_type": task_type,
            "start_date": _convert_iso_date(start_date),
            "end_date": _convert_iso_date(end_date),
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
            "note": _get_text(t, "note") or "",
        })
        task_map[tid] = tasks[-1]

        for child in t:
            local_name = child.tag.split("}", 1)[-1]
            if local_name == "assignment":
                assignments.append({
                    "type": "assignment",
                    "task_id": tid,
                    "resource_id": child.get("idref", ""),
                })
            elif local_name == "prerequisite-task":
                dependencies.append({
                    "type": "dependency",
                    "task_id": tid,
                    "prerequisite_task_id": child.get("idref", ""),
                })

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

    if changelog_content:
        aliases = _resolve_changelog_task_aliases(changelog_content, task_map)
        for dependency in dependencies:
            prerequisite_id = dependency["prerequisite_task_id"]
            dependency["prerequisite_task_id"] = aliases.get(
                prerequisite_id,
                prerequisite_id,
            )

    return projects, resources, tasks, [], assignments, dependencies


def _resolve_changelog_task_aliases(
    changelog_content: str,
    task_map: dict[str, dict],
) -> dict[str, str]:
    """Resolve retired task IDs to current IDs using uniquely matching titles."""
    try:
        changelog_root = ET.fromstring(changelog_content)
    except ET.ParseError:
        return {}

    historical_titles: dict[str, str] = {}
    for change in changelog_root.findall(f".//{NS}change"):
        historical_id = change.get("idref")
        if not historical_id or historical_id in task_map:
            continue
        for nested_change in change.iter(f"{NS}change"):
            if nested_change.get("attribute") == "title" and nested_change.get("to"):
                historical_titles[historical_id] = nested_change.get("to", "")

    current_ids_by_title: dict[str, list[str]] = {}
    for task_id, task in task_map.items():
        current_ids_by_title.setdefault(task.get("name", ""), []).append(task_id)

    aliases = {}
    for historical_id, title in historical_titles.items():
        matches = current_ids_by_title.get(title, [])
        if len(matches) == 1:
            aliases[historical_id] = matches[0]
    return aliases


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

    abs_path = os.path.realpath(os.path.abspath(filepath))
    was_open = abs_path in _open_document_paths()
    if output_path is None:
        suffix = _export_suffix(format_name)
        output_path = os.path.join(tempfile.mkdtemp(), f"export{suffix}")

    # Open file
    subprocess.run(["open", "-a", "OmniPlan", abs_path], capture_output=True, check=True)
    import time
    for _ in range(20):
        if abs_path in _open_document_paths():
            break
        time.sleep(0.25)
    else:
        raise RuntimeError(f"Failed to open document in OmniPlan: {abs_path}")

    try:
        # Escape backslashes and quotes in file paths for safe AppleScript embedding
        safe_path = output_path.replace("\\", "\\\\").replace('"', '\\"')
        safe_format = format_name.replace("\\", "\\\\").replace('"', '\\"')
        prelude = _document_prelude(filepath=abs_path)
        as_script = (
            'tell application "OmniPlan"\n'
            + prelude +
            '    try\n'
            f'        export doc to file "{safe_path}" as "{safe_format}"\n'
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
        if not was_open and abs_path in _open_document_paths():
            _close_document(abs_path)


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

    -- Work week schedule (Sunday=1 through Saturday=7)
    try
        set wkSchedules to week day schedule of sched
        repeat with dayNum from 1 to (count of wkSchedules)
            set daySchedule to item dayNum of wkSchedules
            set dayStart to ""
            set dayEnd to ""
            try
                set dayStart to start time of daySchedule
                set dayEnd to end time of daySchedule
            end try
            set end of output to "weekday|" & dayNum & "|" & dayStart & "|" & dayEnd
        end repeat
    end try

    -- Calendar day schedule
    try
        set calSchedules to calendar day schedule of sched
        if (count of calSchedules) > 0 then
            set end of output to "calSchedule|available"
        end if
    end try

    set AppleScript's text item delimiters to {return}
    return output as string
end tell
'''


def read_schedule_settings(
    filepath: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Read schedule/work-time settings from the active OmniPlan document.

    Returns:
        Dict with keys: granularity, weekdays (list of day schedules).

    Raises:
        RuntimeError: If no document is open.
    """
    old_prelude = '''    set docCount to count of documents
    if docCount = 0 then
        return "NO_DOCUMENT"
    end if
    set doc to document 1
'''
    script = _SCHEDULE_SETTINGS_SCRIPT.replace(
        old_prelude,
        _document_prelude(filepath, document_id),
        1,
    )
    raw = _run_osascript(script)

    if raw.startswith("Error:"):
        raise RuntimeError(raw)

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


def lookup_task(
    search_name: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Find a task by name and return its details (ID, type, etc.).

    Args:
        search_name: Full or partial task name (case-insensitive).

    Returns:
        Formatted list of matching tasks with their IDs.
    """
    safe_name = _escape_applescript_string(search_name)
    prelude = _document_prelude(filepath, document_id)
    script = (
        'tell application "OmniPlan"\n' + prelude +
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




def set_task_completed(
    task_id: str,
    include_subtree: bool = True,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Set a task to 100% complete via AppleScript.

    Args:
        task_id: Task ID — XML ID like "t258" or numeric like "258".
        include_subtree: If True, recursively set all descendants to 100%.

    Returns:
        Summary of what was updated.
    """
    # Strip "t" prefix to get the numeric ID AppleScript uses
    tid = _normalize_task_id(task_id)
    prelude = _document_prelude(filepath, document_id)

    if include_subtree:
        script = f'''
tell application "OmniPlan"
{prelude}
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
            -- "every task of t" returns all descendants, not only direct children.
            set descendants to every task of t
            repeat with child in descendants
                set completed of child to 1.0
                set countUpdated to countUpdated + 1
                set end of resultLines to "Updated: " & name of child
            end repeat
            set AppleScript text item delimiters to return
            return (countUpdated as string) & " tasks updated." & return & (resultLines as string)
        end if
    end repeat
    return "Task not found: {tid}"
end tell'''
    else:
        script = f'''
tell application "OmniPlan"
{prelude}
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


def set_task_progress(
    task_id: str,
    percent_complete: float,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Set a task's completion percentage via AppleScript.

    Args:
        task_id: Task ID, either XML style ("t258") or numeric ("258").
        percent_complete: Completion percentage from 0 through 100.

    Returns:
        Confirmation message.
    """
    if isinstance(percent_complete, bool) or not isinstance(percent_complete, (int, float)):
        raise ValueError("percent_complete must be a number from 0 to 100")
    if not 0 <= percent_complete <= 100:
        raise ValueError("percent_complete must be between 0 and 100")

    tid = _normalize_task_id(task_id)
    percent = float(percent_complete)
    completion_fraction = percent / 100
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {tid} then
            set tname to name of t
            set completed of t to {completion_fraction}
            return "Set " & tname & " progress to " & ({percent} as string) & "%"
        end if
    end repeat
    return "Task {tid} not found"
end tell'''
    return _run_as(script)


def set_task_completed_by_name(
    task_name: str,
    include_subtree: bool = True,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Set a task to 100% complete by name.

    Args:
        task_name: Name of the task to complete (case-sensitive exact match).
        include_subtree: If True, recursively set all descendants to 100%.

    Returns:
        Summary of what was updated.
    """
    # Escape double quotes for AppleScript
    safe_name = _escape_applescript_string(task_name)
    prelude = _document_prelude(filepath, document_id)

    if include_subtree:
        script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    set matches to {{}}
    repeat with t in allTasks
        if name of t = "{safe_name}" then set end of matches to t
    end repeat
    if (count of matches) = 0 then return "Task not found: {safe_name}"
    if (count of matches) > 1 then return "Error: multiple tasks named {safe_name}; use task ID"
    set countUpdated to 0
    set resultLines to {{}}
    set t to item 1 of matches
    set completed of t to 1.0
    set countUpdated to countUpdated + 1
    set end of resultLines to "Updated: " & name of t & " (GROUP)"
    set descendants to every task of t
    repeat with child in descendants
        set completed of child to 1.0
        set countUpdated to countUpdated + 1
        set end of resultLines to "Updated: " & name of child
    end repeat
    set AppleScript text item delimiters to return
    return (countUpdated as string) & " tasks updated." & return & (resultLines as string)
end tell'''
    else:
        script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    set matches to {{}}
    repeat with t in allTasks
        if name of t = "{safe_name}" then set end of matches to t
    end repeat
    if (count of matches) = 0 then return "Task not found: {safe_name}"
    if (count of matches) > 1 then return "Error: multiple tasks named {safe_name}; use task ID"
    set t to item 1 of matches
    set completed of t to 1.0
    return "Updated: " & name of t
end tell'''
    return _run_as(script)


def _get_task_name_from_xml(root, task_id):
    """Get a task's title from the XML root."""
    import xml.etree.ElementTree as ET
    NS = "http://www.omnigroup.com/namespace/OmniPlan/v2"
    tid = _normalize_task_id(task_id)
    task_el = root.find(f".//{{{NS}}}task[@id='t{tid}']")
    if task_el is None:
        task_el = root.find(f".//{{{NS}}}task[@id='{tid}']")
    if task_el is not None:
        title_el = task_el.find(f"{{{NS}}}title")
        if title_el is not None and title_el.text:
            return title_el.text
    return f"t{tid}"


def _reload_document(filepath):
    """Close and re-open a document in OmniPlan so changes are picked up."""
    abs_path = os.path.realpath(os.path.abspath(filepath))
    _run_as(f'''
tell application "OmniPlan"
    try
        close document 1 saving no
    end try
    open POSIX file "{abs_path}"
    return "reloaded"
end tell''')


def add_dependency(
    dependent_task_id: str,
    prerequisite_task_id: str,
    filepath: str | None = None,
    document_id: str | None = None,
    reload: bool = False,
) -> str:
    """Add a finish-to-start dependency: dependent ← prerequisite.

    OmniPlan's AppleScript ``depend`` command writes ``<dependency>`` XML
    elements which the app does not honour — the document format requires
    ``<prerequisite-task idref="..." />`` inside the dependent task element.
    This function patches the .oplx ZIP directly.

    Args:
        dependent_task_id: The task that must wait (AppleScript numeric ID).
        prerequisite_task_id: The task that must finish first.

    Returns:
        Confirmation message.
    """
    dep = _normalize_task_id(dependent_task_id)
    pre = _normalize_task_id(prerequisite_task_id)

    # Resolve filepath
    if not filepath:
        # Try to find the open document
        open_paths = _open_document_paths()
        if open_paths:
            filepath = list(open_paths)[0]
        else:
            raise RuntimeError(
                "Could not determine open document path. "
                "Pass filepath explicitly."
            )

    abs_filepath = os.path.realpath(os.path.abspath(filepath))
    NS = "http://www.omnigroup.com/namespace/OmniPlan/v2"

    with zipfile.ZipFile(abs_filepath, 'r') as z:
        content = z.read("Actual.xml").decode("utf-8")

    root = ET.fromstring(content)
    task_el = root.find(f".//{{{NS}}}task[@id='t{dep}']")
    if task_el is None:
        task_el = root.find(f".//{{{NS}}}task[@id='{dep}']")
    if task_el is None:
        raise RuntimeError(f"Task t{dep} not found in .oplx file")

    # Check if dependency already exists
    for existing in task_el.findall(f"{{{NS}}}prerequisite-task"):
        if existing.get("idref") == f"t{pre}" or existing.get("idref") == pre:
            # Get names
            dep_name = _get_task_name_from_xml(root, dep)
            pre_name = _get_task_name_from_xml(root, pre)
            return f"Dependency already exists: {pre_name} → {dep_name}"

    # Add prerequisite-task element
    prereq_el = ET.SubElement(task_el, f"{{{NS}}}prerequisite-task")
    prereq_el.set("idref", f"t{pre}")

    # Re-serialize and write back
    xml_bytes = ET.tostring(root, encoding="unicode", xml_declaration=True).encode("utf-8")
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".oplx", delete=False)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
            with zipfile.ZipFile(abs_filepath, 'r') as zin:
                for item in zin.infolist():
                    if item.filename == "Actual.xml":
                        zout.writestr(item, xml_bytes)
                    else:
                        zout.writestr(item, zin.read(item.filename))
        os.replace(tmp.name, abs_filepath)
    except:
        os.unlink(tmp.name)
        raise

    # Reload in OmniPlan so the GUI reflects the change (only if requested)
    if reload:
        _reload_document(filepath)

    dep_name = _get_task_name_from_xml(root, dep)
    pre_name = _get_task_name_from_xml(root, pre)
    return f"Added dependency: {pre_name} → {dep_name}"


def remove_dependency(
    dependent_task_id: str,
    prerequisite_task_id: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Remove a dependency between two tasks.

    Args:
        dependent_task_id: The dependent task.
        prerequisite_task_id: The prerequisite task to remove.

    Returns:
        Confirmation message.
    """
    dep = _normalize_task_id(dependent_task_id)
    pre = _normalize_task_id(prerequisite_task_id)
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
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


def set_task_duration(
    task_id: str,
    duration_seconds: int,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Set a task's duration.

    Args:
        task_id: AppleScript numeric task ID.
        duration_seconds: Duration in working seconds (28800 = 1 working day).

    Returns:
        Confirmation message.
    """
    tid = _normalize_task_id(task_id)
    duration_seconds = _validate_nonnegative_seconds(
        duration_seconds,
        "duration_seconds",
    )
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
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


def clear_constraint_date(
    task_id: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Remove the starting constraint (locked start date) from a task.

    Args:
        task_id: AppleScript numeric task ID.

    Returns:
        Confirmation message.
    """
    tid = _normalize_task_id(task_id)
    prelude = _document_prelude(filepath, document_id)
    # Use evaluate javascript to avoid AppleScript keyword conflicts
    script = f'''
tell application "OmniPlan"
{prelude}
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


def rename_task(
    task_id: str,
    new_name: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Rename a task.

    Args:
        task_id: AppleScript numeric task ID.
        new_name: New name for the task.

    Returns:
        Confirmation message.
    """
    tid = _normalize_task_id(task_id)
    safe_name = _escape_applescript_string(new_name)
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
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


def delete_task(
    task_id: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Delete a task and all its children.

    Args:
        task_id: AppleScript numeric task ID.

    Returns:
        Confirmation message.
    """
    tid = _normalize_task_id(task_id)
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
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


def set_task_note(
    task_id: str,
    note_text: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Set a task's note/description via AppleScript.

    Args:
        task_id: AppleScript numeric task ID.
        note_text: The note text to set.

    Returns:
        Confirmation message.
    """
    tid = _normalize_task_id(task_id)
    safe_note = _escape_applescript_string(note_text)
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {tid} then
            set tname to name of t
            set note of t to "{safe_note}"
            return "Set note for: " & tname
        end if
    end repeat
    return "Task {tid} not found"
end tell'''
    return _run_as(script)


def set_resource_note(
    resource_id: str,
    note_text: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Set a resource's note/description via AppleScript.

    Args:
        resource_id: AppleScript numeric resource ID.
        note_text: The note text to set.

    Returns:
        Confirmation message.
    """
    rid = str(resource_id).removeprefix("r").removeprefix("R")
    if not rid.isdigit():
        raise ValueError(f"Invalid resource ID: {resource_id!r}")
    safe_note = _escape_applescript_string(note_text)
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    set allRes to every resource of sce
    repeat with r in allRes
        if id of r = {rid} then
            set rname to name of r
            set note of r to "{safe_note}"
            return "Set note for resource: " & rname
        end if
    end repeat
    return "Resource {rid} not found"
end tell'''
    return _run_as(script)


def add_task(
    parent_task_id: str,
    task_name: str,
    duration_seconds: int = 28800,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Add a new task under a parent group.

    Args:
        parent_task_id: AppleScript numeric task ID of the parent group.
            Pass ``"-1"``, ``"0"``, or ``"root"`` to add a top-level phase
            directly under the project root (sibling of Charter-CD/EVT/etc.).
        task_name: Name for the new task.
        duration_seconds: Duration in working seconds (default 1 day).

    Returns:
        Confirmation message.
    """
    duration_seconds = _validate_nonnegative_seconds(
        duration_seconds,
        "duration_seconds",
    )
    safe_name = _escape_applescript_string(task_name)
    prelude = _document_prelude(filepath, document_id)

    # Detect "add to project root" intent
    parent_str = str(parent_task_id).strip().lower()
    is_root = parent_str in ("-1", "0", "root", "t-1", "t0", "")

    if is_root:
        # Top-level: add directly to the scenario's task list (sibling of phases)
        script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    make new task at end of tasks of sce with properties {{name:"{safe_name}", duration:{duration_seconds}}}
    return "Added top-level task: {safe_name}"
end tell'''
        return _run_as(script)

    pid = _normalize_task_id(parent_task_id)
    script = f'''
tell application "OmniPlan"
{prelude}
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


def find_orphan_tasks(filepath: str) -> list[dict]:
    """Find tasks that exist in the .oplx XML but are not referenced as a
    child of any other task.

    OmniPlan's display only shows tasks reachable from the synthetic root
    (id="t-1") via ``<child-task>`` references. Tasks that exist as
    ``<task>`` elements but are not referenced anywhere become invisible
    "orphans" and can be silently dropped on the next save/load cycle.

    Args:
        filepath: Absolute path to the .oplx file.

    Returns:
        List of {"id": "tNNN", "name": "..."} dicts for each orphan.
        The synthetic root (t-1) is excluded.
    """
    abs_filepath = os.path.realpath(os.path.abspath(filepath))
    with zipfile.ZipFile(abs_filepath, 'r') as z:
        content = z.read("Actual.xml").decode("utf-8")
    root_xml = ET.fromstring(content)

    NS_LOCAL = "http://www.omnigroup.com/namespace/OmniPlan/v2"

    all_ids = set()
    referenced = set()
    names = {}
    for task in root_xml.findall(f".//{{{NS_LOCAL}}}task"):
        tid = task.get("id")
        all_ids.add(tid)
        title_el = task.find(f"{{{NS_LOCAL}}}title")
        names[tid] = title_el.text if title_el is not None else "(no title)"
        for child in task.findall(f"{{{NS_LOCAL}}}child-task"):
            referenced.add(child.get("idref"))

    orphans = []
    for tid in sorted(all_ids):
        if tid == "t-1":
            continue  # synthetic root has no parent by design
        if tid not in referenced:
            orphans.append({"id": tid, "name": names.get(tid, "?")})
    return orphans


def repair_orphan_tasks(
    filepath: str,
    attach_to: str = "t-1",
) -> str:
    """Find orphan tasks and attach them to the given parent so they become
    visible in OmniPlan.

    Use this after direct XML edits that may have left tasks unreferenced.

    Args:
        filepath: Absolute path to the .oplx file.
        attach_to: Task ID to attach orphans to. Defaults to ``"t-1"`` (the
            synthetic root, making them top-level phases).

    Returns:
        Confirmation message listing repaired tasks.
    """
    abs_filepath = os.path.realpath(os.path.abspath(filepath))
    if abs_filepath in _open_document_paths():
        raise RuntimeError(
            "Cannot repair orphans while the document is open in OmniPlan. "
            "Close the document first to avoid losing changes on next save."
        )

    NS_LOCAL = "http://www.omnigroup.com/namespace/OmniPlan/v2"
    ET.register_namespace('', NS_LOCAL)

    with zipfile.ZipFile(abs_filepath, 'r') as z:
        content = z.read("Actual.xml").decode("utf-8")
    root_xml = ET.fromstring(content)

    # Find orphans inline (don't re-open the file)
    all_ids = set()
    referenced = set()
    names = {}
    for task in root_xml.findall(f".//{{{NS_LOCAL}}}task"):
        tid = task.get("id")
        all_ids.add(tid)
        title_el = task.find(f"{{{NS_LOCAL}}}title")
        names[tid] = title_el.text if title_el is not None else "(no title)"
        for child in task.findall(f"{{{NS_LOCAL}}}child-task"):
            referenced.add(child.get("idref"))

    orphans = []
    for tid in sorted(all_ids):
        if tid == "t-1":
            continue
        if tid not in referenced:
            orphans.append((tid, names.get(tid, "?")))

    if not orphans:
        return "No orphan tasks found"

    # Locate the attachment parent
    target = root_xml.find(f".//{{{NS_LOCAL}}}task[@id='{attach_to}']")
    if target is None:
        raise RuntimeError(f"Attachment parent {attach_to} not found")

    # Add child-task references for each orphan
    for tid, _name in orphans:
        cref = ET.SubElement(target, f"{{{NS_LOCAL}}}child-task")
        cref.set("idref", tid)

    # Write back
    xml_bytes = ET.tostring(
        root_xml, encoding="unicode", xml_declaration=True
    ).encode("utf-8")
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".oplx", delete=False)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
            with zipfile.ZipFile(abs_filepath, 'r') as zin:
                for item in zin.infolist():
                    if item.filename == "Actual.xml":
                        zout.writestr(item, xml_bytes)
                    else:
                        zout.writestr(item, zin.read(item.filename))
        os.replace(tmp.name, abs_filepath)
    except Exception:
        os.unlink(tmp.name)
        raise

    target_name = (
        target.find(f"{{{NS_LOCAL}}}title").text
        if target.find(f"{{{NS_LOCAL}}}title") is not None
        else attach_to
    )
    lines = [f"Attached {len(orphans)} orphan task(s) to {attach_to} ({target_name}):"]
    for tid, name in orphans:
        lines.append(f"  - {tid}: {name}")
    return "\n".join(lines)


def set_task_estimate(filepath: str, task_id: str, min_seconds: int, max_seconds: int) -> str:
    """Set a task's min-estimate and max-estimate (uncertainty range).

    Modifies the .oplx file on disk directly (AppleScript doesn't expose
    these properties). The file must be saved in OmniPlan first.

    Args:
        filepath: Absolute path to the .oplx file.
        task_id: XML task ID (e.g. "t258").
        min_seconds: Minimum estimate in working seconds.
        max_seconds: Maximum estimate in working seconds.

    Returns:
        Confirmation message.
    """
    tid = _normalize_task_id(task_id)
    abs_filepath = os.path.realpath(os.path.abspath(filepath))
    if abs_filepath in _open_document_paths():
        raise RuntimeError(
            "Cannot edit estimate XML while the document is open in OmniPlan. "
            "Close the document first to avoid losing changes on the next save."
        )

    with zipfile.ZipFile(abs_filepath, 'r') as z:
        names = z.namelist()
        if "Actual.xml" not in names:
            raise RuntimeError("Actual.xml not found in .oplx file")
        content = z.read("Actual.xml").decode("utf-8")

    root = ET.fromstring(content)

    # Find the task
    task_el = root.find(f".//{{http://www.omnigroup.com/namespace/OmniPlan/v2}}task[@id='t{tid}']")
    if task_el is None:
        task_el = root.find(f".//{{http://www.omnigroup.com/namespace/OmniPlan/v2}}task[@id='{task_id}']")
    if task_el is None:
        raise RuntimeError(f"Task {task_id} not found in .oplx file")

    name_el = task_el.find(f"{{http://www.omnigroup.com/namespace/OmniPlan/v2}}title")
    task_name = name_el.text if name_el is not None else task_id

    NS = "http://www.omnigroup.com/namespace/OmniPlan/v2"

    # Remove existing min-estimate / max-estimate
    for child in list(task_el):
        local = child.tag.split("}")[1] if "}" in child.tag else child.tag
        if local in ("min-estimate", "max-estimate"):
            task_el.remove(child)

    # Add new elements in correct position (after effort)
    effort_el = task_el.find(f"{{{NS}}}effort")
    insert_after = effort_el if effort_el is not None else None

    min_el = ET.SubElement(task_el, f"{{{NS}}}min-estimate")
    min_el.text = str(min_seconds)

    max_el = ET.SubElement(task_el, f"{{{NS}}}max-estimate")
    max_el.text = str(max_seconds)

    # Re-serialize
    xml_bytes = ET.tostring(root, encoding="unicode", xml_declaration=True).encode("utf-8")

    # Write back to ZIP
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".oplx", delete=False)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
            with zipfile.ZipFile(abs_filepath, 'r') as zin:
                for item in zin.infolist():
                    if item.filename == "Actual.xml":
                        zout.writestr(item, xml_bytes)
                    else:
                        zout.writestr(item, zin.read(item.filename))
        os.replace(tmp.name, abs_filepath)
    except:
        os.unlink(tmp.name)
        raise

    min_days = round(min_seconds / 28800, 1)
    max_days = round(max_seconds / 28800, 1)
    return f"Set {task_name} estimate range: min={min_days}d, max={max_days}d"


def add_resource(
    name: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Add a new resource to the active OmniPlan document.

    Args:
        name: Name of the new resource.

    Returns:
        Confirmation message.
    """
    safe_name = _escape_applescript_string(name)
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    make new resource at end of resources of sce with properties {{name:"{safe_name}"}}
    return "Added resource: {safe_name}"
end tell'''
    return _run_as(script)


def save_document(
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Save the current OmniPlan document.

    Returns:
        Confirmation message.
    """
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
    try
        save doc
        return "Document saved"
    on error e
        return "Save error: " & e
    end try
end tell'''
    return _run_as(script)


def reorder_task(
    task_id: str,
    before_task_id: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Move a task before another task in the same parent group.

    Both tasks must be siblings (share the same parent group).
    If they have different parents, moves task_id under before_task_id's parent first,
    but only if they are not in a parent-child relationship.

    Args:
        task_id: AppleScript numeric task ID of the task to move.
        before_task_id: AppleScript numeric task ID of the reference task.

    Returns:
        Confirmation message.
    """
    tid = _normalize_task_id(task_id)
    bid = _normalize_task_id(before_task_id)
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    set taskToMove to missing value
    set refTask to missing value
    repeat with t in allTasks
        if id of t = {tid} then set taskToMove to t
        if id of t = {bid} then set refTask to t
    end repeat
    if taskToMove is missing value then return "Error: task {tid} not found"
    if refTask is missing value then return "Error: reference task {bid} not found"
    set tname to name of taskToMove
    set rname to name of refTask

    -- Get parents
    set myParent to missing value
    set refParent to missing value
    try
        set myParent to parent task of taskToMove
    end try
    try
        set refParent to parent task of refTask
    end try

    -- If refTask is taskToMove's parent, this is a no-op / invalid
    if refParent is not missing value and (id of refParent) = {tid} then
        return "Error: cannot reorder a task before its own child"
    end if
    -- If taskToMove is refTask's parent, invalid
    if myParent is not missing value and (id of myParent) = {bid} then
        return "Error: cannot reorder a task before its own parent"
    end if

    -- If different parents, move taskToMove under refParent first
    if myParent is not missing value and refParent is not missing value then
        if id of myParent is not id of refParent then
            move taskToMove to end of child tasks of refParent
        end if
    else if refParent is not missing value and myParent is missing value then
        -- taskToMove is a top-level task, move it under refParent
        move taskToMove to end of child tasks of refParent
    else if myParent is not missing value and refParent is missing value then
        -- refTask is top-level, need to move taskToMove to top-level too
        -- move to end of tasks of sce (top level)
        move taskToMove to end of tasks of sce
    end if

    -- Now reorder before the reference task
    move taskToMove to before refTask
    return "Moved " & tname & " before " & rname
end tell'''
    return _run_as(script)


def set_task_type(
    task_id: str,
    task_type: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Change a task's type (standard task, group task, milestone task).

    Args:
        task_id: AppleScript numeric task ID.
        task_type: One of 'standard', 'group', 'milestone'.

    Returns:
        Confirmation message.
    """
    tid = _normalize_task_id(task_id)
    type_map = {
        "standard": "standard task",
        "group": "group task",
        "milestone": "milestone task",
    }
    if task_type not in type_map:
        raise ValueError("task_type must be standard, group, or milestone")
    as_type = type_map[task_type]
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {tid} then
            set tname to name of t
            set task type of t to {as_type}
            return "Changed " & tname & " to {task_type} type"
        end if
    end repeat
    return "Task {tid} not found"
end tell'''
    return _run_as(script)


def move_task(
    task_id: str,
    target_parent_id: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Move a task under a new parent group.

    Args:
        task_id: AppleScript numeric task ID of the task to move.
        target_parent_id: AppleScript numeric task ID of the destination group.

    Returns:
        Confirmation message.
    """
    tid = _normalize_task_id(task_id)
    pid = _normalize_task_id(target_parent_id)
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    set taskToMove to missing value
    set targetParent to missing value
    repeat with t in allTasks
        if id of t = {tid} then set taskToMove to t
        if id of t = {pid} then set targetParent to t
    end repeat
    if taskToMove is missing value then return "Error: task {tid} not found"
    if targetParent is missing value then return "Error: parent task {pid} not found"
    set tname to name of taskToMove
    set pname to name of targetParent
    move taskToMove to end of child tasks of targetParent
    return "Moved: " & tname & " → under " & pname
end tell'''
    return _run_as(script)


def set_task_constraint_date(
    task_id: str,
    date_string: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Set a task's starting constraint date (earliest start).

    Args:
        task_id: AppleScript numeric task ID.
        date_string: Date string parseable by AppleScript, e.g. "2026年6月15日".

    Returns:
        Confirmation message.
    """
    tid = _normalize_task_id(task_id)
    safe_date = _escape_applescript_string(date_string)
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {tid} then
            set tname to name of t
            try
                set starting constraint date of t to date "{safe_date}"
                return "Set starting constraint for " & tname & " to {safe_date}"
            on error e
                return "Error: " & e
            end try
        end if
    end repeat
    return "Task {tid} not found"
end tell'''
    return _run_as(script)


def clear_task_constraint_date(
    task_id: str,
    filepath: str | None = None,
    document_id: str | None = None,
) -> str:
    """Remove a task's starting constraint date.

    Args:
        task_id: AppleScript numeric task ID.

    Returns:
        Confirmation message.
    """
    tid = _normalize_task_id(task_id)
    prelude = _document_prelude(filepath, document_id)
    script = f'''
tell application "OmniPlan"
{prelude}
    set sce to frontEditingScenario of project of doc
    set allTasks to every task of sce
    repeat with t in allTasks
        if id of t = {tid} then
            set tname to name of t
            try
                set starting constraint date of t to missing value
            end try
            try
                set ending constraint date of t to missing value
            end try
            return "Cleared constraint dates for: " & tname
        end if
    end repeat
    return "Task {tid} not found"
end tell'''
    return _run_as(script)
