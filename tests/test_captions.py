import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from vidbrief.captions import CaptionError, CaptionLoginRequired, fetch_caption_lines


URL = "https://www.bilibili.com/video/BV1eZgt6YEP5"
TRACK = "https://aisubtitle.hdslb.com/example.json"
PAGES = [{"page": 1, "cid": 42}, {"page": 2, "cid": 43}]
SETTINGS = SimpleNamespace(cookies_file=None, cookies_from_browser=None)


def ok(data):
    return {"code": 0, "data": data}


class CaptionTests(unittest.TestCase):
    def setUp(self):
        factory = self.enterContext(patch("vidbrief.captions.YoutubeDL"))
        self.enterContext(patch("vidbrief.captions._yt_dlp_captions", return_value=[]))
        self.session = factory.return_value.__enter__.return_value

    def responses(self, *data):
        self.session.urlopen.side_effect = [io.BytesIO(json.dumps(item).encode()) for item in data]

    def test_only_one_preferred_track_and_every_cue(self):
        tracks = [{"lan": "zh-CN", "subtitle_url": ""},
                  {"lan": "en", "subtitle_url": TRACK + "?en"},
                  {"lan": "ai-zh", "subtitle_url": TRACK + "?ai"},
                  {"lan": "zh-Hans", "subtitle_url": TRACK.removeprefix("https:")}]
        self.responses(ok(PAGES), ok({"subtitle": {"subtitles": tracks}}),
                       {"body": [{"from": 5, "content": "结尾"}, {"from": 1, "content": "重复"},
                                 {"from": 2, "content": "重复"}]})
        self.assertEqual(fetch_caption_lines(URL, 2, SETTINGS), ["重复", "重复", "结尾"])
        urls = [urlsplit(call.args[0].url) for call in self.session.urlopen.call_args_list]
        self.assertEqual([u.path for u in urls], ["/x/player/pagelist", "/x/player/v2", "/example.json"])
        self.assertEqual(parse_qs(urls[1].query)["cid"], ["43"])
        self.assertEqual(urls[2].geturl(), TRACK)

    def test_empty_tracks_vs_login(self):
        for login in [False, True]:
            with self.subTest(login=login):
                self.session.reset_mock()
                self.responses(ok(PAGES), ok({"subtitle": {"subtitles": []}, "need_login_subtitle": login}))
                if login:
                    with self.assertRaises(CaptionLoginRequired):
                        fetch_caption_lines(URL, 1, SETTINGS)
                else:
                    self.assertEqual(fetch_caption_lines(URL, 1, SETTINGS), [])
                self.assertEqual(self.session.urlopen.call_count, 2)

    def test_invalid_page_or_api_error_stops_early(self):
        self.responses(ok(PAGES))
        with self.assertRaisesRegex(CaptionError, "第 3 P"):
            fetch_caption_lines(URL, 3, SETTINGS)
        self.responses({"code": -404})
        with self.assertRaisesRegex(CaptionError, "-404"):
            fetch_caption_lines(URL, 1, SETTINGS)

    def test_network_error_is_not_empty_subtitles(self):
        self.session.urlopen.side_effect = TimeoutError()
        with self.assertRaisesRegex(CaptionError, "字幕请求失败"):
            fetch_caption_lines(URL, 1, SETTINGS)

    def test_invalid_track_body_is_an_error(self):
        self.responses(ok(PAGES), ok({"subtitle": {"subtitles": [{"lan": "en", "subtitle_url": TRACK}]}}),
                       {"body": [{"from": 0, "wrong_key": "bad"}]})
        with self.assertRaisesRegex(CaptionError, "字幕行"):
            fetch_caption_lines(URL, 1, SETTINGS)
