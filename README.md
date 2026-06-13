<p align="center">
  <img src="https://img.shields.io/badge/macOS-required-blue" alt="macOS">
  <img src="https://img.shields.io/badge/python-≥3.10-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/github/v/release/cygnusyang/omniplan-mcp" alt="Release">
</p>

# OmniPlan MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that lets Claude read and analyze project schedule files — **OmniPlan (.oplx)** and **Microsoft Project (.mpp)** formats.

Ask Claude questions like:
- *"What's the current project schedule?"*
- *"List all milestones and their dates"*
- *"Show me tasks related to the robotic arm"*
- *"What's the overall progress percentage?"*

## Features

| Feature | Description |
|---------|-------------|
| 📂 **Read .mpp** | Parse Microsoft Project files via OmniPlan bridge |
| 📂 **Read .oplx** | Direct XML parsing (no OmniPlan needed) |
| 🏛️ **Full hierarchy** | Groups, tasks, milestones with dates and progress |
| 🔍 **Search** | Find tasks by keyword across the entire schedule |
| 👤 **Resources** | List all human resources and assignments |
| 📊 **Summary** | Phase overview, progress statistics, timeline |
| 🔒 **Safe concurrency** | Direct AppleScript reading avoids temp-file conflicts when multiple sessions run |

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **macOS** | Required (for AppleScript/OmniPlan bridge) |
| **Python 3.10+** | For running the MCP server |
| **OmniPlan** | Only needed for `.mpp` files; `.oplx` works without it |

### Install OmniPlan (optional — only for .mpp files)

```bash
brew install --cask omniplan
```

> **First run**: macOS may prompt for Accessibility/Automation permissions when OmniPlan is called via AppleScript. Grant them in **System Settings → Privacy & Security → Automation**.

## Quick Start

### 1. Install

```bash
# Option A: One-line installer (recommended)
curl -fsSL https://raw.githubusercontent.com/cygnusyang/omniplan-mcp/main/install.sh | bash

# Option B: Manual clone
git clone https://github.com/cygnusyang/omniplan-mcp.git
cd omniplan-mcp
pip install -e .
```

### 2. Configure Claude Code

Add to your `~/.claude/settings.json`:

<details>
<summary><b>uv run (recommended)</b></summary>

```json
{
  "mcpServers": {
    "omniplan": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/Users/yourusername/.local/share/omniplan-mcp",
        "omniplan-mcp"
      ],
      "env": {}
    }
  }
}
```
</details>

<details>
<summary><b>pip install (after PyPI publish)</b></summary>

```json
{
  "mcpServers": {
    "omniplan": {
      "command": "uvx",
      "args": ["omniplan-mcp"],
      "env": {}
    }
  }
}
```
</details>

<details>
<summary><b>Direct Python</b></summary>

```json
{
  "mcpServers": {
    "omniplan": {
      "command": "/path/to/python3",
      "args": ["-m", "omniplan_mcp"],
      "env": {
        "PYTHONPATH": "/path/to/omniplan-mcp/src"
      }
    }
  }
}
```
</details>

### 3. Restart Claude Code

The MCP server will start automatically. You can now ask Claude about your project files!

## Usage Examples

### Read a project schedule

```
你：帮我读取 PLB1011 项目计划，看看有哪些阶段
Claude：调用 read_schedule → 显示完整任务树
```

### List milestones

```
你：列出所有里程碑节点
Claude：调用 list_milestones → 显示所有 ◇ 里程碑
```

### Search for tasks

```
你：搜索所有关于"机械臂"的任务
Claude：调用 search_tasks → 显示匹配的任务列表
```

### Project summary

```
你：这个项目的整体进度怎么样？
Claude：调用 schedule_summary → 显示阶段概览和进度统计
```

## Tools Reference

| Tool | Description | Parameters |
|------|-------------|------------|
| `read_schedule` | Full task hierarchy with dates and progress | `filepath` (required), `format`: tree/flat/json |
| `list_milestones` | All milestone tasks | `filepath` |
| `list_resources` | All human resources | `filepath` |
| `search_tasks` | Search tasks by keyword | `filepath`, `keyword` |
| `schedule_summary` | Phase overview and progress stats | `filepath` |

## How It Works

```
.mpp file ──→ OmniPlan (AppleScript direct read) ──→ pipe-delimited records ──→ Claude
                          ↑
.oplx file ───────────────┴─── direct XML parsing ──────┘
```

### For .oplx files
Direct XML parsing — fast, no external dependencies.

### For .mpp files
1. MCP server opens the `.mpp` file in OmniPlan via the macOS `open` command
2. Reads all project data (tasks, resources, dates, progress) directly from OmniPlan's in-memory object model via AppleScript
3. Parses the pipe-delimited output into structured records
4. Closes the document

> No temporary files are created — data is read directly from OmniPlan's in-memory model.

## Project Structure

```
omniplan-mcp/
├── install.sh                  # One-click installer
├── pyproject.toml              # Package metadata (PyPI-ready)
├── README.md                   # This file
├── LICENSE                     # MIT license
├── .gitignore
├── src/
│   └── omniplan_mcp/
│       ├── __init__.py         # Package version
│       ├── __main__.py         # CLI entry point
│       ├── server.py           # MCP server (tools & handlers)
│       └── parser.py           # .mpp (AppleScript) / .oplx (XML) parsing
└── tests/
    └── test_parser.py          # Unit tests
```

## Development

```bash
# Clone
git clone https://github.com/cygnusyang/omniplan-mcp.git
cd omniplan-mcp

# Install in editable mode
pip install -e .

# Run tests
python -m pytest tests/

# Run the server directly (stdio)
python -m omniplan_mcp
```

### Publishing to PyPI

Published automatically via GitHub Actions (Trusted Publisher) when a tag is pushed:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Manual build (for testing):

```bash
pip install build
python -m build
```

## Requirements

- **Python 3.10+**
- **macOS** (for OmniPlan AppleScript bridge)
- **OmniPlan** (only for `.mpp` files; optional for `.oplx`)

## Limitations

- `.mpp` parsing requires OmniPlan to be installed
- Only supports macOS (AppleScript dependency)
- Does not modify `.mpp` files — read-only

## License

MIT License — see [LICENSE](LICENSE) for details.

## Related

- [Model Context Protocol](https://modelcontextprotocol.io)
- [OmniPlan](https://www.omnigroup.com/omniplan/)
- [Claude Code MCP Servers](https://docs.anthropic.com/en/docs/claude-code/mcp-servers)
