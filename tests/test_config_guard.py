# -*- coding: utf-8 -*-
"""ConfigStore 覆盖式保存防护测试：
主配置文件（models/auth/settings.json）在磁盘上损坏时，save() 必须拒绝写入，
避免内存中的空数据把用户仅存的配置抹掉。
"""

import json

import pytest

import config_store


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """把配置路径指到临时目录，隔离真实 ~/.pi/agent。"""
    monkeypatch.setattr(config_store, "AGENT_DIR", tmp_path)
    monkeypatch.setattr(config_store, "MODELS_PATH", tmp_path / "models.json")
    monkeypatch.setattr(config_store, "AUTH_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(config_store, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(config_store, "CACHE_GUARD_CONFIG_PATH", tmp_path / "cache-compat-guard.json")
    monkeypatch.setattr(config_store, "VISION_CONFIG_PATH", tmp_path / "vision-bridge.json")
    monkeypatch.setattr(config_store, "SNAPSHOTS_DIR", tmp_path / "backups")
    yield tmp_path


def _write(path, text):
    path.write_text(text, encoding="utf-8")


def test_read_json_tracks_corruption(tmp_path):
    p = tmp_path / "broken.json"
    _write(p, "{not valid json")
    assert config_store.read_json(p) == {}
    assert p in config_store._CORRUPT_JSON_FILES


def test_save_blocked_when_models_json_corrupt(isolated_config):
    # 磁盘上的 models.json 损坏；内存中是解析失败后的空数据
    models_p = isolated_config / "models.json"
    _write(models_p, '{"providers": {"a": {"baseUrl": "https://x"}}')  # 缺右括号
    store = config_store.ConfigStore()
    assert store.providers() == {}  # 解析失败 → 空

    store.add_provider("new", "https://example.com", "sk-test", "m1", "M1", False)
    assert not store.save()  # 必须拒绝覆盖式保存
    assert "models.json" in store.last_save_error
    # 磁盘上的原损坏文件保持原样，未被空数据覆盖
    assert models_p.read_text(encoding="utf-8") == '{"providers": {"a": {"baseUrl": "https://x"}}'


def test_save_allowed_after_external_repair(isolated_config):
    models_p = isolated_config / "models.json"
    _write(models_p, "corrupted")
    store = config_store.ConfigStore()
    assert not store.save()

    # 用户在磁盘上修复了文件（例如从快照恢复）
    good = {"providers": {"a": {"baseUrl": "https://x", "models": []}}}
    _write(models_p, json.dumps(good))
    store.load()
    assert store.save()
    assert store.last_save_error == ""


def test_corrupt_critical_files_lists_only_broken(isolated_config):
    _write(isolated_config / "settings.json", "???")
    (isolated_config / "auth.json").write_text("{}", encoding="utf-8")
    store = config_store.ConfigStore()
    broken = [p.name for p, _ in store.corrupt_critical_files()]
    assert broken == ["settings.json"]
