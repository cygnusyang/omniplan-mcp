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
from .server import format_schedule_summary, format_task_tree, format_tasks_table, search_tasks
from .server import evaluate_omniplan_script as mcp_evaluate_omniplan_script

# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_file(filepath: str) -> tuple:
    """Read and parse a schedule file, returning the standard 6-tuple."""
    return parser._read_schedule(filepath)


def _echo_json(data, indent: int = 2) -> None:
    """Print data as formatted JSON."""
    click.echo(json.dumps(data, indent=indent, ensure_ascii=False, default=str))


def _require_omniplan_open(write_operation: str) -> None:
    """Check that OmniPlan is running (best-effort warning)."""
    # AppleScript will fail with a clear error if OmniPlan isn't running,
    # so this is just a gentle reminder for the common case.
    pass


def _strip_task_id(task_id: str) -> str:
    """Normalize XML-style t258 → 258 for AppleScript."""
    return task_id.lstrip("t")


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
    projects, resources, tasks, violations, assignments, dependencies = _parse_file(filepath)

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
    click.echo(format_tasks_table(tasks))

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
    result = _parse_file(filepath)

    if as_json:
        _echo_json({
            "projects": len(result[0]),
            "resources": len(result[1]),
            "tasks": len(result[2]),
            "violations": len(result[3]),
            "assignments": len(result[4]),
            "dependencies": len(result[5]),
        })
        return

    click.echo(format_schedule_summary(result))


# ── search ───────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("filepath", type=click.Path(exists=True))
@click.argument("query")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def search(filepath: str, query: str, as_json: bool) -> None:
    """Search tasks by name or ID."""
    _, _, tasks, _, _, _ = _parse_file(filepath)
    results = search_tasks(tasks, query)

    if as_json:
        _echo_json(results)
        return

    if not results:
        click.echo(f"No tasks matching '{query}'.")
        return

    click.echo(f"Found {len(results)} task(s) matching '{query}':\n")
    click.echo(format_tasks_table(results))


# ── tasks (list tasks as table) ──────────────────────────────────────────────

@cli.command("tasks")
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--tree", is_flag=True, help="Show as indented tree")
def list_tasks(filepath: str, as_json: bool, tree: bool) -> None:
    """List all tasks in the schedule."""
    _, _, tasks, _, _, _ = _parse_file(filepath)

    if as_json:
        _echo_json(tasks)
        return

    if tree:
        click.echo(format_task_tree(tasks))
    else:
        click.echo(format_tasks_table(tasks))


# ── resources ────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def resources(filepath: str, as_json: bool) -> None:
    """List all resources."""
    _, resources, _, _, _, _ = _parse_file(filepath)

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
    _, _, _, _, _, dependencies = _parse_file(filepath)

    if as_json:
        _echo_json(dependencies)
        return

    if not dependencies:
        click.echo("No dependencies found.")
        return

    click.echo(f"\n{'='*60}")
    click.echo(f"🔗  Dependencies ({len(dependencies)})")
    click.echo(f"{'='*60}")
    for dep in dependencies:
        click.echo(f"  {dep.get('from_task', '?')}  →  {dep.get('to_task', '?')}")


# ── lookup (needs open OmniPlan) ────────────────────────────────────────────

@cli.command()
@click.argument("search_name")
def lookup(search_name: str) -> None:
    """Find a task by name (requires open OmniPlan document)."""
    result = parser.lookup_task_by_name(search_name)
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
@click.argument("task_id")
@click.argument("estimate", callback=lambda ctx, param, value: _parse_duration_seconds(value))
def set_estimate(task_id: str, estimate: int) -> None:
    """Set a task's estimated effort (requires open OmniPlan document).

    ESTIMATE can be seconds (3600), days (3d), hours (4h), or minutes (30m).
    """
    result = parser.set_task_estimate(task_id, estimate)
    click.echo(result)


# ── eval (raw AppleScript/Omni Automation) ──────────────────────────────────

@cli.command()
@click.argument("script")
@click.option("--js", "as_javascript", is_flag=True, help="Interpret script as Omni Automation JavaScript (not AppleScript)")
def eval_script(script: str, as_javascript: bool) -> None:
    """Evaluate an AppleScript or Omni Automation script against OmniPlan."""
    if as_javascript:
        result = parser.evaluate_omniplan_script(script)
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
    click.echo(result)


# ── save ────────────────────────────────────────────────────────────────────

@cli.command()
def save() -> None:
    """Save the open OmniPlan document to disk."""
    result = parser.save_document()
    click.echo(result)


# ── entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point."""
    cli()


if __name__ == "__main__":
    main()
