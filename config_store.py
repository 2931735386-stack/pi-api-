# -*- coding: utf-8 -*-
"""配置存储与读写引擎：
管理 ~/.pi/agent/ 下的 models.json / auth.json / settings.json /
cache-compat-guard.json / vision-bridge.json / api-switcher.json。
"""

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from cache_compat import (
    load_guard_config,
    provider_cache_policy,
    remove_provider_cache_policy,
    rename_provider_cache_policy,
    save_guard_config,
    set_provider_cache_policy,
)
from vision_config import (
    effective_vision_route,
    load_vision_config,
    migrate_legacy_vision_routes,
    normalize_candidates,
    normalize_vision_mode,
    remove_provider_vision_routes,
    remove_vision_route,
    rename_provider_vision_routes,
    save_vision_config,
    set_vision_route,
)


# =============================================================================
# 路径常量
# =============================================================================

AGENT_DIR = Path.home() / ".pi" / "agent"
MODELS_PATH = AGENT_DIR / "models.json"
AUTH_PATH = AGENT_DIR / "auth.json"
SETTINGS_PATH = AGENT_DIR / "settings.json"

APP_CONFIG_PATH = AGENT_DIR / "api-switcher.json"
CACHE_GUARD_CONFIG_PATH = AGENT_DIR / "cache-compat-guard.json"
VISION_CONFIG_PATH = AGENT_DIR / "vision-bridge.json"
VISION_BRIDGE_NAME = "vision-bridge.ts"

SNAPSHOTS_DIR = AGENT_DIR / "backups"
SNAPSHOTS_KEEP = 20
SNAPSHOT_FILES = (
    "models.json",
    "auth.json",
    "settings.json",
    "cache-compat-guard.json",
    "vision-bridge.json",
)

# pi 思考等级（从低到高），null 表示该等级不支持
THINKING_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]

# 启动以来解析失败的 JSON 文件 {Path: 错误信息}
_CORRUPT_JSON_FILES = {}


# =============================================================================
# 底层 I/O 与工具函数
# =============================================================================

def _atomic_write_text_file(path: Path, text: str) -> None:
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path: Path):
    """读取 JSON 文件；损坏时返回 {} 并记录路径供 UI 警告与保存拦截。"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _CORRUPT_JSON_FILES[path] = str(exc)
        return {}


def write_json(path: Path, data) -> bool:
    """原子写入：先写临时文件再替换，防止写入中断导致数据损坏。"""
    try:
        _atomic_write_text_file(
            path, json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        )
        return True
    except (OSError, ValueError):
        return False


def snapshot_configs():
    """把当前配置复制到 backups/<时间戳>/；失败静默。"""
    try:
        existing = [f for f in SNAPSHOT_FILES if (AGENT_DIR / f).exists()]
        if not existing:
            return
        dest = SNAPSHOTS_DIR / time.strftime("%Y%m%d-%H%M%S")
        dest.mkdir(parents=True, exist_ok=True)
        for name in existing:
            shutil.copy2(AGENT_DIR / name, dest / name)
        pat = re.compile(r"^\d{8}-\d{6}$")
        snaps = sorted(
            d for d in SNAPSHOTS_DIR.iterdir() if d.is_dir() and pat.match(d.name)
        )
        for old in snaps[:-SNAPSHOTS_KEEP]:
            shutil.rmtree(old, ignore_errors=True)
    except OSError:
        pass


def _load_app_config():
    """读取应用自身配置（主题/字体/费率）。"""
    default = {"theme": "terminal", "font": "", "font_size": 13}
    if not APP_CONFIG_PATH.exists():
        return default
    try:
        d = json.loads(APP_CONFIG_PATH.read_text(encoding="utf-8"))
        default.update(d)
        return default
    except Exception:
        return default


def _save_app_config(cfg):
    try:
        APP_CONFIG_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def install_vision_bridge() -> str:
    """安装打包的 vision-bridge 扩展（不覆盖用户自定义修改）。"""
    bundled_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    source = bundled_dir / VISION_BRIDGE_NAME
    target_dir = AGENT_DIR / "extensions"
    target = target_dir / VISION_BRIDGE_NAME
    if not source.exists():
        return "视觉桥接扩展未找到"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        source_text = source.read_text(encoding="utf-8")
        if target.exists():
            target_text = target.read_text(encoding="utf-8")
            if target_text == source_text:
                return "视觉桥接扩展已就绪"
            if not target_text.startswith("// Managed by pi-api-switcher."):
                return "已保留用户自定义视觉桥接扩展"
            _atomic_write_text_file(target, source_text)
            return "已更新视觉桥接扩展"
        _atomic_write_text_file(target, source_text)
        return "已安装视觉桥接扩展"
    except OSError as exc:
        return f"视觉桥接扩展安装失败：{exc}"


def get_max_thinking_level(model: dict) -> str:
    """判断模型支持的最高思考等级。"""
    if not model.get("reasoning"):
        return "off"
    tlm = model.get("thinkingLevelMap")
    if not tlm:
        return "high"
    for lvl in reversed(THINKING_LEVELS):
        val = tlm.get(lvl)
        if val is not None:
            return lvl
    return "off"


def ensure_thinking_map(model: dict):
    """确保模型有 thinkingLevelMap，没有则按最高等级生成。"""
    if "thinkingLevelMap" not in model:
        mx = get_max_thinking_level(model)
        model["thinkingLevelMap"] = build_thinking_map(mx)
    return model["thinkingLevelMap"]


def build_thinking_map(max_level: str) -> dict:
    """构造最高支持到 max_level 的 thinkingLevelMap。"""
    m = {}
    idx = THINKING_LEVELS.index(max_level)
    for i, lvl in enumerate(THINKING_LEVELS):
        m[lvl] = lvl if i <= idx else None
    m["off"] = None
    return m


def merge_model_edits(stored_models, edited_models):
    """合并表格编辑字段，保留底层未展示的元数据。"""
    stored_by_id = {
        model.get("id"): model
        for model in stored_models
        if isinstance(model, dict) and model.get("id")
    }
    merged_models = []
    for edited in edited_models:
        model_id = edited.get("id")
        stored = stored_by_id.get(model_id, {})
        merged = dict(stored)
        merged.update(edited)
        stored_map = stored.get("thinkingLevelMap") if isinstance(stored, dict) else None
        edited_map = edited.get("thinkingLevelMap")
        if isinstance(stored_map, dict) and isinstance(edited_map, dict):
            protected_map = dict(edited_map)
            for level, stored_value in stored_map.items():
                if stored_value is None and protected_map.get(level) is not None:
                    protected_map[level] = None
            if isinstance(stored_map.get("off"), str) and protected_map.get("off") is None:
                protected_map["off"] = stored_map["off"]
            merged["thinkingLevelMap"] = protected_map
        if "thinkingLevelMap" not in edited:
            merged.pop("thinkingLevelMap", None)
        if "visionModel" not in edited:
            merged.pop("visionModel", None)
        if "visionMode" not in edited:
            merged.pop("visionMode", None)
        merged_models.append(merged)
    return merged_models


def validate_baseurl(url: str) -> bool:
    """基础 URL 校验：非空且以 http:// 或 https:// 开头。"""
    if not url:
        return False
    return url.startswith("http://") or url.startswith("https://")


# =============================================================================
# ConfigStore
# =============================================================================

class ConfigStore:
    """封装对三个核心 JSON 文件及配套防护扩展配置的读写。"""

    def __init__(self):
        self.last_save_error = ""
        self.load()

    def corrupt_critical_files(self):
        """实时探测三个主配置文件，返回无法解析的 [(path, err)]。"""
        out = []
        for path in (MODELS_PATH, AUTH_PATH, SETTINGS_PATH):
            if not path.exists():
                continue
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                out.append((path, str(exc)))
        return out

    def load(self):
        self.models = read_json(MODELS_PATH)
        self.auth = read_json(AUTH_PATH)
        self.settings = read_json(SETTINGS_PATH)
        self.cache_guard = load_guard_config(CACHE_GUARD_CONFIG_PATH)
        self.vision = load_vision_config(VISION_CONFIG_PATH)
        if migrate_legacy_vision_routes(self.models, self.vision):
            save_vision_config(VISION_CONFIG_PATH, self.vision)
        self._clean_stale_enabled_models()

    def _clean_stale_enabled_models(self):
        """清理已删除模型的 *-request 别名。"""
        enabled = self.settings.get("enabledModels")
        if not isinstance(enabled, list):
            return
        configured = {
            model.get("id")
            for provider in self.models.get("providers", {}).values()
            if isinstance(provider, dict)
            for model in provider.get("models", [])
            if isinstance(model, dict) and model.get("id")
        }
        cleaned = []
        for model_id in enabled:
            if not isinstance(model_id, str):
                continue
            if model_id.endswith("-request"):
                base_id = model_id[:-8]
                raw_id = base_id.split("/", 1)[1] if "/" in base_id else base_id
                if base_id in configured or raw_id in configured:
                    continue
            cleaned.append(model_id)
        if cleaned != enabled:
            self.settings["enabledModels"] = cleaned
            write_json(SETTINGS_PATH, self.settings)

    def providers(self):
        return self.models.get("providers", {})

    def provider_names(self):
        return list(self.providers().keys())

    def get_provider(self, name):
        return self.providers().get(name, {})

    def api_key(self, name):
        inline = self.get_provider(name).get("apiKey")
        if inline:
            return inline
        return self.auth.get(name, {}).get("key", "")

    def set_api_key(self, name, key):
        if key:
            self.auth[name] = {"type": "api_key", "key": key}
        elif name in self.auth:
            del self.auth[name]
        p = self.get_provider(name)
        if p and "apiKey" in p:
            del p["apiKey"]

    def default_provider(self):
        return self.settings.get("defaultProvider", "")

    def default_model(self):
        return self.settings.get("defaultModel", "")

    def save(self) -> bool:
        # 防覆盖保护：主配置文件在磁盘上损坏时拒绝写入
        corrupt = self.corrupt_critical_files()
        if corrupt:
            self.last_save_error = "；".join(f"{p.name}：{err}" for p, err in corrupt)
            return False
        self.last_save_error = ""
        snapshot_configs()
        ok1 = write_json(MODELS_PATH, self.models)
        ok2 = write_json(AUTH_PATH, self.auth)
        ok3 = write_json(SETTINGS_PATH, self.settings)
        ok4 = save_guard_config(CACHE_GUARD_CONFIG_PATH, self.cache_guard)
        ok5 = save_vision_config(VISION_CONFIG_PATH, self.vision)
        return ok1 and ok2 and ok3 and ok4 and ok5

    def cache_policy(self, provider):
        return provider_cache_policy(self.cache_guard, provider)

    def set_cache_policy(self, provider, policy):
        set_provider_cache_policy(self.cache_guard, provider, policy)

    def vision_route(self, provider, model):
        route = self.vision.get("routes", {}).get(f"{provider}/{model.get('id', '')}")
        if route:
            return {
                "mode": normalize_vision_mode(route.get("mode")),
                "candidates": normalize_candidates(route.get("candidates", [])),
            }
        return effective_vision_route(self.vision, provider, model)

    def set_vision_route(self, provider, model_id, mode, candidates):
        set_vision_route(self.vision, provider, model_id, mode, candidates)

    def remove_vision_route(self, provider, model_id):
        remove_vision_route(self.vision, provider, model_id)

    def sync_vision_routes(self, provider, models):
        current_routes = self.vision.get("routes", {})
        managed_keys = {
            f"{provider}/{model.get('id', '')}"
            for model in models
            if isinstance(model, dict) and model.get("id")
        }
        for key in list(current_routes.keys()):
            if key.startswith(f"{provider}/") and key not in managed_keys:
                current_routes.pop(key, None)
        for model in models:
            if not isinstance(model, dict) or not model.get("id"):
                continue
            mid = model["id"]
            mode = model.get("visionMode")
            candidates = model.get("visionModel")
            if mode is not None or candidates is not None:
                self.set_vision_route(provider, mid, mode, candidates)
            elif f"{provider}/{mid}" in current_routes:
                self.remove_vision_route(provider, mid)

    def set_default(self, provider, model_id):
        self.settings["defaultProvider"] = provider
        self.settings["defaultModel"] = model_id
        self.sync_enabled_models(provider)

    def sync_enabled_models(self, provider=None):
        """同步 enabledModels 列表，确保所有 provider 的模型都可被 pi 发现。"""
        all_models = {}
        for p_name, p_data in self.providers().items():
            if not isinstance(p_data, dict):
                continue
            for m in p_data.get("models", []):
                if isinstance(m, dict) and m.get("id"):
                    mid = m["id"]
                    all_models.setdefault(mid, []).append(p_name)

        current = self.settings.get("enabledModels", [])
        if not isinstance(current, list):
            current = []

        seen = set(current)
        new_enabled = list(current)

        for mid, p_list in all_models.items():
            if len(p_list) == 1:
                p_name = p_list[0]
                bare_key = mid
                scoped_key = f"{p_name}/{mid}"
                if bare_key not in seen:
                    new_enabled.append(bare_key)
                    seen.add(bare_key)
                if scoped_key not in seen:
                    new_enabled.append(scoped_key)
                    seen.add(scoped_key)
            else:
                for p_name in p_list:
                    scoped_key = f"{p_name}/{mid}"
                    if scoped_key not in seen:
                        new_enabled.append(scoped_key)
                        seen.add(scoped_key)

        valid_keys = set()
        for mid, p_list in all_models.items():
            if len(p_list) == 1:
                valid_keys.add(mid)
                valid_keys.add(f"{p_list[0]}/{mid}")
            else:
                for p_name in p_list:
                    valid_keys.add(f"{p_name}/{mid}")

        new_enabled = [
            k for k in new_enabled
            if not isinstance(k, str) or k in valid_keys or not any(
                k.startswith(f"{p}/") for p in self.provider_names()
            )
        ]
        self.settings["enabledModels"] = new_enabled

    def add_provider(self, name, base_url, api_key, model_id, model_name, reasoning):
        providers = self.models.setdefault("providers", {})
        models = []
        if model_id:
            m = {"id": model_id, "name": model_name or model_id}
            if reasoning:
                m["reasoning"] = True
            models.append(m)
        providers[name] = {
            "baseUrl": base_url,
            "api": "openai-completions",
            "models": models,
        }
        self.set_api_key(name, api_key)
        self.sync_enabled_models(name)

    def rename_provider(self, old_name, new_name):
        if old_name == new_name:
            return True
        if not new_name or not new_name.strip():
            raise ValueError("新名称不能为空")
        new_name = new_name.strip()
        providers = self.models.get("providers", {})
        if new_name in providers:
            raise ValueError(f"供应商 '{new_name}' 已存在")
        if old_name not in providers:
            raise ValueError(f"供应商 '{old_name}' 不存在")

        # 1. 迁移 providers 中的键名，保持原插入顺序
        new_providers = {}
        for k, v in providers.items():
            if k == old_name:
                new_providers[new_name] = v
            else:
                new_providers[k] = v
        self.models["providers"] = new_providers

        # 2. 迁移 auth.json
        if old_name in self.auth:
            self.auth[new_name] = self.auth.pop(old_name)

        # 3. 迁移 settings.json 中的 defaultProvider
        if self.settings.get("defaultProvider") == old_name:
            self.settings["defaultProvider"] = new_name

        # 4. 迁移旧版 visionModel 中的引用
        old_prefix = f"{old_name}:"
        for p in self.models.get("providers", {}).values():
            if not isinstance(p, dict):
                continue
            for m in p.get("models", []):
                if not isinstance(m, dict):
                    continue
                legacy = m.get("visionModel")
                if isinstance(legacy, str) and old_prefix in legacy:
                    m["visionModel"] = "|".join(
                        f"{new_name}:{value[len(old_prefix):]}"
                        if value.startswith(old_prefix) else value
                        for value in legacy.split("|")
                    )

        # 5. 迁移 enabledModels 中的 scoped 条目
        old_scoped_prefix = f"{old_name}/"
        enabled = self.settings.get("enabledModels", [])
        if isinstance(enabled, list):
            self.settings["enabledModels"] = [
                f"{new_name}/{m[len(old_scoped_prefix):]}"
                if isinstance(m, str) and m.startswith(old_scoped_prefix) else m
                for m in enabled
            ]

        rename_provider_cache_policy(self.cache_guard, old_name, new_name)
        rename_provider_vision_routes(self.vision, old_name, new_name)
        self.sync_enabled_models()
        return True

    def remove_provider(self, name):
        p = self.get_provider(name)
        model_ids = {str(m.get("id", "")) for m in p.get("models", []) if m.get("id")}
        scoped_prefix = f"{name}/"

        self.models.get("providers", {}).pop(name, None)
        self.auth.pop(name, None)
        remove_provider_cache_policy(self.cache_guard, name)
        remove_provider_vision_routes(self.vision, name)

        if self.settings.get("defaultProvider") == name:
            self.settings["defaultProvider"] = ""
            self.settings["defaultModel"] = ""

        enabled = self.settings.get("enabledModels", [])
        if isinstance(enabled, list):
            remaining_ids = {
                str(m.get("id", ""))
                for other_p in self.providers().values()
                if isinstance(other_p, dict)
                for m in other_p.get("models", [])
                if isinstance(m, dict) and m.get("id")
            }
            cleaned = []
            for item in enabled:
                if not isinstance(item, str):
                    continue
                if item.startswith(scoped_prefix):
                    continue
                if item in model_ids and item not in remaining_ids:
                    continue
                cleaned.append(item)
            self.settings["enabledModels"] = cleaned

        self.sync_enabled_models()
