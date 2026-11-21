from mcp.server.fastmcp import FastMCP

from .captions import fetch_caption_lines
from .links import normalize
from .settings import Settings

mcp = FastMCP("BiliBrief")


@mcp.tool(structured_output=False)
def bili_subtitles(url: str) -> str:
    """读取 B 站链接或 BV/av 号的完整平台字幕，以纯文本返回。分 P 可用 ?p=2 指定。"""
    video_url, page = normalize(url)
    lines = fetch_caption_lines(video_url, page, Settings.from_env())
    return "\n".join(lines) if lines else "当前视频没有可用的平台字幕。"


def main() -> None:
    mcp.run()
