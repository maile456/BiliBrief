import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vidbrief.settings import Settings
from vidbrief.subtitles import fetch_transcript


def caption(text):
    return {"ext": "srt", "data": f"1\n00:00:01,000 --> 00:00:03,000\n{text}\n\n"}


class SubtitleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.settings = Settings(cache_dir=self.root)

    def fetch(self, info=None):
        return fetch_transcript("https://www.bilibili.com/video/BVtest", self.root, self.settings, info)

    def test_chinese_order_and_inline_reuse(self):
        tracks = {"en": [caption("English")], "ai-zh": [caption("AI")],
                  "zh-Hant": [caption("人工")], "danmaku": [{"ext": "xml", "url": "ignored"}]}
        with patch("yt_dlp.YoutubeDL") as factory:
            segments, source, warnings = self.fetch({"subtitles": tracks})
            self.assertEqual((segments[0].text, source, warnings), ("人工", "subtitle", []))
            self.assertEqual(len(list(self.root.iterdir())), 1)
            del tracks["zh-Hant"]
            segments, source, warnings = self.fetch({"subtitles": tracks})
            self.assertEqual((segments[0].text, source, warnings), ("AI", "ai_subtitle", []))
            factory.assert_not_called()

    def test_no_track_no_lookup_and_no_danmaku_request(self):
        with patch("yt_dlp.YoutubeDL") as factory:
            for info in ({}, {"subtitles": {"danmaku": [{"url": "never", "ext": "xml"}]}}):
                segments, source, warnings = self.fetch(info)
                self.assertEqual((segments, source), ([], "none"))
                self.assertTrue(warnings)
            factory.assert_not_called()

    def test_url_only_reads_one_track_then_uses_cache(self):
        tracks = {"zh": [{"ext": "vtt", "url": "https://cache.example/zh"}],
                  "en": [{"ext": "vtt", "url": "https://cache.example/en"}]}
        with patch("yt_dlp.YoutubeDL") as factory:
            ydl = factory.return_value.__enter__.return_value
            ydl.urlopen.return_value.__enter__.return_value.read.return_value = (
                b"WEBVTT\n\n00:01.000 --> 00:03.000\nHello\n\n")
            for _ in range(2):
                segments, source, warnings = self.fetch({"subtitles": tracks})
                self.assertEqual((segments[0].text, source, warnings), ("Hello", "subtitle", []))
            self.assertEqual(ydl.urlopen.call_count, 1)
            self.assertEqual(ydl.urlopen.call_args.args[0].url, "https://cache.example/zh")
            ydl.extract_info.assert_not_called()
            ydl.download.assert_not_called()

    def test_metadata_lookup_enables_tracks_without_listing_or_stdout(self):
        with patch("yt_dlp.YoutubeDL") as factory:
            ydl = factory.return_value.__enter__.return_value
            ydl.extract_info.return_value = {"automatic_captions": {"en": [caption("hello")]}}
            with contextlib.redirect_stdout(io.StringIO()) as output:
                segments, source, warnings = self.fetch()
            self.assertEqual(output.getvalue(), "")
            self.assertEqual((segments[0].text, source, warnings), ("hello", "ai_subtitle", []))
            opts = factory.call_args.args[0]
            self.assertTrue(opts["writesubtitles"] and opts["writeautomaticsub"])
            self.assertTrue(opts["logtostderr"] and opts["quiet"])
            self.assertFalse(opts.get("listsubtitles"))
            self.assertFalse(ydl.extract_info.call_args.kwargs["download"])
            ydl.download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
