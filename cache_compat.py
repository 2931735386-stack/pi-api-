"""Prompt-cache compatibility management for pi API Switcher.

This module keeps OpenAI-compatible transport shape separate from support for
OpenAI-specific prompt-cache fields. Unknown third-party endpoints fail closed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CACHE_GUARD_PACKAGE_SOURCE = "./managed/pi-api-switcher-cache-guard"
CACHE_GUARD_DIR_NAME = "pi-api-switcher-cache-guard"
CACHE_GUARD_CONFIG_NAME = "cache-compat-guard.json"
CACHE_GUARD_BUNDLE_NAME = "cache-compat-guard"
CACHE_OPTIMIZER_NO_KEY_ENV = "PI_CACHE_OPTIMIZER_NO_OPENAI_CACHE_KEY"
MANAGED_MARKER = "// Managed by pi-api-switcher."

CACHE_POLICY_OPTIONS = [
    ("自动安全（推荐）", "auto"),
    ("严格兼容（禁用专有缓存）", "strict"),
    ("仅缓存键（禁用 24h）", "key"),
    ("长缓存（端点明确支持）", "long"),
]
CACHE_POLICIES = {value for _, value in CACHE_POLICY_OPTIONS}
OFFICIAL_OPENAI_HOSTS = {"api.openai.com"}


def normalize_cache_policy(value: Any) -> str:
    """Return a supported policy, falling back to the safe automatic mode."""
    return value if value in CACHE_POLICIES else "auto"


def is_official_openai_base_url(base_url: str) -> bool:
    """Match the actual OpenAI API host, not substring lookalikes."""
    try:
        return (urlparse(base_url.strip()).hostname or "").lower() in OFFICIAL_OPENAI_HOSTS
    except (AttributeError, ValueError):
        return False


def effective_cache_policy(policy: str, base_url: str) -> str:
    """Resolve automatic mode: official OpenAI allows long cache; others are safe."""
    normalized = normalize_cache_policy(policy)
    if normalized != "auto":
        return normalized
    return "long" if is_official_openai_base_url(base_url) else "safe"


def apply_provider_cache_compat(provider: dict[str, Any], policy: str) -> str:
    """Align Pi core long-retention generation with the guard's provider policy.

    Pi currently defaults supportsLongCacheRetention to true for many unknown
    OpenAI-compatible endpoints. Writing an explicit false prevents unsupported
    fields at the source; the runtime guard remains the final safety layer.
    """
    api = str(provider.get("api", "openai-completions"))
    if api not in {"openai-completions", "openai-responses", "azure-openai-responses"}:
        return normalize_cache_policy(policy)

    effective = effective_cache_policy(policy, str(provider.get("baseUrl", "")))
    compat = provider.get("compat")
    if not isinstance(compat, dict):
        compat = {}
        provider["compat"] = compat
    compat["supportsLongCacheRetention"] = effective == "long"
    return effective


def default_guard_config() -> dict[str, Any]:
    return {
        "version": 1,
        "defaultPolicy": "auto",
        "providers": {},
        "models": {},
    }


def load_guard_config(path: Path) -> dict[str, Any]:
    """Load and sanitize the guard config without accepting arbitrary values."""
    raw: Any = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            raw = {}
    if not isinstance(raw, dict):
        raw = {}

    providers_raw = raw.get("providers")
    models_raw = raw.get("models")
    providers = {
        str(key): normalize_cache_policy(value)
        for key, value in (providers_raw.items() if isinstance(providers_raw, dict) else [])
        if value in CACHE_POLICIES
    }
    models = {
        str(key): normalize_cache_policy(value)
        for key, value in (models_raw.items() if isinstance(models_raw, dict) else [])
        if value in CACHE_POLICIES
    }
    return {
        "version": 1,
        "defaultPolicy": normalize_cache_policy(raw.get("defaultPolicy")),
        "providers": providers,
        "models": models,
    }


def provider_cache_policy(config: dict[str, Any], provider_name: str) -> str:
    providers = config.get("providers")
    if isinstance(providers, dict):
        return normalize_cache_policy(providers.get(provider_name))
    return "auto"


def set_provider_cache_policy(config: dict[str, Any], provider_name: str, policy: str) -> None:
    providers = config.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        config["providers"] = providers
    providers[provider_name] = normalize_cache_policy(policy)


def remove_provider_cache_policy(config: dict[str, Any], provider_name: str) -> None:
    providers = config.get("providers")
    if isinstance(providers, dict):
        providers.pop(provider_name, None)
    models = config.get("models")
    if isinstance(models, dict):
        prefix = f"{provider_name}/"
        for key in list(models):
            if str(key).startswith(prefix):
                models.pop(key, None)


def rename_provider_cache_policy(
    config: dict[str, Any], old_name: str, new_name: str,
) -> None:
    """Move provider- and model-scoped cache policies to a new provider key."""
    providers = config.get("providers")
    if isinstance(providers, dict) and old_name in providers:
        providers[new_name] = providers.pop(old_name)
    models = config.get("models")
    if isinstance(models, dict):
        old_prefix = f"{old_name}/"
        for key in list(models):
            if str(key).startswith(old_prefix):
                policy = models.pop(key)
                models[f"{new_name}/{str(key)[len(old_prefix):]}"] = policy


def atomic_write_json(path: Path, data: Any) -> bool:
    """Write JSON through a sibling temporary file and atomically replace."""
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
        return True
    except (OSError, ValueError, TypeError):
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def save_guard_config(path: Path, config: dict[str, Any]) -> bool:
    sanitized = load_guard_config_from_value(config)
    return atomic_write_json(path, sanitized)


def load_guard_config_from_value(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return default_guard_config()
    providers_raw = raw.get("providers")
    models_raw = raw.get("models")
    return {
        "version": 1,
        "defaultPolicy": normalize_cache_policy(raw.get("defaultPolicy")),
        "providers": {
            str(key): value
            for key, value in (providers_raw.items() if isinstance(providers_raw, dict) else [])
            if value in CACHE_POLICIES
        },
        "models": {
            str(key): value
            for key, value in (models_raw.items() if isinstance(models_raw, dict) else [])
            if value in CACHE_POLICIES
        },
    }


def _package_source(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict) and isinstance(entry.get("source"), str):
        return entry["source"]
    return None


def _is_guard_package_source(source: str | None, target_dir: Path) -> bool:
    if not source:
        return False
    normalized = source.replace("\\", "/").rstrip("/").lower()
    canonical = CACHE_GUARD_PACKAGE_SOURCE.lower().lstrip("./")
    target = str(target_dir).replace("\\", "/").rstrip("/").lower()
    return normalized.lstrip("./") == canonical or normalized == target


def register_guard_package(settings_path: Path, target_dir: Path) -> bool:
    """Place the guard last in the package list so it runs after cache optimizer."""
    settings: Any = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return False
    if not isinstance(settings, dict):
        return False

    packages = settings.get("packages")
    if not isinstance(packages, list):
        packages = []
    packages = [
        entry for entry in packages
        if not _is_guard_package_source(_package_source(entry), target_dir)
    ]
    packages.append(CACHE_GUARD_PACKAGE_SOURCE)
    settings["packages"] = packages
    return atomic_write_json(settings_path, settings)


def install_cache_guard(agent_dir: Path, bundle_root: Path) -> str:
    """Install/update the bundled guard and register it after npm extensions."""
    source_dir = bundle_root / CACHE_GUARD_BUNDLE_NAME
    target_dir = agent_dir / "managed" / CACHE_GUARD_DIR_NAME
    source_index = source_dir / "index.ts"
    source_package = source_dir / "package.json"
    if not source_index.exists() or not source_package.exists():
        return "缓存兼容 Guard 资源未找到"

    try:
        source_text = source_index.read_text(encoding="utf-8")
        package_text = source_package.read_text(encoding="utf-8")
        target_index = target_dir / "index.ts"
        target_package = target_dir / "package.json"
        target_dir.mkdir(parents=True, exist_ok=True)

        config_path = agent_dir / CACHE_GUARD_CONFIG_NAME
        if target_index.exists():
            existing = target_index.read_text(encoding="utf-8")
            if existing != source_text and not existing.startswith(MANAGED_MARKER):
                if not register_guard_package(agent_dir / "settings.json", target_dir):
                    return "已保留自定义缓存 Guard，但注册失败"
                if not config_path.exists() and not save_guard_config(config_path, default_guard_config()):
                    return "已保留自定义缓存 Guard，但配置初始化失败"
                return "已保留用户自定义缓存兼容 Guard"

        _atomic_write_text(target_index, source_text)
        _atomic_write_text(target_package, package_text)
        if not register_guard_package(agent_dir / "settings.json", target_dir):
            return "缓存兼容 Guard 已复制，但 settings.json 注册失败"
        if not config_path.exists() and not save_guard_config(config_path, default_guard_config()):
            return "缓存兼容 Guard 已注册，但配置初始化失败"
        return "缓存兼容 Guard 已就绪"
    except OSError as exc:
        return f"缓存兼容 Guard 安装失败：{exc}"


def _atomic_write_text(path: Path, text: str) -> None:
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def disable_optimizer_cache_key_fallback() -> str:
    """Persistently disable the optimizer's broad cache-key fallback on Windows.

    The managed guard supplies an opaque key only for explicit key/long policies.
    Pi core-generated fields are still checked by the final request hook.
    """
    os.environ[CACHE_OPTIMIZER_NO_KEY_ENV] = "1"
    if sys.platform != "win32":
        return "当前进程已关闭通用缓存键注入"

    try:
        import ctypes
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            winreg.SetValueEx(key, CACHE_OPTIMIZER_NO_KEY_ENV, 0, winreg.REG_SZ, "1")

        # Notify newly launched GUI applications that the user environment changed.
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            2000,
            None,
        )
        return "通用缓存键注入已关闭"
    except (OSError, ImportError, AttributeError):
        return "当前进程已关闭通用缓存键注入（用户环境写入失败）"
