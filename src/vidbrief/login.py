"""Log in to Bilibili with the official QR flow.

The command stores only the SESSDATA cookie in a per-user Netscape cookie
file.  It never prints the QR URL, qrcode key, cookie value, or login URL.
"""

from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import time
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


_PASSPORT = "https://passport.bilibili.com"
_GENERATE = _PASSPORT + "/x/passport-login/web/qrcode/generate"
_POLL = _PASSPORT + "/x/passport-login/web/qrcode/poll"
_SOURCE = "main-fe-header"
_TIMEOUT = 12
_SUCCESS = 0
_NOT_SCANNED = 86101
_SCANNED = 86090
_EXPIRED = 86038


class LoginError(RuntimeError):
    """A QR login operation failed without exposing login material."""


class LoginExpired(LoginError):
    pass


class LoginTimeout(LoginError):
    pass


def _request_json(url: str) -> dict[str, Any]:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "passport.bilibili.com":
        raise LoginError("登录请求地址无效。")
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Referer": "https://www.bilibili.com/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urlopen(request, timeout=_TIMEOUT) as response:
            value = json.load(response)
            set_cookie = response.headers.get_all("Set-Cookie") or []
    except (HTTPError, URLError, OSError, ValueError):
        raise LoginError("B 站登录请求失败，请稍后重试。") from None
    if not isinstance(value, dict):
        raise LoginError("B 站登录响应格式异常。")
    # The successful poll response commonly carries SESSDATA in Set-Cookie
    # instead of putting it in the callback URL.
    value["_set_cookie_headers"] = set_cookie
    return value


def generate_qr(request: Callable[[str], dict[str, Any]] = _request_json) -> tuple[str, str]:
    """Return the private QR URL and key without logging either value."""
    query = urlencode({"source": _SOURCE})
    response = request(f"{_GENERATE}?{query}")
    if response.get("code") != _SUCCESS or not isinstance(response.get("data"), dict):
        raise LoginError("B 站没有生成登录二维码。")
    data = response["data"]
    qr_url = data.get("url")
    qr_key = data.get("qrcode_key")
    if not isinstance(qr_url, str) or not isinstance(qr_key, str) or not qr_url or not qr_key:
        raise LoginError("B 站返回的二维码信息不完整。")
    qr_parts = urlsplit(qr_url)
    qr_host = qr_parts.hostname or ""
    if qr_parts.scheme != "https" or not (qr_host == "bilibili.com" or qr_host.endswith(".bilibili.com")):
        raise LoginError("B 站返回了无效的二维码地址。")
    return qr_url, qr_key


def _extract_sessdata(login_url: str) -> str:
    parts = urlsplit(login_url)
    host = parts.hostname or ""
    if parts.scheme != "https" or not (host == "bilibili.com" or host.endswith(".bilibili.com")):
        raise LoginError("B 站返回了无效的登录结果。")
    value = parse_qs(parts.query, keep_blank_values=False).get("SESSDATA", [""])[0]
    if not value or "\n" in value or "\r" in value or ";" in value:
        raise LoginError("B 站登录结果中没有有效的会话。")
    return value


def _extract_sessdata_from_headers(headers: object) -> str:
    if not isinstance(headers, list):
        return ""
    for raw in headers:
        if not isinstance(raw, str):
            continue
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except (TypeError, ValueError):
            continue
        morsel = cookie.get("SESSDATA")
        if morsel is not None and morsel.value and not any(
            char in morsel.value for char in "\r\n;\t"
        ):
            return morsel.value
    return ""


def poll_once(qr_key: str, request: Callable[[str], dict[str, Any]] = _request_json) -> tuple[str, str | None]:
    """Return (state, sessdata), where state is pending, scanned, or success."""
    url = f"{_POLL}?{urlencode({'qrcode_key': qr_key, 'source': _SOURCE})}"
    response = request(url)
    if response.get("code") not in (None, _SUCCESS):
        raise LoginError("B 站登录未完成，请稍后重试。")
    data = response.get("data")
    code = data.get("code") if isinstance(data, dict) else None
    if code == _SUCCESS and isinstance(data, dict):
        login_url = data.get("url")
        if isinstance(login_url, str):
            try:
                return "success", _extract_sessdata(login_url)
            except LoginError:
                pass
        sessdata = _extract_sessdata_from_headers(response.get("_set_cookie_headers"))
        if sessdata:
            return "success", sessdata
        raise LoginError("B 站登录结果中没有有效的会话。")
    if code == _NOT_SCANNED:
        return "pending", None
    if code == _SCANNED:
        return "scanned", None
    if code == _EXPIRED:
        raise LoginExpired("二维码已过期，请重新运行登录命令。")
    raise LoginError("B 站登录未完成，请稍后重试。")


def save_sessdata(value: str, path: Path | None = None) -> Path:
    """Atomically save one SESSDATA cookie in Netscape format."""
    if not value or any(char in value for char in "\r\n;\t"):
        raise LoginError("登录会话格式无效。")
    if path is None:
        try:
            from .settings import saved_session_path
        except ImportError:
            saved_session_path = None
        if saved_session_path is not None:
            path = saved_session_path()
        else:
            root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "BiliBrief"
            path = root / "bilibili.cookies.txt"
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\t" + value + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".bilibili.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path


def _qr_png(url: str) -> bytes:
    try:
        import segno
    except ImportError:
        raise LoginError("扫码登录需要安装可选依赖 segno。") from None
    output = io.BytesIO()
    segno.make(url, error="M").save(output, kind="png", scale=6, border=2)
    return output.getvalue()


def run_login(*, request: Callable[[str], dict[str, Any]] = _request_json, timeout: float = 180.0,
              interval: float = 2.0, show_window: bool = True) -> Path:
    qr_url, qr_key = generate_qr(request)
    window = label = image = None
    if show_window:
        try:
            import tkinter as tk
        except ImportError:
            raise LoginError("当前 Python 没有可用的桌面扫码窗口。") from None
        png = _qr_png(qr_url)
        window = tk.Tk()
        window.title("BiliBrief 登录")
        image = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        label = tk.Label(window, image=image, text="请用 B 站 App 扫码并确认", compound="top")
        label.pack(padx=18, pady=18)
        window.update()
    deadline = time.monotonic() + timeout
    state = "pending"
    try:
        while time.monotonic() < deadline:
            if window is not None:
                window.update()
            state, sessdata = poll_once(qr_key, request)
            if state == "success":
                return save_sessdata(sessdata or "")
            wait_until = time.monotonic() + interval
            while time.monotonic() < wait_until:
                if window is not None:
                    window.update()
                time.sleep(min(0.1, max(0.01, wait_until - time.monotonic())))
        raise LoginTimeout("二维码登录等待超时，请重新运行登录命令。")
    finally:
        if window is not None:
            window.destroy()


def main() -> None:
    try:
        path = run_login()
    except LoginError as exc:
        print(str(exc))
        return
    print("B 站登录状态已保存到本机。")
    del path


if __name__ == "__main__":
    main()
