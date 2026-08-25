import datetime
import json
import tempfile
import unittest
from pathlib import Path

import analytics


class VisionAnalyticsTests(unittest.TestCase):
    def setUp(self):
        analytics._RAW_RECORDS_CACHE.clear()

    def test_input_hook_usage_is_counted_and_cache_hit_is_not_doubled(self):
        now_ms = int(datetime.datetime.now().timestamp() * 1000)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            session = root / "session.jsonl"
            entries = [
                {
                    "type": "custom",
                    "customType": "vision-bridge-usage-v1",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "data": {
                        "timestamp": now_ms,
                        "activeProvider": "v4flash",
                        "activeModel": "deepseek-v4-flash",
                        "visionProvider": "gemini",
                        "visionModel": "gemini-3.7-flash",
                        "status": "success",
                        "source": "input",
                        "requested": True,
                        "includeInTotals": True,
                        "cached": False,
                        "latencyMs": 1200,
                        "imageBytes": 1000,
                        "imageCount": 1,
                        "usage": {
                            "input": 100,
                            "output": 20,
                            "cacheRead": 0,
                            "cacheWrite": 0,
                            "reasoning": 0,
                            "totalTokens": 120,
                        },
                    },
                },
                {
                    "type": "custom",
                    "customType": "vision-bridge-usage-v1",
                    "data": {
                        "timestamp": now_ms + 1,
                        "activeProvider": "v4flash",
                        "activeModel": "deepseek-v4-flash",
                        "visionProvider": "gemini",
                        "visionModel": "gemini-3.7-flash",
                        "status": "cache_hit",
                        "source": "input",
                        "requested": False,
                        "includeInTotals": False,
                        "cached": True,
                        "latencyMs": 0,
                        "imageBytes": 1000,
                        "imageCount": 1,
                        "usage": {},
                    },
                },
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "provider": "v4flash",
                        "model": "deepseek-v4-flash",
                        "timestamp": now_ms + 2,
                        "stopReason": "stop",
                        "usage": {
                            "input": 50,
                            "output": 10,
                            "cacheRead": 0,
                            "cacheWrite": 0,
                            "reasoning": 0,
                            "totalTokens": 60,
                        },
                    },
                },
            ]
            session.write_text(
                "\n".join(json.dumps(entry) for entry in entries) + "\n",
                encoding="utf-8",
            )

            data = analytics.parse_session_records(root, "day")
            self.assertEqual(data["total_calls"], 2)
            self.assertEqual(data["total_tokens"], 180)
            self.assertEqual(data["vision_calls"], 1)
            self.assertEqual(data["vision_success"], 1)
            self.assertEqual(data["vision_cache_hits"], 1)
            self.assertEqual(data["vision_avg_latency_ms"], 1200)
            self.assertIn("vision:gemini/gemini-3.7-flash", data["models"])
            self.assertEqual(
                data["models"]["vision:gemini/gemini-3.7-flash"]["total"],
                120,
            )


if __name__ == "__main__":
    unittest.main()
