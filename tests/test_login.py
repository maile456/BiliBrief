import tempfile
import unittest
from pathlib import Path

from vidbrief.login import (
    LoginError,
    LoginExpired,
    generate_qr,
    poll_once,
    save_sessdata,
)


class LoginTests(unittest.TestCase):
    def test_generate_and_poll_never_need_printing(self):
        generate = {"code": 0, "data": {"url": "https://passport.bilibili.com/h5/abc", "qrcode_key": "fixture-key"}}
        self.assertEqual(generate_qr(lambda _url: generate)[1], "fixture-key")
        pending = {"code": 0, "data": {"code": 86101, "message": "未扫码"}}
        scanned = {"code": 0, "data": {"code": 86090, "message": "已扫码"}}
        success = {"code": 0, "data": {"code": 0, "url": "https://passport.bilibili.com/h5/ok?SESSDATA=fixture-token"}}
        self.assertEqual(poll_once("key", lambda _url: pending), ("pending", None))
        self.assertEqual(poll_once("key", lambda _url: scanned), ("scanned", None))
        self.assertEqual(poll_once("key", lambda _url: success), ("success", "fixture-token"))

        header_success = {
            "code": 0,
            "data": {"code": 0, "url": "https://passport.bilibili.com/h5-app/passport/login/scan"},
            "_set_cookie_headers": ["SESSDATA=header-token; Domain=.bilibili.com; Path=/"],
        }
        self.assertEqual(poll_once("key", lambda _url: header_success), ("success", "header-token"))

    def test_expired_and_bad_qr_are_errors(self):
        expired = {"code": 0, "data": {"code": 86038, "message": "已过期"}}
        with self.assertRaises(LoginExpired):
            poll_once("key", lambda _url: expired)
        bad = {"code": 0, "data": {"url": "http://evil.example/qr", "qrcode_key": "key"}}
        with self.assertRaises(LoginError):
            generate_qr(lambda _url: bad)

    def test_save_is_netscape_and_replaces_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookies.txt"
            self.assertEqual(save_sessdata("fixture-token", path), path)
            text = path.read_text(encoding="utf-8")
            self.assertIn(".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tfixture-token", text)
            with self.assertRaises(LoginError):
                save_sessdata("bad;token", path)


if __name__ == "__main__":
    unittest.main()
