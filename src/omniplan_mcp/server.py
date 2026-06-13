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
    build_task_tree,
    get_resources_staff,
    parse_file,
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
            description="List all human resources (staff) in a project schedule.",
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
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # Platform check — OmniPlan is macOS only
    if sys.platform != "darwin":
        return [
            types.TextContent(
                type="text",
                text=(
                    "This MCP server requires macOS. "
                    "OmniPlan is only available on macOS."
                ),
            )
        ]

    filepath = arguments.get("filepath", "")

    if not os.path.exists(filepath):
        return [
            types.TextContent(type="text", text=f"File not found: {filepath}")
        ]

    try:
        projects, resources, tasks = parse_file(filepath)
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
        return _format_resources(resources)
    elif name == "search_tasks":
        keyword = arguments.get("keyword", "")
        return _format_search(tasks, keyword)
    elif name == "schedule_summary":
        return _format_summary(projects, resources, tasks)
    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


# ── Output Formatters ─────────────────────────────────────────────────────


def _format_read_schedule(
    projects: list[dict], tasks: list[dict], fmt: str
) -> list[types.TextContent]:
    """Format the full schedule output."""
    if fmt == "json":
        return [
            types.TextContent(
                type="text",
                text=json.dumps(tasks, indent=2, ensure_ascii=False),
            )
        ]

    lines = []

    # Project info
    if projects:
        p = projects[0]
        lines.append(f"\U0001f4ca {p.get('title', 'Untitled')}")
        if p.get("start_date"):
            lines.append(f"\U0001f4c5 Start: {p['start_date']} → End: {p.get('end_date', '')}")
            if p.get("percent_complete"):
                lines.append(f"\U0001f4c8 Overall: {p['percent_complete']:.1f}%")
        lines.append("")

    # Stats
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
    """Format milestone list."""
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


def _format_resources(resources: list[dict]) -> list[types.TextContent]:
    """Format resource list."""
    staff = get_resources_staff(resources)
    lines = [f"\U0001f464 Resources ({len(staff)})", "=" * 60]
    for r in staff:
        lines.append(f"  \U0001f464 {r['name']}")

    if not staff:
        lines.append("  (no staff resources found)")

    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_search(tasks: list[dict], keyword: str) -> list[types.TextContent]:
    """Format search results."""
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
            pct_str = f" [{pct}%]" if pct else ""
            lines.append(f"  {marker}{name:50s} {start}→{end}{pct_str}")

    lines.append(f"\nFound {found} matching tasks")
    return [types.TextContent(type="text", text="\n".join(lines))]


def _format_summary(
    projects: list[dict], resources: list[dict], tasks: list[dict]
) -> list[types.TextContent]:
    """Format project summary."""
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
