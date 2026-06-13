# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An MCP (Model Context Protocol) server that reads OmniPlan (.oplx) and Microsoft Project (.mpp) schedule files and exposes them as tools for Claude. macOS only — AppleScript bridge required for .mpp files.

## Architecture

```
src/omniplan_mcp/
├── __init__.py      # Version (__version__ = "0.4.0")
├── __main__.py      # CLI entry point: python -m omniplan_mcp
├── server.py        # MCP server: tool definitions (13 tools) + output formatters
└── parser.py        # Two parsing paths:
                      #   - read_mpp(): AppleScript bridge → pipe-delimited → dict
                      #   - read_oplx(): Direct XML parsing from .oplx (ZIP) → dict
```

### Key Design Decisions

1. **Dual parser architecture**: `.mpp` files open OmniPlan and read via AppleScript's in-memory object model. `.oplx` files parse XML directly (no OmniPlan needed). Both return identical 6-tuples: `(projects, resources, tasks, violations, assignments, dependencies)`.

2. **Two ID systems**: XML (.oplx) uses string IDs like `"t258"`. AppleScript uses sequential integers starting at 1. The `build_task_tree()` function and `parent_id` field must handle both types: `.oplx` uses `""` or `"t-1"` for no-parent, while AppleScript uses `-1`.

3. **Percent-complete computation**: `.oplx` files store completion as `effort-done / effort` ratio, not a `<percent-complete>` tag. Group tasks don't have either — their completion is computed bottom-up from children.

4. **AppleScript quoting**: When embedding strings in AppleScript via `evaluate_javascript()` or `export_schedule()`, backslashes and double quotes must be escaped with `\\"` to avoid syntax errors.

### Critical Bug Patterns

- Task ID comparisons must match the ID system in use: `if id of t = 329` (not `"t329"`) in AppleScript
- Raw `$` in Python raw strings (`r'...'`) used in AppleScript templates can trigger `SyntaxWarning: invalid escape sequence`
- `.oplx` ZIP files contain `Actual.xml` (task data), `__TOC.xml` (view settings), `__changelog.xml` (edit history), and `Preview.png`

## Commands

```bash
# Install in editable mode
cd /Users/cygnus/tools/omniplan-mcp
pip install -e .

# Run tests
python -m pytest tests/ -v

# Run the MCP server directly (stdio mode)
python -m omniplan_mcp

# Build distribution
python -m build

# Publish (via GitHub Actions — tag triggers auto-publish to PyPI)
git tag v0.X.Y && git push origin v0.X.Y
```

## Write Operation Tools

The following tools **modify** the active OmniPlan document (requires macOS + open document):

| Tool | Function | Key Params |
|------|----------|------------|
| `lookup_task` | Find task by name → get numeric ID | `search_name` |
| `set_task_completed` | Mark task 100% done | `task_id`, `include_subtree` |
| `set_task_completed_by_name` | Same, by name | `task_name`, `include_subtree` |
| `add_dependency` | Add prerequisite | `dependent_task_id`, `prerequisite_task_id` |
| `remove_dependency` | Remove prerequisite | `dependent_task_id`, `prerequisite_task_id` |
| `set_task_duration` | Change duration | `task_id`, `duration_seconds` |
| `clear_constraint_date` | Remove locked start | `task_id` |
| `rename_task` | Rename | `task_id`, `new_name` |
| `delete_task` | Delete + children | `task_id` |
| `add_task` | Add child task | `parent_task_id`, `task_name`, `duration_seconds` |
| `save_document` | Save to disk | (none) |

**AppleScript ID rule**: XML `t258` → AppleScript `id of t` = `258`. Pass numeric `"258"` or XML `"t258"` — both work (the `t` prefix is stripped).

## MCP Tools (25 total)

### Read Tools (13)

| Tool | File Path | Parser Needed? |
|------|-----------|----------------|
| `read_schedule` | server.py:376 | Yes (.oplx/.mpp) |
| `list_milestones` | server.py:380 | Yes |
| `list_resources` | server.py:383 | Yes |
| `search_tasks` | server.py:387 | Yes |
| `schedule_summary` | server.py:389 | Yes |
| `get_task_detail` | server.py:392 | Yes |
| `get_resource_detail` | server.py:396 | Yes |
| `list_violations` | server.py:399 | Yes |
| `list_assignments` | server.py:400 | Yes |
| `list_dependencies` | server.py:401 | Yes |
| `evaluate_omniplan_script` | server.py:347 | No (JS eval) |
| `export_schedule` | server.py:350 | No (AppleScript) |
| `get_schedule_settings` | server.py:355 | No (AppleScript) |

## Testing

Tests use a hand-crafted `.oplx` ZIP in memory (no real files). The test XML includes all three task types (group, standard, milestone), resources, and dates.

To add a new test: add a new function `test_*` in `tests/test_parser.py` and create test XML in the `TEST_XML` constant (or create a separate XML string for edge cases).
