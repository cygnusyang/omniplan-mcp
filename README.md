# OmniPlan MCP

An MCP (Model Context Protocol) server **and CLI** for reading and writing
[OmniPlan](https://www.omnigroup.com/omniplan/) (.oplx) and
Microsoft Project (.mpp) schedule files.

> macOS only — AppleScript bridge required for .mpp and all write operations.

## Installation

```bash
pip install omniplan-mcp
```

Or install from source in editable mode:

```bash
cd /Users/cygnus/work/github/omniplan-mcp
pip install -e .
```

## Usage

### CLI mode (human-friendly)

Read and display a schedule:

```bash
# Read a complete schedule
omniplan-mcp read schedule.oplx

# Show a high-level summary
omniplan-mcp summary schedule.oplx

# Search for tasks by name
omniplan-mcp search schedule.oplx "design"

# List all tasks (table or tree view)
omniplan-mcp tasks schedule.oplx
omniplan-mcp tasks schedule.oplx --tree

# List resources or dependencies
omniplan-mcp resources schedule.oplx
omniplan-mcp dependencies schedule.oplx
```

Modify a schedule (requires the document to be open in OmniPlan):

```bash
# Find a task's ID by name
omniplan-mcp lookup "Task Name"

# Mark a task as complete
omniplan-mcp set-done 258
omniplan-mcp set-done 258 --subtree

# Add/remove dependencies
omniplan-mcp add-dep 260 258
omniplan-mcp rm-dep 260 258

# Set duration (seconds, days, hours, or minutes)
omniplan-mcp set-duration 258 3d
omniplan-mcp set-duration 258 28800

# Add a new child task
omniplan-mcp add-task 258 "Subtask" 2d

# Rename, delete, clear constraints
omniplan-mcp rename 258 "New Name"
omniplan-mcp delete 258
omniplan-mcp clear-constraint 258

# Save the document
omniplan-mcp save

# JSON output (read commands)
omniplan-mcp read schedule.oplx --json
omniplan-mcp summary schedule.oplx --json
```

Get help:

```bash
omniplan-mcp --help
omniplan-mcp read --help
```

### MCP server mode (for AI tools)

Start the MCP server in stdio mode:

```bash
omniplan-mcp serve
```

Configure your MCP host (e.g., Claude Code) to use it:

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

## Architecture

```
src/omniplan_mcp/
├── __init__.py      # Version (__version__ = "0.4.0")
├── __main__.py      # CLI entry point: delegates to cli.py
├── cli.py           # CLI subcommands (click)
├── server.py        # MCP server: tool definitions + output formatters
└── parser.py        # Two parsing paths + write operations (AppleScript bridge)
tests/
└── test_parser.py   # Unit tests with in-memory .oplx ZIPs
```

### Dual-mode design

The package provides **two interfaces** from the same codebase:

1. **CLI mode** (`omniplan-mcp read ...`, `omniplan-mcp set-done ...`) — human-friendly terminal output
2. **MCP server mode** (`omniplan-mcp serve`) — JSON-RPC over stdio for AI tools

Both share the same parser (`parser.py`) and AppleScript bridge.

### Key design decisions

1. **Dual parser architecture**: `.mpp` files open OmniPlan and read via AppleScript's in-memory object model. `.oplx` files parse XML directly (no OmniPlan needed). Both return identical 6-tuples: `(projects, resources, tasks, violations, assignments, dependencies)`.

2. **Two ID systems**: XML (.oplx) uses string IDs like `"t258"`. AppleScript uses sequential integers starting at 1. All write operations strip the `t` prefix automatically.

3. **Write operations work on the open OmniPlan document**: Tools like `add_dependency`, `set_task_duration`, `clear_constraint_date` generate AppleScript that targets `document 1` of `application "OmniPlan"`. The document must be open.

4. **Read tools work from file** (.oplx or .mpp): `read`, `summary`, `search`, `tasks`, `resources`, `dependencies` parse the file on disk.

5. **`list_dependencies` reads from the baseline scenario**, not the editing scenario.

### Omni Automation JavaScript vs JXA

`evaluate_omniplan_script` uses **Omni Automation JavaScript** (not JXA/AppleScript JS). See the full explanation in the MCP server documentation.

### Percent-complete computation

.oplx files store completion as `effort-done / effort` ratio. Group tasks compute completion bottom-up from children. Task status is computed: 100% → "finished", else compare end date to today.

## Development

```bash
# Install in editable mode
pip install -e .

# Run tests
python -m pytest tests/ -v

# Build distribution
python -m build
```

## Testing

Tests use a hand-crafted `.oplx` ZIP in memory (no real files). Add new test functions in `tests/test_parser.py` with inline XML constants. Tests cover: parsing, resource filtering, tree building, string parent IDs, percent-complete from effort, outline_depth, task_status, and Actual.xml preference.
