"""Check the stdio interface offline. Pass a video link to also test live access."""

import argparse
import asyncio
import os
import sys
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify(video: str | None) -> None:
    keys = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SYSTEMROOT",
            "TMP", "PYTHONUTF8", "VIDBRIEF_COOKIES_FILE", "VIDBRIEF_COOKIES_FROM_BROWSER")
    env = {key: os.environ[key] for key in keys if key in os.environ}
    env["PYTHONUTF8"] = "1"
    params = StdioServerParameters(command=sys.executable, args=["-m", "bilibrief"], env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(minutes=1)) as session:
            result = await session.initialize()
            assert result.serverInfo.name == "BiliBrief"
            tools = (await session.list_tools()).tools
            assert [tool.name for tool in tools] == ["bili_subtitles"]
            schema = tools[0].inputSchema
            assert schema["required"] == ["url"]
            assert set(schema["properties"]) == {"url"}
            assert schema["properties"]["url"]["type"] == "string"

            bad = await session.call_tool("bili_subtitles", {"url": "example.invalid"})
            assert bad.isError
            print("stdio OK: bili_subtitles(url)", flush=True)
            if video is None:
                return

            response = await session.call_tool("bili_subtitles", {"url": video})
            if response.isError:
                message = " ".join(item.text for item in response.content if item.type == "text")
                if "需要登录" in message:
                    print("Video subtitle access requires a Bilibili login", flush=True)
                    return
                raise AssertionError(response.content)
            assert len(response.content) == 1 and response.content[0].type == "text"
            assert response.structuredContent is None
            text = response.content[0].text
            assert text.strip()
            print(f"Received one text block ({len(text)} characters)", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video", nargs="?")
    asyncio.run(verify(parser.parse_args().video))
