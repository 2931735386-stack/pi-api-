"""Versioned Vision Bridge configuration helpers for pi API Switcher."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from cache_compat import atomic_write_json

VISION_CONFIG_NAME = "vision-bridge.json"
VISION_MODES = {"auto", "native", "force", "off"}
VISION_MODE_OPTIONS = [
    ("自动（推荐）", "auto"),
    ("原生直传", "native"),
    ("强制桥接", "force"),
    ("关闭图片", "off"),
]

DEFAULT_VISION_LIMITS = {
    "mode": "auto",
    "candidates": [],
    "timeoutMs": 60_000,
    "cooldownMs": 60_000,
    "maxImages": 4,
    "maxImageBytes": 10_000_000,
    "maxTotalImageBytes": 20_000_000,
    "maxUserTextChars": 4_000,
    "maxDescriptionChars": 8_000,
    "sessionCacheEntries": 16,
}

_LIMIT_RANGES = {
    "timeoutMs": (5_000, 300_000),
    "cooldownMs": (0, 600_000),
    "maxImages": (1, 16),
    "maxImageBytes": (100_000, 50_000_000),
    "maxTotalImageBytes": (100_000, 100_000_000),
    "maxUserTextChars": (256, 32_000),
    "maxDescriptionChars": (1_000, 32_000),
    "sessionCacheEntries": (0, 128),
}


def normalize_vision_mode(value: Any) -> str:
    return value if value in VISION_MODES else "auto"


def _normalize_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def normalize_candidate(value: Any) -> str | None:
    """Normalize `provider:model`, `provider/model`, or mapping input to provider/model."""
    provider = ""
    model_id = ""
    if isinstance(value, dict):
        provider = str(value.get("provider", "")).strip()
        model_id = str(value.get("modelId", value.get("model", ""))).strip()
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if ":" in text:
            provider, model_id = text.split(":", 1)
        elif "/" in text:
            provider, model_id = text.split("/", 1)
        else:
            return None
        provider = provider.strip()
        model_id = model_id.strip()
    if not provider or not model_id:
        return None
    return f"{provider}/{model_id}"


def normalize_candidates(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_values = value.split("|")
    elif isinstance(value, list):
        raw_values = value
    else:
        raw_values = []
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        candidate = normalize_candidate(raw)
        if candidate and candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


def candidates_to_legacy(candidates: list[str]) -> str:
    values = []
    for candidate in normalize_candidates(candidates):
        provider, model_id = candidate.split("/", 1)
        values.append(f"{provider}:{model_id}")
    return "|".join(values)


def default_vision_config() -> dict[str, Any]:
    return {
        "version": 2,
        "defaults": deepcopy(DEFAULT_VISION_LIMITS),
        "routes": {},
    }


def _sanitize_settings(value: Any, *, include_candidates: bool = True) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    settings: dict[str, Any] = {
        "mode": normalize_vision_mode(raw.get("mode")),
    }
    if include_candidates:
        settings["candidates"] = normalize_candidates(raw.get("candidates", []))
    for key, (minimum, maximum) in _LIMIT_RANGES.items():
        if key in raw:
            settings[key] = _normalize_int(
                raw.get(key),
                int(DEFAULT_VISION_LIMITS[key]),
                minimum,
                maximum,
            )
    return settings


def sanitize_vision_config(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    defaults_raw = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    defaults = deepcopy(DEFAULT_VISION_LIMITS)
    defaults.update(_sanitize_settings(defaults_raw))

    routes_raw = raw.get("routes") if isinstance(raw.get("routes"), dict) else {}
    routes: dict[str, dict[str, Any]] = {}
    for key, route in routes_raw.items():
        if not isinstance(key, str) or "/" not in key or not isinstance(route, dict):
            continue
        provider, model_id = key.split("/", 1)
        if not provider.strip() or not model_id.strip():
            continue
        routes[f"{provider.strip()}/{model_id.strip()}"] = _sanitize_settings(route)
    return {"version": 2, "defaults": defaults, "routes": routes}


def load_vision_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_vision_config()
    try:
        import json

        return sanitize_vision_config(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return default_vision_config()


def save_vision_config(path: Path, config: dict[str, Any]) -> bool:
    return atomic_write_json(path, sanitize_vision_config(config))


def route_key(provider: str, model_id: str) -> str:
    return f"{provider}/{model_id}"


def effective_vision_route(
    config: dict[str, Any],
    provider: str,
    model: dict[str, Any],
) -> dict[str, Any]:
    clean = sanitize_vision_config(config)
    defaults = deepcopy(clean["defaults"])
    key = route_key(provider, str(model.get("id", "")))
    route = clean["routes"].get(key)
    if route:
        defaults.update(route)
    else:
        defaults["mode"] = normalize_vision_mode(model.get("visionMode", defaults.get("mode")))
        legacy = normalize_candidates(model.get("visionModel", ""))
        if legacy:
            defaults["candidates"] = legacy
    defaults["mode"] = normalize_vision_mode(defaults.get("mode"))
    defaults["candidates"] = normalize_candidates(defaults.get("candidates", []))
    return defaults


def set_vision_route(
    config: dict[str, Any],
    provider: str,
    model_id: str,
    mode: str,
    candidates: list[str],
) -> None:
    clean = sanitize_vision_config(config)
    config.clear()
    config.update(clean)
    routes = config.setdefault("routes", {})
    key = route_key(provider, model_id)
    route = dict(routes.get(key, {}))
    route.update({
        "mode": normalize_vision_mode(mode),
        "candidates": normalize_candidates(candidates),
    })
    routes[key] = route


def remove_vision_route(config: dict[str, Any], provider: str, model_id: str) -> None:
    routes = config.get("routes")
    if isinstance(routes, dict):
        routes.pop(route_key(provider, model_id), None)


def remove_provider_vision_routes(config: dict[str, Any], provider: str) -> None:
    routes = config.get("routes")
    if not isinstance(routes, dict):
        return
    prefix = f"{provider}/"
    for key in list(routes):
        if str(key).startswith(prefix):
            routes.pop(key, None)


def rename_provider_vision_routes(
    config: dict[str, Any], old_provider: str, new_provider: str,
) -> None:
    """Move route keys and candidate references to a renamed provider."""
    clean = sanitize_vision_config(config)
    old_prefix = f"{old_provider}/"

    def rename_candidates(value: Any) -> list[str]:
        return [
            f"{new_provider}/{candidate[len(old_prefix):]}"
            if candidate.startswith(old_prefix) else candidate
            for candidate in normalize_candidates(value)
        ]

    defaults = clean["defaults"]
    defaults["candidates"] = rename_candidates(defaults.get("candidates", []))
    routes: dict[str, dict[str, Any]] = {}
    for key, route in clean["routes"].items():
        route_copy = dict(route)
        route_copy["candidates"] = rename_candidates(route_copy.get("candidates", []))
        new_key = f"{new_provider}/{key[len(old_prefix):]}" if key.startswith(old_prefix) else key
        routes[new_key] = route_copy
    clean["routes"] = routes
    config.clear()
    config.update(clean)


def migrate_legacy_vision_routes(models_config: Any, config: dict[str, Any]) -> int:
    """Copy legacy model fields into v2 routes without overriding existing routes."""
    providers = models_config.get("providers") if isinstance(models_config, dict) else None
    if not isinstance(providers, dict):
        return 0
    clean = sanitize_vision_config(config)
    config.clear()
    config.update(clean)
    routes = config.setdefault("routes", {})
    migrated = 0
    for provider, provider_config in providers.items():
        if not isinstance(provider_config, dict):
            continue
        models = provider_config.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if not isinstance(model, dict) or not model.get("id"):
                continue
            candidates = normalize_candidates(model.get("visionModel", ""))
            mode = normalize_vision_mode(model.get("visionMode"))
            key = route_key(str(provider), str(model["id"]))
            if key in routes or (not candidates and "visionMode" not in model):
                continue
            routes[key] = {"mode": mode, "candidates": candidates}
            migrated += 1
    return migrated
