#!/usr/bin/env python3
"""Entry point for omniplan-mcp.

Usage:
    python -m omniplan_mcp serve       # Start MCP server (stdio mode)
    python -m omniplan_mcp read <file> # Read a schedule file
    python -m omniplan_mcp --help      # Show all commands
"""

from .cli import main

if __name__ == "__main__":
    main()
