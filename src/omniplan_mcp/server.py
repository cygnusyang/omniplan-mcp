"""
MCP server for OmniPlan project schedule files.

Provides tools for reading, searching, and analyzing .mpp and .oplx files.
macOS only — requires OmniPlan for .mpp files.
"""

import json
import os
import sys
from typing import Any

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

from . import __version__
from .parser import (
    add_dependency,
    add_task,
    build_task_tree,
    clear_constraint_date,
    delete_task,
    evaluate_javascript,
    export_schedule,
    get_resources_staff,
    lookup_task,
    parse_file,
    read_schedule_settings,
    remove_dependency,
    rename_task,
    save_document,
    set_task_completed,
    set_task_completed_by_name,
    set_task_duration,
)

server = Server("omniplan-mcp")


# ── Helper: format task tree ────────────────────────────────────────────


def _format_tree(tasks: list[dict], level: int = 0, lines: list[str] | None = None) -> list[str]:
    """Recursively format tasks as a tree."""
    if lines is None:
        lines = []

    for t in tasks:
        prefix = "  " * level
        name = t.get("name", "")
        ttype = t.get("task_type", "")

        marker = "◇ " if ttype == "milestone" else ("▣ " if ttype == "group" else "  ")

        start = t.get("start_date", "")
        end = t.get("end_date", "")
        pct = t.get("percent_complete", "")
        effort = t.get("effort_hours", "")

        parts = []
        if start:
            parts.append(str(start))
        if end:
            parts.append(f"→{end}")
        if effort and float(effort) > 0:
            parts.append(f"({effort}h)")
        if pct:
            parts.append(f"[{pct}%]")

        info = " ".join(parts)
        lines.append(f"{prefix}{marker}{name:50s} {info}")

        children = t.get("children", [])
        if children:
            _format_tree(children, level + 1, lines)

    return lines


def _status_icon(status: str) -> str:
    """Map task status to an icon."""
    mapping = {
        "ok": "✅",
        "close to due date": "⚠️",
        "due now": "🔴",
        "past due": "🔴",
        "finished": "✅",
    }
    return mapping.get(status, "❓")


# ── Tool Definitions ──────────────────────────────────────────────────────


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="read_schedule",
            description=(
                "Read a project schedule file (.mpp or .oplx) and return "
                "the full task hierarchy with dates and progress."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the .mpp or .oplx file",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["tree", "flat", "json"],
                        "description": (
                            "Output format: tree (hierarchical, default), "
                            "flat (all tasks), json (raw data)"
                        ),
                    },
                },
                "required": ["filepath"],
            },
        ),
        types.Tool(
            name="list_milestones",
            description="List all milestone tasks from a project schedule file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the .mpp or .oplx file",
                    }
                },
                "required": ["filepath"],
            },
        ),
        types.Tool(
            name="list_resources",
            description="List all human resources (staff) with details (cost, hours, efficiency).",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the .mpp or .oplx file",
                    },
                    "detail": {
                        "type": "string",
                        "enum": ["simple", "full"],
                        "description": "simple = names only, full = with cost/hours/efficiency",
                    },
                },
                "required": ["filepath"],
            },
        ),
        types.Tool(
            name="search_tasks",
            description="Search for tasks by keyword in a project schedule file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the .mpp or .oplx file",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Search keyword (case-insensitive)",
                    },
                },
                "required": ["filepath", "keyword"],
            },
        ),
        types.Tool(
            name="schedule_summary",
            description=(
                "Get a summary of the project schedule including phase overview, "
                "progress stats, and timeline."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the .mpp or .oplx file",
                    }
                },
                "required": ["filepath"],
            },
        ),
        types.Tool(
            name="get_task_detail",
            description="Get detailed information about a specific task by name or ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the .mpp or .oplx file",
                    },
                    "task_id": {
                        "type": "integer",
                        "description": "Task ID (integer, from OmniPlan internal id)",
                    },
                    "task_name": {
                        "type": "string",
                        "description": "Task name to search for (case-insensitive partial match)",
                    },
                },
                "required": ["filepath"],
            },
        ),
        types.Tool(
            name="get_resource_detail",
            description="Get detailed information about a specific resource by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the .mpp or .oplx file",
                    },
                    "resource_name": {
                        "type": "string",
                        "description": "Resource name (case-insensitive partial match)",
                    },
                },
                "required": ["filepath", "resource_name"],
            },
        ),
        types.Tool(
            name="list_violations",
            description="List all scheduling violations/conflicts in the project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the .mpp or .oplx file",
                    }
                },
                "required": ["filepath"],
            },
        ),
        types.Tool(
            name="list_assignments",
            description="List all resource-to-task assignments in the project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the .mpp or .oplx file",
                    }
                },
                "required": ["filepath"],
            },
        ),
        types.Tool(
            name="list_dependencies",
            description="List all task dependency relationships (prerequisite/successor chains).",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the .mpp or .oplx file",
                    }
                },
                "required": ["filepath"],
            },
        ),
        types.Tool(
            name="get_schedule_settings",
            description=(
                "Read schedule/work-time settings from the active OmniPlan document, "
                "including scheduling granularity, weekday working hours, "
                "and calendar day schedule availability."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        types.Tool(
            name="evaluate_omniplan_script",
            description=(
                "Evaluate Omni Automation JavaScript code in OmniPlan's runtime. "
                "Powerful access to the full Omni Automation API (Alert, Form, "
                "FilePicker, Document, Application, Task, Resource, etc.). "
                "Note: An OmniPlan document must be open for this to work."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": (
                            "JavaScript code to evaluate using Omni Automation API. "
                            "Example: 'document.name' or 'new Alert(\"Hello\", \"World\").show()'"
                        ),
                    },
                },
                "required": ["script"],
            },
        ),
        # ── Write Operations ────────────────────────────────────────────────
        types.Tool(
            name="set_task_completed",
            description=(
                "Set a task to 100% complete. Requires an open OmniPlan document. "
                "Use AppleScript task ID (numeric, e.g. 258) or XML ID (e.g. t258). "
                "With include_subtree=true, also sets all descendant tasks to 100%."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID (AppleScript numeric like 258, or XML like t258)",
                    },
                    "include_subtree": {
                        "type": "boolean",
                        "description": "Also set all child tasks to 100% (default: true)",
                        "default": True,
                    },
                },
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="set_task_completed_by_name",
            description=(
                "Set a task to 100% complete by exact name. "
                "With include_subtree=true, also sets all descendant tasks to 100%."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_name": {
                        "type": "string",
                        "description": "Exact name of the task",
                    },
                    "include_subtree": {
                        "type": "boolean",
                        "description": "Also set all child tasks to 100% (default: true)",
                        "default": True,
                    },
                },
                "required": ["task_name"],
            },
        ),
        types.Tool(
            name="add_dependency",
            description=(
                "Add a finish-to-start dependency: dependent_task ← prerequisite_task. "
                "The dependent task will wait for the prerequisite to finish."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "dependent_task_id": {
                        "type": "string",
                        "description": "The task that must wait (AppleScript numeric ID)",
                    },
                    "prerequisite_task_id": {
                        "type": "string",
                        "description": "The task that must finish first",
                    },
                },
                "required": ["dependent_task_id", "prerequisite_task_id"],
            },
        ),
        types.Tool(
            name="remove_dependency",
            description="Remove a dependency between two tasks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dependent_task_id": {
                        "type": "string",
                        "description": "The dependent task",
                    },
                    "prerequisite_task_id": {
                        "type": "string",
                        "description": "The prerequisite task to remove",
                    },
                },
                "required": ["dependent_task_id", "prerequisite_task_id"],
            },
        ),
        types.Tool(
            name="set_task_duration",
            description=(
                "Set a task's duration in working seconds. "
                "1 working day = 28800 seconds. "
                "Example: 5 days = 144000 seconds."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID (AppleScript numeric)",
                    },
                    "duration_seconds": {
                        "type": "integer",
                        "description": "Duration in working seconds",
                    },
                },
                "required": ["task_id", "duration_seconds"],
            },
        ),
        types.Tool(
            name="clear_constraint_date",
            description="Remove the starting constraint (locked start date) from a task.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID (AppleScript numeric)",
                    },
                },
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="rename_task",
            description="Rename a task.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID (AppleScript numeric)",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New name for the task",
                    },
                },
                "required": ["task_id", "new_name"],
            },
        ),
        types.Tool(
            name="delete_task",
            description="Delete a task and all its children.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID (AppleScript numeric)",
                    },
                },
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="add_task",
            description="Add a new task under a parent group.",
            inputSchema={
                "type": "object",
                "properties": {
                    "parent_task_id": {
                        "type": "string",
                        "description": "Parent group task ID (AppleScript numeric)",
                    },
                    "task_name": {
                        "type": "string",
                        "description": "Name for the new task",
                    },
                    "duration_seconds": {
                        "type": "integer",
                        "description": "Duration in working seconds (default: 28800 = 1 day)",
                        "default": 28800,
                    },
                },
                "required": ["parent_task_id", "task_name"],
            },
        ),
        types.Tool(
            name="save_document",
            description="Save the current OmniPlan document.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        types.Tool(
            name="lookup_task",
            description=(
                "Search for a task by name and return its ID, type, and other details. "
                "Use this to find the correct numeric ID before calling other write operations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_name": {
                        "type": "string",
                        "description": "Full or partial task name (case-insensitive)",
                    },
                },
                "required": ["search_name"],
            },
        ),
        types.Tool(
            name="export_schedule",
            description=(
                "Export the current OmniPlan schedule to a specific format. "
                "Returns the path to the exported file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute path to the .mpp or .oplx file to export",
                    },
                    "format": {
                        "type": "string",
                        "description": (
                            "Export format. Options: OmniPlan XML (.oplx, default), "
                            "OmniPlan Template (.oplt), HTML, CSV, "
                            "Tab Delimited Text, iCal, OmniGraffle XML"
                        ),
                        "default": "OmniPlan XML",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Where to save the exported file (optional, auto-generated if omitted)",
                    },
                },
                "required": ["filepath"],
            },
        ),
    ]


# ── Tool Handlers ─────────────────────────────────────────────────────────


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # Platform check
    if sys.platform != "darwin":
        return [
            types.TextContent(
                type="text",
                text="This MCP server requires macOS. OmniPlan is only available on macOS.",
            )
        ]

    # Tools that don't need file parsing
    if name == "evaluate_omniplan_script":
        script = arguments.get("script", "")
        return _format_evaluate_script(script)
    elif name == "export_schedule":
        filepath = arguments.get("filepath", "")
        fmt = arguments.get("format", "OmniPlan XML")
        output_path = arguments.get("output_path")
        return _format_export(filepath, fmt, output_path)
    elif name == "get_schedule_settings":
        return _format_schedule_settings()

    # Tools that require file parsing
    filepath = arguments.get("filepath", "")

    if not os.path.exists(filepath):
        return [
            types.TextContent(type="text", text=f"File not found: {filepath}")
        ]

    try:
        projects, resources, tasks, violations, assignments, dependencies = parse_file(filepath)
    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"Error parsing file: {type(e).__name__}: {e}",
            )
        ]

    if name == "read_schedule":
        fmt = arguments.get("format", "tree")
        return _format_read_schedule(projects, tasks, fmt)
    elif name == "list_milestones":
        return _format_milestones(tasks)
    elif name == "list_resources":
        detail = arguments.get("detail", "simple")
        return _format_resources(resources, detail)
    elif name == "search_tasks":
        keyword = arguments.get("keyword", "")
        return _format_search(tasks, keyword)
    elif name == "schedule_summary":
        return _format_summary(projects, resources, tasks, violations)
    elif name == "get_task_detail":
        task_id = arguments.get("task_id")
        task_name = arguments.get("task_name", "")
        return _format_task_detail(tasks, task_id, task_name)
    elif name == "get_resource_detail":
        rname = arguments.get("resource_name", "")
        return _format_resource_detail(resources, rname)
    elif name == "list_violations":
        return _format_violations(violations, tasks)
    elif name == "list_assignments":
        return _format_assignments(assignments, tasks, resources)
    elif name == "list_dependencies":
        return _format_dependencies(dependencies, tasks)
    # ── Write Operation Handlers ────────────────────────────────────────
    elif name == "lookup_task":
        search_name = arguments.get("search_name", "")
        result = lookup_task(search_name)
        return [types.TextContent(type="text", text=result)]
    elif name == "set_task_completed":
        task_id = arguments.get("task_id", "")
        include_subtree = arguments.get("include_subtree", True)
        result = set_task_completed(task_id, include_subtree)
        return [types.TextContent(type="text", text=result)]
    elif name == "set_task_completed_by_name":
        task_name = arguments.get("task_name", "")
        include_subtree = arguments.get("include_subtree", True)
        result = set_task_completed_by_name(task_name, include_subtree)
        return [types.TextContent(type="text", text=result)]
    elif name == "add_dependency":
        dep = arguments.get("dependent_task_id", "")
        pre = arguments.get("prerequisite_task_id", "")
        result = add_dependency(dep, pre)
        return [types.TextContent(type="text", text=result)]
    elif name == "remove_dependency":
        dep = arguments.get("dependent_task_id", "")
        pre = arguments.get("prerequisite_task_id", "")
        result = remove_dependency(dep, pre)
        return [types.TextContent(type="text", text=result)]
    elif name == "set_task_duration":
        task_id = arguments.get("task_id", "")
        duration_seconds = arguments.get("duration_seconds", 0)
        result = set_task_duration(task_id, duration_seconds)
        return [types.TextContent(type="text", text=result)]
    elif name == "clear_constraint_date":
        task_id = arguments.get("task_id", "")
        result = clear_constraint_date(task_id)
        return [types.TextContent(type="text", text=result)]
    elif name == "rename_task":
        task_id = arguments.get("task_id", "")
        new_name = arguments.get("new_name", "")
        result = rename_task(task_id, new_name)
        return [types.TextContent(type="text", text=result)]
    elif name == "delete_task":
        task_id = arguments.get("task_id", "")
        result = delete_task(task_id)
        return [types.TextContent(type="text", text=result)]
    elif name == "add_task":
        parent_id = arguments.get("parent_task_id", "")
        task_name = arguments.get("task_name", "")
        duration_seconds = arguments.get("duration_seconds", 28800)
        result = add_task(parent_id, task_name, duration_seconds)
        return [types.TextContent(type="text", text=result)]
    elif name == "save_document":
        result = save_document()
        return [types.TextContent(type="text", text=result)]
    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


# ── Helper: build task name map ─────────────────────────────────────────


def _task_name_map(tasks: list[dict]) -> dict[int, str]:
    return {t["id"]: t.get("name", f"Task #{t['id']}") for t in tasks}


def _resource_name_map(resources: list[dict]) -> dict[int, str]:
    return {r["id"]: r.get("name", f"Resource #{r['id']}") for r in resources}


def _format_evaluate_script(script: str) -> list[types.TextContent]:
    """Evaluate Omni Automation JavaScript and return result."""
    try:
        result = evaluate_javascript(script)
        if result.startswith("ERROR:"):
            return [types.TextContent(type="text", text=f"JavaScript error: {result[6:].strip()}")]
        return [types.TextContent(type="text", text=result)]
    except RuntimeError as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]


def _format_export(filepath: str, fmt: str, output_path: str | None) -> list[types.TextContent]:
    """Export schedule and return the output path."""
    if not os.path.exists(filepath):
        return [types.TextContent(type="text", text=f"File not found: {filepath}")]
    try:
        result = export_schedule(filepath, fmt, output_path)
        if result.startswith("ERROR:"):
            return [types.TextContent(type="text", text=f"Export error: {result[6:].strip()}")]
        return [
            types.TextContent(
                type="text",
                text=f"Schedule exported successfully.\nFormat: {fmt}\nOutput: {result}",
            )
        ]
    except (RuntimeError, FileNotFoundError) as e:
        return [types.TextContent(type="text", text=f"Export error: {e}")]


def _format_schedule_settings() -> list[types.TextContent]:
    """Read and format schedule/work-time settings."""
    try:
        settings = read_schedule_settings()
    except RuntimeError as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]

    lines = ["\U0001f4c5 Schedule Settings", "=" * 60]

    gran = settings.get("granularity", "")
    if gran:
        lines.append(f"Scheduling Granularity: {gran}")

    weekdays = settings.get("weekdays", [])
    if weekdays:
        lines.append(f"\nWorking Hours ({len(weekdays)} days):")
        for d in weekdays:
            start = d.get("start_time", "")
            end = d.get("end_time", "")
            day_name = d.get("day", f"Day {d['day_number']}")
            if start and end:
                lines.append(f"  {day_name:10s} {start} → {end}")
            else:
                lines.append(f"  {day_name:10s} (non-working)")

    if settings.get("has_calendar_schedule"):
        lines.append("\nCalendar day schedule: Available (custom exceptions)")

    return [types.TextContent(type="text", text="\n".join(lines))]


# ── Output Formatters ─────────────────────────────────────────────────────


def _format_read_schedule(
    projects: list[dict], tasks: list[dict], fmt: str
) -> list[types.TextContent]:
    if fmt == "json":
        return [
            types.TextContent(
                type="text",
                text=json.dumps(tasks, indent=2, ensure_ascii=False),
            )
        ]

    lines = []

    if projects:
        p = projects[0]
        lines.append(f"\U0001f4ca {p.get('title', 'Untitled')}")
        if p.get("start_date"):
            lines.append(f"\U0001f4c5 Start: {p['start_date']} → End: {p.get('end_date', '')}")
            if p.get("percent_complete"):
                lines.append(f"\U0001f4c8 Overall: {p['percent_complete']:.1f}%")
        if p.get("violation_count"):
            lines.append(f"⚠️ Violations: {p['violation_count']}")
        lines.append("")

    total = len(tasks)
    milestones = sum(1 for t in tasks if t["task_type"] == "milestone")
    groups = sum(1 for t in tasks if t["task_type"] == "group")
    lines.append(f"\U0001f4cb Tasks: {total} total ({groups} groups, {milestones} milestones)")
    lines.append("")

    if fmt == "flat":
        for t in tasks:
            name = t.get("name", "")
            if not name:
                continue
            marker = "◇ " if t["task_type"] == "milestone" else ("▣ " if t["task_type"] == "group" else "  ")
            start = t.get("start_date", "")
            end = t.get("end_date", "")
            pct = t.get("percent_complete", "")
            pct_str = f" [{pct}%]" if pct else ""
            lines.append(f"  {marker}{name:50s} {start}→{end}{pct_str}")
    else:
        tree = build_task_tree(tasks)
        _format_tree(tree, 0, lines)

    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_milestones(tasks: list[dict]) -> list[types.TextContent]:
    lines = ["◇ Milestones", "=" * 60]
    for t in tasks:
        if t["task_type"] == "milestone":
            name = t.get("name", "")
            start = t.get("start_date", "")
            end = t.get("end_date", "")
            pct = t.get("percent_complete", "")
            pct_str = f" [{pct}%]" if pct else ""
            lines.append(f"  ◇ {name:50s} {start}→{end}{pct_str}")
    if len(lines) == 1:
        lines.append("  (no milestones found)")
    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_resources(resources: list[dict], detail: str = "simple") -> list[types.TextContent]:
    staff = get_resources_staff(resources)
    lines = [f"\U0001f464 Resources ({len(staff)})", "=" * 60]

    if detail == "full":
        for r in staff:
            name = r.get("name", "")
            rtype = r.get("resource_type", "")
            hrs = round(r.get("total_seconds", 0) / 3600, 1)
            cost = r.get("total_cost", 0)
            eff = r.get("efficiency", 1.0)
            lines.append(f"  \U0001f464 {name:25s} type={rtype}  hours={hrs}h  cost=${cost}  efficiency={eff*100:.0f}%")
    else:
        for r in staff:
            lines.append(f"  \U0001f464 {r['name']}")

    if not staff:
        lines.append("  (no staff resources found)")
    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_search(tasks: list[dict], keyword: str) -> list[types.TextContent]:
    keyword_lower = keyword.lower()
    lines = [f"\U0001f50d Search results for '{keyword}'", "=" * 60]
    found = 0
    for t in tasks:
        name = t.get("name", "")
        if name and keyword_lower in name.lower():
            found += 1
            marker = "◇ " if t["task_type"] == "milestone" else ("▣ " if t["task_type"] == "group" else "  ")
            start = t.get("start_date", "")
            end = t.get("end_date", "")
            pct = t.get("percent_complete", "")
            status = t.get("task_status", "")
            icon = _status_icon(status)
            pct_str = f" [{pct}%]" if pct else ""
            lines.append(f"  {icon} {marker}{name:50s} {start}→{end}{pct_str}")
    lines.append(f"\nFound {found} matching tasks")
    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_summary(
    projects: list[dict], resources: list[dict], tasks: list[dict], violations: list[dict]
) -> list[types.TextContent]:
    lines = ["\U0001f4ca Project Schedule Summary", "=" * 60]

    if projects:
        p = projects[0]
        lines.append(f"\U0001f4c5 Project: {p.get('title', 'Untitled')}")
        if p.get("start_date"):
            lines.append(f"   Start: {p['start_date']}")
        if p.get("end_date"):
            lines.append(f"   End:   {p['end_date']}")
        if p.get("percent_complete"):
            lines.append(f"   Overall Progress: {p['percent_complete']:.1f}%")
        if p.get("duration_seconds"):
            days = round(p["duration_seconds"] / 28800, 1)
            lines.append(f"   Duration: {days} working days")
        if p.get("effort_seconds"):
            hrs = round(p["effort_seconds"] / 3600, 1)
            lines.append(f"   Total Effort: {hrs} person-hours")
        if p.get("violation_count"):
            lines.append(f"   ⚠️ Violations: {p['violation_count']}")

    staff = get_resources_staff(resources)
    lines.append(f"\U0001f464 Resources: {len(staff)} staff")

    total = len(tasks)
    milestones = sum(1 for t in tasks if t["task_type"] == "milestone")
    groups = sum(1 for t in tasks if t["task_type"] == "group")
    tasks_only = sum(1 for t in tasks if t["task_type"] == "task")

    lines.append(f"\n\U0001f4cb Total tasks: {total}")
    lines.append(f"   • Groups: {groups}")
    lines.append(f"   • Tasks: {tasks_only}")
    lines.append(f"   • Milestones: {milestones}")

    completed = sum(1 for t in tasks if t["task_type"] == "task" and t.get("percent_complete", 0) >= 100)
    in_progress_count = sum(1 for t in tasks if t["task_type"] == "task" and 0 < t.get("percent_complete", 0) < 100)
    not_started = sum(1 for t in tasks if t["task_type"] == "task" and t.get("percent_complete", 0) == 0)

    lines.append(f"\n\U0001f4c8 Progress (tasks only):")
    lines.append(f"   ✅ Completed: {completed}")
    lines.append(f"   \U0001f504 In Progress: {in_progress_count}")
    lines.append(f"   ⏳ Not Started: {not_started}")

    past_due = sum(1 for t in tasks if t.get("task_status") == "past due")
    if past_due:
        lines.append(f"   🔴 Past Due: {past_due}")

    lines.append(f"\n\U0001f4cb Phases:")
    for t in tasks:
        if t["task_type"] == "group" and t.get("outline_depth", 0) == 1:
            name = t.get("name", "")
            start = t.get("start_date", "")
            end = t.get("end_date", "")
            pct = t.get("percent_complete", "")
            pct_str = f" [{pct}%]" if pct else ""
            lines.append(f"  ▣ {name:45s} {start}→{end}{pct_str}")

    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_task_detail(tasks: list[dict], task_id: int | None, task_name: str) -> list[types.TextContent]:
    """Format detailed info for a specific task."""
    matches = []
    for t in tasks:
        if task_id is not None and t["id"] == task_id:
            matches.append(t)
            break
        if task_name and task_name.lower() in t.get("name", "").lower():
            matches.append(t)

    if not matches:
        return [types.TextContent(type="text", text=f"No task found matching id={task_id} name='{task_name}'")]

    results = []
    for t in matches:
        lines = [f"\U0001f4cb Task Detail: {t.get('name', '')}", "=" * 60]
        lines.append(f"  ID:             {t['id']}")
        lines.append(f"  Type:           {t['task_type']}")
        lines.append(f"  Status:         {_status_icon(t.get('task_status', ''))} {t.get('task_status', 'N/A')}")
        lines.append(f"  WBS:            {t.get('outline_number', '')}")
        lines.append(f"  Level:          {t.get('outline_depth', '')}")
        lines.append(f"  Start:          {t.get('start_date', 'N/A')}")
        lines.append(f"  End:            {t.get('end_date', 'N/A')}")
        start_const = t.get('starting_constraint_date', '')
        end_const = t.get('ending_constraint_date', '')
        if start_const:
            lines.append(f"  Constraint Start: {start_const}")
        if end_const:
            lines.append(f"  Constraint End:   {end_const}")
        lines.append(f"  Duration:       {t.get('duration_days', '0')} days")
        lines.append(f"  Progress:       {t.get('percent_complete', 0)}%")
        lines.append(f"  Effort:         {t.get('effort_hours', '0')}h")
        lines.append(f"  Remaining:      {t.get('remaining_effort_hours', '0')}h")
        lines.append(f"  Completed:      {t.get('completed_effort_hours', '0')}h")
        lines.append(f"  Priority:       {t.get('priority', 'N/A')}")
        lines.append(f"  Static Cost:    ${t.get('static_cost', 0)}")
        lines.append(f"  Resource Cost:  ${t.get('resource_cost', 0)}")
        lines.append(f"  Total Cost:     ${t.get('total_cost', 0)}")
        lines.append(f"  Assignments:    {t.get('assignment_count', 0)}")
        lines.append(f"  Prerequisites:  {t.get('prerequisite_count', 0)}")
        lines.append(f"  Dependents:     {t.get('dependent_count', 0)}")
        lines.append(f"  Child Tasks:    {t.get('child_task_count', 0)}")
        note = t.get("note", "")
        if note:
            lines.append(f"  Note:           {note}")
        results.append("\n".join(lines))

    return [types.TextContent(type="text", text="\n\n".join(results))]


def _format_resource_detail(resources: list[dict], rname: str) -> list[types.TextContent]:
    """Format detailed info for a specific resource."""
    matches = [r for r in resources if rname.lower() in r.get("name", "").lower()]
    if not matches:
        return [types.TextContent(type="text", text=f"No resource found matching '{rname}'")]

    results = []
    for r in matches:
        lines = [f"\U0001f464 Resource Detail: {r.get('name', '')}", "=" * 60]
        lines.append(f"  ID:             {r['id']}")
        lines.append(f"  Type:           {r.get('resource_type', 'N/A')}")
        lines.append(f"  Level:          {r.get('outline_depth', 0)}")
        lines.append(f"  Units:          {r.get('number', 1.0) * 100:.0f}%")
        lines.append(f"  Efficiency:     {r.get('efficiency', 1.0) * 100:.0f}%")
        lines.append(f"  Cost/Use:       ${r.get('cost_per_use', 0)}")
        lines.append(f"  Cost/Hour:      ${r.get('cost_per_hour', 0)}/h")
        hrs = round(r.get("total_seconds", 0) / 3600, 1)
        lines.append(f"  Total Hours:    {hrs}h")
        lines.append(f"  Total Uses:     {r.get('total_uses', 0)}")
        lines.append(f"  Total Cost:     ${r.get('total_cost', 0)}")
        email = r.get("email", "")
        if email:
            lines.append(f"  Email:          {email}")
        note = r.get("note", "")
        if note:
            lines.append(f"  Note:           {note}")
        results.append("\n".join(lines))

    return [types.TextContent(type="text", text="\n\n".join(results))]


def _format_violations(violations: list[dict], tasks: list[dict]) -> list[types.TextContent]:
    """Format violation list."""
    task_names = _task_name_map(tasks)
    lines = [f"⚠️ Violations ({len(violations)})", "=" * 60]

    if not violations:
        lines.append("  (no violations found)")

    for v in violations:
        vtype = v.get("violation_type", "unknown")
        desc = v.get("description", "")
        tid = v.get("task_id", -1)
        tname = task_names.get(tid, f"Task #{tid}") if tid != -1 else "N/A"
        lines.append(f"  ⚠️ [{vtype}] {desc}")
        lines.append(f"       Task: {tname}")

    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_assignments(assignments: list[dict], tasks: list[dict], resources: list[dict]) -> list[types.TextContent]:
    """Format assignment list."""
    task_names = _task_name_map(tasks)
    res_names = _resource_name_map(resources)
    lines = [f"\U0001f4cb Assignments ({len(assignments)})", "=" * 60]

    if not assignments:
        lines.append("  (no assignments found in this project)")

    for a in assignments:
        tid = a.get("task_id", 0)
        rid = a.get("resource_id", 0)
        tname = task_names.get(tid, f"Task #{tid}")
        rname = res_names.get(rid, f"Resource #{rid}")
        lines.append(f"  \U0001f464 {rname:20s} → \U0001f4cb {tname}")

    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_dependencies(dependencies: list[dict], tasks: list[dict]) -> list[types.TextContent]:
    """Format dependency list."""
    task_names = _task_name_map(tasks)
    lines = [f"\U0001f517 Dependencies ({len(dependencies)})", "=" * 60]

    if not dependencies:
        lines.append("  (no dependencies found in this project)")

    for d in dependencies:
        tid = d.get("task_id", 0)
        pid = d.get("prerequisite_task_id", 0)
        tname = task_names.get(tid, f"Task #{tid}")
        pname = task_names.get(pid, f"Task #{pid}")
        lines.append(f"  \U0001f4cb {tname:45s} ← {pname}")

    return [types.TextContent(type="text", text="\n".join(lines))]


# ── Main ───────────────────────────────────────────────────────────────────


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="omniplan-mcp",
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
