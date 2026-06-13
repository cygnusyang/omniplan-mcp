"""
Entry point for the omniplan-mcp server.

Run directly:
    python -m omniplan_mcp
"""

import asyncio

import mcp.server.stdio
from mcp.server import NotificationOptions
from mcp.server.models import InitializationOptions

from . import __version__
from .server import server


def main():
    """Run the MCP server over stdio transport."""
    asyncio.run(_run())


async def _run():
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
    main()
