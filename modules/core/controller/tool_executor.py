from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession

async def execute_tool(server, tool: str, arguments: dict):
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            return result
