"""Live MCP protocol smoke — proves the server actually speaks MCP.

Spawns the packaged server (`python -m accountable_surface.server`) as an MCP
stdio server, connects a real client, runs the handshake, lists tools, and calls
them over the wire. No internet.

Run: python examples/smoke_mcp.py   (mcp must be importable in this process; the
subprocess gets the package + sibling repos via PYTHONPATH set below).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
CM = "C:/dev/public/coherence-membrane/src"
PS = "C:/dev/public/proof-surface/src"


async def main() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), CM, PS])
    params = StdioServerParameters(
        command="python",
        args=["-m", "accountable_surface.server"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print("tools:", names)
            assert {"perceive", "propose", "session_journal", "interocept"} <= set(names), names

            res = await session.call_tool("propose", {"action_kind": "delete", "target": "x"})
            text = res.content[0].text if res.content else "{}"
            print("propose(delete, no operator grant) ->", text)

            jr = await session.call_tool("session_journal", {})
            jtext = jr.content[0].text if jr.content else "[]"
            print("session_journal ->", jtext)

    print("MCP ROUND-TRIP OK")


if __name__ == "__main__":
    asyncio.run(main())
