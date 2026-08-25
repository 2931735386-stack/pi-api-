import json
import tempfile
import unittest
from pathlib import Path

from cache_compat import (
    CACHE_GUARD_PACKAGE_SOURCE,
    apply_provider_cache_compat,
    effective_cache_policy,
    install_cache_guard,
    is_official_openai_base_url,
    load_guard_config,
    normalize_cache_policy,
    register_guard_package,
    save_guard_config,
    set_provider_cache_policy,
)
from app import ConfigStore, merge_model_edits


class CacheCompatPolicyTests(unittest.TestCase):
    def test_official_openai_host_matching_rejects_lookalikes(self):
        self.assertTrue(is_official_openai_base_url("https://api.openai.com/v1"))
        self.assertFalse(is_official_openai_base_url("https://api.openai.com.evil.example/v1"))
        self.assertFalse(is_official_openai_base_url("https://proxy.example/v1/api.openai.com"))
        self.assertFalse(is_official_openai_base_url("not a url"))

    def test_auto_policy_is_fail_closed_for_third_party(self):
        self.assertEqual(effective_cache_policy("auto", "https://api.openai.com/v1"), "long")
        self.assertEqual(effective_cache_policy("auto", "https://proxy.example/v1"), "safe")
        self.assertEqual(normalize_cache_policy("unknown"), "auto")

    def test_provider_compat_tracks_long_retention_only(self):
        provider = {
            "baseUrl": "https://proxy.example/v1",
            "api": "openai-completions",
            "compat": {"supportsDeveloperRole": False},
        }
        self.assertEqual(apply_provider_cache_compat(provider, "auto"), "safe")
        self.assertFalse(provider["compat"]["supportsLongCacheRetention"])
        self.assertFalse(provider["compat"]["supportsDeveloperRole"])

        self.assertEqual(apply_provider_cache_compat(provider, "long"), "long")
        self.assertTrue(provider["compat"]["supportsLongCacheRetention"])

    def test_guard_config_round_trip_is_sanitized(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cache-compat-guard.json"
            config = {"version": 99, "defaultPolicy": "bad", "providers": {}, "models": {}}
            set_provider_cache_policy(config, "v4flash", "strict")
            config["providers"]["bad"] = "arbitrary"
            self.assertTrue(save_guard_config(path, config))
            loaded = load_guard_config(path)
            self.assertEqual(loaded["version"], 1)
            self.assertEqual(loaded["defaultPolicy"], "auto")
            self.assertEqual(loaded["providers"], {"v4flash": "strict"})

    def test_guard_package_is_registered_last(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = root / "settings.json"
            target = root / "managed" / "pi-api-switcher-cache-guard"
            settings.write_text(
                json.dumps({"packages": [CACHE_GUARD_PACKAGE_SOURCE, "npm:pi-cache-optimizer"]}),
                encoding="utf-8",
            )
            self.assertTrue(register_guard_package(settings, target))
            packages = json.loads(settings.read_text(encoding="utf-8"))["packages"]
            self.assertEqual(packages, ["npm:pi-cache-optimizer", CACHE_GUARD_PACKAGE_SOURCE])

    def test_guard_install_copies_bundle_and_initializes_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent = root / "agent"
            bundle = root / "bundle"
            source = bundle / "cache-compat-guard"
            source.mkdir(parents=True)
            (source / "index.ts").write_text(
                "// Managed by pi-api-switcher. test\nexport default function() {}\n",
                encoding="utf-8",
            )
            (source / "package.json").write_text(
                json.dumps({"pi": {"extensions": ["./index.ts"]}}),
                encoding="utf-8",
            )
            agent.mkdir()
            (agent / "settings.json").write_text(
                json.dumps({"packages": ["npm:pi-cache-optimizer"]}),
                encoding="utf-8",
            )

            status = install_cache_guard(agent, bundle)
            self.assertIn("已就绪", status)
            self.assertTrue((agent / "managed/pi-api-switcher-cache-guard/index.ts").exists())
            self.assertTrue((agent / "cache-compat-guard.json").exists())
            packages = json.loads((agent / "settings.json").read_text(encoding="utf-8"))["packages"]
            self.assertEqual(packages[-1], CACHE_GUARD_PACKAGE_SOURCE)


class ModelMergeTests(unittest.TestCase):
    def test_table_edits_preserve_advanced_fields(self):
        stored = [{
            "id": "model-a",
            "name": "Old",
            "reasoning": True,
            "input": ["text"],
            "contextWindow": 100,
            "maxTokens": 10,
            "compat": {"thinkingFormat": "deepseek"},
            "headers": {"x-test": "1"},
            "visionModel": "vision:model",
        }]
        edited = [{
            "id": "model-a",
            "name": "New",
            "reasoning": False,
            "input": ["text"],
            "contextWindow": 200,
            "maxTokens": 20,
        }]
        merged = merge_model_edits(stored, edited)[0]
        self.assertEqual(merged["name"], "New")
        self.assertEqual(merged["compat"], {"thinkingFormat": "deepseek"})
        self.assertEqual(merged["headers"], {"x-test": "1"})
        self.assertNotIn("thinkingLevelMap", merged)
        self.assertNotIn("visionModel", merged)

    def test_table_edits_preserve_provider_specific_off_mapping(self):
        stored = [{
            "id": "glm-5.2",
            "reasoning": True,
            "thinkingLevelMap": {
                "off": "none", "minimal": None, "low": "low", "high": "high"
            },
        }]
        edited = [{
            "id": "glm-5.2",
            "reasoning": True,
            "thinkingLevelMap": {
                "off": None, "minimal": "minimal", "low": "low", "high": "high"
            },
        }]
        merged = merge_model_edits(stored, edited)[0]
        self.assertEqual(merged["thinkingLevelMap"]["off"], "none")
        self.assertIsNone(merged["thinkingLevelMap"]["minimal"])

    def test_provider_rename_migrates_all_configuration_references(self):
        store = object.__new__(ConfigStore)
        store.models = {
            "providers": {
                "old-provider": {"models": [{"id": "text-model"}]},
                "other": {"models": [{"id": "other-model", "visionModel": "old-provider:text-model"}]},
            }
        }
        store.auth = {"old-provider": {"type": "api_key", "key": "secret"}}
        store.settings = {
            "defaultProvider": "old-provider",
            "defaultModel": "text-model",
            "enabledModels": ["text-model", "other-model"],
        }
        store.cache_guard = {
            "version": 1,
            "defaultPolicy": "auto",
            "providers": {"old-provider": "long"},
            "models": {"old-provider/text-model": "key"},
        }
        store.vision = {
            "version": 2,
            "defaults": {"mode": "auto", "candidates": ["old-provider/text-model"]},
            "routes": {
                "old-provider/text-model": {
                    "mode": "force", "candidates": ["old-provider/text-model"]
                },
                "other/other-model": {
                    "mode": "auto", "candidates": ["old-provider/text-model"]
                },
            },
        }

        self.assertTrue(store.rename_provider("old-provider", "new-provider"))
        self.assertNotIn("old-provider", store.models["providers"])
        self.assertIn("new-provider", store.models["providers"])
        self.assertEqual(store.auth["new-provider"]["key"], "secret")
        self.assertEqual(store.settings["defaultProvider"], "new-provider")
        self.assertEqual(store.cache_guard["providers"], {"new-provider": "long"})
        self.assertEqual(store.cache_guard["models"], {"new-provider/text-model": "key"})
        self.assertIn("new-provider/text-model", store.vision["routes"])
        self.assertNotIn("old-provider/text-model", store.vision["routes"])
        self.assertEqual(
            store.vision["routes"]["other/other-model"]["candidates"],
            ["new-provider/text-model"],
        )
        self.assertEqual(store.vision["defaults"]["candidates"], ["new-provider/text-model"])
        self.assertEqual(
            store.models["providers"]["other"]["models"][0]["visionModel"],
            "new-provider:text-model",
        )


if __name__ == "__main__":
    unittest.main()
