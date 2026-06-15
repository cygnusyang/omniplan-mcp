# CHANGELOG

## v0.5.0 (2026-06-15)

### Added

- **Notes support** — New `get-note` / `set-note` CLI commands to read and write task and resource notes. Supports `--resource` flag for resource notes. Requires open OmniPlan document for write operations.
- **MCP tools for notes** — `set_task_note` / `set_resource_note` MCP tools with `filepath`/`document_id` selectors.
- **AppleScript write operations** — `set_task_note()` / `set_resource_note()` in parser.py, with proper AppleScript string escaping.
- **`.oplx` XML note parsing** — `<note>` elements now extracted from tasks and resources during direct XML parsing.
- **`add_resource()` AppleScript function** — New write operation to add resources to open OmniPlan documents.
- **CLI `eval-script` command** — Evaluate AppleScript or Omni Automation JavaScript (`--js` flag) against OmniPlan.

### Changed

- **Dual-mode architecture** — Package now operates as both a CLI tool and MCP server:
  - `omniplan-mcp serve` — MCP server mode (stdio)
  - `omniplan-mcp read|summary|search|tasks|resources|dependencies` — Human-friendly read commands
  - `omniplan-mcp set-done|add-dep|set-duration|...` — Write commands (need open OmniPlan)
  - Human-friendly duration parsing: `3d`, `4h`, `30m`, `2 days`, etc.
- **`pyproject.toml`** — Added `click` dependency; `omniplan-mcp` CLI entry point script.
- **CLI `set-estimate`** — Signature updated to match parser: `set-estimate <filepath> <task_id> <min> <max>`.
- **Tests** — 73 passing tests (44 CLI + 19 parser + 10 notes). Test XML format fixed to use correct `<scenario>` namespace.
- **Documentation** — README and CLAUDE.md fully updated with CLI usage and dual-mode documentation.
