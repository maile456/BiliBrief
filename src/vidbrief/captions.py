"""Read one Bilibili subtitle track through the site's player APIs."""

import json
import re
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

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


def _subtitle_lines(raw: object, ext: str) -> list[str]:
    """Convert one yt-dlp subtitle payload to ordered plain-text lines."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", errors="replace")
    if not isinstance(raw, str):
        raise CaptionError("B 站返回的字幕正文格式异常。")
    if ext.lower() in {"json", "json3"}:
        try:
            value = json.loads(raw)
            body = value.get("body") if isinstance(value, dict) else None
            if not isinstance(body, list):
                raise ValueError
            cues = sorted(body, key=lambda cue: float(cue["from"]))
            return [str(cue["content"]).strip() for cue in cues if str(cue.get("content", "")).strip()]
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise CaptionError("B 站返回的字幕正文格式异常。") from None

    lines: list[str] = []
    rows = raw.lstrip("\ufeff").splitlines()
    for index, row in enumerate(rows):
        if "-->" not in row:
            continue
        index += 1
        cue: list[str] = []
        while index < len(rows) and rows[index].strip():
            value = re.sub(r"<[^>]+>", "", rows[index]).strip()
            if value:
                cue.append(value)
            index += 1
        if cue:
            lines.append(" ".join(cue))
    if not lines:
        raise CaptionError("B 站返回的字幕正文格式异常。")
    return lines


def _yt_dlp_captions(url: str, page: int, settings: Settings) -> list[str]:
    """Let yt-dlp's Bilibili extractor handle the current WBI subtitle API."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if page > 1:
        query["p"] = str(page)
    requested = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    options = {
        "quiet": True,
        "no_warnings": True,
        "logtostderr": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "socket_timeout": 15,
    }
    if settings.cookies_file:
        options["cookiefile"] = str(settings.cookies_file)
    if settings.cookies_from_browser:
        options["cookiesfrombrowser"] = tuple(settings.cookies_from_browser.split(":"))
    try:
        with YoutubeDL(options) as session:
            info = session.extract_info(requested, download=False)
    except Exception as exc:
        raise CaptionError(f"B 站字幕请求失败（{type(exc).__name__}）。") from None
    expected_id = parts.path.rstrip("/").rsplit("/", 1)[-1]
    actual_id = str(info.get("id") or "").split("_p", 1)[0]
    if actual_id != expected_id:
        raise CaptionError("B 站返回的视频身份与请求不一致。")
    candidates: list[tuple[tuple[bool, bool, bool, str], str, dict]] = []
    for group, automatic in ((info.get("subtitles") or {}, False), (info.get("automatic_captions") or {}, True)):
        if not isinstance(group, dict):
            continue
        for language, formats in group.items():
            if not isinstance(language, str) or not isinstance(formats, list):
                continue
            normalized = language.lower().replace("_", "-").removeprefix("ai-")
            chinese = normalized.split("-")[0] in {"zh", "cmn", "yue"}
            preferred = normalized in {"zh", "zh-hans", "zh-cn"}
            for track in formats:
                if isinstance(track, dict) and track.get("data"):
                    ext = str(track.get("ext", "srt"))
                    priority = (not chinese, automatic, not preferred, normalized)
                    candidates.append((priority, ext, track))
    if not candidates:
        return []
    _, ext, track = min(candidates, key=lambda item: item[0])
    return _subtitle_lines(track["data"], ext)


def fetch_caption_lines(url: str, page: int, settings: Settings) -> list[str]:
    # yt-dlp's Bilibili extractor handles the current WBI-signed subtitle API.
    # Use it first so an older player endpoint cannot return a stale track.
    signed_lines = _yt_dlp_captions(url, page, settings)
    if signed_lines:
        return signed_lines

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
            return _yt_dlp_captions(url, page, settings)
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
