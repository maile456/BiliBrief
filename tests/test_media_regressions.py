import contextlib
import importlib.util
import io
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from yt_dlp import YoutubeDL

from vidbrief.media import _VIDEO_FORMAT, _yt_dlp_options, extract_frames
from vidbrief.settings import Settings


class MediaTests(unittest.TestCase):
    def test_dash_video_only_format(self):
        output = io.StringIO()
        settings = Settings(cache_dir=Path("."))
        with contextlib.redirect_stdout(output):
            with YoutubeDL({**_yt_dlp_options(settings), "format": _VIDEO_FORMAT}) as downloader:
                info = downloader.process_ie_result({
                    "id": "sample", "title": "sample",
                    "formats": [
                        {"url": "https://example.org/a.m4a", "format_id": "a", "vcodec": "none", "acodec": "aac"},
                        {"url": "https://example.org/v.mp4", "format_id": "v", "height": 720, "vcodec": "avc1", "acodec": "none"},
                    ],
                }, download=False)
        self.assertEqual(info["format_id"], "v")
        self.assertEqual(output.getvalue(), "")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_frame_source_timestamps_and_persistence(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            sample = root / "sample.mp4"
            subprocess.run([
                "ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
                "testsrc2=d=4:r=3:s=160x120", "-output_ts_offset", "5", "-c:v", "mpeg4", str(sample),
            ], check=True)
            frames, warnings = extract_frames(sample, root, start=.21, end=3.55, interval=1)
            self.assertEqual(warnings, [])
            self.assertEqual([round(f.timestamp, 3) for f in frames], [.333, 1.333, 2.333, 3.333])
            original = Path(frames[0].path).read_bytes()
            later, warnings = extract_frames(sample, root, start=1.4, end=3.9, interval=2)
            self.assertEqual(warnings, [])
            self.assertEqual([round(f.timestamp, 3) for f in later], [1.667, 3.667])
            self.assertEqual(Path(frames[0].path).read_bytes(), original)
            self.assertTrue(original.startswith(bytes.fromhex("ffd8")))
            self.assertEqual(extract_frames(sample, root, start=.21, end=3.55, interval=1)[0], frames)
            self.assertEqual(extract_frames(sample, root, start=10, end=12), ([], ["no video frames in the requested range"]))

    @unittest.skipUnless(importlib.util.find_spec("faster_whisper"), "requires the ASR extra")
    def test_whisper_audio_decoder(self):
        from faster_whisper.audio import decode_audio

        with tempfile.TemporaryDirectory() as work:
            sample = Path(work) / "silence.wav"
            with wave.open(str(sample), "wb") as stream:
                stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                stream.writeframes(bytes(32000))
            self.assertEqual(len(decode_audio(str(sample))), 16000)
