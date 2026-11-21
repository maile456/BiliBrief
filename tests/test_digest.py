import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from vidbrief.llm import make_digest
from vidbrief.models import TranscriptSegment
from vidbrief.settings import Settings


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.data = [TranscriptSegment(i * 60, i * 60 + 15, f"第{i}节，因为成本变化，所以需要对比价格。", "subtitle") for i in range(200)]
        self.url = "https://www.bilibili.com/video/BV1x341177NN?p=2&extra=dontcopy"

    def digest(self, warnings, **options):
        return make_digest("价格", self.data, "subtitle", [], warnings,
                           Settings(cache_dir=Path("."), **options), "fast", url=self.url)

    def test_extractive_bound_and_part(self):
        result = self.digest([])
        self.assertLess(len(result), 1500)
        self.assertIn("摘录", result)
        self.assertIn("p=2&t=", result)
        self.assertNotIn("dontcopy", result)
        self.assertRegex(result, r"第1[6-9]\d节")

    def test_full_duration_model_request(self):
        def respond(request, **kwargs):
            content = json.loads(request.data)["messages"][1]["content"]
            evidence = json.loads(content)["evidence"]
            self.assertLessEqual(len(evidence), 48)
            self.assertLessEqual(len(content), 18000)
            self.assertGreater(int(evidence[-1]["text"].split("节")[0][1:]), 180)
            result = {"overview": "价格会随成本变化", "overview_id": 0,
                      "points": [{"text": "先比较成本", "id": 1}]}
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode())

        with patch("urllib.request.urlopen", side_effect=respond):
            result = self.digest([], llm_base_url="http://test.invalid/v1")
        self.assertIn("模型归纳", result)
        self.assertIn("p=2&t=", result)

    def test_invalid_response_falls_back(self):
        for body in (b"oops", b'{"choices":[]}', b'{"choices":[{"message":{"content":"{}"}}]}'):
            with self.subTest(body=body):
                warnings = []
                with patch("urllib.request.urlopen", return_value=io.BytesIO(body)):
                    result = self.digest(warnings, llm_base_url="http://test.invalid/v1")
                self.assertIn("摘录", result)
                self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()

