"""Read one Bilibili subtitle track through the site's player APIs."""

import json
from urllib.parse import urlencode, urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError, RequestError

from .settings import Settings


class CaptionError(RuntimeError):
    pass


class CaptionLoginRequired(CaptionError):
    pass


def _json(session, url, referer):
    try:
        with session.urlopen(Request(url, headers={"Referer": referer})) as response:
            return json.load(response)
    except HTTPError as exc:
        raise CaptionError(f"B 站字幕请求失败（HTTP {exc.status}）。") from None
    except (RequestError, OSError, ValueError) as exc:
        raise CaptionError(f"B 站字幕请求失败（{type(exc).__name__}）。") from None


def _api(session, path, params, referer):
    data = _json(session, "https://api.bilibili.com" + path + "?" + urlencode(params), referer)
    if not isinstance(data, dict) or "code" not in data:
        raise CaptionError("B 站接口响应格式异常。")
    if data["code"] == -101:
        raise CaptionLoginRequired("B 站提示读取字幕需要登录。")
    if data["code"] != 0:
        raise CaptionError(f"B 站接口返回错误（代码 {data['code']}）。")
    return data.get("data")


def _priority(track):
    language = str(track.get("lan", "")).lower().replace("_", "-")
    locale = language.removeprefix("ai-")
    chinese = locale.split("-")[0] in {"zh", "cmn", "yue"}
    automatic = language.startswith("ai-") or track.get("ai_status") == 1 or track.get("type") == 1
    return not chinese, automatic, locale not in {"zh", "zh-hans", "zh-cn"}


def _track_url(track):
    if not isinstance(track, dict) or not isinstance(track.get("subtitle_url"), str):
        raise CaptionError("B 站字幕轨缺少下载地址。")
    url = track["subtitle_url"]
    if url.startswith("//"):
        url = "https:" + url
    parts = urlsplit(url)
    host = parts.hostname or ""
    domains = ("bilibili.com", "hdslb.com", "bilivideo.com", "bilivideo.cn")
    if (parts.scheme != "https" or parts.username is not None or parts.password is not None
            or not any(host == domain or host.endswith("." + domain) for domain in domains)):
        raise CaptionError("B 站返回了不支持的字幕地址。")
    return url


def fetch_caption_lines(url: str, page: int, settings: Settings) -> list[str]:
    video_id = urlsplit(url).path.rsplit("/", 1)[-1]
    video = {"aid": video_id[2:]} if video_id.startswith("av") else {"bvid": video_id}
    options = {"quiet": True, "no_warnings": True, "logtostderr": True, "socket_timeout": 12}
    if settings.cookies_file:
        options["cookiefile"] = str(settings.cookies_file)
    if settings.cookies_from_browser:
        options["cookiesfrombrowser"] = tuple(settings.cookies_from_browser.split(":"))

    with YoutubeDL(options, auto_init=False) as session:
        pages = _api(session, "/x/player/pagelist", video, url)
        if not isinstance(pages, list) or not pages or not all(isinstance(p, dict) for p in pages):
            raise CaptionError("B 站未返回有效的视频分 P 信息。")
        part = next((p for p in pages if p.get("page") == page), None)
        if part is None:
            raise CaptionError(f"视频中没有第 {page} P。")
        if not isinstance(part.get("cid"), int):
            raise CaptionError("B 站未返回此分 P 的视频标识。")

        player = _api(session, "/x/player/v2", {**video, "cid": part["cid"]}, url)
        if not isinstance(player, dict):
            raise CaptionError("B 站未返回播放器信息。")
        subtitles = player.get("subtitle")
        tracks = subtitles.get("subtitles") if isinstance(subtitles, dict) else None
        if not isinstance(tracks, list) or not all(isinstance(t, dict) for t in tracks):
            raise CaptionError("B 站返回的字幕列表格式异常。")
        available = [t for t in tracks if t.get("subtitle_url")]
        if not available and player.get("need_login_subtitle"):
            raise CaptionLoginRequired("B 站提示读取该视频的字幕需要登录。")
        if not tracks:
            return []
        if not available:
            raise CaptionError("B 站字幕轨缺少下载地址。")
        track = min(available, key=_priority)
        caption = _json(session, _track_url(track), url)

    body = caption.get("body") if isinstance(caption, dict) else None
    if not isinstance(body, list):
        raise CaptionError("B 站返回的字幕正文格式异常。")
    try:
        ordered = sorted(body, key=lambda cue: float(cue["from"]))
        return [text for cue in ordered if (text := cue["content"].strip())]
    except (KeyError, TypeError, AttributeError, ValueError):
        raise CaptionError("B 站返回的字幕行格式异常。") from None
