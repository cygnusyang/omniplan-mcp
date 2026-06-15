# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An MCP (Model Context Protocol) server **and CLI** that reads **and writes** OmniPlan (.oplx) and Microsoft Project (.mpp) schedule files. macOS only — AppleScript bridge required for .mpp and all write operations.

## Core Principle: Always use MCP tools and AppleScript — never directly modify files

All modifications to OmniPlan schedule data MUST go through:
1. **MCP tools** (preferred) — `set_task_duration`, `add_dependency`, `clear_constraint_date`, etc.
2. **`evaluate_omniplan_script`** — For operations not covered by existing tools (Omni Automation JS)
3. **AppleScript** via `osascript` (last resort) — For complex operations

**NEVER** unzip the .oplx file and directly edit XML. The MCP tools exist specifically to avoid this.

## Architecture

```
src/omniplan_mcp/
├── __init__.py      # Version (__version__ = "0.4.0")
├── __main__.py      # Entry point: delegates to cli.main()
├── cli.py           # CLI subcommands (click) — both human CLI and MCP server mode
├── server.py        # MCP server: tool definitions + output formatters
└── parser.py        # Two parsing paths + write operations (AppleScript bridge)
tests/
└── test_parser.py   # Unit tests with in-memory .oplx ZIPs
```

### Dual-mode design

The package provides **two interfaces** from the same codebase:

1. **CLI mode** (`omniplan-mcp read ...`) — human-friendly terminal output
2. **MCP server mode** (`omniplan-mcp serve`) — JSON-RPC over stdio for AI tools

Both share the same parser (`parser.py`) and AppleScript bridge.

## CLI Commands

### Read commands (work from file, no OmniPlan needed for .oplx)

| Command | Description | Example |
|---------|-------------|---------|
| `read <file>` | Display complete schedule | `omniplan-mcp read plan.oplx` |
| `summary <file>` | High-level summary | `omniplan-mcp summary plan.oplx --json` |
| `search <file> <query>` | Search tasks | `omniplan-mcp search plan.oplx "design"` |
| `tasks <file>` | List all tasks | `omniplan-mcp tasks plan.oplx --tree` |
| `resources <file>` | List resources | `omniplan-mcp resources plan.oplx` |
| `dependencies <file>` | List dependencies | `omniplan-mcp dependencies plan.oplx` |

### Write commands (require open OmniPlan document)

| Command | Description | Example |
|---------|-------------|---------|
| `serve` | Start MCP server (stdio) | `omniplan-mcp serve` |
| `lookup <name>` | Find task by name | `omniplan-mcp lookup "Design"` |
| `set-done <id>` | Mark task 100% done | `omniplan-mcp set-done 258 --subtree` |
| `set-done-by-name <name>` | Same, by name | `omniplan-mcp set-done-by-name "Design"` |
| `add-dep <dependent> <prereq>` | Add dependency | `omniplan-mcp add-dep 260 258` |
| `rm-dep <dependent> <prereq>` | Remove dependency | `omniplan-mcp rm-dep 260 258` |
| `set-duration <id> <duration>` | Set duration | `omniplan-mcp set-duration 258 3d` |
| `clear-constraint <id>` | Remove locked date | `omniplan-mcp clear-constraint 258` |
| `rename <id> <name>` | Rename task | `omniplan-mcp rename 258 "New"` |
| `delete <id>` | Delete task | `omniplan-mcp delete 258` |
| `add-task <parent> <name> <duration>` | Add child task | `omniplan-mcp add-task 258 "Sub" 2d` |
| `add-resource <name>` | Add resource | `omniplan-mcp add-resource "Alice"` |
| `set-estimate <id> <estimate>` | Set effort estimate | `omniplan-mcp set-estimate 258 3d` |
| `save` | Save document | `omniplan-mcp save` |
| `eval-script <script>` | Run raw AppleScript/JS | `omniplan-mcp eval-script --js '...'` |

Duration format: seconds (`3600`), days (`3d`), hours (`4h`), minutes (`30m`).

## MCP Server Configuration

Configure your MCP host to use `omniplan-mcp serve`:

```json
{
  "mcpServers": {
    "omniplan": {
      "command": "omniplan-mcp",
      "args": ["serve"]
    }
  }
}
```

## Key Design Decisions

1. **Dual parser architecture**: `.mpp` files open OmniPlan and read via AppleScript's in-memory object model. `.oplx` files parse XML directly (no OmniPlan needed). Both return identical 6-tuples: `(projects, resources, tasks, violations, assignments, dependencies)`.

2. **Two ID systems**: XML (.oplx) uses string IDs like `"t258"`. AppleScript uses sequential integers starting at 1. All write operations strip the `t` prefix automatically.

3. **Write operations work on the open OmniPlan document**: Tools like `add_dependency`, `set_task_duration`, `clear_constraint_date` generate AppleScript that targets `document 1` of `application "OmniPlan"`. The document must be open.

4. **Read tools work from file** (.oplx or .mpp): `read_schedule`, `schedule_summary`, `search_tasks` etc. parse the file on disk. For .oplx they use direct XML parsing; for .mpp they temporarily open in OmniPlan.

5. **`list_dependencies` reads from the baseline scenario**, not the editing scenario. When you write dependencies via AppleScript, they won't appear in `list_dependencies` output if the baseline hasn't been updated.

### Omni Automation JavaScript vs JXA

`evaluate_omniplan_script` uses **Omni Automation JavaScript** (not JXA/AppleScript JS). Key differences:
- `document` is available as a global — but its properties are not enumerable via `Object.keys()` or `for...in`
- `Application` is a CallbackObject, **not** a constructor — `new Application("OmniPlan")` fails
- `Application.documents[0]` returns `undefined` — use AppleScript `evaluate javascript` instead
- To find available properties, try `typeof document.propertyName` or `document.propertyName`
- The `document.name` works and returns the filename
- Use AppleScript wrapper for complex write operations that the existing tools don't cover

### Percent-complete computation

.oplx files store completion as `effort-done / effort` ratio. Group tasks compute completion bottom-up from children. Task status is computed: 100% → "finished", else compare end date to today.

## Write Operation Tools (all require open OmniPlan document)

| Tool | Description | Key Params |
|------|-------------|------------|
| `lookup_task` | Find task by name → get numeric ID | `search_name` |
| `set_task_completed` | Mark task 100% done | `task_id`, `include_subtree` |
| `set_task_completed_by_name` | Same, by name | `task_name`, `include_subtree` |
| `add_dependency` | Add prerequisite | `dependent_task_id`, `prerequisite_task_id` |
| `remove_dependency` | Remove prerequisite | `dependent_task_id`, `prerequisite_task_id` |
| `set_task_duration` | Change duration (1 day = 28800s) | `task_id`, `duration_seconds` |
| `clear_constraint_date` | Remove locked start/end date | `task_id` |
| `rename_task` | Rename | `task_id`, `new_name` |
| `delete_task` | Delete + children | `task_id` |
| `add_task` | Add child task | `parent_task_id`, `task_name`, `duration_seconds` |
| `save_document` | Save to disk | (none) |

### AppleScript ID rule

XML `t258` → AppleScript `id of t` = `258`. Pass numeric `"258"` or XML `"t258"` — both work.

### Duration math

1 working day = 28800 seconds (8 hours). Use: `days * 28800 = duration_seconds`.

## Commands

```bash
# Install in editable mode
cd /Users/cygnus/work/github/omniplan-mcp
pip install -e .

# Run tests
python -m pytest tests/ -v

# Run the CLI directly
omniplan-mcp read schedule.oplx
omniplan-mcp serve  # MCP server mode

# Build distribution
python -m build
```

## Testing

Tests use a hand-crafted `.oplx` ZIP in memory (no real files). Add new test functions in `tests/test_parser.py` with inline XML constants. Tests cover: parsing, resource filtering, tree building, string parent IDs, percent-complete from effort, outline_depth, task_status, and Actual.xml preference.

## Critical Bug Patterns

- Raw `$` in Python raw strings (`r'...'`) used in AppleScript templates can trigger `SyntaxWarning: invalid escape sequence`
- `.oplx` ZIP files contain `Actual.xml` (task data), `__TOC.xml` (view settings), `__changelog.xml` (edit history), and `Preview.png`
- `list_dependencies` reads from the baseline scenario, not the editing scenario — dependencies written via AppleScript may not appear until baseline is updated
- `clear_constraint_date` uses `starting constraint date` / `ending constraint date` AppleScript properties (not `locked-start-date` which is the XML element name)
