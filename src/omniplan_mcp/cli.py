"""Command-line interface for omniplan-mcp.

Provides both human-friendly CLI subcommands and MCP server mode.
"""

import sys
import json
import asyncio
from typing import Optional

import click

from . import __version__
from . import parser
from .parser import parse_file, build_task_tree, get_resources_staff


# ── helpers ──────────────────────────────────────────────────────────────────

def _echo_json(data, indent: int = 2) -> None:
    """Print data as formatted JSON."""
    click.echo(json.dumps(data, indent=indent, ensure_ascii=False, default=str))


def _parse_duration_seconds(duration_str: str) -> int:
    """Parse a human-friendly duration string into seconds.

    Accepts:
      - Plain integer seconds: "3600"
      - Days: "3d", "2 days"
      - Hours: "4h", "2 hours"
      - Minutes: "30m", "15 minutes"
    """
    duration_str = duration_str.strip().lower()

    # Try plain integer seconds first
    try:
        return int(duration_str)
    except ValueError:
        pass

    # Try suffixed formats
    multipliers = {
        "d": 28800, "day": 28800, "days": 28800,
        "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
        "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    }
    for suffix, multiplier in multipliers.items():
        if duration_str.endswith(suffix):
            try:
                num_str = duration_str[: -len(suffix)].strip()
                # Handle "2 days" — split on space
                if " " in num_str:
                    num_str = num_str.split()[0]
                return int(float(num_str) * multiplier)
            except (ValueError, IndexError):
                pass

    raise click.BadParameter(
        f"Could not parse duration: '{duration_str}'. "
        "Use seconds (3600), days (3d), hours (4h), or minutes (30m)."
    )


def _format_tasks_table(tasks: list[dict]) -> str:
    """Format tasks as a simple table string."""
    lines = []
    for t in tasks:
        name = t.get("name", "")
        ttype = t.get("task_type", "")
        marker = "◇ " if ttype == "milestone" else ("▣ " if ttype == "group" else "  ")
        start = t.get("start_date", "")
        end = t.get("end_date", "")
        pct = t.get("percent_complete", "")
        pct_str = f" [{pct}%]" if pct else ""
        lines.append(f"  {marker}{name:50s} {start}→{end}{pct_str}")
    return "\n".join(lines)


def _format_tree(tasks: list[dict], level: int = 0, lines: list[str] | None = None) -> list[str]:
    """Recursively format tasks as an indented tree."""
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


# ── CLI group ────────────────────────────────────────────────────────────────

@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="omniplan-mcp")
def cli() -> None:
    """OmniPlan schedule reader and writer.

    Read, search, and modify OmniPlan (.oplx) and Microsoft Project (.mpp)
    schedule files. Write operations require the schedule to be open in OmniPlan.
    """


# ── serve (MCP server mode) ──────────────────────────────────────────────────

@cli.command()
def serve() -> None:
    """Start MCP server (stdio mode)."""
    from .server import main
    asyncio.run(main())


# ── read ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def read(filepath: str, as_json: bool) -> None:
    """Read and display a complete schedule."""
    projects, resources, tasks, violations, assignments, dependencies = parse_file(filepath)

    if as_json:
        _echo_json({
            "projects": projects,
            "resources": resources,
            "tasks": tasks,
            "violations": violations,
            "assignments": assignments,
            "dependencies": dependencies,
        })
        return

    # Projects
    click.echo(f"\n{'='*60}")
    click.echo(f"📋  Projects")
    click.echo(f"{'='*60}")
    for proj in projects:
        click.echo(f"  {proj.get('name', 'Untitled')}  (start: {proj.get('start', '?')},  end: {proj.get('end', '?')})")

    # Tasks
    click.echo(f"\n{'='*60}")
    click.echo(f"📌  Tasks ({len(tasks)})")
    click.echo(f"{'='*60}")
    click.echo(_format_tasks_table(tasks))

    # Resources
    click.echo(f"\n{'='*60}")
    click.echo(f"👤  Resources ({len(resources)})")
    click.echo(f"{'='*60}")
    for r in resources:
        click.echo(f"  {r.get('name', '?')}  ({r.get('type', '?')})")

    # Dependencies
    click.echo(f"\n{'='*60}")
    click.echo(f"🔗  Dependencies ({len(dependencies)})")
    click.echo(f"{'='*60}")
    if dependencies:
        for dep in dependencies:
            click.echo(f"  {dep.get('from_task', '?')}  →  {dep.get('to_task', '?')}")
    else:
        click.echo("  (none)")

    # Violations
    if violations:
        click.echo(f"\n{'='*60}")
        click.echo(f"⚠️  Violations ({len(violations)})")
        click.echo(f"{'='*60}")
        for v in violations:
            click.echo(f"  {v}")


# ── summary ──────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def summary(filepath: str, as_json: bool) -> None:
    """Show a high-level schedule summary."""
    projects, resources, tasks, violations, assignments, dependencies = parse_file(filepath)

    if as_json:
        _echo_json({
            "projects": len(projects),
            "resources": len(resources),
            "tasks": len(tasks),
            "violations": len(violations),
            "assignments": len(assignments),
            "dependencies": len(dependencies),
        })
        return

    # Build summary text
    lines = []
    if projects:
        p = projects[0]
        lines.append(f"📅  Project: {p.get('title', 'Untitled')}")
        if p.get("start_date"):
            lines.append(f"     Start: {p['start_date']}")
        if p.get("end_date"):
            lines.append(f"     End:   {p['end_date']}")
        if p.get("percent_complete"):
            lines.append(f"     Overall Progress: {p['percent_complete']:.1f}%")
        if p.get("duration_seconds"):
            days = round(p["duration_seconds"] / 28800, 1)
            lines.append(f"     Duration: {days} working days")
        if p.get("effort_seconds"):
            hrs = round(p["effort_seconds"] / 3600, 1)
            lines.append(f"     Total Effort: {hrs} person-hours")

    staff = get_resources_staff(resources)
    lines.append(f"\n👤  Resources: {len(staff)} staff")

    total = len(tasks)
    milestones = sum(1 for t in tasks if t["task_type"] == "milestone")
    groups = sum(1 for t in tasks if t["task_type"] == "group")
    tasks_only = total - milestones - groups

    lines.append(f"\n📌  Total tasks: {total}")
    lines.append(f"     • Groups: {groups}")
    lines.append(f"     • Tasks: {tasks_only}")
    lines.append(f"     • Milestones: {milestones}")

    completed = sum(1 for t in tasks if t["task_type"] == "task" and t.get("percent_complete", 0) >= 100)
    in_progress = sum(1 for t in tasks if t["task_type"] == "task" and 0 < t.get("percent_complete", 0) < 100)
    not_started = sum(1 for t in tasks if t["task_type"] == "task" and t.get("percent_complete", 0) == 0)
    lines.append(f"\n📊  Progress (tasks only):")
    lines.append(f"     ✅ Completed: {completed}")
    lines.append(f"     🔄 In Progress: {in_progress}")
    lines.append(f"     ⏳ Not Started: {not_started}")

    past_due = sum(1 for t in tasks if t.get("task_status") == "past due")
    if past_due:
        lines.append(f"     🔴 Past Due: {past_due}")

    click.echo("\n".join(lines))


# ── search ───────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("filepath", type=click.Path(exists=True))
@click.argument("query")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def search(filepath: str, query: str, as_json: bool) -> None:
    """Search tasks by name or ID."""
    _, _, tasks, _, _, _ = parse_file(filepath)
    query_lower = query.lower()
    results = [t for t in tasks if t.get("name") and query_lower in t["name"].lower()]

    if as_json:
        _echo_json(results)
        return

    if not results:
        click.echo(f"No tasks matching '{query}'.")
        return

    click.echo(f"Found {len(results)} task(s) matching '{query}':\n")
    click.echo(_format_tasks_table(results))


# ── tasks (list tasks as table) ──────────────────────────────────────────────

@cli.command("tasks")
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--tree", is_flag=True, help="Show as indented tree")
def list_tasks(filepath: str, as_json: bool, tree: bool) -> None:
    """List all tasks in the schedule."""
    _, _, tasks, _, _, _ = parse_file(filepath)

    if as_json:
        _echo_json(tasks)
        return

    if tree:
        tree_data = build_task_tree(tasks)
        lines = _format_tree(tree_data)
        click.echo("\n".join(lines))
    else:
        click.echo(_format_tasks_table(tasks))


# ── resources ────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def resources(filepath: str, as_json: bool) -> None:
    """List all resources."""
    _, resources, _, _, _, _ = parse_file(filepath)

    if as_json:
        _echo_json(resources)
        return

    if not resources:
        click.echo("No resources found.")
        return

    click.echo(f"\n{'='*60}")
    click.echo(f"👤  Resources ({len(resources)})")
    click.echo(f"{'='*60}")
    for r in resources:
        click.echo(f"  {r.get('name', '?')}  ({r.get('type', '?')})")


# ── dependencies ─────────────────────────────────────────────────────────────

@cli.command()
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def dependencies(filepath: str, as_json: bool) -> None:
    """List all task dependencies."""
    _, _, _, _, _, deps = parse_file(filepath)

    if as_json:
        _echo_json(deps)
        return

    if not deps:
        click.echo("No dependencies found.")
        return

    click.echo(f"\n{'='*60}")
    click.echo(f"🔗  Dependencies ({len(deps)})")
    click.echo(f"{'='*60}")
    for dep in deps:
        click.echo(f"  {dep.get('from_task', '?')}  →  {dep.get('to_task', '?')}")


# ── lookup (needs open OmniPlan) ────────────────────────────────────────────

@cli.command()
@click.argument("search_name")
def lookup(search_name: str) -> None:
    """Find a task by name (requires open OmniPlan document)."""
    result = parser.lookup_task(search_name)
    click.echo(result)


# ── set-done ─────────────────────────────────────────────────────────────────

@cli.command(name="set-done")
@click.argument("task_id")
@click.option("--subtree", is_flag=True, help="Include child tasks")
def set_done(task_id: str, subtree: bool) -> None:
    """Mark a task as 100% complete (requires open OmniPlan document)."""
    result = parser.set_task_completed(task_id, include_subtree=subtree)
    click.echo(result)


@cli.command(name="set-done-by-name")
@click.argument("task_name")
@click.option("--subtree", is_flag=True, help="Include child tasks")
def set_done_by_name(task_name: str, subtree: bool) -> None:
    """Mark a task as 100% complete by name (requires open OmniPlan document)."""
    result = parser.set_task_completed_by_name(task_name, include_subtree=subtree)
    click.echo(result)


# ── add-dep / rm-dep ────────────────────────────────────────────────────────

@cli.command(name="add-dep")
@click.argument("dependent_task_id")
@click.argument("prerequisite_task_id")
def add_dep(dependent_task_id: str, prerequisite_task_id: str) -> None:
    """Add a dependency (requires open OmniPlan document)."""
    result = parser.add_dependency(dependent_task_id, prerequisite_task_id)
    click.echo(result)


@cli.command(name="rm-dep")
@click.argument("dependent_task_id")
@click.argument("prerequisite_task_id")
def rm_dep(dependent_task_id: str, prerequisite_task_id: str) -> None:
    """Remove a dependency (requires open OmniPlan document)."""
    result = parser.remove_dependency(dependent_task_id, prerequisite_task_id)
    click.echo(result)


# ── set-duration ────────────────────────────────────────────────────────────

@cli.command(name="set-duration")
@click.argument("task_id")
@click.argument("duration", callback=lambda ctx, param, value: _parse_duration_seconds(value))
def set_duration(task_id: str, duration: int) -> None:
    """Set task duration (requires open OmniPlan document).

    DURATION can be seconds (3600), days (3d), hours (4h), or minutes (30m).
    """
    result = parser.set_task_duration(task_id, duration)
    click.echo(result)


# ── clear-constraint ────────────────────────────────────────────────────────

@cli.command(name="clear-constraint")
@click.argument("task_id")
def clear_constraint(task_id: str) -> None:
    """Remove a task's locked start/end date (requires open OmniPlan document)."""
    result = parser.clear_constraint_date(task_id)
    click.echo(result)


# ── rename ──────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("task_id")
@click.argument("new_name")
def rename(task_id: str, new_name: str) -> None:
    """Rename a task (requires open OmniPlan document)."""
    result = parser.rename_task(task_id, new_name)
    click.echo(result)


# ── delete ──────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("task_id")
def delete(task_id: str) -> None:
    """Delete a task and its children (requires open OmniPlan document)."""
    result = parser.delete_task(task_id)
    click.echo(result)


# ── add-task ────────────────────────────────────────────────────────────────

@cli.command(name="add-task")
@click.argument("parent_task_id")
@click.argument("task_name")
@click.argument("duration", callback=lambda ctx, param, value: _parse_duration_seconds(value))
def add_task(parent_task_id: str, task_name: str, duration: int) -> None:
    """Add a new child task (requires open OmniPlan document).

    DURATION can be seconds (3600), days (3d), hours (4h), or minutes (30m).
    """
    result = parser.add_task(parent_task_id, task_name, duration)
    click.echo(result)


# ── add-resource ────────────────────────────────────────────────────────────

@cli.command(name="add-resource")
@click.argument("name")
def add_resource(name: str) -> None:
    """Add a new resource (requires open OmniPlan document)."""
    result = parser.add_resource(name)
    click.echo(result)


# ── set-estimate ────────────────────────────────────────────────────────────

@cli.command(name="set-estimate")
@click.argument("filepath", type=click.Path(exists=True))
@click.argument("task_id")
@click.argument("min_duration", callback=lambda ctx, param, value: _parse_duration_seconds(value))
@click.argument("max_duration", callback=lambda ctx, param, value: _parse_duration_seconds(value))
def set_estimate(filepath: str, task_id: str, min_duration: int, max_duration: int) -> None:
    """Set a task's estimate range (min / max in working seconds).

    FILEPATH is the path to the .oplx file (must be closed in OmniPlan).
    DURATION values can be seconds (3600), days (3d), hours (4h), or minutes (30m).
    """
    result = parser.set_task_estimate(filepath, task_id, min_duration, max_duration)
    click.echo(result)


# ── eval (raw AppleScript/Omni Automation) ──────────────────────────────────

@cli.command(name="eval-script")
@click.argument("script")
@click.option("--js", "as_javascript", is_flag=True, help="Interpret script as Omni Automation JavaScript (not AppleScript)")
def eval_script(script: str, as_javascript: bool) -> None:
    """Evaluate an AppleScript or Omni Automation script against OmniPlan."""
    if as_javascript:
        result = parser.evaluate_javascript(script)
    else:
        # Run as raw AppleScript
        import subprocess
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            click.echo(f"Error: {result.stderr.strip()}", err=True)
            sys.exit(1)
        click.echo(result.stdout.strip())
        return
    click.echo(result)


# ── save ────────────────────────────────────────────────────────────────────

@cli.command()
def save() -> None:
    """Save the open OmniPlan document to disk."""
    result = parser.save_document()
    click.echo(result)


# ── get-note / set-note ────────────────────────────────────────────────────

@cli.command(name="get-note")
@click.argument("filepath", type=click.Path(exists=True))
@click.argument("item_id")
@click.option("--resource", "is_resource", is_flag=True, help="Look up a resource instead of a task")
def get_note(filepath: str, item_id: str, is_resource: bool) -> None:
    """Get the note/description of a task or resource from a schedule file."""
    projects, resources, tasks, violations, assignments, dependencies = parse_file(filepath)

    if is_resource:
        for r in resources:
            if r.get("id") == item_id or str(r.get("id")) == item_id.lstrip("r"):
                note = r.get("note", "")
                if note:
                    click.echo(f"Note for resource {r.get('name', item_id)}:\n{note}")
                else:
                    click.echo(f"Resource '{r.get('name', item_id)}' has no note.")
                return
        click.echo(f"Resource '{item_id}' not found.", err=True)
        sys.exit(1)
    else:
        for t in tasks:
            if t.get("id") == item_id or str(t.get("id")) == item_id.lstrip("t"):
                note = t.get("note", "")
                if note:
                    click.echo(f"Note for task '{t.get('name', item_id)}':\n{note}")
                else:
                    click.echo(f"Task '{t.get('name', item_id)}' has no note.")
                return
        click.echo(f"Task '{item_id}' not found.", err=True)
        sys.exit(1)


@cli.command(name="set-note")
@click.argument("item_id")
@click.argument("note_text")
@click.option("--resource", "is_resource", is_flag=True, help="Set a resource note instead of a task note")
def set_note(item_id: str, note_text: str, is_resource: bool) -> None:
    """Set the note/description of a task or resource (requires open OmniPlan document)."""
    if is_resource:
        result = parser.set_resource_note(item_id, note_text)
    else:
        result = parser.set_task_note(item_id, note_text)
    click.echo(result)


# ── entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point."""
    cli()


if __name__ == "__main__":
    main()
