"""Run with project Python. Pass a BV id to also check ASR/captions, frames and search."""
import argparse
import asyncio
import base64
import json
import os
import sys
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify(video):
    network_env = {key: os.environ[key] for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                   "NO_PROXY", "HF_HOME", "SYSTEMROOT", "TMP", "PYTHONUTF8") if key in os.environ}
    params = StdioServerParameters(command=sys.executable, args=["-m", "bilibrief"], env=network_env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(minutes=15)) as session:
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "BiliBrief"
            names = sorted(t.name for t in (await session.list_tools()).tools)
            assert names == ["bili_digest", "bili_resolve", "bili_search", "bili_window"]
            print("stdio OK:", ", ".join(names), flush=True)

            async def call(tool, **args):
                res = await session.call_tool(tool, args)
                assert not res.isError, res.content[0].text
                return json.loads(res.content[0].text), res.content[1:]

            bad, _ = await call("bili_resolve", url="example.invalid")
            assert bad["status"] == "error"
            if video is None:
                return
            meta, _ = await call("bili_resolve", url=video)
            assert meta["status"] == "ok", meta
            print("video:", meta["video_id"], meta["title"], meta["duration"], flush=True)
            card, _ = await call("bili_digest", url=video, visual="never")
            assert card["status"] == "ok" and card["evidence"], card.get("warnings")
            print("digest:", card["data_source"], card["segment_count"], card["artifact_dir"], flush=True)
            excerpt = card["evidence"][0]
            hits, _ = await call("bili_search", url=video, query=excerpt["text"][:3])
            assert hits["matches"]
            t = min(int(excerpt["t"]), max(0, meta["duration"] - 4))
            window, images = await call("bili_window", url=video, start=t, end=t + 4, interval=2)
            assert len(images) == len(window["frames"]) and len(images) > 0, window["warnings"]
            assert all(i.type == "image" and base64.b64decode(i.data).startswith(b"\xff\xd8") for i in images)
            print("search hits:", len(hits["matches"]), "window JPEGs:", len(images), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video", nargs="?")
    asyncio.run(verify(parser.parse_args().video))
