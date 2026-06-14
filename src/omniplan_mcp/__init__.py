#!/usr/bin/env python3
"""
OmniPlan MCP Server

A Model Context Protocol (MCP) server that reads and analyzes project schedule files
in OmniPlan (.oplx) and Microsoft Project (.mpp) formats.

## Features

- Read .mpp files via OmniPlan AppleScript bridge
- Read .oplx files via direct XML parsing
- List milestones, resources, tasks
- Search tasks by keyword
- Project schedule summary with progress stats

## Usage (as CLI)

    pip install -e .
    omniplan-mcp

## Usage (as MCP server)

Add to Claude Code settings.json:

    "mcpServers": {
        "omniplan": {
            "command": "uv",
            "args": ["run", "--directory", "/path/to/omniplan-mcp", "omniplan-mcp"],
            "env": {}
        }
    }
"""

__version__ = "0.4.1"
