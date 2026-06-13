"""
OmniPlan project file parser.

Handles reading .mpp files (via OmniPlan AppleScript bridge) and .oplx files
(direct XML parsing), extracting task hierarchies, resources, and metadata.
"""

import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from typing import Any

from .lock import omniplan_lock

# OmniPlan XML namespace
NS = "{http://www.omnigroup.com/namespace/OmniPlan/v2}"


def get_text(elem: ET.Element | None, tag: str) -> str:
    """Get text content of a child element by tag name."""
    if elem is None:
        return ""
    el = elem.find(f"{NS}{tag}")
    return el.text.strip() if el is not None and el.text else ""


def convert_date(d: str) -> str:
    """Convert ISO date string to YYYY-MM-DD format."""
    if not d:
        return ""
    try:
        dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return d[:10] if len(d) >= 10 else d


def parse_oplx(filepath: str) -> tuple[ET.Element, str]:
    """Parse an .oplx file (ZIP containing XML schedule data).

    Returns:
        Tuple of (XML root element, source description).
    """
    with zipfile.ZipFile(filepath) as z:
        names = z.namelist()
        # Find the main XML file with task data
        target = None
        for n in names:
            if n.endswith(".xml"):
                content = z.read(n).decode("utf-8")
                if "<task" in content and "<title>" in content:
                    target = content
                    break
        if target is None:
            # Fallback: try Actual.xml
            target = z.read("Actual.xml").decode("utf-8")

    root = ET.fromstring(target)
    return root, filepath


def parse_oplx_directory(dirpath: str) -> tuple[ET.Element, str]:
    """Parse an .oplx directory (OmniPlan's folder export format)."""
    # Find the main XML file (largest, not TOC/changelog)
    candidates = []
    for f in os.listdir(dirpath):
        if f.endswith(".xml") and f not in ("__TOC.xml", "__changelog.xml"):
            fp = os.path.join(dirpath, f)
            candidates.append((os.path.getsize(fp), fp))

    if not candidates:
        raise RuntimeError(f"No XML data file found in {dirpath}")

    # Use the largest XML file
    candidates.sort(reverse=True)
    target = candidates[0][1]
    root = ET.parse(target).getroot()
    return root, dirpath


def export_mpp_via_omniplan(filepath: str) -> str:
    """Use OmniPlan to open .mpp and export as .oplx directory.

    Acquires a cross-process lock to prevent AppleScript conflicts
    when multiple Claude Code sessions are running.

    Returns:
        Path to the exported .oplx directory.
    """
    abs_path = os.path.abspath(filepath)

    # Create temp directory for export
    export_dir = tempfile.mkdtemp(suffix="_oplx")

    script = f"""
    tell application "OmniPlan"
        set doc to open "{abs_path}"
        set exportPath to "{export_dir}/exported.oplx"
        save doc in exportPath
        close doc
    end tell
    """

    with omniplan_lock():
        result = subprocess.run(
            ["osascript", "-l", "AppleScript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
        )

    if result.returncode != 0:
        shutil.rmtree(export_dir, ignore_errors=True)
        raise RuntimeError(
            f"OmniPlan export failed: {result.stderr}\n"
            f"Make sure OmniPlan is installed and you have granted "
            f"accessibility/automation permissions."
        )

    # The export is a directory with .oplx extension
    export_path = f"{export_dir}/exported.oplx"
    if os.path.isdir(export_path):
        return export_path
    else:
        shutil.rmtree(export_dir, ignore_errors=True)
        raise RuntimeError(
            f"Expected export directory not found at {export_path}"
        )


def parse_file(filepath: str) -> tuple[ET.Element, str]:
    """Parse either .mpp or .oplx file.

    Args:
        filepath: Path to the schedule file.

    Returns:
        Tuple of (XML root element, cleanup_path).
        The cleanup_path is a temp directory to remove after use, or empty string.

    Raises:
        ValueError: If file format is unsupported.
        RuntimeError: If parsing or export fails.
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".oplx":
        # .oplx can be a file (ZIP) or directory (folder export)
        if os.path.isdir(filepath):
            return parse_oplx_directory(filepath)
        return parse_oplx(filepath)
    elif ext == ".mpp":
        export_dir = export_mpp_via_omniplan(filepath)
        root, _ = parse_oplx_directory(export_dir)
        return root, export_dir
    else:
        raise ValueError(
            f"Unsupported file format: {ext}. Supported: .mpp, .oplx"
        )


def build_task_map(root: ET.Element) -> dict[str, ET.Element]:
    """Build a dict mapping task IDs to task elements."""
    tasks = root.findall(f".//{NS}task")
    return {t.get("id", ""): t for t in tasks}


def task_to_dict(task: ET.Element) -> dict[str, Any]:
    """Convert a task XML element to a plain dict."""
    return {
        "id": task.get("id", ""),
        "title": get_text(task, "title"),
        "type": get_text(task, "type"),
        "start_date": convert_date(get_text(task, "start-date")),
        "end_date": convert_date(get_text(task, "end-date")),
        "percent_complete": get_text(task, "percent-complete"),
        "effort": get_text(task, "effort"),
        "duration": get_text(task, "duration"),
        "priority": get_text(task, "priority"),
        "notes": get_text(task, "notes"),
    }


def collect_all_tasks(
    task_id: str,
    task_map: dict,
    level: int = 0,
    results: list | None = None,
) -> list[dict]:
    """Recursively collect all tasks under a given parent, with hierarchy levels."""
    if results is None:
        results = []
    if task_id not in task_map:
        return results

    task = task_map[task_id]
    info = task_to_dict(task)
    info["level"] = level
    results.append(info)

    for child in task:
        tag = child.tag.split("}")[1] if "}" in child.tag else child.tag
        if tag == "child-task":
            collect_all_tasks(child.get("idref", ""), task_map, level + 1, results)

    return results


def get_resources(root: ET.Element) -> list[dict[str, str]]:
    """Extract all staff resources from the schedule."""
    resources = []
    for r in root.findall(f".//{NS}resource"):
        rtype = get_text(r, "type")
        if rtype == "Staff":
            resources.append({
                "id": r.get("id", ""),
                "name": get_text(r, "name"),
            })
    return resources
