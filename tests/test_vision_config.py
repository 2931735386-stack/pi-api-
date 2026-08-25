import tempfile
import unittest
from pathlib import Path

from vision_config import (
    candidates_to_legacy,
    default_vision_config,
    effective_vision_route,
    load_vision_config,
    migrate_legacy_vision_routes,
    normalize_candidates,
    normalize_vision_mode,
    save_vision_config,
    set_vision_route,
)


class VisionConfigTests(unittest.TestCase):
    def test_candidate_normalization_and_legacy_round_trip(self):
        candidates = normalize_candidates(
            "gemini:gemini-3.7-flash|glm/glm-5.2|gemini:gemini-3.7-flash|bad"
        )
        self.assertEqual(candidates, ["gemini/gemini-3.7-flash", "glm/glm-5.2"])
        self.assertEqual(
            candidates_to_legacy(candidates),
            "gemini:gemini-3.7-flash|glm:glm-5.2",
        )
        self.assertEqual(normalize_vision_mode("invalid"), "auto")

    def test_legacy_routes_migrate_without_overriding_v2(self):
        models = {
            "providers": {
                "v4flash": {
                    "models": [{
                        "id": "deepseek-v4-flash",
                        "visionModel": "gemini:gemini-3.7-flash|glm:glm-5.2",
                        "visionMode": "force",
                    }]
                }
            }
        }
        config = default_vision_config()
        self.assertEqual(migrate_legacy_vision_routes(models, config), 1)
        route = config["routes"]["v4flash/deepseek-v4-flash"]
        self.assertEqual(route["mode"], "force")
        self.assertEqual(
            route["candidates"],
            ["gemini/gemini-3.7-flash", "glm/glm-5.2"],
        )
        self.assertEqual(migrate_legacy_vision_routes(models, config), 0)

    def test_effective_route_merges_limits_and_route(self):
        config = default_vision_config()
        config["defaults"]["timeoutMs"] = 45_000
        set_vision_route(
            config,
            "v4flash",
            "deepseek-v4-flash",
            "auto",
            ["gemini/gemini-3.7-flash", "glm/glm-5.2"],
        )
        route = effective_vision_route(
            config,
            "v4flash",
            {"id": "deepseek-v4-flash", "input": ["text"]},
        )
        self.assertEqual(route["timeoutMs"], 45_000)
        self.assertEqual(route["mode"], "auto")
        self.assertEqual(len(route["candidates"]), 2)
        config["routes"]["v4flash/deepseek-v4-flash"]["maxImages"] = 2
        set_vision_route(
            config,
            "v4flash",
            "deepseek-v4-flash",
            "force",
            ["gemini/gemini-3.7-flash"],
        )
        self.assertEqual(config["routes"]["v4flash/deepseek-v4-flash"]["maxImages"], 2)

    def test_config_round_trip_clamps_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "vision-bridge.json"
            config = default_vision_config()
            config["defaults"]["maxImages"] = 999
            config["defaults"]["timeoutMs"] = 1
            self.assertTrue(save_vision_config(path, config))
            loaded = load_vision_config(path)
            self.assertEqual(loaded["version"], 2)
            self.assertEqual(loaded["defaults"]["maxImages"], 16)
            self.assertEqual(loaded["defaults"]["timeoutMs"], 5_000)


if __name__ == "__main__":
    unittest.main()
