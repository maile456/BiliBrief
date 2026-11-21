"""Normalize ordinary Bilibili share links to a video and a single part."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

_ID = r"(BV[0-9A-Za-z]{10}|av[0-9]+)"
_HOSTS = {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize(value: str, page: int | None = None) -> tuple[str, int]:
    value = value.strip()
    if re.fullmatch(_ID, value):
        value = f"https://www.bilibili.com/video/{value}"
    parts = urlsplit(value)
    if (parts.scheme not in {"https", "http"} or parts.username is not None
            or parts.password is not None or parts.port not in {None, 80, 443}):
        raise ValueError("请输入 B 站视频链接、b23.tv 短链或 BV 号。")
    if parts.hostname == "b23.tv":
        if not re.fullmatch(r"/[a-zA-Z0-9]+/?", parts.path):
            raise ValueError("无效的 B 站短链。")
        short = "https://b23.tv" + parts.path
        try:
            with build_opener(_NoRedirect).open(Request(short, method="GET"), timeout=10):
                raise ValueError("短链没有指向 B 站视频。")
        except HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                raise ValueError(f"短链解析失败，HTTP {exc.code}") from None
            parts = urlsplit(urljoin(short, exc.headers.get("Location", "")))
        except (URLError, OSError) as exc:
            raise ValueError("短链暂时不可用，请使用 BV 号或长链接。") from exc
    match = re.fullmatch(r"/video/" + _ID + r"/?", parts.path)
    if not match or parts.hostname not in _HOSTS:
        raise ValueError("仅支持 B 站普通投稿的视频页和 BV/av 号。")
    try:
        chosen = int(parse_qs(parts.query).get("p", ["1"])[-1]) if page is None else page
    except ValueError:
        raise ValueError("分 P 编号须为正整数。") from None
    if not 1 <= chosen <= 10000:
        raise ValueError("分 P 编号须在 1 至 10000 之间。")
    return "https://www.bilibili.com/video/" + match[1], chosen


def list_parts(bvid: str) -> list[dict]:
    if not re.fullmatch(r"BV[A-Za-z0-9]{10}", bvid):
        return []
    req = Request(f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}",
                  headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"})
    try:
        with urlopen(req, timeout=8) as response:
            rows = json.load(response).get("data") or []
        return [{"page": r["page"], "cid": r["cid"], "title": r.get("part", ""),
                 "duration": r.get("duration")} for r in rows]
    except (ValueError, KeyError, TypeError, OSError):
        return []
