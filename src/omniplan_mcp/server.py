"""
MCP server for OmniPlan project schedule files.

Provides tools for reading, searching, and analyzing .mpp and .oplx files.
"""

import os
import shutil
from typing import Any

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

from . import __version__
from .parser import (
    NS,
    build_task_map,
    convert_date,
    get_text,
    get_resources,
    parse_file,
    task_to_dict,
    collect_all_tasks,
)

server = Server("omniplan-mcp")


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
            description=(
                "List all human resources (staff) in a project schedule."
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
    ]


# ── Tool Handlers ─────────────────────────────────────────────────────────


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict
) -> list[types.TextContent]:
    filepath = arguments.get("filepath", "")

    if not os.path.exists(filepath):
        return [
            types.TextContent(
                type="text", text=f"File not found: {filepath}"
            )
        ]

    cleanup_path = ""
    try:
        root, cleanup_path = parse_file(filepath)
    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"Error parsing file: {type(e).__name__}: {e}",
            )
        ]

    task_map = build_task_map(root)

    try:
        if name == "read_schedule":
            fmt = arguments.get("format", "tree")
            return _format_read_schedule(root, task_map, fmt)
        elif name == "list_milestones":
            return _format_milestones(task_map)
        elif name == "list_resources":
            return _format_resources(root)
        elif name == "search_tasks":
            keyword = arguments.get("keyword", "")
            return _format_search(task_map, keyword)
        elif name == "schedule_summary":
            return _format_summary(root, task_map)
        else:
            return [
                types.TextContent(
                    type="text", text=f"Unknown tool: {name}"
                )
            ]
    finally:
        # Clean up temp export directory if created from .mpp
        if cleanup_path and os.path.isdir(cleanup_path) and "tmp" in cleanup_path:
            shutil.rmtree(cleanup_path, ignore_errors=True)


# ── Output Formatters ─────────────────────────────────────────────────────


def _format_read_schedule(
    root: ET.Element, task_map: dict, fmt: str
) -> list[types.TextContent]:
    """Format the full schedule output."""
    if fmt == "json":
        return _format_json_schedule(task_map)
    elif fmt == "flat":
        return _format_flat_schedule(task_map)

    return _format_tree_schedule(root, task_map)


def _find_root_task(task_map: dict) -> str | None:
    """Find the root task ID (unnamed top-level group)."""
    for tid, task in task_map.items():
        title = get_text(task, "title")
        if not title and task.find(f"{NS}child-task") is not None:
            return tid
    return None


def _format_tree_schedule(
    root: ET.Element, task_map: dict
) -> list[types.TextContent]:
    """Format as hierarchical tree."""
    lines = []

    # Project start date
    start_date = get_text(root, "start-date")
    if start_date:
        lines.append(f"📅 Project Start: {convert_date(start_date)}")

    # Stats
    total = len(task_map)
    milestones = sum(
        1 for t in task_map.values() if get_text(t, "type") == "milestone"
    )
    groups = sum(
        1 for t in task_map.values() if get_text(t, "type") == "group"
    )
    lines.append(
        f"📋 Tasks: {total} total ({groups} groups, {milestones} milestones)"
    )
    lines.append("")

    tree_lines: list[str] = []

    def print_task(tid: str, level: int = 0) -> None:
        if tid not in task_map:
            return
        task = task_map[tid]
        title = get_text(task, "title")
        ttype = get_text(task, "type")
        prefix = "  " * level

        # Skip unnamed root
        if not title and tid == _find_root_task(task_map):
            for child in task:
                tag = (
                    child.tag.split("}")[1]
                    if "}" in child.tag
                    else child.tag
                )
                if tag == "child-task":
                    print_task(child.get("idref", ""), level)
            return

        start = convert_date(get_text(task, "start-date"))
        end = convert_date(get_text(task, "end-date"))
        pct = get_text(task, "percent-complete")
        effort = get_text(task, "effort")

        if ttype == "milestone":
            marker = "◇ "
        elif ttype == "group":
            marker = "▣ "
        else:
            marker = "  "

        parts = []
        if start:
            parts.append(start)
        if end:
            parts.append(f"→{end}")
        if effort:
            parts.append(f"({effort}h)")
        if pct:
            parts.append(f"[{pct}%]")

        info = " ".join(parts)
        tree_lines.append(f"{prefix}{marker}{title:50s} {info}")

        for child in task:
            tag = (
                child.tag.split("}")[1]
                if "}" in child.tag
                else child.tag
            )
            if tag == "child-task":
                print_task(child.get("idref", ""), level + 1)

    root_id = _find_root_task(task_map)
    if root_id:
        print_task(root_id)
    else:
        # Print all top-level tasks
        for task in root.findall(f".//{NS}task"):
            if get_text(task, "title"):
                print_task(task.get("id", ""))

    lines.extend(tree_lines)
    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_flat_schedule(task_map: dict) -> list[types.TextContent]:
    """Format as flat task list."""
    lines = ["📋 All Tasks (flat view)", "=" * 80]

    for tid, task in task_map.items():
        title = get_text(task, "title")
        if not title:
            continue
        ttype = get_text(task, "type")
        start = convert_date(get_text(task, "start-date"))
        end = convert_date(get_text(task, "end-date"))
        pct = get_text(task, "percent-complete")

        marker = (
            "◇ "
            if ttype == "milestone"
            else ("▣ " if ttype == "group" else "  ")
        )
        pct_str = f" [{pct}%]" if pct else ""
        lines.append(f"  {marker}{title:50s} {start}→{end}{pct_str}")

    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_json_schedule(task_map: dict) -> list[types.TextContent]:
    """Format as JSON."""
    import json

    all_tasks = []
    for tid, task in task_map.items():
        title = get_text(task, "title")
        if title:
            all_tasks.append(task_to_dict(task))

    return [
        types.TextContent(
            type="text", text=json.dumps(all_tasks, indent=2, ensure_ascii=False)
        )
    ]


def _format_milestones(task_map: dict) -> list[types.TextContent]:
    """Format milestone list."""
    lines = ["◇ Milestones", "=" * 60]

    for task in task_map.values():
        ttype = get_text(task, "type")
        if ttype == "milestone":
            title = get_text(task, "title")
            start = convert_date(get_text(task, "start-date"))
            end = convert_date(get_text(task, "end-date"))
            pct = get_text(task, "percent-complete")
            pct_str = f" [{pct}%]" if pct else ""
            lines.append(f"  ◇ {title:50s} {start}→{end}{pct_str}")

    if len(lines) == 1:
        lines.append("  (no milestones found)")

    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_resources(root: ET.Element) -> list[types.TextContent]:
    """Format resource list."""
    resources = get_resources(root)
    lines = [
        f"👤 Resources ({len(resources)})",
        "=" * 60,
    ]
    for r in resources:
        lines.append(f"  👤 {r['name']}")

    if not resources:
        lines.append("  (no staff resources found)")

    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_search(task_map: dict, keyword: str) -> list[types.TextContent]:
    """Format search results."""
    keyword_lower = keyword.lower()
    lines = [f"🔍 Search results for '{keyword}'", "=" * 60]

    found = 0
    for task in task_map.values():
        title = get_text(task, "title")
        if title and keyword_lower in title.lower():
            found += 1
            ttype = get_text(task, "type")
            start = convert_date(get_text(task, "start-date"))
            end = convert_date(get_text(task, "end-date"))
            pct = get_text(task, "percent-complete")

            marker = (
                "◇ "
                if ttype == "milestone"
                else ("▣ " if ttype == "group" else "  ")
            )
            pct_str = f" [{pct}%]" if pct else ""
            lines.append(
                f"  {marker}{title:50s} {start}→{end}{pct_str}"
            )

    lines.append(f"\nFound {found} matching tasks")
    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_summary(
    root: ET.Element, task_map: dict
) -> list[types.TextContent]:
    """Format project summary."""
    lines = ["📊 Project Schedule Summary", "=" * 60]

    # Project dates
    start_date = get_text(root, "start-date")
    if start_date:
        lines.append(f"📅 Project Start: {convert_date(start_date)}")

    # Resource count
    resources = get_resources(root)
    lines.append(f"👤 Resources: {len(resources)} staff")

    # Task counts
    total = len(task_map)
    milestones = sum(
        1 for t in task_map.values() if get_text(t, "type") == "milestone"
    )
    groups = sum(
        1 for t in task_map.values() if get_text(t, "type") == "group"
    )
    tasks_with_pct = sum(
        1 for t in task_map.values() if get_text(t, "percent-complete")
    )

    lines.append(f"\n📋 Total tasks: {total}")
    lines.append(f"   • Groups: {groups}")
    lines.append(f"   • Milestones: {milestones}")
    lines.append(f"   • Tasks with progress: {tasks_with_pct}")

    # Progress distribution
    completed = sum(
        1 for t in task_map.values()
        if get_text(t, "percent-complete") == "100"
    )
    in_progress_count = sum(
        1 for t in task_map.values()
        if get_text(t, "percent-complete")
        and get_text(t, "percent-complete") != "100"
        and get_text(t, "percent-complete") != "0"
    )
    not_started = sum(
        1 for t in task_map.values()
        if get_text(t, "type") not in ("group", "milestone")
        and not get_text(t, "percent-complete")
    )

    lines.append(f"\n📈 Progress:")
    lines.append(f"   ✅ Completed: {completed}")
    lines.append(f"   🔄 In Progress: {in_progress_count}")
    lines.append(f"   ⏳ Not Started: {not_started}")

    # Phase summary (top-level groups)
    lines.append(f"\n📋 Phases:")
    for task in task_map.values():
        ttype = get_text(task, "type")
        if ttype == "group":
            title = get_text(task, "title")
            if title:
                start = convert_date(get_text(task, "start-date"))
                end = convert_date(get_text(task, "end-date"))
                lines.append(f"  ▣ {title:45s} {start}→{end}")

    return [types.TextContent(type="text", text="\n".join(lines))]
