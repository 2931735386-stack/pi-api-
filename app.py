#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pi-api-switcher — CC Switch 风格的 pi API/模型配置桌面管理器

管理 pi 的 ~/.pi/agent/ 三个配置文件：
  - models.json    (providers 段：baseUrl / api / models / compat)
  - auth.json      (provider 名 -> {type, key})
  - settings.json  (defaultProvider / defaultModel / enabledModels)

功能：
  1. 切换当前激活的 provider/model（写回 settings.json，pi 下次启动生效）
  2. 增删改 provider（baseUrl / apiKey / 模型列表）
  3. 连通性测试（对各端点发 /models 请求）
  4. 系统托盘常驻 + 快速切换菜单

依赖：PyQt5（Anaconda 自带）
打包：pyinstaller --noconsole --onefile --icon=icon.ico app.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
from copy import deepcopy
import time
import urllib.request
import urllib.error
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve, QThread, pyqtSignal, QLockFile
from PyQt5.QtWidgets import QShortcut
from PyQt5.QtGui import QKeySequence
from dashboard_tab import ModernDashboardTab
from extensions_tab import SkillsExtensionsTab
from sites_tab import SitesTab
from cache_compat import (
    CACHE_POLICY_OPTIONS,
    apply_provider_cache_compat,
    disable_optimizer_cache_key_fallback,
    install_cache_guard,
    load_guard_config,
    normalize_cache_policy,
    provider_cache_policy,
    remove_provider_cache_policy,
    rename_provider_cache_policy,
    save_guard_config,
    set_provider_cache_policy,
)
from vision_config import (
    VISION_MODE_OPTIONS,
    candidates_to_legacy,
    effective_vision_route,
    load_vision_config,
    migrate_legacy_vision_routes,
    normalize_candidates,
    normalize_vision_mode,
    rename_provider_vision_routes,
    remove_provider_vision_routes,
    remove_vision_route,
    save_vision_config,
    set_vision_route,
)


# =============================================================================
# 配置路径
# =============================================================================

AGENT_DIR = Path.home() / ".pi" / "agent"
MODELS_PATH = AGENT_DIR / "models.json"
AUTH_PATH = AGENT_DIR / "auth.json"
SETTINGS_PATH = AGENT_DIR / "settings.json"

# 应用自身配置（保存主题/字体选择）
APP_CONFIG_PATH = AGENT_DIR / "api-switcher.json"
CACHE_GUARD_CONFIG_PATH = AGENT_DIR / "cache-compat-guard.json"
VISION_CONFIG_PATH = AGENT_DIR / "vision-bridge.json"
VISION_BRIDGE_NAME = "vision-bridge.ts"


def _atomic_write_text_file(path: Path, text: str) -> None:
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def install_vision_bridge() -> str:
    """Install the bundled pi extension without overwriting user customizations.

    Returns a short status string for the UI. The source is included as a PyInstaller
    data file and falls back to the source directory during development.
    """
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

# pi 思考等级（从低到高），null 表示该等级不支持
THINKING_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]


# =============================================================================
# 多主题配色
# =============================================================================

THEMES = {
    # ===== Modern Light (拟物卡片微拟态风格) =====
    "modern_light": {
        "bg": "#f4f6f9", "bg_alt": "#ebf0f5", "panel": "#ffffff", "border": "#e2e8f0",
        "text": "#0f172a", "text_dim": "#64748b",
        "accent": "#3b82f6", "accent_2": "#8b5cf6", "accent_hover": "#2563eb",
        "green": "#10b981", "red": "#ef4444", "yellow": "#f59e0b", "blue": "#3b82f6",
        "btn_text": "#ffffff",
    },
    # ===== Terminal 风格：黑灰底 + 暖橙强调，极简终端感 =====
    "terminal": {
        "bg": "#0d0d0d", "bg_alt": "#080808", "panel": "#1a1a1a", "border": "#2a2a2a",
        "text": "#e8e8e8", "text_dim": "#7a7a7a",
        "accent": "#ff8c42", "accent_2": "#d4a373", "accent_hover": "#ffa05c",
        "green": "#7cb342", "red": "#ef5350", "yellow": "#ffca28", "blue": "#5c9eff",
        "btn_text": "#0d0d0d",
    },
    # ===== Codex 风格（OpenAI CLI）：白色底 + 绿色强调，简洁明亮 =====
    "codex": {
        "bg": "#ffffff", "bg_alt": "#f5f5f5", "panel": "#f0f0f0", "border": "#e0e0e0",
        "text": "#1a1a1a", "text_dim": "#666666",
        "accent": "#10a37f", "accent_2": "#0d8c6f", "accent_hover": "#0e9170",
        "green": "#10a37f", "red": "#ef4444", "yellow": "#f59e0b", "blue": "#3b82f6",
        "btn_text": "#ffffff",
    },
    # ===== Claude Code 风格：暖橙赭 + 米色终端，温润纸质调 =====
    "claude": {
        "bg": "#1c1815", "bg_alt": "#15110e", "panel": "#2a231d", "border": "#3d3429",
        "text": "#f0e6d8", "text_dim": "#a89b8a",
        "accent": "#e07a3c", "accent_2": "#c89968", "accent_hover": "#f08850",
        "green": "#8fa856", "red": "#d96552", "yellow": "#d4a83a", "blue": "#6b8cb4",
        "btn_text": "#1c1815",
    },
    # ===== DeepSeek 风格：深蓝底 + 科技青蓝，冷调未来感 =====
    "deepseek": {
        "bg": "#0a1428", "bg_alt": "#050b18", "panel": "#11203a", "border": "#1e3050",
        "text": "#dce8f5", "text_dim": "#7890b0",
        "accent": "#1ec8e8", "accent_2": "#4d8aff", "accent_hover": "#3dd9f0",
        "green": "#26d97f", "red": "#ff5c7c", "yellow": "#ffce47", "blue": "#4d8aff",
        "btn_text": "#0a1428",
    },
    # ===== 青绿+錡蓝（默认/原） =====
    "teal": {
        "bg": "#0f1117", "bg_alt": "#0a0c12", "panel": "#1a1d27", "border": "#2a2e3a",
        "text": "#e6e8ef", "text_dim": "#8b90a0",
        "accent": "#2dd4bf", "accent_2": "#6366f1", "accent_hover": "#5eead4",
        "green": "#34d399", "red": "#f87171", "yellow": "#fbbf24", "blue": "#38bdf8",
        "btn_text": "#0f1117",
    },
    # ===== GitHub Night：紫+蓝（深色高对比） =====
    "night": {
        "bg": "#0d1117", "bg_alt": "#010409", "panel": "#161b22", "border": "#30363d",
        "text": "#e6edf3", "text_dim": "#8b949e",
        "accent": "#d2a8ff", "accent_2": "#79c0ff", "accent_hover": "#bc8cff",
        "green": "#3fb950", "red": "#ff7b72", "yellow": "#e3b341", "blue": "#58a6ff",
        "btn_text": "#0d1117",
    },
    # ===== 浅色主题 =====
    "light": {
        "bg": "#fafafa", "bg_alt": "#f0f0f0", "panel": "#ffffff", "border": "#e0e0e0",
        "text": "#1a1a1a", "text_dim": "#666666",
        "accent": "#0891b2", "accent_2": "#4f46e5", "accent_hover": "#06b6d4",
        "green": "#16a34a", "red": "#dc2626", "yellow": "#ca8a04", "blue": "#2563eb",
        "btn_text": "#ffffff",
    },
}

# 默认色（向后兼容）
COLORS = THEMES["terminal"]

# Windows 常用中文字体（按优先级）
FONT_CANDIDATES = [
    "Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑",
    "PingFang SC", "Noto Sans CJK SC", "Source Han Sans CN",
    "SimHei", "黑体", "Segoe UI", "Arial",
]


def _load_app_config():
    """读取应用自身配置（主题/字体）。"""
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
        APP_CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def detect_available_fonts():
    """检测系统实际可用的中文字体（从 QFontDatabase 里找）。"""
    from PyQt5.QtGui import QFontDatabase
    db = QFontDatabase()
    families = set(db.families())
    available = []
    if families:
        # 预建 {字体名小写: 字体名原写} 字典，O(1) 查找
        families_lower = {fam.lower(): fam for fam in families}
        # 优先匹配常见中文字体名
        for f in FONT_CANDIDATES:
            fam = families_lower.get(f.lower())
            if fam:
                if fam not in available:
                    available.append(fam)
                continue
            # 宽松匹配：候选名是某字体名的子串
            for low, fam in families_lower.items():
                if f in low or low in f.lower():
                    if fam not in available:
                        available.append(fam)
                    break
        # 补充几个常用于代码的英文等宽字体
        for f in ["Consolas", "Cascadia Code", "JetBrains Mono", "Segoe UI Mono"]:
            fam = families_lower.get(f.lower())
            if fam and fam not in available:
                available.append(fam)
    if not available:
        # offscreen / 无 GUI 后端时退回系统已知可用字体
        available = FONT_CANDIDATES[:6]
    return available



def get_max_thinking_level(model: dict) -> str:
    """判断模型支持的最高思考等级。
    依据 thinkingLevelMap：从 max 往下找第一个非 null 的等级。
    若模型 reasoning=False 或无 map，返回 'off'。"""
    if not model.get("reasoning"):
        return "off"
    tlm = model.get("thinkingLevelMap")
    if not tlm:
        # 没有映射但支持推理 → 默认支持到 high
        return "high"
    for lvl in reversed(THINKING_LEVELS):
        val = tlm.get(lvl)
        if val is not None:
            return lvl
    return "off"


def ensure_thinking_map(model: dict):
    """确保模型有 thinkingLevelMap，没有则按当前最高等级生成一个。"""
    if "thinkingLevelMap" not in model:
        mx = get_max_thinking_level(model)
        model["thinkingLevelMap"] = build_thinking_map(mx)
    return model["thinkingLevelMap"]


def build_thinking_map(max_level: str) -> dict:
    """构造一个“最高支持到 max_level”的 thinkingLevelMap。"""
    m = {}
    idx = THINKING_LEVELS.index(max_level)
    for i, lvl in enumerate(THINKING_LEVELS):
        m[lvl] = lvl if i <= idx else None
    # off 永远是 None（关闭思考）
    m["off"] = None
    return m


def merge_model_edits(stored_models, edited_models):
    """Merge table-managed fields while preserving advanced model metadata."""
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
        # Preserve provider-specific explicit off values such as "none". The
        # generic table editor only controls the maximum level and otherwise
        # emits off=null, which would make Pi clamp `off` to `minimal`.
        stored_map = stored.get("thinkingLevelMap") if isinstance(stored, dict) else None
        edited_map = edited.get("thinkingLevelMap")
        if isinstance(stored_map, dict) and isinstance(edited_map, dict):
            protected_map = dict(edited_map)
            # Preserve every explicit capability hole. The table edits only the
            # highest level and cannot safely infer that a provider gained an
            # intermediate level such as `minimal`.
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
    """校验 baseUrl 格式：必须以 http:// 或 https:// 开头。"""
    return re.match(r"^https?://", url.strip()) is not None


# 启动以来解析失败的 JSON 文件 {Path: 错误信息}，供 UI 提示与保存防护使用
_CORRUPT_JSON_FILES = {}


def read_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # 损坏时返回 {} 并记录，ConfigStore 会据此阻止覆盖式保存，
        # 避免用空数据把用户仅存的配置抹掉
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


# =============================================================================
# 数据模型
# =============================================================================

# 快照目录：每次保存前备份 5 个配置文件，保留最近 SNAPSHOTS_KEEP 份
SNAPSHOTS_DIR = AGENT_DIR / "backups"
SNAPSHOTS_KEEP = 20
SNAPSHOT_FILES = ("models.json", "auth.json", "settings.json",
                  "cache-compat-guard.json", "vision-bridge.json")


def snapshot_configs():
    """把当前配置复制到 backups/<时间戳>/；失败静默（备份不应阻塞保存）。"""
    try:
        existing = [f for f in SNAPSHOT_FILES if (AGENT_DIR / f).exists()]
        if not existing:
            return
        dest = SNAPSHOTS_DIR / time.strftime("%Y%m%d-%H%M%S")
        dest.mkdir(parents=True, exist_ok=True)
        for name in existing:
            shutil.copy2(AGENT_DIR / name, dest / name)
        # 只保留最近 N 份（仅限本工具生成的 <时间戳> 格式目录，不动其他来源的备份）
        pat = re.compile(r"^\d{8}-\d{6}$")
        snaps = sorted(d for d in SNAPSHOTS_DIR.iterdir()
                       if d.is_dir() and pat.match(d.name))
        for old in snaps[:-SNAPSHOTS_KEEP]:
            shutil.rmtree(old, ignore_errors=True)
    except OSError:
        pass


class ConfigStore:
    """封装对三个 JSON 文件的读写。"""

    def __init__(self):
        self.last_save_error = ""
        self.load()

    def corrupt_critical_files(self):
        """实时探测三个主配置文件，返回无法解析的 [(path, err)]。

        每次保存前重新读盘检查：用户在外部修复后无需重启即可解除拦截。
        """
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
        """Remove obsolete `*-request` aliases when the canonical model exists."""
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
                # 兼容 bare ID 或 provider/model 格式的 *-request 清理
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
        # 统一只写 auth.json，避免双重存储导致读取优先级歧义
        if key:
            self.auth[name] = {"type": "api_key", "key": key}
        elif name in self.auth:
            del self.auth[name]
        # 清理 models.json 中可能遗留的内嵌 apiKey 字段
        p = self.get_provider(name)
        if p and "apiKey" in p:
            del p["apiKey"]

    def default_provider(self):
        return self.settings.get("defaultProvider", "")

    def default_model(self):
        return self.settings.get("defaultModel", "")

    def save(self) -> bool:
        # 防覆盖保护：主配置文件在磁盘上无法解析时拒绝写入，
        # 避免内存中的不完整数据把用户仅存的配置抹掉（快照里通常还有好备份）
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
        return effective_vision_route(self.vision, provider, model)

    def set_vision_route(self, provider, model_id, mode, candidates):
        set_vision_route(self.vision, provider, model_id, mode, candidates)

    def remove_vision_route(self, provider, model_id):
        remove_vision_route(self.vision, provider, model_id)

    def sync_vision_routes(self, provider, models):
        model_ids = {str(model.get("id", "")) for model in models if model.get("id")}
        routes = self.vision.get("routes")
        if isinstance(routes, dict):
            prefix = f"{provider}/"
            for key in list(routes):
                if str(key).startswith(prefix) and str(key)[len(prefix):] not in model_ids:
                    routes.pop(key, None)
        for model in models:
            model_id = str(model.get("id", ""))
            if not model_id:
                continue
            mode = normalize_vision_mode(model.get("visionMode"))
            candidates = normalize_candidates(model.get("visionModel", ""))
            self.set_vision_route(provider, model_id, mode, candidates)

    def set_default(self, provider, model_id):
        self.settings["defaultProvider"] = provider
        self.settings["defaultModel"] = model_id
        self.sync_enabled_models(provider)

    def sync_enabled_models(self, provider=None):
        """将所有已配置 provider 的模型同步到 enabledModels 白名单。
        
        对于同一模型 ID 在多个 provider 中存在的情况（如 glm-5.2 在 glm 与 免费 供应商中均有），
        自动以 `provider/model`（如 `glm/glm-5.2`、`免费/glm-5.2`）格式写入，
        确保在 Pi 终端 /model 菜单中能同时展示并带上各自的供应商标注，不会互相覆盖。
        对于无重名冲突的模型，同时保留其 bare ID 保持最大兼容。
        """
        enabled = list(self.settings.get("enabledModels", []))
        providers = self.providers()
        if not isinstance(providers, dict):
            return

        # 统计每个 model ID 出现的 provider 集合
        id_to_providers: dict[str, list[str]] = {}
        for p_name, p_data in providers.items():
            if not isinstance(p_data, dict):
                continue
            for m in p_data.get("models", []):
                if isinstance(m, dict) and m.get("id"):
                    mid = str(m["id"]).strip()
                    if mid:
                        id_to_providers.setdefault(mid, []).append(str(p_name))

        # 为每个 provider 下的模型构建 scoped 或 bare 格式条目
        for mid, p_list in id_to_providers.items():
            if len(p_list) > 1:
                # 存在同名模型：必须为每个 provider 注入 scoped 标识
                for p_name in p_list:
                    scoped = f"{p_name}/{mid}"
                    if scoped not in enabled:
                        enabled.append(scoped)
                # 移除有歧义的裸 ID，避免 Pi /model 出现解析覆盖
                if mid in enabled:
                    enabled.remove(mid)
            else:
                # 唯一模型：注入 scoped 或 bare（优先保留或添加 bare）
                p_name = p_list[0]
                scoped = f"{p_name}/{mid}"
                if mid not in enabled and scoped not in enabled:
                    enabled.append(mid)

        self.settings["enabledModels"] = enabled

    def add_provider(self, name, base_url, api_key, model_id, model_name, reasoning):
        p = {
            "baseUrl": base_url,
            "api": "openai-completions",
            "name": model_name,
            "models": [
                {
                    "id": model_id,
                    "name": model_name,
                    "reasoning": reasoning,
                    "input": ["text", "image"] if reasoning else ["text"],
                    "contextWindow": 128000,
                    "maxTokens": 16384,
                }
            ],
        }
        self.models.setdefault("providers", {})[name] = p
        # API Key 统一只写 auth.json，不再内嵌到 models.json
        if api_key:
            self.auth[name] = {"type": "api_key", "key": api_key}
        self.sync_enabled_models()

    def rename_provider(self, old_name, new_name):
        """Rename a provider key and migrate all local configuration references."""
        old_name = str(old_name).strip()
        new_name = str(new_name).strip()
        providers = self.models.setdefault("providers", {})
        if not old_name or old_name not in providers:
            raise ValueError("供应商不存在")
        if not new_name:
            raise ValueError("供应商名称不能为空")
        if new_name != old_name and new_name in providers:
            raise ValueError("供应商名称已存在")
        if new_name == old_name:
            return False

        provider = providers.pop(old_name)
        providers[new_name] = provider
        if old_name in self.auth:
            self.auth[new_name] = self.auth.pop(old_name)
        if self.settings.get("defaultProvider") == old_name:
            self.settings["defaultProvider"] = new_name
        # 兼容旧版模型字段：部分配置仍直接把候选写在 visionModel 中。
        old_prefix = f"{old_name}:"
        for provider in providers.values():
            for model in provider.get("models", []) if isinstance(provider, dict) else []:
                if not isinstance(model, dict):
                    continue
                legacy = model.get("visionModel")
                if isinstance(legacy, str):
                    model["visionModel"] = "|".join(
                        f"{new_name}:{value[len(old_prefix):]}"
                        if value.startswith(old_prefix) else value
                        for value in legacy.split("|")
                    )

        # 迁移 enabledModels 中的 scoped 条目 (old_name/model -> new_name/model)
        old_scoped_prefix = f"{old_name}/"
        enabled = self.settings.get("enabledModels", [])
        if isinstance(enabled, list):
            self.settings["enabledModels"] = [
                f"{new_name}/{m[len(old_scoped_prefix):]}" if isinstance(m, str) and m.startswith(old_scoped_prefix) else m
                for m in enabled
            ]

        rename_provider_cache_policy(self.cache_guard, old_name, new_name)
        rename_provider_vision_routes(self.vision, old_name, new_name)
        self.sync_enabled_models()
        return True

    def remove_provider(self, name):
        # 先获取该 provider 的模型 ID 列表
        p = self.get_provider(name)
        model_ids = {str(m.get("id", "")) for m in p.get("models", []) if m.get("id")}
        scoped_prefix = f"{name}/"

        self.models.get("providers", {}).pop(name, None)
        self.auth.pop(name, None)
        remove_provider_cache_policy(self.cache_guard, name)
        remove_provider_vision_routes(self.vision, name)

        # 清理 settings.json 中的悬空引用
        if self.settings.get("defaultProvider") == name:
            self.settings["defaultProvider"] = ""
            self.settings["defaultModel"] = ""

        # 清理 enabledModels：移除该 provider 的 scoped 条目
        enabled = self.settings.get("enabledModels", [])
        if isinstance(enabled, list):
            # 获取剩余其他 provider 依然拥有的模型 ID 集合
            remaining_ids = {
                str(m.get("id", ""))
                for other_p in self.providers().values()
                if isinstance(other_p, dict)
                for m in other_p.get("models", [])
                if isinstance(m, dict) and m.get("id")
            }
            # 移除属于该 provider 的 scoped 项；若是裸 ID，仅在其他 provider 都没有时才移除
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

        # 重新同步一次，确保剩余供应商中的同名/唯一模型状态正确
        self.sync_enabled_models()


# =============================================================================
# 连通性测试（线程）
# =============================================================================

# =============================================================================
# 已知模型上下文对照表（用于「探测能力」时匹配主流模型的 contextWindow）
# 键为模型 id 的小写子串（尽量精确），值为上下文 token 数。
# 注：上下文无法通过通用 API 直接探测，只能查表/查文档；这里维护一份常见模型表。
# =============================================================================

KNOWN_CONTEXT = {
    # OpenAI GPT 系列
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4.1": 1047576,
    "gpt-4.1-mini": 1047576,
    "gpt-4.1-nano": 1047576,
    "o1": 200000,
    "o3": 200000,
    "o4-mini": 200000,
    "gpt-5": 272000,
    "gpt-5.6": 1050000,
    # Claude 系列
    "claude-3-opus": 200000,
    "claude-3.5": 200000,
    "claude-3.7": 200000,
    "claude-4": 200000,
    "claude-sonnet": 200000,
    "claude-haiku": 200000,
    "claude-opus": 200000,
    # Gemini 系列
    "gemini-1.5": 2000000,
    "gemini-2.0": 2000000,
    "gemini-2.5": 2000000,
    "gemini-3": 2000000,
    # DeepSeek 系列
    "deepseek-v3": 64000,
    "deepseek-r1": 64000,
    "deepseek-v4": 1048576,
    "deepseek-chat": 64000,
    "deepseek-reasoner": 64000,
    # Kimi / Moonshot
    "kimi-k2": 262144,
    "kimi-k3": 217000,
    "moonshot": 128000,
    # GLM / 智谱
    "glm-4": 128000,
    "glm-4.5": 128000,
    "glm-4.6": 200000,
    "glm-5": 128000,
    # Qwen 通义千问
    "qwen2.5": 128000,
    "qwen-max": 128000,
    "qwen3": 128000,
    "qwen-long": 10000000,
    # Grok
    "grok-2": 128000,
    "grok-3": 128000,
    "grok-4": 200000,
    # 其他
    "llama-3.1": 128000,
    "llama-3.3": 128000,
    "llama-4": 200000,
    "mistral-large": 128000,
    "gpt-oss": 128000,
}


# 模块加载时预排序静态上下文键（按长度降序，精确/较长匹配优先），避免每次调用重排
_KNOWN_CONTEXT_SORTED = sorted(KNOWN_CONTEXT.keys(), key=len, reverse=True)


def lookup_context_window(model_id: str):
    """根据模型 id 在已知对照表中查找上下文窗口，返回 int 或 None。"""
    if not model_id:
        return None
    low = model_id.lower()
    # 使用模块加载时预排序的列表，O(n) 查找但避免了重复排序
    for key in _KNOWN_CONTEXT_SORTED:
        if key in low:
            return KNOWN_CONTEXT[key]
    return None


def probe_model_capability(base_url, api_key, model_id, timeout=8.0):
    """主动探测单个模型是否支持图片输入。
    发一个带 1x1 透明 PNG 的 minimal chat 请求，
    若返回正常或未报“不支持图片/image”类错误，则认为支持图片。
    返回 (ok, supports_image, msg)。
    """
    url = base_url.rstrip("/") + "/chat/completions"
    # 1x1 透明 PNG 的 base64
    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "回复 ok"},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
                ],
            }
        ],
        "max_tokens": 1,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "pi-api-switcher/1.0")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency = (time.time() - t0) * 1000
            resp.read()
            return True, True, f"{resp.status} 支持图片（{int(latency)}ms）"
    except urllib.error.HTTPError as e:
        latency = (time.time() - t0) * 1000
        return True, False, f"{e.code} 不支持图片（{int(latency)}ms）"
    except urllib.error.URLError as e:
        latency = (time.time() - t0) * 1000
        return False, False, f"连接失败: {e.reason}"
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return False, False, f"错误: {e}"


def test_endpoint(base_url, api_key, timeout=5.0):
    """对 OpenAI 兼容端点发 GET /models 请求。
    返回 (ok, latency_ms, msg, model_infos: list[dict])。
    每个 model_info 尽量携带 {id, contextWindow, input, reasoning} 等能力信息，
    端点未返回则字段缺失。
    """
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("User-Agent", "pi-api-switcher/1.0")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency = (time.time() - t0) * 1000
            body = resp.read().decode("utf-8", "ignore")
            # 尝试解析模型列表
            model_infos = []
            try:
                data = json.loads(body)
                for m in data.get("data", []):
                    if isinstance(m, str):
                        model_infos.append({"id": m})
                        continue
                    if not isinstance(m, dict):
                        continue
                    mid = m.get("id", "")
                    if not mid:
                        continue
                    info = {"id": mid}
                    # 能力/上下文字段（不同端点字段名不同，尽量兼容）
                    ctx = None
                    for key in ("contextWindow", "context_window", "contextLength",
                                "context_length", "maxContextTokens", "max_context_tokens",
                                "contextWindowTokens", "inputTokens", "context"):
                        if key in m and m[key] is not None:
                            ctx = m[key]
                            break
                    if ctx is not None:
                        try:
                            info["contextWindow"] = int(ctx)
                        except (TypeError, ValueError):
                            pass
                    # 输入能力
                    inp = m.get("input") or m.get("inputTypes") or m.get("input_types")
                    if inp is None:
                        # 有些端点用 capabilities/modalities
                        caps = m.get("capabilities") or {}
                        if isinstance(caps, dict):
                            inp = caps.get("input") or caps.get("modalities")
                    if inp is not None:
                        if isinstance(inp, str):
                            inp = [inp]
                        if isinstance(inp, list):
                            info["input"] = [str(x) for x in inp]
                    # 推理能力
                    reas = m.get("reasoning")
                    if reas is None:
                        caps = m.get("capabilities") or {}
                        if isinstance(caps, dict):
                            reas = caps.get("reasoning")
                    if reas is not None:
                        info["reasoning"] = bool(reas)
                    model_infos.append(info)
            except Exception:
                pass
            return True, int(latency), f"{resp.status} OK", model_infos
    except urllib.error.HTTPError as e:
        latency = (time.time() - t0) * 1000
        # 401/403 说明端点通了但鉴权有问题；404 说明路径不对但服务在
        if e.code in (401, 403):
            return True, int(latency), f"{e.code} 鉴权失败（端点可达）", []
        return False, int(latency), f"HTTP {e.code}", []
    except urllib.error.URLError as e:
        latency = (time.time() - t0) * 1000
        return False, int(latency), f"连接失败: {e.reason}", []
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return False, int(latency), f"错误: {e}", []


# =============================================================================
# 图标生成（PIL 绘制，打包成 .ico）
# =============================================================================

def generate_icon_ico(path: Path):
    """生成以 "π" 字样为主题的渐变圆角图标。"""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:
        return False

    size = 256
    supersample = 2  # 2x 超采样抗锯齿，绘制在 512x512 再缩回 256
    SS = size * supersample

    # 1. 渐变圆角背景（深色系，呼应应用暗色主题）
    bg = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    top = (30, 30, 46, 255)        # #1e1e2e
    bottom = (49, 50, 68, 255)     # #313244
    for y in range(SS):
        t = y / SS
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        bd.line([(0, y), (SS, y)], fill=(r, g, b, 255))

    # 2. 顶部高光渐变条（青绿→錡蓝，作为“pi”主题的识别色带）
    hl = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hl)
    h_top = (45, 212, 191, 255)   # #2dd4bf 青绿 teal
    h_bottom = (99, 102, 241, 255) # #6366f1 錡蓝 indigo
    hl_h = 14 * supersample
    for y in range(0, hl_h):
        t = y / hl_h
        r = int(h_top[0] + (h_bottom[0] - h_top[0]) * t)
        g = int(h_top[1] + (h_bottom[1] - h_top[1]) * t)
        b = int(h_top[2] + (h_bottom[2] - h_top[2]) * t)
        hd.line([(0, y), (SS, y)], fill=(r, g, b, 255))

    # 3. 圆角遮罩应用到背景 + 高光
    radius = 56 * supersample
    mask = Image.new("L", (SS, SS), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, SS - 1, SS - 1], radius=radius, fill=255)

    final = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    final.paste(bg, (0, 0), mask)
    final.paste(hl, (0, 0), mask)

    d = ImageDraw.Draw(final)

    # 4. 中心 “π” 字符
    font_path = None
    for candidate in [
        "C:/Windows/Fonts/seguisb.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/simhei.ttf",
    ]:
        try:
            ImageFont.truetype(candidate, 100)
            font_path = candidate
            break
        except Exception:
            continue

    if font_path:
        glyph = "\u03c0"  # π
        target_h = 150 * supersample
        font = ImageFont.truetype(font_path, 200 * supersample)
        try:
            bbox = d.textbbox((0, 0), glyph, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if h > 0:
                scale = target_h / h
                font = ImageFont.truetype(font_path, int(200 * supersample * scale))
                bbox = d.textbbox((0, 0), glyph, font=font)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
        except Exception:
            w, h = 120 * supersample, 140 * supersample

        x = (SS - w) / 2 - bbox[0]
        y = (SS - h) / 2 - bbox[1]
        d.text((x, y), glyph, font=font, fill=(205, 214, 244, 255))  # #cdd6f4
    else:
        # 无字体时：手绘简化的 π
        cx, cy = SS // 2, SS // 2
        lw = 22 * supersample
        d.line([(cx - 60 * supersample, cy - 40 * supersample),
                (cx + 60 * supersample, cy - 40 * supersample)], fill=(205, 214, 244, 255), width=lw)
        d.line([(cx - 40 * supersample, cy - 40 * supersample),
                (cx - 40 * supersample, cy + 55 * supersample)], fill=(205, 214, 244, 255), width=lw)
        d.line([(cx + 40 * supersample, cy - 40 * supersample),
                (cx + 40 * supersample, cy + 55 * supersample)], fill=(205, 214, 244, 255), width=lw)

    # 5. 底部小圆点装饰（青绿/錡蓝两色）
    r = 10 * supersample
    d.ellipse([SS // 2 - 60 * supersample - r, SS - 30 * supersample - r,
               SS // 2 - 60 * supersample + r, SS - 30 * supersample + r],
              fill=(45, 212, 191, 255))
    d.ellipse([SS // 2 + 60 * supersample - r, SS - 30 * supersample - r,
               SS // 2 + 60 * supersample + r, SS - 30 * supersample + r],
              fill=(99, 102, 241, 255))

    # 缩回目标尺寸（超采样抗锯齿）
    final = final.resize((size, size), Image.LANCZOS)
    final = final.filter(ImageFilter.SMOOTH)
    final.save(path, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    return True


# =============================================================================
# 后台工作线程（统一使用 QThread + pyqtSignal）
# =============================================================================

# 批量测速时同时进行的网络请求上限：避免供应商很多时打爆本地临时端口或触发上游限流
MAX_CONCURRENT_PROBES = 8


class TestEndpointWorker(QThread):
    """异步测试端点连通性，与 DataLoadWorker 风格一致。"""
    result_ready = pyqtSignal(str, bool, int, str, str)  # name, ok, latency, msg, payload

    def __init__(self, base_url, api_key, name="", parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key
        self.name = name

    def run(self):
        ok, latency, msg, model_infos = test_endpoint(self.base_url, self.api_key)
        payload = json.dumps(model_infos, ensure_ascii=False)
        self.result_ready.emit(self.name, ok, latency, msg, payload)


class ProbeModelsWorker(QThread):
    """逐个探测模型能力（是否支持图片），每完成一个发信号更新表格。
    避免同步阻塞主线程。"""
    result_ready = pyqtSignal(int, str, bool, bool, str)  # row, mid, ok, supports, msg

    def __init__(self, base_url, api_key, selected, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key
        self.selected = selected  # [(row, mid), ...]

    def run(self):
        for row, mid in self.selected:
            ok, supports, msg = probe_model_capability(self.base_url, self.api_key, mid)
            self.result_ready.emit(row, mid, ok, supports, msg)


class BatchEndpointTester(QThread):
    """并发测试全部端点，内部用线程池把同时进行的请求数限制在 MAX_CONCURRENT_PROBES。
    每得到一个结果立即发信号，UI 可增量更新（不再受线程数 = 供应商数限制）。"""
    result_ready = pyqtSignal(str, bool, int, str, str)  # name, ok, latency, msg, payload

    def __init__(self, targets, parent=None):
        super().__init__(parent)
        self.targets = targets  # [(name, base_url, api_key), ...]
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(MAX_CONCURRENT_PROBES, len(self.targets))) as pool:
            futures = {
                pool.submit(test_endpoint, base_url, key): (name, base_url)
                for name, base_url, key in self.targets
                if not self._stop
            }
            for fut in list(futures):
                if self._stop:
                    break
                name, _url = futures[fut]
                try:
                    ok, latency, msg, model_infos = fut.result()
                except Exception as e:  # 线程池内未捕获异常也当作单个失败，不影响其他端点
                    ok, latency, msg, model_infos = False, 0, f"错误: {e}", []
                payload = json.dumps(model_infos, ensure_ascii=False)
                self.result_ready.emit(name, ok, int(latency), msg, payload)


# =============================================================================
# 快捷键速查面板
# =============================================================================

class ShortcutsDialog(QtWidgets.QDialog):
    """全局快捷键速查面板 (Shortcuts Cheat Sheet)。"""

    def __init__(self, parent=None, theme=None):
        super().__init__(parent)
        self.setWindowTitle("快捷键速查指南")
        self.resize(520, 480)
        c = theme or THEMES.get("terminal", {})
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c.get('panel', '#1a1a1a')};
                color: {c.get('text', '#e8e8e8')};
            }}
            QLabel#dialogTitle {{
                font-size: 16px;
                font-weight: 800;
                color: {c.get('accent', '#3b82f6')};
            }}
            QLabel#groupTitle {{
                font-size: 13px;
                font-weight: 700;
                color: {c.get('text', '#ffffff')};
                padding-top: 6px;
            }}
            QFrame#keyCard {{
                background-color: {c.get('bg_alt', '#0f1117')};
                border: 1px solid {c.get('border', '#2a2e3a')};
                border-radius: 8px;
                padding: 4px 8px;
            }}
            QLabel#keyBadge {{
                background-color: {c.get('bg', '#000000')};
                color: {c.get('accent', '#3b82f6')};
                border: 1px solid {c.get('border', '#3d3429')};
                border-radius: 4px;
                font-family: Consolas, "JetBrains Mono", monospace;
                font-weight: 700;
                font-size: 11px;
                padding: 2px 6px;
            }}
            QLabel#keyDesc {{
                color: {c.get('text_dim', '#888888')};
                font-size: 12px;
            }}
            QPushButton#closeBtn {{
                background-color: {c.get('accent', '#3b82f6')};
                color: {c.get('btn_text', '#ffffff')};
                border-radius: 6px;
                font-weight: 700;
                padding: 6px 20px;
                border: none;
            }}
            QPushButton#closeBtn:hover {{
                background-color: {c.get('accent_hover', '#2563eb')};
            }}
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("⌨️ 全局快捷键速查 (Shortcuts Cheat Sheet)")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        groups = [
            ("🚀 导航与全局", [
                ("Ctrl + 1", "切换至「用量统计与监控」看板"),
                ("Ctrl + 2", "切换至「供应商与模型配置」"),
                ("Ctrl + F", "聚焦并全选搜索框"),
                ("F5 / Ctrl + R", "刷新看板用量数据 / 列表"),
                ("Esc", "清空搜索框并取消焦点"),
                ("F1", "打开此快捷键帮助面板"),
            ]),
            ("⚙️ 配置与操作", [
                ("Ctrl + S", "保存当前供应商与模型配置"),
                ("Ctrl + Enter", "将选中的模型设为系统默认"),
                ("Ctrl + N", "添加新的 API 供应商"),
                ("Ctrl + T", "测试当前端点连通性"),
                ("Ctrl + Shift + T", "并发测试全部供应商连通性与延迟"),
            ]),
        ]

        for g_title, items in groups:
            lbl_g = QtWidgets.QLabel(g_title)
            lbl_g.setObjectName("groupTitle")
            layout.addWidget(lbl_g)

            frame = QtWidgets.QFrame()
            frame.setObjectName("keyCard")
            grid = QtWidgets.QGridLayout(frame)
            grid.setContentsMargins(10, 8, 10, 8)
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(6)

            for row, (k_seq, desc) in enumerate(items):
                badge = QtWidgets.QLabel(k_seq)
                badge.setObjectName("keyBadge")
                badge.setAlignment(Qt.AlignCenter)
                grid.addWidget(badge, row, 0)

                lbl_desc = QtWidgets.QLabel(desc)
                lbl_desc.setObjectName("keyDesc")
                grid.addWidget(lbl_desc, row, 1)

            layout.addWidget(frame)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = QtWidgets.QPushButton("关闭 (Esc)")
        btn_close.setObjectName("closeBtn")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)


# =============================================================================
# 主窗口
# =============================================================================

class SnapshotsDialog(QtWidgets.QDialog):
    """列出 backups/ 下的配置快照，支持恢复（恢复后重启应用生效）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("恢复配置快照")
        self.resize(560, 380)

        layout = QtWidgets.QVBoxLayout(self)
        hint = QtWidgets.QLabel(
            f"每次保存前会自动备份到 {SNAPSHOTS_DIR}（保留最近 {SNAPSHOTS_KEEP} 份）。\n"
            "选中一份快照后点“恢复”，应用将重启以加载恢复的配置。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.listw = QtWidgets.QListWidget(self)
        if SNAPSHOTS_DIR.is_dir():
            for d in sorted(SNAPSHOTS_DIR.iterdir(), reverse=True):
                if not d.is_dir():
                    continue
                names = ", ".join(sorted(p.name for p in d.glob("*.json")))
                item = QtWidgets.QListWidgetItem(f"{d.name}    ({names})")
                item.setData(QtCore.Qt.UserRole, str(d))
                self.listw.addItem(item)
        layout.addWidget(self.listw, 1)

        btns = QtWidgets.QHBoxLayout()
        btn_open = QtWidgets.QPushButton("📂 打开备份目录")
        btn_open.clicked.connect(lambda: os.startfile(str(SNAPSHOTS_DIR)) if SNAPSHOTS_DIR.is_dir() else None)
        btn_restore = QtWidgets.QPushButton("⏪ 恢复选中快照")
        btn_restore.clicked.connect(self._restore)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_open)
        btns.addStretch(1)
        btns.addWidget(btn_restore)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

    def _restore(self):
        item = self.listw.currentItem()
        if item is None:
            QtWidgets.QMessageBox.information(self, "提示", "请先选中一份快照。")
            return
        src = Path(item.data(QtCore.Qt.UserRole))
        ret = QtWidgets.QMessageBox.question(
            self, "确认恢复",
            "将把当前配置文件覆盖为该快照内容，确定继续？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if ret != QtWidgets.QMessageBox.Yes:
            return
        try:
            for f in SNAPSHOT_FILES:
                s = src / f
                if s.exists():
                    shutil.copy2(s, AGENT_DIR / f)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "恢复失败", str(exc))
            return
        self.accept()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, store: ConfigStore):
        super().__init__()
        self.store = store
        self.tray = None  # 由 main() 注入，用于增删后刷新托盘菜单
        self._testing = False
        self._closed = False
        self.setWindowTitle("pi API Switcher")
        self.resize(1060, 740)
        self.setMinimumSize(880, 580)

        # 应用配置：主题 + 字体
        self.app_config = _load_app_config()
        self.theme_name = self.app_config.get("theme", "terminal")
        self.font_family = self.app_config.get("font", "")
        self.font_size = int(self.app_config.get("font_size", 13))
        global COLORS
        COLORS = THEMES.get(self.theme_name, THEMES["terminal"])

        # 测速结果缓存 {provider_name: {"ok": bool, "latency": int}}
        self._provider_test_results = {}
        self._batch_tester = None  # 当前批量测速线程（BatchEndpointTester）

        self._build_menu()  # 菜单栏（必须在 _build_ui 前）
        self._build_ui()
        self._setup_shortcuts()  # 注册全局快捷键
        self._apply_font()
        self._apply_style()
        if hasattr(self, 'dashboard_tab') and hasattr(self.dashboard_tab, '_apply_theme_to_children'):
            self.dashboard_tab._apply_theme_to_children(COLORS)
        self.refresh_list()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Tab Widget 包含「📊 用量看板」与「⚙️ API 配置」
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.setDocumentMode(True)

        # Tab 1: 现代仪表盘
        self.dashboard_tab = ModernDashboardTab(self)
        self.tabs.addTab(self.dashboard_tab, "📊 用量统计与监控")
        self.tabs.setTabToolTip(0, "用量统计与监控看板 (Ctrl+1)")

        # Tab 2: 原有 API 供应商配置页
        config_page = QtWidgets.QWidget()
        config_root = QtWidgets.QHBoxLayout(config_page)
        config_root.setContentsMargins(0, 0, 0, 0)
        config_root.setSpacing(0)

        # ---- 左侧：provider 列表 ----
        left = QtWidgets.QWidget()
        left.setMinimumWidth(220)
        left.setMaximumWidth(460)
        left.setObjectName("sidebar")
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 12, 12)
        lv.setSpacing(8)

        title = QtWidgets.QLabel("API 供应商")
        title.setObjectName("sidebarTitle")
        lv.addWidget(title)

        # 搜索过滤框
        self.ed_search = QtWidgets.QLineEdit()
        self.ed_search.setPlaceholderText("🔍 搜索供应商或模型 (Ctrl+F)...")
        self.ed_search.setToolTip("搜索供应商或模型名称 (Ctrl+F，按 Esc 清空)")
        self.ed_search.setObjectName("sidebarSearch")
        self.ed_search.textChanged.connect(self._on_search_text_changed)
        lv.addWidget(self.ed_search)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setObjectName("providerList")
        self.list_widget.currentItemChanged.connect(self.on_select)
        lv.addWidget(self.list_widget, 1)

        btn_row = QtWidgets.QGridLayout()
        btn_row.setHorizontalSpacing(6)
        btn_row.setVerticalSpacing(6)
        self.btn_add = QtWidgets.QPushButton("＋ 添加")
        self.btn_rename = QtWidgets.QPushButton("重命名")
        self.btn_del = QtWidgets.QPushButton("删除")
        self.btn_test_all = QtWidgets.QPushButton("⚡ 全部测速")
        self.btn_add.setObjectName("accentBtn")
        self.btn_rename.setObjectName("ghostBtn")
        self.btn_del.setObjectName("dangerBtn")
        self.btn_test_all.setObjectName("ghostBtn")
        self.btn_add.setToolTip("添加新的 API 供应商端点 (Ctrl+N)")
        self.btn_rename.setToolTip("修改当前供应商名称，并迁移关联配置")
        self.btn_del.setToolTip("删除当前选中的供应商")
        self.btn_test_all.setToolTip("并发测试所有供应商端点连通性并显示延迟 (Ctrl+Shift+T)")
        self.btn_add.clicked.connect(self.on_add)
        self.btn_rename.clicked.connect(self.on_rename_provider)
        self.btn_del.clicked.connect(self.on_del)
        self.btn_test_all.clicked.connect(self.on_test_all_providers)
        btn_row.addWidget(self.btn_add, 0, 0)
        btn_row.addWidget(self.btn_rename, 0, 1)
        btn_row.addWidget(self.btn_del, 1, 0)
        btn_row.addWidget(self.btn_test_all, 1, 1)
        btn_row.setColumnStretch(0, 1)
        btn_row.setColumnStretch(1, 1)
        lv.addLayout(btn_row)

        self.sidebar_footer = QtWidgets.QLabel("v1.2 · pi API Switcher")
        self.sidebar_footer.setObjectName("sidebarFooter")
        self.sidebar_footer.setAlignment(QtCore.Qt.AlignCenter)
        lv.addWidget(self.sidebar_footer)

        # 使用 QSplitter 允许按需拖动供应商栏宽度。
        self.provider_splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.provider_splitter.setObjectName("providerSplitter")
        self.provider_splitter.setChildrenCollapsible(False)
        self.provider_splitter.setHandleWidth(6)
        self.provider_splitter.addWidget(left)

        # ---- 右侧：详情/编辑 ----
        right = QtWidgets.QWidget()
        right.setObjectName("content")
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(20, 20, 20, 20)
        rv.setSpacing(12)

        self.detail_title = QtWidgets.QLabel("未选择供应商")
        self.detail_title.setObjectName("detailTitle")
        rv.addWidget(self.detail_title)

        # 空状态提示（无 provider 时显示）
        self.empty_hint = QtWidgets.QWidget()
        self.empty_hint.setObjectName("emptyHint")
        empty_lay = QtWidgets.QVBoxLayout(self.empty_hint)
        empty_lay.setAlignment(QtCore.Qt.AlignCenter)
        self.empty_icon = QtWidgets.QLabel("π")
        self.empty_icon.setObjectName("emptyIcon")
        self.empty_icon.setAlignment(QtCore.Qt.AlignCenter)
        empty_text = QtWidgets.QLabel("从左侧选择或添加供应商")
        empty_text.setObjectName("emptyText")
        empty_text.setAlignment(QtCore.Qt.AlignCenter)
        empty_sub = QtWidgets.QLabel("支持管理多个 API 端点，一键切换默认模型")
        empty_sub.setObjectName("emptySubText")
        empty_sub.setAlignment(QtCore.Qt.AlignCenter)
        empty_lay.addWidget(self.empty_icon)
        empty_lay.addWidget(empty_text)
        empty_lay.addWidget(empty_sub)

        # 空状态图标浮动动画
        self._empty_float_offset = 0.0
        self._empty_float_dir = 1.0
        self._empty_timer = QtCore.QTimer(self)
        self._empty_timer.setInterval(100)
        self._empty_timer.timeout.connect(self._animate_empty_icon)

        # 可操作的引导按钮：直接复用 on_add
        self.btn_empty_add = QtWidgets.QPushButton("＋ 添加第一个供应商")
        self.btn_empty_add.setObjectName("accentBtn")
        self.btn_empty_add.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_empty_add.setFixedWidth(220)
        self.btn_empty_add.clicked.connect(self.on_add)
        empty_lay.addSpacing(12)
        empty_lay.addWidget(self.btn_empty_add, 0, QtCore.Qt.AlignCenter)
        rv.addWidget(self.empty_hint)

        # 表单
        form = QtWidgets.QGridLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)

        self.ed_baseurl = self._add_field(form, 0, "Base URL")
        btn_site_fill = QtWidgets.QPushButton("🌐")
        btn_site_fill.setObjectName("eyeBtn")
        btn_site_fill.setFixedWidth(36)
        btn_site_fill.setToolTip("从站点管理选择一个站点，自动填充 Base URL 与 API Key")
        btn_site_fill.clicked.connect(self._on_fill_from_site)
        self.btn_add_to_sites = QtWidgets.QPushButton("📥")
        self.btn_add_to_sites.setObjectName("eyeBtn")
        self.btn_add_to_sites.setFixedWidth(36)
        self.btn_add_to_sites.setToolTip("把当前供应商的 Base URL 与 API Key 一键加入站点管理")
        self.btn_add_to_sites.clicked.connect(self._on_add_provider_to_sites)
        url_btns = QtWidgets.QHBoxLayout()
        url_btns.setSpacing(4)
        url_btns.addWidget(btn_site_fill)
        url_btns.addWidget(self.btn_add_to_sites)
        form.addLayout(url_btns, 0, 2)

        # API Key + 显示/隐藏按钮
        form.addWidget(QtWidgets.QLabel("API Key"), 1, 0)
        key_row = QtWidgets.QHBoxLayout()
        key_row.setSpacing(6)
        self.ed_apikey = QtWidgets.QLineEdit()
        self.ed_apikey.setEchoMode(QtWidgets.QLineEdit.Password)
        self.ed_apikey.setPlaceholderText("sk-...")
        self.btn_eye = QtWidgets.QPushButton("👁")
        self.btn_eye.setObjectName("eyeBtn")
        self.btn_eye.setFixedWidth(36)
        self.btn_eye.setCheckable(True)
        self.btn_eye.clicked.connect(self.on_toggle_key_visible)
        key_row.addWidget(self.ed_apikey, 1)
        key_row.addWidget(self.btn_eye)
        form.addLayout(key_row, 1, 1)

        self.ed_model_name = self._add_field(form, 2, "显示名")

        form.addWidget(QtWidgets.QLabel("缓存兼容"), 3, 0)
        cache_row = QtWidgets.QHBoxLayout()
        self.cache_policy_combo = QtWidgets.QComboBox()
        for label, value in CACHE_POLICY_OPTIONS:
            self.cache_policy_combo.addItem(label, value)
        self.cache_policy_combo.setToolTip(
            "自动安全：官方 OpenAI 保留缓存参数，第三方端点自动剥离；\n"
            "严格兼容：同时禁用 prompt_cache_key、24h retention 和会话亲和头；\n"
            "仅缓存键/长缓存：仅在端点文档明确支持时启用。"
        )
        self.cache_policy_hint = QtWidgets.QLabel("第三方 OpenAI-compatible 端点建议使用自动安全")
        self.cache_policy_hint.setObjectName("fieldHint")
        cache_row.addWidget(self.cache_policy_combo, 1)
        cache_row.addWidget(self.cache_policy_hint)
        form.addLayout(cache_row, 3, 1)

        rv.addLayout(form)

        # ---- 多模型表格 ----
        models_label = QtWidgets.QLabel("模型列表（可配置多个）")
        models_label.setObjectName("sectionLabel")
        rv.addWidget(models_label)

        # 列：0 模型ID / 1 显示名 / 2 推理 / 3 输入 / 4 思考上限 / 5 上下文 / 6 最大输出 / 7 视觉模型
        self.model_table = QtWidgets.QTableWidget(0, 8)
        self.model_table.setHorizontalHeaderLabels(
            ["模型 ID", "显示名", "推理", "输入", "思考上限", "上下文", "最大输出", "视觉模型"]
        )
        self.model_table.setObjectName("modelTable")
        self.model_table.setAlternatingRowColors(True)
        # 固定数字列的最小内容宽度；窄窗口时使用水平滚动，避免相邻单元格文字重叠。
        self.model_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.model_table.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.model_table.setWordWrap(False)
        self.model_table.setTextElideMode(QtCore.Qt.ElideNone)
        self.model_table.horizontalHeader().setMinimumSectionSize(40)
        self.model_table.horizontalHeader().setStretchLastSection(False)
        self.model_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.model_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.model_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self.model_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)  # 输入列
        self.model_table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.Fixed)
        self.model_table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.Fixed)  # 上下文
        self.model_table.horizontalHeader().setSectionResizeMode(6, QtWidgets.QHeaderView.Fixed)  # 最大输出
        self.model_table.horizontalHeader().setSectionResizeMode(7, QtWidgets.QHeaderView.Fixed)  # 视觉模型
        # 固定列宽（加宽上下文/最大输出，避免大数字如 1048576 挤压重叠）
        self.model_table.setColumnWidth(2, 48)   # 推理
        self.model_table.setColumnWidth(3, 110)  # 输入
        self.model_table.setColumnWidth(4, 88)   # 思考上限
        self.model_table.setColumnWidth(5, 128)  # 上下文，容纳 7-8 位数字
        self.model_table.setColumnWidth(6, 112)  # 最大输出，避免与上下文列重叠
        self.model_table.setColumnWidth(7, 150)  # 视觉模型
        self.model_table.setMinimumWidth(48 + 110 + 88 + 110 + 88 + 128 + 112 + 150 + 24)
        # 关键：禁用排序，避免点击表头时 cell widget（复选框/下拉框/按钮）错位
        self.model_table.setSortingEnabled(False)
        # 数字列双击编辑，其余列通过 widget 交互；文本列双击编辑
        self.model_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        self.model_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.model_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.model_table.verticalHeader().setVisible(False)
        self.model_table.verticalHeader().setDefaultSectionSize(40)
        self.model_table.setMinimumHeight(160)
        rv.addWidget(self.model_table)

        # 模型表格操作按钮
        model_btn_row = QtWidgets.QHBoxLayout()
        self.btn_add_model = QtWidgets.QPushButton("＋ 添加模型")
        self.btn_del_model = QtWidgets.QPushButton("删除选中")
        self.btn_add_model.setObjectName("ghostBtn")
        self.btn_del_model.setObjectName("ghostBtn")
        self.btn_add_model.clicked.connect(self.on_add_model_row)
        self.btn_del_model.clicked.connect(self.on_del_model_row)
        model_btn_row.addWidget(self.btn_add_model)
        model_btn_row.addWidget(self.btn_del_model)
        model_btn_row.addStretch(1)
        rv.addLayout(model_btn_row)

        # 默认标记
        self.lbl_default = QtWidgets.QLabel("")
        self.lbl_default.setObjectName("defaultBadge")
        rv.addWidget(self.lbl_default)

        rv.addStretch(1)

        # 底部按钮
        bottom = QtWidgets.QHBoxLayout()
        self.btn_test = QtWidgets.QPushButton("⚡ 测试连通性")
        self.btn_save = QtWidgets.QPushButton("保存")
        self.btn_default = QtWidgets.QPushButton("★ 设为默认")
        self.btn_test.setObjectName("ghostBtn")
        self.btn_save.setObjectName("accentBtn")
        self.btn_default.setObjectName("primaryBtn")
        self.btn_test.setToolTip("测试当前端点连通性与模型列表 (Ctrl+T)")
        self.btn_save.setToolTip("保存当前供应商与模型配置 (Ctrl+S)")
        self.btn_default.setToolTip("将当前选中的模型设为系统默认并写入 settings.json (Ctrl+Enter)")
        self.btn_test.clicked.connect(self.on_test)
        self.btn_save.clicked.connect(self.on_save)
        self.btn_default.clicked.connect(self.on_set_default)
        bottom.addWidget(self.btn_test)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_save)
        bottom.addWidget(self.btn_default)
        rv.addLayout(bottom)

        # 状态栏（含 loading 动画）
        status_row = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("就绪")
        self.status.setObjectName("statusBar")
        self.loading_dots = QtWidgets.QLabel("")
        self.loading_dots.setObjectName("loadingDots")
        self.loading_dots.setVisible(False)
        self._loading_timer = QtCore.QTimer(self)
        self._loading_timer.setInterval(400)
        self._loading_dots_count = 0
        self._loading_timer.timeout.connect(self._animate_loading)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.loading_dots)
        rv.addLayout(status_row)

        self.provider_splitter.addWidget(right)
        self.provider_splitter.setStretchFactor(0, 0)
        self.provider_splitter.setStretchFactor(1, 1)
        self.provider_splitter.setSizes([260, 800])
        config_root.addWidget(self.provider_splitter, 1)

        self.tabs.addTab(config_page, "⚙️ 供应商与模型配置")
        self.tabs.setTabToolTip(1, "供应商端点与模型配置 (Ctrl+2)")

        self.ext_tab = SkillsExtensionsTab(self.store)
        self.tabs.addTab(self.ext_tab, "🧩 技能与插件")

        self.sites_tab = SitesTab(self)
        self.tabs.addTab(self.sites_tab, "🌐 站点管理")
        root.addWidget(self.tabs)

    def _add_field(self, form, row, label):
        lbl = QtWidgets.QLabel(label)
        lbl.setFixedWidth(90)
        form.addWidget(lbl, row, 0)
        ed = QtWidgets.QLineEdit()
        form.addWidget(ed, row, 1)
        return ed

    # ---- 样式 ----
    def _make_theme_icon(self, color_hex):
        pix = QtGui.QPixmap(14, 14)
        pix.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setBrush(QtGui.QBrush(QtGui.QColor(color_hex)))
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(1, 1, 12, 12)
        p.end()
        return QtGui.QIcon(pix)

    def _build_menu(self):
        """构建顶部菜单栏：外观（主题 + 字体）、工具（快照恢复）。"""
        bar = self.menuBar()
        bar.setObjectName("menuBar")

        # 工具菜单
        menu_tools = bar.addMenu("工具")
        act_snapshots = menu_tools.addAction("⏪ 恢复配置快照...")
        act_snapshots.triggered.connect(self.show_snapshots_dialog)

        # 外观菜单
        menu_view = bar.addMenu("外观")

        # 主题子菜单
        menu_theme = menu_view.addMenu("主题")
        theme_names = {
            "modern_light": "Modern Light (现代微拟态/卡片风格)",
            "terminal": "Terminal（黑灰+暖橙）",
            "codex": "Codex（白色+绿调）",
            "claude": "Claude Code（橙赭+米色）",
            "deepseek": "DeepSeek（深蓝+青）",
            "teal": "青绿+靛蓝",
            "night": "GitHub Night（紫+蓝）",
            "light": "浅色（灰白）",
        }
        theme_group = QtWidgets.QActionGroup(self)
        theme_group.setExclusive(True)
        for key, label in theme_names.items():
            t_clr = THEMES.get(key, {}).get("accent", "#3b82f6")
            act = menu_theme.addAction(self._make_theme_icon(t_clr), label)
            act.setCheckable(True)
            act.setChecked(key == self.theme_name)
            theme_group.addAction(act)
            act.triggered.connect(lambda _=False, k=key: self._switch_theme(k))

        # 字体子菜单
        menu_font = menu_view.addMenu("字体")
        # 自动检测可用字体
        self._available_fonts = detect_available_fonts()
        font_group = QtWidgets.QActionGroup(self)
        font_group.setExclusive(True)
        # “跟随系统”项
        act_sys = menu_font.addAction("跟随系统")
        act_sys.setCheckable(True)
        act_sys.setChecked(not self.font_family)
        font_group.addAction(act_sys)
        act_sys.triggered.connect(lambda: self._switch_font(""))
        menu_font.addSeparator()
        for fam in self._available_fonts:
            act = menu_font.addAction(fam)
            act.setCheckable(True)
            act.setChecked(fam == self.font_family)
            font_group.addAction(act)
            act.triggered.connect(lambda _=False, f=fam: self._switch_font(f))

        # 字号子菜单
        menu_size = menu_view.addMenu("字号")
        size_group = QtWidgets.QActionGroup(self)
        size_group.setExclusive(True)
        for sz in [11, 12, 13, 14, 15, 16]:
            act = menu_size.addAction(f"{sz} px")
            act.setCheckable(True)
            act.setChecked(sz == self.font_size)
            size_group.addAction(act)
            act.triggered.connect(lambda _=False, s=sz: self._switch_font_size(s))

        # 帮助菜单
        menu_help = bar.addMenu("帮助")
        act_shortcuts = menu_help.addAction("⌨️ 快捷键速查 (F1)")
        act_shortcuts.triggered.connect(self.show_shortcuts_dialog)
        menu_help.addSeparator()
        act_about = menu_help.addAction("ℹ️ 关于 pi API Switcher")
        act_about.triggered.connect(self.show_about_dialog)

    def _setup_shortcuts(self):
        """注册全局高效快捷键映射。"""
        # 保存与设为默认
        QShortcut(QKeySequence("Ctrl+S"), self, self.on_save)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.on_set_default)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self.on_set_default)

        # 连通性测试
        QShortcut(QKeySequence("Ctrl+T"), self, self.on_test)
        QShortcut(QKeySequence("Ctrl+Shift+T"), self, self.on_test_all_providers)

        # 供应商管理
        QShortcut(QKeySequence("Ctrl+N"), self, self.on_add)
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search)

        # 选项卡切换
        QShortcut(QKeySequence("Ctrl+1"), self, lambda: self.tabs.setCurrentIndex(0))
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.tabs.setCurrentIndex(1))

        # 刷新
        QShortcut(QKeySequence("Ctrl+R"), self, self._on_global_refresh)
        QShortcut(QKeySequence("F5"), self, self._on_global_refresh)

        # 帮助与退出
        QShortcut(QKeySequence("F1"), self, self.show_shortcuts_dialog)
        QShortcut(QKeySequence("Esc"), self, self._on_escape)

    def _focus_search(self):
        if self.tabs.currentIndex() != 1:
            self.tabs.setCurrentIndex(1)
        self.ed_search.setFocus()
        self.ed_search.selectAll()

    def _on_global_refresh(self):
        if self.tabs.currentIndex() == 0:
            self.dashboard_tab.load_data()
            self.show_toast("🔄 看板用量数据已刷新")
        else:
            self.refresh_list()
            self.show_toast("🔄 供应商配置列表已刷新")

    def _on_escape(self):
        if self.ed_search.hasFocus():
            self.ed_search.clear()
            self.list_widget.setFocus()

    def show_shortcuts_dialog(self):
        c = THEMES.get(self.theme_name, THEMES["terminal"])
        dlg = ShortcutsDialog(self, theme=c)
        dlg.exec_()

    def _on_add_provider_to_sites(self):
        """一键把当前编辑中的供应商 (Base URL + API Key) 加入站点管理。"""
        base_url = self.ed_baseurl.text().strip()
        if not base_url:
            self.set_status("Base URL 为空，无法加入站点管理", "warn")
            return
        key = self.ed_apikey.text().strip()
        sites = self.sites_tab._sites()
        # 同 URL 同 Key 视为重复；同 URL 不同 Key 是不同账号，允许并存
        for s in sites:
            if s.get("baseUrl", "") == base_url and s.get("apiKey", "") == key:
                self.set_status(f"已存在于站点管理：{s.get('name', '')}", "info")
                self.show_toast(f"ℹ️ 站点「{s.get('name', '')}」已存在，无需重复添加")
                return
        name = self.current_name() or base_url.split("//", 1)[-1].split("/", 1)[0]
        sites.append({"name": name, "baseUrl": base_url, "apiKey": key,
                      "note": f"来自供应商 {self.current_name()}"})
        self.sites_tab._save()
        self.sites_tab.reload()
        self.show_toast(f"✓ 已加入站点管理：{name}")
        self.set_status(f"已加入站点管理：{name}", "ok")

    def _on_fill_from_site(self):
        """从站点管理选一个站点，填充 Base URL 与 API Key。"""
        site = self.sites_tab.fill_provider_from_site()
        if not site:
            return
        self.ed_baseurl.setText(site.get("baseUrl", ""))
        if site.get("apiKey"):
            self.ed_apikey.setText(site["apiKey"])
            self.set_status(f"已从站点「{site['name']}」填充 Base URL 与 API Key", "ok")
        else:
            self.set_status(f"已从站点「{site['name']}」填充 Base URL（该站点未配置 Key）", "info")

    def show_snapshots_dialog(self):
        dlg = SnapshotsDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            ret = QtWidgets.QMessageBox.question(
                self, "重启应用",
                "快照已恢复。立即重启应用以加载恢复的配置？\n（选择“否”则下次手动启动时生效）",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes)
            if ret == QtWidgets.QMessageBox.Yes:
                # 重启自身：frozen 时 sys.executable 是 exe，开发态是 python.exe
                subprocess.Popen([sys.executable] + sys.argv,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
                QtWidgets.qApp.quit()

    def show_about_dialog(self):
        QtWidgets.QMessageBox.about(
            self,
            "关于 pi API Switcher",
            "<h3>pi API Switcher</h3>"
            "<p>CC Switch 风格的 pi API / 模型配置桌面管理器 (PyQt5)。</p>"
            "<p>支持快速切换默认模型、用量监控看板、并发测速、视觉模型桥接、缓存兼容防护与全局快捷键体系。</p>"
            "<p>项目主页: <a href='https://github.com/2931735386-stack/pi-api-'>GitHub Repository</a></p>"
        )

    def _switch_theme(self, name):
        self.theme_name = name
        self.app_config["theme"] = name
        _save_app_config(self.app_config)
        global COLORS
        COLORS = THEMES.get(name, THEMES["terminal"])
        self._apply_style()
        if hasattr(self, 'dashboard_tab') and hasattr(self.dashboard_tab, '_apply_theme_to_children'):
            self.dashboard_tab._apply_theme_to_children(COLORS)
        self.set_status(f"已切换主题：{name}", "ok")
        self.show_toast(f"🎨 已应用主题：{name}")

    def _switch_font(self, family):
        self.font_family = family
        self.app_config["font"] = family
        _save_app_config(self.app_config)
        self._apply_font()
        self._apply_style()
        self.set_status(f"已切换字体：{family or '跟随系统'}", "ok")
        self.show_toast(f"🔤 字体已切换：{family or '跟随系统'}")

    def _switch_font_size(self, size):
        self.font_size = size
        self.app_config["font_size"] = size
        _save_app_config(self.app_config)
        self._apply_font()
        self._apply_style()
        self.set_status(f"已切换字号：{size} px", "ok")
        self.show_toast(f"🔍 字号已设为：{size} px")

    def _apply_font(self):
        """统一设置全局字体。"""
        from PyQt5.QtGui import QFont
        fam = self.font_family or None
        font = QFont(fam, self.font_size)
        # 防止中文乱码：明确指定一个 fallback
        font.setStyleHint(QFont.SansSerif)
        QtWidgets.QApplication.instance().setFont(font)

    def _apply_style(self):
        """重新生成并应用全局样式表。"""
        c = THEMES.get(self.theme_name, THEMES["terminal"])
        parts = [
            self._qss_global(c),
            self._qss_menubar(c),
            self._qss_sidebar(c),
            self._qss_content(c),
            self._qss_empty_state(c),
            self._qss_model_table(c),
            self._qss_inputs(c),
            self._qss_buttons(c),
            self._qss_status(c),
            self._qss_tabs(c),
            self._qss_cards(c),
            self._qss_filter_bar(c),
            self._qss_scrollbar(c),
        ]
        self.setStyleSheet("\n".join(parts))

    @staticmethod
    def _qss_global(c):
        return f"""
            /* === 全局 === */
            QMainWindow, QWidget {{ background: {c['bg']}; color: {c['text']}; }}
            QLabel {{ color: {c['text_dim']}; font-size: 13px; }}
            QLabel#fieldHint {{ color: {c['text_dim']}; font-size: 11px; padding-left: 6px; }}
            QToolTip {{
                background-color: {c['panel']};
                color: {c['text']};
                border: 1px solid {c['accent']};
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 12px;
            }}
        """

    @staticmethod
    def _qss_menubar(c):
        bt = c["btn_text"]
        return f"""
            /* === 菜单栏 === */
            QMenuBar {{ background: {c['bg_alt']}; color: {c['text_dim']};
                         border-bottom: 1px solid {c['border']}; padding: 3px 8px; }}
            QMenuBar::item {{ background: transparent; padding: 5px 12px; border-radius: 6px;
                               font-size: 13px; }}
            QMenuBar::item:selected {{ background: {c['panel']}; color: {c['accent']}; }}
            QMenu {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']};
                     padding: 6px; border-radius: 8px; }}
            QMenu::item {{ padding: 7px 28px 7px 20px; border-radius: 6px; font-size: 13px; }}
            QMenu::item:selected {{ background: {c['accent']}; color: {bt}; }}
            QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 10px; }}
        """

    @staticmethod
    def _qss_sidebar(c):
        return f"""
            /* === 侧边栏 === */
            #sidebar {{ background: {c['bg_alt']};
                         border-right: 1px solid {c['border']}; }}
            #sidebarTitle {{ font-size: 15px; font-weight: 700; color: {c['accent']};
                              padding: 6px 4px 2px 4px; letter-spacing: 0.5px; }}
            #sidebarSearch {{
                background: {c['panel']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                color: {c['text']};
                margin-bottom: 4px;
            }}
            #sidebarSearch:focus {{
                border-color: {c['accent']};
            }}
            #sidebarFooter {{ color: {c['text_dim']}; font-size: 11px; padding: 6px 0 2px 0; opacity: 0.7; }}
            #providerList {{ background: transparent; border: none; outline: none; font-size: 13px; }}
            #providerList::item {{ padding: 11px 10px; border-radius: 8px; margin: 1px 0;
                                    border-left: 3px solid transparent; }}
            #providerList::item:selected {{ background: {c['panel']}; color: {c['accent']};
                                             border-left: 3px solid {c['accent']}; font-weight: 600; }}
            #providerList::item:hover:!selected {{ background: {c['panel']}; }}
        """

    @staticmethod
    def _qss_content(c):
        return f"""
            /* === 右侧内容区 === */
            #content {{ background: {c['bg']}; }}
            #detailTitle {{ font-size: 24px; font-weight: 700; color: {c['text']};
                             padding: 2px 0 4px 0; letter-spacing: -0.3px; }}
            #sectionLabel {{ font-size: 13px; font-weight: 600; color: {c['text']};
                              margin-top: 10px; margin-bottom: 4px;
                              border-left: 3px solid {c['accent']}; border-bottom: none;
                              padding-left: 8px; }}
        """

    @staticmethod
    def _qss_empty_state(c):
        return f"""
            /* === 空状态 === */
            #emptyHint {{ background: transparent; }}
            #emptyIcon {{ font-size: 64px; color: {c['border']}; font-weight: 300;
                           padding-bottom: 8px; }}
            #emptyText {{ color: {c['text_dim']}; font-size: 16px; font-weight: 500;
                           padding: 0; }}
            #emptySubText {{ color: {c['border']}; font-size: 13px; padding-top: 4px; }}
        """

    @staticmethod
    def _qss_model_table(c):
        return f"""
            /* === 模型表格 === */
            #modelTable {{
                background: {c['panel']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                gridline-color: {c['border']};
                color: {c['text']};
                font-size: 13px;
                selection-background-color: transparent;
                selection-color: {c['text']};
            }}
            #modelTable::item {{
                padding: 5px 8px;
            }}
            #modelTable::item:alternate {{
                background: {c['bg_alt']};
            }}
            #modelTable::item:selected {{
                background: {c['bg_alt']};
                color: {c['text']};
            }}
            #modelTable QWidget {{
                background: transparent;
            }}
            /* 原地编辑器必须不透明，否则会和底层 item 文本发生重影。 */
            #modelTable QLineEdit {{
                background: {c['panel']};
                color: {c['text']};
                border: 1px solid {c['accent']};
                border-radius: 3px;
                padding: 0 6px;
                selection-background-color: {c['accent']};
                selection-color: {c['btn_text']};
            }}
            #modelTable QComboBox {{
                background: {c['panel']};
                color: {c['text']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 12px;
            }}
            #modelTable QComboBox:hover {{
                border-color: {c['accent']};
            }}
            #modelTable QCheckBox {{
                background: transparent;
            }}
            QHeaderView::section {{
                background: {c['bg_alt']};
                color: {c['text_dim']};
                border: none;
                padding: 7px 10px;
                font-size: 12px;
                font-weight: 600;
            }}
            /* === 进度条 === */
            QProgressBar#modelProgressBar {{
                background: {c['border']};
                border-radius: 2px;
                border: none;
            }}
        """

    @staticmethod
    def _qss_inputs(c):
        bt = c["btn_text"]
        return f"""
            /* === 输入框 === */
            QLineEdit {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px;
                         padding: 9px 12px; font-size: 13px; color: {c['text']}; }}
            QLineEdit:focus {{ border: 1px solid {c['accent']}; }}
            QLineEdit:disabled {{ background: {c['bg_alt']}; color: {c['text_dim']}; }}
            QCheckBox {{ color: {c['text_dim']}; font-size: 13px; spacing: 6px; }}
            QCheckBox::indicator {{ width: 16px; height: 16px; }}
            QComboBox {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']};
                         border-radius: 6px; padding: 5px 10px; font-size: 13px; }}
            QComboBox:hover {{ border-color: {c['text_dim']}; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['text']};
                                            border: 1px solid {c['border']}; border-radius: 6px;
                                            selection-background-color: {c['accent']};
                                            selection-color: {bt}; outline: none; }}
        """

    @staticmethod
    def _qss_buttons(c):
        bt = c["btn_text"]
        accent2_hover = c["accent_2"]
        return f"""
            /* === 按钮 === */
            QPushButton {{ border: none; border-radius: 6px; padding: 9px 18px;
                            font-size: 13px; font-weight: 600; }}
            #accentBtn {{ background: {c['accent']}; color: {bt}; }}
            #accentBtn:hover {{ background: {c['accent_hover']}; }}
            #accentBtn:pressed {{ background: {c['panel']}; color: {c['text']}; }}
            #accentBtn:disabled {{ background: {c['border']}; color: {c['text_dim']}; }}
            #primaryBtn {{ background: {c['accent_2']}; color: #ffffff; }}
            #primaryBtn:hover {{ background: {accent2_hover}; }}
            #primaryBtn:pressed {{ background: {c['panel']}; color: {c['text']}; }}
            #primaryBtn:disabled {{ background: {c['border']}; color: {c['text_dim']}; }}
            #dangerBtn {{ background: transparent; color: {c['red']}; border: 1px solid {c['red']}; }}
            #dangerBtn:hover {{ background: {c['red']}; color: {bt}; }}
            #dangerBtn:pressed {{ background: {c['red']}; color: {bt}; }}
            #ghostBtn {{ background: transparent; color: {c['text_dim']}; border: 1px solid {c['border']}; }}
            #ghostBtn:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}
            #ghostBtn:pressed {{ background: {c['panel']}; }}
            #ghostBtn:disabled {{ color: {c['border']}; }}
            #eyeBtn {{ background: transparent; color: {c['text_dim']}; border: 1px solid {c['border']};
                        border-radius: 6px; font-size: 15px; }}
            #eyeBtn:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}
            #eyeBtn:checked {{ background: {c['accent']}; color: {bt}; border-color: {c['accent']}; }}
        """

    @staticmethod
    def _qss_status(c):
        return f"""
            /* === 默认标记 & 状态栏 === */
            #defaultBadge {{ color: {c['green']}; font-size: 13px; font-weight: 600;
                              padding: 4px 0; }}
            #statusBar {{ color: {c['text_dim']}; font-size: 12px; padding-top: 8px;
                          border-top: 1px solid {c['border']}; }}
            #loadingDots {{ color: {c['accent']}; font-size: 14px; font-weight: 700;
                             padding-top: 8px; min-width: 24px; }}
        """

    @staticmethod
    def _qss_tabs(c):
        return f"""
            /* === 现代主选项卡 (Tabs) === */
            QTabWidget#mainTabs::pane {{
                border: none;
                background: {c['bg']};
            }}
            QTabWidget#mainTabs QTabBar::tab {{
                background: {c['bg_alt']};
                color: {c['text_dim']};
                padding: 10px 22px;
                font-size: 13px;
                font-weight: 700;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 4px;
                border: 1px solid {c['border']};
                border-bottom: none;
            }}
            QTabWidget#mainTabs QTabBar::tab:selected {{
                background: {c['panel']};
                color: {c['accent']};
                border-top: 3px solid {c['accent']};
            }}
            QTabWidget#mainTabs QTabBar::tab:hover:!selected {{
                background: {c['panel']};
                color: {c['text']};
            }}
            /* === 全局 Toast 提示胶囊 === */
            #toastWidget {{
                background: {c['panel']};
                border: 1.5px solid {c['accent']};
                border-radius: 20px;
            }}
            #toastText {{
                font-size: 13px;
                font-weight: 700;
                color: {c['text']};
            }}
        """

    @staticmethod
    def _qss_cards(c):
        return f"""
            /* === KPI 卡片微拟态容器与文字层次 === */
            QFrame#kpiCard {{
                background-color: {c['panel']};
                border: 1px solid {c['border']};
                border-radius: 14px;
            }}
            QFrame#kpiCard:hover {{
                border: 1px solid {c['accent']};
            }}
            QFrame#modelCard {{
                background-color: {c['bg_alt']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
            QFrame#modelCard:hover {{
                border: 1px solid {c['accent']};
            }}
            QLabel#cardTitle {{
                font-size: 13px;
                font-weight: 700;
                color: {c['text_dim']};
            }}
            QLabel#cardBigValue {{
                font-size: 24px;
                font-weight: 800;
                color: {c['text']};
                letter-spacing: -0.5px;
            }}
            QLabel#cardSubInfo {{
                font-size: 11px;
                color: {c['text_dim']};
            }}
            QLabel#sectionHeaderTitle {{
                font-size: 16px;
                font-weight: 800;
                color: {c['text']};
            }}
            QLabel#dateRangeLabel {{
                font-size: 12px;
                font-weight: 500;
                color: {c['text_dim']};
            }}
            QLabel#rangeBadge {{
                font-size: 11px;
                font-weight: 600;
                color: {c['text_dim']};
                background: {c['bg_alt']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                padding: 2px 8px;
            }}
            QLabel#rowLabel {{
                font-size: 12px;
                color: {c['text_dim']};
            }}
            QLabel#rowValue {{
                font-size: 16px;
                font-weight: 800;
                color: {c['text']};
            }}
            QLabel#subHint {{
                font-size: 10px;
                color: {c['text_dim']};
            }}
            QLabel#modelName {{
                font-size: 12px;
                font-weight: 700;
                color: {c['text']};
            }}
            QLabel#modelSub {{
                font-size: 10px;
                color: {c['text_dim']};
            }}
        """

    @staticmethod
    def _qss_filter_bar(c):
        return f"""
            /* === Segmented Filter Buttons === */
            QFrame#segmentedFilterBox {{
                background: {c['bg_alt']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
            QPushButton#filterSegmentBtn {{
                background: transparent;
                color: {c['text_dim']};
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton#filterSegmentBtn:checked {{
                background: {c['panel']};
                color: {c['accent']};
                border: 1px solid {c['border']};
            }}
            QPushButton#filterRefreshBtn {{
                background: {c['panel']};
                color: {c['accent']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton#filterRefreshBtn:hover {{
                background: {c['bg_alt']};
                border-color: {c['accent']};
            }}
        """

    @staticmethod
    def _qss_scrollbar(c):
        """细条圆角滚动条，与主题协调（隐藏默认箭头按钮）。"""
        return f"""
            /* === 滚动条（细条圆角，主题化） === */
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 2px 0;
                border: none;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 8px;
                margin: 0 2px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {c['border']};
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::handle:horizontal {{
                background: {c['border']};
                border-radius: 3px;
                min-width: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {c['text_dim']};
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {c['text_dim']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                background: none;
                border: none;
                width: 0;
                height: 0;
            }}
            QScrollBar::add-page, QScrollBar::sub-page {{
                background: transparent;
            }}
        """

    # ---- 数据刷新 ----
    # Provider 名称前缀 → emoji 图标映射（便于侧边栏快速定位）
    _PROVIDER_ICONS = {
        "deepseek": "🌊",
        "claude": "🟠",
        "anthropic": "🟠",
        "openai": "🟢",
        "kimi": "🌙",
        "moonshot": "🌙",
        "glm": "💎",
        "zhipu": "💎",
        "gemini": "✨",
        "google": "✨",
        "qwen": "🐉",
        "grok": "⚡",
        "llama": "🦙",
        "mistral": "🌀",
    }

    def _provider_icon(self, name):
        """根据 provider 名称前缀返回 emoji 图标。"""
        low = (name or "").lower()
        for prefix, icon in self._PROVIDER_ICONS.items():
            if prefix in low:
                return icon
        return "🔌"

    def _animate_empty_icon(self):
        """空状态 π 图标缓慢上下浮动动画。"""
        self._empty_float_offset += 0.5 * self._empty_float_dir
        if abs(self._empty_float_offset) >= 5:
            self._empty_float_dir *= -1
        c = THEMES.get(self.theme_name, THEMES["terminal"])
        border_clr = c.get("border", "#e2e8f0")
        self.empty_icon.setStyleSheet(
            f"font-size: 64px; color: {border_clr}; font-weight: 300; "
            f"padding-bottom: {8 + self._empty_float_offset:.1f}px;"
        )

    def _on_search_text_changed(self, text):
        """左侧列表即时搜索过滤。"""
        self.refresh_list(keep_selection=True)

    def _provider_item_text(self, name, p=None):
        """构造侧边栏单个 provider 条目的显示文本（列表构建与测速徽章更新共用）。"""
        if p is None:
            p = self.store.get_provider(name)
        m_count = len(p.get("models", []))
        marker = "★ " if name == self.store.default_provider() else "   "
        icon = self._provider_icon(name)
        # 测速指示状态
        test_res = self._provider_test_results.get(name)
        latency_badge = ""
        if test_res:
            if test_res.get("ok"):
                lat = test_res.get("latency", 0)
                dot = "🟢" if lat < 600 else "🟡"
                latency_badge = f" {dot}{lat}ms"
            else:
                latency_badge = " 🔴超时"
        return f"{icon} {marker}{name} ({m_count}模型){latency_badge}"

    def _update_provider_test_badge(self, name):
        """只更新指定 provider 的列表条目文本。

        替代原先每个测速结果都全量重建 QListWidget 的做法（O(N²) 且闪烁、丢滚动位置）。
        若该条目被搜索过滤隐藏或列表尚未构建，跳过即可——下次 refresh_list 会带上新徽章。
        """
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.data(QtCore.Qt.UserRole) == name:
                it.setText(self._provider_item_text(name))
                break

    def refresh_list(self, select_name=None, keep_selection=False):
        current_sel = self.current_name() if keep_selection else select_name
        self.list_widget.clear()
        names = self.store.provider_names()
        search_kw = getattr(self, "ed_search", None).text().strip().lower() if hasattr(self, "ed_search") else ""

        for name in names:
            p = self.store.get_provider(name)
            models = p.get("models", [])

            # 搜索过滤匹配（provider 名、base_url、或模型 id/name）
            if search_kw:
                match_p = search_kw in name.lower() or search_kw in (p.get("baseUrl", "")).lower()
                match_m = any(search_kw in (m.get("id", "")).lower() or search_kw in (m.get("name", "")).lower() for m in models)
                if not (match_p or match_m):
                    continue

            item = QtWidgets.QListWidgetItem(self._provider_item_text(name, p))
            item.setData(QtCore.Qt.UserRole, name)
            self.list_widget.addItem(item)

        # 空状态：无 provider 时显示引导，隐藏表单
        has_any = len(names) > 0
        self.empty_hint.setVisible(not has_any)
        self.detail_title.setVisible(has_any)
        if not has_any:
            if hasattr(self, '_empty_timer') and not self._empty_timer.isActive():
                self._empty_timer.start()
        else:
            if hasattr(self, '_empty_timer') and self._empty_timer.isActive():
                self._empty_timer.stop()
        # 隐藏/显示表单区域
        for w in [self.ed_baseurl.parentWidget() or self.ed_baseurl,
                  self.ed_apikey.parentWidget() or self.ed_apikey,
                  self.model_table, self.btn_test, self.btn_save, self.btn_default,
                  self.btn_rename, self.lbl_default]:
            if w:
                w.setVisible(has_any)
        if current_sel:
            for i in range(self.list_widget.count()):
                if self.list_widget.item(i).data(QtCore.Qt.UserRole) == current_sel:
                    self.list_widget.setCurrentRow(i)
                    break
        elif self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def on_test_all_providers(self):
        """并发测速所有 Provider 端点并更新侧边栏呼吸灯与延迟。

        使用 BatchEndpointTester（线程池，最多 MAX_CONCURRENT_PROBES 路并发），
        避免 N 个端点同时开 N 个线程打爆本地端口或触发上游限流。
        """
        names = self.store.provider_names()
        if not names:
            self.set_status("无可用供应商", "warn")
            return

        # 上一批还在跑则先取消，快速连点不会叠加请求
        old_tester = getattr(self, "_batch_tester", None)
        if old_tester is not None and old_tester.isRunning():
            old_tester.stop()
            old_tester.wait(1500)

        self.btn_test_all.setEnabled(False)
        self.set_status(f"正在并发测速 {len(names)} 个供应商端点...", "info")
        self.show_toast(f"⚡ 开始测试 {len(names)} 个端点...")

        self._pending_batch_count = len(names)
        targets = []
        for name in names:
            p = self.store.get_provider(name)
            base_url = p.get("baseUrl", "").strip()
            key = self.store.api_key(name)
            if not base_url:
                # 空 URL 直接在主线程标记失败，不进线程池
                self._on_single_provider_tested(name, False, 0, "Base URL 为空", "[]")
                continue
            targets.append((name, base_url, key))

        if not targets:
            return  # 全部为空 URL 时上面已把计数归零并重新启用按钮
        self._batch_tester = BatchEndpointTester(targets, parent=self)
        self._batch_tester.result_ready.connect(self._on_single_provider_tested)
        self._batch_tester.start()

    @QtCore.pyqtSlot(str, bool, int, str, str)
    def _on_single_provider_tested(self, name, ok, latency, msg, payload):
        self._provider_test_results[name] = {"ok": ok, "latency": latency, "msg": msg}
        # 只更新对应条目，避免 N 个结果触发 N 次全量列表重建
        self._update_provider_test_badge(name)
        if hasattr(self, "_pending_batch_count"):
            self._pending_batch_count -= 1
            if self._pending_batch_count <= 0:
                self.btn_test_all.setEnabled(True)
                succ_cnt = sum(1 for v in self._provider_test_results.values() if v.get("ok"))
                self.set_status(f"测速完成：{succ_cnt}/{len(self._provider_test_results)} 个端点正常", "ok")
                self.show_toast(f"✓ 测速完成：{succ_cnt} 个端点正常")

    def _is_dirty_for(self, name: str) -> bool:
        """检测指定 provider 的表单内容是否有未保存改动（明确传 name，不依赖 currentItem）。

        根本原因：currentItemChanged 触发时 currentItem() 已指向新选中项。
        若直接调用 _is_dirty()，会拿新 provider 的存储数据与旧表单内容比较，
        永远不相等 → 每次切换都误弹「未保存的改动」弹窗。
        """
        if not name:
            return False
        p = self.store.get_provider(name)
        if not p:
            return False
        # Base URL
        if self.ed_baseurl.text().strip() != (p.get("baseUrl") or ""):
            return True
        # API Key
        cur_key = self.ed_apikey.text().strip()
        if cur_key != (self.store.api_key(name) or ""):
            return True
        # 显示名
        if self.ed_model_name.text().strip() != (p.get("name") or ""):
            return True
        # 缓存兼容策略
        if normalize_cache_policy(self.cache_policy_combo.currentData()) != self.store.cache_policy(name):
            return True
        # 模型表格
        table_models = self._read_model_table()
        stored_models = p.get("models", [])
        if len(table_models) != len(stored_models):
            return True
        for tm, sm in zip(table_models, stored_models):
            if tm.get("id") != sm.get("id"):
                return True
            if tm.get("name") != sm.get("name"):
                return True
            if tm.get("reasoning") != sm.get("reasoning", False):
                return True
            if tm.get("input") != sm.get("input"):
                return True
            if get_max_thinking_level(tm) != get_max_thinking_level(sm):
                return True
            if tm.get("contextWindow", 128000) != sm.get("contextWindow", 128000):
                return True
            if tm.get("maxTokens", 16384) != sm.get("maxTokens", 16384):
                return True
            stored_route = self.store.vision_route(name, sm)
            if normalize_vision_mode(tm.get("visionMode")) != stored_route.get("mode", "auto"):
                return True
            if normalize_candidates(tm.get("visionModel", "")) != stored_route.get("candidates", []):
                return True
        return False

    def _is_dirty(self) -> bool:
        """检测当前表单/表格是否有未保存的改动（保存/关闭等场景）。"""
        return self._is_dirty_for(self.current_name() or "")

    def _confirm_discard(self, prev_name: str = None) -> bool:
        """有未保存改动时弹窗确认是否丢弃。返回 True 表示可以继续切换。
        prev_name：切换前的 provider 名，传入时对该 provider 做检测；
                   不传时回退到 _is_dirty()（用于非切换场景）。"""
        dirty = self._is_dirty_for(prev_name) if prev_name else self._is_dirty()
        if not dirty:
            return True
        ret = QtWidgets.QMessageBox.question(
            self, "未保存的改动",
            "当前供应商有未保存的修改，是否丢弃并切换？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return ret == QtWidgets.QMessageBox.Yes

    def on_select(self, current, prev):
        if not current:
            return
        prev_name = prev.data(QtCore.Qt.UserRole) if prev else None
        # 关键修复：明确传 prev_name，避免 currentItem() 已切换导致误判
        if prev_name and current.data(QtCore.Qt.UserRole) != prev_name:
            if not self._confirm_discard(prev_name):
                # 用户取消：选回原来的项，用 blockSignals 避免触发递归
                self.list_widget.blockSignals(True)
                for i in range(self.list_widget.count()):
                    if self.list_widget.item(i).data(QtCore.Qt.UserRole) == prev_name:
                        self.list_widget.setCurrentRow(i)
                        break
                self.list_widget.blockSignals(False)
                return
        name = current.data(QtCore.Qt.UserRole)
        p = self.store.get_provider(name)
        self.detail_title.setText(name)
        self.ed_baseurl.setText(p.get("baseUrl", ""))
        self.ed_apikey.setText(self.store.api_key(name))
        self.ed_model_name.setText(p.get("name", ""))
        cache_policy = self.store.cache_policy(name)
        policy_index = self.cache_policy_combo.findData(cache_policy)
        self.cache_policy_combo.setCurrentIndex(max(0, policy_index))

        # 填充模型表格（多模型）
        self._fill_model_table(p.get("models", []))

        # 默认标记（胶囊徽章样式）
        is_default = name == self.store.default_provider()
        if is_default:
            c = THEMES.get(self.theme_name, THEMES["terminal"])
            g_clr = c.get("green", "#10b981")
            self.lbl_default.setText(f"  ✓ 当前默认模型 · {self.store.default_model()}  ")
            self.lbl_default.setStyleSheet(
                f"background: {g_clr}1e; color: {g_clr}; "
                f"border: 1px solid {g_clr}44; border-radius: 10px; padding: 4px 10px; font-weight: 600;"
            )
        else:
            self.lbl_default.setText("")
            self.lbl_default.setStyleSheet("")

    def _fill_model_table(self, models):
        """将模型列表填到表格中。"""
        self.model_table.setRowCount(0)
        provider_name = self.current_name() or ""
        for m in models:
            route = self.store.vision_route(provider_name, m)
            self._add_model_row(
                m.get("id", ""),
                m.get("name", ""),
                bool(m.get("reasoning", False)),
                ",".join(m.get("input", ["text"])),
                get_max_thinking_level(m),
                m.get("contextWindow", 128000),
                m.get("maxTokens", 16384),
                candidates_to_legacy(route.get("candidates", [])),
                route.get("mode", "auto"),
            )
        # 若表格为空，加一行空行便于编辑
        if self.model_table.rowCount() == 0:
            self._add_model_row("", "", False, "text", "off", 128000, 16384, "")

    def _add_model_row(self, mid, name, reasoning, input_types, max_thinking="off",
                       context_window=128000, max_tokens=16384, vision_model="",
                       vision_mode="auto"):
        row = self.model_table.rowCount()
        self.model_table.insertRow(row)

        # 列0：模型 ID
        item_id = QtWidgets.QTableWidgetItem(mid)
        self.model_table.setItem(row, 0, item_id)

        # 列1：显示名
        item_name = QtWidgets.QTableWidgetItem(name)
        self.model_table.setItem(row, 1, item_name)

        # 列2：推理（复选框居中）
        chk = QtWidgets.QCheckBox()
        chk.setChecked(reasoning)
        chk.setStyleSheet("margin: 0;")
        chk.setFocusPolicy(QtCore.Qt.NoFocus)
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.addWidget(chk, 0, QtCore.Qt.AlignCenter)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(QtCore.Qt.AlignCenter)
        self.model_table.setCellWidget(row, 2, w)

        # 列3：输入类型（下拉框）
        combo = QtWidgets.QComboBox()
        combo.addItems(["text", "text,image"])
        combo.setCurrentText(input_types if input_types else "text")
        combo.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.model_table.setCellWidget(row, 3, combo)
        # 输入类型变化时联动更新视觉模型按钮（运行时定位行，避免删除行后错位）
        combo.currentTextChanged.connect(
            lambda txt, c=combo: self._on_input_changed(
                self.model_table.indexAt(c.pos()).row(), txt)
        )

        # 列4：思考上限（下拉框，点击编辑）
        think_combo = QtWidgets.QComboBox()
        think_combo.addItems(THINKING_LEVELS)
        if max_thinking in THINKING_LEVELS:
            think_combo.setCurrentText(max_thinking)
        # 未勾选推理时禁用
        think_combo.setEnabled(reasoning)
        think_combo.setFocusPolicy(QtCore.Qt.StrongFocus)
        # 推理复选框联动：取消勾选时禁用思考等级并重置为 off
        chk.toggled.connect(lambda checked, c=think_combo: self._on_reasoning_toggled(checked, c))
        self.model_table.setCellWidget(row, 4, think_combo)

        # 列5：上下文窗口（居中对齐，留出充足内边距）
        item_ctx = QtWidgets.QTableWidgetItem(str(context_window))
        item_ctx.setData(QtCore.Qt.UserRole, context_window)
        item_ctx.setTextAlignment(QtCore.Qt.AlignCenter)
        item_ctx.setTextAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignHCenter)
        item_ctx.setToolTip(str(context_window))
        self.model_table.setItem(row, 5, item_ctx)

        # 列6：最大输出 tokens（居中对齐）
        item_max = QtWidgets.QTableWidgetItem(str(max_tokens))
        item_max.setData(QtCore.Qt.UserRole, max_tokens)
        item_max.setTextAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignHCenter)
        item_max.setToolTip(str(max_tokens))
        self.model_table.setItem(row, 6, item_max)

        # 列7：视觉模型（纯文本模型可挂一个视觉插件）
        vision_btn = QtWidgets.QPushButton()
        vision_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        vision_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._update_vision_btn(
            vision_btn, vision_model, input_types, name or mid, vision_mode
        )
        vision_btn.clicked.connect(
            lambda _=False, b=vision_btn: self._on_pick_vision_model(
                self.model_table.indexAt(b.pos()).row())
        )
        # 外层容器居中，避免按钮被拉伸占满整个 cell
        vw = QtWidgets.QWidget()
        vlay = QtWidgets.QHBoxLayout(vw)
        vlay.addWidget(vision_btn, 0, QtCore.Qt.AlignCenter)
        vlay.setContentsMargins(2, 1, 2, 1)
        vlay.setAlignment(QtCore.Qt.AlignCenter)
        vw.setStyleSheet("background: transparent;")
        self.model_table.setCellWidget(row, 7, vw)

    def _on_reasoning_toggled(self, checked, think_combo):
        think_combo.setEnabled(checked)
        if not checked:
            think_combo.setCurrentText("off")

    # ---- 视觉模型（Vision Bridge v2） ----
    def _update_vision_btn(self, btn, vision_model, input_types, model_name="",
                           vision_mode="auto"):
        """更新视觉模式、候选链和有效路由提示。"""
        candidates = normalize_candidates(vision_model)
        legacy_value = candidates_to_legacy(candidates)
        mode = normalize_vision_mode(vision_mode)
        has_image = "image" in [x.strip() for x in (input_types or "").split(",")]
        btn.setStyleSheet("""
            QPushButton {
                border: none; border-radius: 4px; padding: 2px 8px;
                font-size: 11px; background: transparent;
            }
            QPushButton:hover { background: rgba(128,128,128,0.15); }
        """)
        first = self._short_vision_label(legacy_value) if candidates else ""
        fallback = f" +{len(candidates) - 1}" if len(candidates) > 1 else ""
        if mode == "off":
            text = "🚫 关闭图片"
            effective = "拒绝图片"
        elif mode == "native":
            text = "🖼 原生直传" if has_image else "⚠ 原生不可用"
            effective = "主模型直接接收图片" if has_image else "纯文本主模型将拒绝图片"
        elif mode == "force":
            text = f"🎯 强制 {first}{fallback}" if candidates else "⚠ 强制未配置"
            effective = "始终先调用视觉候选链"
        elif has_image:
            text = "🖼 自动·原生"
            effective = "主模型原生接收图片"
        elif candidates:
            text = f"🎯 自动 {first}{fallback}"
            effective = "纯文本主模型使用视觉候选链"
        else:
            text = "＋ 配置视觉"
            effective = "纯文本主模型尚无视觉候选"
        btn.setText(text)
        btn.setEnabled(True)
        btn.setToolTip(
            f"模式：{mode}\n有效行为：{effective}\n"
            f"候选顺序：{' → '.join(candidates) if candidates else '(无)'}\n"
            "点击配置模式、候选与回退优先级"
        )
        btn.setProperty("visionModel", legacy_value)
        btn.setProperty("visionMode", mode)

    def _short_vision_label(self, vision_model):
        """把第一个 provider/model 候选转成友好显示名。"""
        candidates = normalize_candidates(vision_model)
        if not candidates:
            return ""
        provider, model_id = candidates[0].split("/", 1)
        display = model_id
        p = self.store.get_provider(provider)
        for model in p.get("models", []):
            if model.get("id") == model_id:
                display = model.get("name") or model_id
                break
        label = f"{provider}/{display}"
        return label if len(label) <= 22 else label[:21] + "…"

    def _vision_btn_at(self, row):
        """获取某行视觉配置按钮（兼容 cell widget 容器）。"""
        widget = self.model_table.cellWidget(row, 7)
        if widget is None:
            return None
        if isinstance(widget, QtWidgets.QPushButton):
            return widget
        return widget.findChild(QtWidgets.QPushButton)

    def _on_input_changed(self, row, txt):
        """输入能力变化时重新计算视觉模式的有效行为。"""
        if row < 0:
            return
        btn = self._vision_btn_at(row)
        if not btn:
            return
        name_item = self.model_table.item(row, 1)
        id_item = self.model_table.item(row, 0)
        model_name = (name_item.text().strip() if name_item else "") or \
                     (id_item.text().strip() if id_item else "")
        self._update_vision_btn(
            btn,
            btn.property("visionModel") or "",
            txt,
            model_name,
            btn.property("visionMode") or "auto",
        )

    def _on_pick_vision_model(self, row):
        """编辑视觉模式及有序的多模型回退链。"""
        if row < 0:
            return
        btn = self._vision_btn_at(row)
        if not btn:
            return
        available = self._collect_vision_candidates()
        current = normalize_candidates(btn.property("visionModel") or "")
        current_mode = normalize_vision_mode(btn.property("visionMode") or "auto")

        # 已保存但当前不可用的候选仍展示并标记，防止静默丢配置。
        available_map = {value: label for label, value in available}
        ordered_values = current + [value for _, value in available if value not in current]

        box = QtWidgets.QDialog(self)
        box.setWindowTitle("Vision Bridge v2 配置")
        box.resize(560, 520)
        lay = QtWidgets.QVBoxLayout(box)

        tip = QtWidgets.QLabel(
            "选择运行模式与候选模型。勾选多个候选可自动回退；"
            "拖动列表项可调整优先级。"
        )
        tip.setWordWrap(True)
        lay.addWidget(tip)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("运行模式"))
        mode_combo = QtWidgets.QComboBox()
        for label, value in VISION_MODE_OPTIONS:
            mode_combo.addItem(label, value)
        mode_combo.setCurrentIndex(max(0, mode_combo.findData(current_mode)))
        mode_row.addWidget(mode_combo, 1)
        lay.addLayout(mode_row)

        mode_help = QtWidgets.QLabel(
            "自动：原生视觉直传，纯文本走桥接；原生：只允许主模型直传；"
            "强制：即使主模型支持图片也先桥接；关闭：移除并拒绝图片。"
        )
        mode_help.setWordWrap(True)
        mode_help.setObjectName("fieldHint")
        lay.addWidget(mode_help)

        lst = QtWidgets.QListWidget()
        lst.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        lst.setDefaultDropAction(QtCore.Qt.MoveAction)
        for value in ordered_values:
            label = available_map.get(value, f"⚠ 当前不可用 · {value}")
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, value)
            item.setFlags(
                item.flags() | QtCore.Qt.ItemIsUserCheckable
                | QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled
            )
            item.setCheckState(QtCore.Qt.Checked if value in current else QtCore.Qt.Unchecked)
            lst.addItem(item)
        lay.addWidget(lst, 1)

        btn_clear = QtWidgets.QPushButton("清空候选")
        btn_clear.setObjectName("dangerBtn")
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_ok = QtWidgets.QPushButton("确定")
        btn_ok.setObjectName("accentBtn")
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(btn_clear)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

        btn_clear.clicked.connect(
            lambda: [lst.item(i).setCheckState(QtCore.Qt.Unchecked) for i in range(lst.count())]
        )
        btn_cancel.clicked.connect(box.reject)

        def selected_candidates():
            return [
                lst.item(i).data(QtCore.Qt.UserRole)
                for i in range(lst.count())
                if lst.item(i).checkState() == QtCore.Qt.Checked
            ]

        def accept_config():
            mode = normalize_vision_mode(mode_combo.currentData())
            selected = selected_candidates()
            input_combo = self.model_table.cellWidget(row, 3)
            input_types = input_combo.currentText() if isinstance(input_combo, QtWidgets.QComboBox) else "text"
            has_image = "image" in input_types.split(",")
            if mode == "force" and not selected:
                QtWidgets.QMessageBox.warning(box, "缺少候选", "强制桥接模式至少需要一个视觉模型。")
                return
            if mode == "auto" and not has_image and not selected:
                QtWidgets.QMessageBox.warning(box, "缺少候选", "纯文本模型的自动模式至少需要一个视觉模型。")
                return
            box.accept()

        btn_ok.clicked.connect(accept_config)

        c = COLORS
        box.setStyleSheet(f"""
            QDialog {{ background: {c['bg']}; }}
            QLabel {{ color: {c['text']}; font-size: 13px; }}
            QListWidget {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px;
                           color: {c['text']}; font-size: 13px; }}
            QListWidget::item {{ padding: 7px 8px; }}
            QListWidget::item:selected {{ background: {c['accent']}; color: {c['btn_text']}; }}
            QComboBox {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']};
                         border-radius: 6px; padding: 6px 10px; }}
            QPushButton {{ background: {c['panel']}; color: {c['text']}; border-radius: 6px;
                           padding: 8px 14px; font-size: 13px; }}
            QPushButton#accentBtn {{ background: {c['accent']}; color: {c['btn_text']}; font-weight: 600; }}
            QPushButton#dangerBtn {{ background: transparent; color: {c['red']}; border: 1px solid {c['red']}; }}
        """)

        if box.exec_() != QtWidgets.QDialog.Accepted:
            return
        input_combo = self.model_table.cellWidget(row, 3)
        input_types = input_combo.currentText() if isinstance(input_combo, QtWidgets.QComboBox) else "text"
        name_item = self.model_table.item(row, 1)
        id_item = self.model_table.item(row, 0)
        model_name = (name_item.text().strip() if name_item else "") or \
                     (id_item.text().strip() if id_item else "")
        mode = normalize_vision_mode(mode_combo.currentData())
        selected = selected_candidates()
        self._update_vision_btn(
            btn, candidates_to_legacy(selected), input_types, model_name, mode
        )
        self.set_status(
            f"视觉配置已更新：{mode} · {len(selected)} 个候选（记得点保存）",
            "info",
        )

    def _read_model_table(self):
        """从表格读取模型列表（忽略空 ID 的行）。"""
        models = []
        for row in range(self.model_table.rowCount()):
            item_id = self.model_table.item(row, 0)
            mid = item_id.text().strip() if item_id else ""
            if not mid:
                continue
            item_name = self.model_table.item(row, 1)
            name = item_name.text().strip() if item_name else ""

            # 推理
            reasoning = False
            w = self.model_table.cellWidget(row, 2)
            if w:
                chk = w.findChild(QtWidgets.QCheckBox)
                if chk:
                    reasoning = chk.isChecked()

            # 输入类型
            input_types = "text"
            cw = self.model_table.cellWidget(row, 3)
            if cw and isinstance(cw, QtWidgets.QComboBox):
                input_types = cw.currentText()

            # 思考上限
            max_think = "off"
            tw = self.model_table.cellWidget(row, 4)
            if tw and isinstance(tw, QtWidgets.QComboBox):
                max_think = tw.currentText()

            # 上下文窗口（可编辑数字）
            context_window = self._read_int_cell(row, 5, 128000)
            max_tokens = self._read_int_cell(row, 6, 16384)

            # Vision Bridge v2：有序候选链 + 模式
            vision_model = ""
            vision_mode = "auto"
            vbtn = self._vision_btn_at(row)
            if vbtn:
                vision_model = vbtn.property("visionModel") or ""
                vision_mode = normalize_vision_mode(vbtn.property("visionMode") or "auto")

            model = {
                "id": mid,
                "name": name or mid,
                "reasoning": reasoning,
                "input": [x.strip() for x in input_types.split(",") if x.strip()],
                "contextWindow": context_window,
                "maxTokens": max_tokens,
            }
            # 只有推理模型才写 thinkingLevelMap
            if reasoning and max_think != "off":
                model["thinkingLevelMap"] = build_thinking_map(max_think)
            # 同时写入旧字段和 v2 模式，支持旧版回滚与新运行时。
            if vision_model:
                model["visionModel"] = candidates_to_legacy(normalize_candidates(vision_model))
            model["visionMode"] = vision_mode
            models.append(model)
        return models

    def _read_int_cell(self, row, col, default):
        """从表格单元格读取一个非负整数，失败返回默认值。"""
        item = self.model_table.item(row, col)
        if item is None:
            return default
        txt = item.text().strip()
        if not txt:
            return default
        try:
            val = int(txt)
            return val if val > 0 else default
        except ValueError:
            return default

    def on_add_model_row(self):
        self._add_model_row("", "", False, "text", "off", 128000, 16384, "")
        self.model_table.scrollToBottom()

    def on_del_model_row(self):
        rows = sorted({idx.row() for idx in self.model_table.selectedIndexes()}, reverse=True)
        if not rows:
            cur = self.model_table.currentRow()
            if cur >= 0:
                rows = [cur]
        for r in rows:
            self.model_table.removeRow(r)
        if self.model_table.rowCount() == 0:
            self._add_model_row("", "", False, "text", "off", 128000, 16384, "")

    def on_toggle_key_visible(self, checked):
        self.ed_apikey.setEchoMode(
            QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password
        )

    # ---- 操作 ----
    def on_add(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "添加供应商", "供应商名称（英文小写）:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.store.provider_names():
            QtWidgets.QMessageBox.warning(self, "已存在", f"供应商 '{name}' 已存在")
            return
        self.store.add_provider(name, "", "", "", name, False)
        self._save_store()
        self.refresh_list(select_name=name)
        self._refresh_tray()

    def on_rename_provider(self):
        old_name = self.current_name()
        if not old_name:
            self.set_status("请先选择供应商", "warn")
            return
        new_name, ok = QtWidgets.QInputDialog.getText(
            self,
            "修改供应商名称",
            "供应商名称（仅支持字母、数字、点、下划线和短横线）:",
            QtWidgets.QLineEdit.Normal,
            old_name,
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+", new_name):
            QtWidgets.QMessageBox.warning(
                self, "名称无效", "名称只能包含字母、数字、点（.）、下划线（_）和短横线（-）。"
            )
            return
        if new_name == old_name:
            return
        if new_name in self.store.provider_names():
            QtWidgets.QMessageBox.warning(self, "已存在", f"供应商 '{new_name}' 已存在。")
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "确认修改名称",
            f"将供应商「{old_name}」改为「{new_name}」，并同步迁移 API Key、默认设置、缓存策略和视觉路由。\n是否继续？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return
        snapshot = {
            "models": deepcopy(self.store.models),
            "auth": deepcopy(self.store.auth),
            "settings": deepcopy(self.store.settings),
            "cache_guard": deepcopy(self.store.cache_guard),
            "vision": deepcopy(self.store.vision),
        }
        try:
            self.store.rename_provider(old_name, new_name)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "修改失败", str(exc))
            return
        if not self._save_store():
            self.store.models = snapshot["models"]
            self.store.auth = snapshot["auth"]
            self.store.settings = snapshot["settings"]
            self.store.cache_guard = snapshot["cache_guard"]
            self.store.vision = snapshot["vision"]
            self.store.save()
            self.refresh_list(select_name=old_name)
            QtWidgets.QMessageBox.critical(
                self, "保存失败",
                "修改供应商名称失败，已恢复原名称。\n"
                f"原因：{self.store.last_save_error or '请检查文件写入权限'}"
            )
            return
        self._provider_test_results.pop(old_name, None)
        self.refresh_list(select_name=new_name)
        self._refresh_tray()
        self.set_status(f"已将供应商 {old_name} 重命名为 {new_name}", "ok")
        self.show_toast(f"✓ 供应商已改名：{new_name}")

    def on_del(self):
        name = self.current_name()
        if not name:
            return
        # 高危操作：要求输入 provider 名字确认
        text, ok = QtWidgets.QInputDialog.getText(
            self, "确认删除",
            f"将永久删除供应商「{name}」及其 API Key 与模型配置。\n"
            f"请输入供应商名称确认（{name}）：",
        )
        if not ok:
            return
        if text.strip() != name:
            QtWidgets.QMessageBox.warning(self, "已取消", "输入不匹配，未删除。")
            return
        self.store.remove_provider(name)
        if not self._save_store():
            return
        self.refresh_list()
        self._refresh_tray()
        self.set_status(f"已删除 {name}", "ok")

    def _refresh_tray(self):
        if self.tray is not None:
            self.tray._build_menu()

    def _save_store(self) -> bool:
        """统一保存入口：主配置文件损坏时弹窗拦截并引导恢复，其余失败由调用方提示。"""
        if self.store.save():
            return True
        corrupt = self.store.corrupt_critical_files()
        if corrupt and self.isVisible():
            names = "\n".join(f"• {p.name}：{err}" for p, err in corrupt)
            QtWidgets.QMessageBox.warning(
                self, "配置文件损坏",
                "以下配置文件无法解析，为防止数据被覆盖丢失，本次修改未写入磁盘：\n\n"
                f"{names}\n\n"
                "可从「快照备份」恢复历史版本，或手动修复文件后重试。",
            )
        return False

    def on_save(self):
        name = self.current_name()
        if not name:
            self.set_status("请先选择供应商", "warn")
            return
        p = self.store.get_provider(name)
        base_url = self.ed_baseurl.text().strip()

        # 输入验证
        if not base_url:
            QtWidgets.QMessageBox.warning(self, "提示", "Base URL 不能为空")
            return
        if not validate_baseurl(base_url):
            QtWidgets.QMessageBox.warning(self, "提示", "Base URL 必须以 http:// 或 https:// 开头")
            return

        # 从表格读取多模型；保留 GUI 未展示的 compat/cost/headers 等高级字段。
        models = merge_model_edits(p.get("models", []), self._read_model_table())
        if not models:
            QtWidgets.QMessageBox.warning(self, "提示", "至少需要一个模型（请填写模型 ID）")
            return

        p["baseUrl"] = base_url
        p["name"] = self.ed_model_name.text().strip() or name
        p["models"] = models
        self.store.sync_vision_routes(name, models)

        # 缓存兼容：OpenAI 请求格式不等于支持 OpenAI 专有缓存字段。
        cache_policy = normalize_cache_policy(self.cache_policy_combo.currentData())
        self.store.set_cache_policy(name, cache_policy)
        effective_policy = apply_provider_cache_compat(p, cache_policy)

        # 同步 enabledModels 白名单（让 pi /model 能显示这些模型）
        self.store.sync_enabled_models(name)

        # apiKey
        key = self.ed_apikey.text().strip()
        self.store.set_api_key(name, key)

        if self._save_store():
            self.set_status(
                f"已保存 {name}（{len(models)} 个模型）· 缓存策略 {effective_policy} · "
                "重启 pi 或执行 /reload 生效",
                "ok",
            )
            self.show_toast(f"💾 已成功保存配置：{name}")
            self.refresh_list(select_name=name)
            self._refresh_tray()
        else:
            self.set_status("保存失败", "err")
            self.show_toast("❌ 保存失败，请检查文件写入权限", 3000)

    def on_set_default(self):
        name = self.current_name()
        if not name:
            return
        # 优先取当前选中的模型行，否则取第一个
        model_id = None
        rows = {idx.row() for idx in self.model_table.selectedIndexes()}
        if rows:
            item = self.model_table.item(sorted(rows)[0], 0)
            model_id = item.text().strip() if item else None
        if not model_id:
            item = self.model_table.item(0, 0)
            model_id = item.text().strip() if item else None
        if not model_id:
            QtWidgets.QMessageBox.warning(self, "提示", "请先在模型列表填写模型 ID")
            return
        self.store.set_default(name, model_id)
        if self._save_store():
            self.set_status(f"已将 {name}/{model_id} 设为默认（pi 下次启动生效）", "ok")
            self.show_toast(f"⭐ 已设为默认模型：{name} / {model_id}")
        else:
            self.set_status("设置默认模型失败：" + (self.store.last_save_error or "文件写入失败"), "err")
            return
        self.refresh_list(select_name=name)
        self._refresh_tray()

    def _animate_loading(self):
        """Braille 旋转 Spinner 动画。"""
        frames = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
        self._loading_dots_count = (self._loading_dots_count + 1) % len(frames)
        self.loading_dots.setText(frames[self._loading_dots_count])

    def closeEvent(self, event):
        self._closed = True
        super().closeEvent(event)

    def on_test(self):
        name = self.current_name()
        if not name:
            return
        base_url = self.ed_baseurl.text().strip()
        key = self.ed_apikey.text().strip()
        if not base_url:
            self.set_status("Base URL 为空", "err")
            return
        self.set_status(f"正在测试 {name}", "info")
        self.loading_dots.setVisible(True)
        self._loading_dots_count = 0
        self._loading_timer.start()
        self.btn_test.setEnabled(False)
        self._testing = True

        # 统一使用 QThread + pyqtSignal（与 DataLoadWorker 一致）
        self._test_worker = TestEndpointWorker(base_url, key)
        self._test_worker.result_ready.connect(self._on_test_done)
        self._test_worker.start()

    def show_toast(self, message, duration=2200):
        """在窗口中上方弹出平滑淡入淡出与位移动效的现代胶囊 Toast 提示。"""
        if hasattr(self, "_toast_label") and self._toast_label:
            try:
                self._toast_label.deleteLater()
            except Exception:
                pass
            self._toast_label = None

        toast = QtWidgets.QFrame(self)
        toast.setObjectName("toastWidget")
        toast.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

        layout = QtWidgets.QHBoxLayout(toast)
        layout.setContentsMargins(18, 9, 18, 9)
        lbl = QtWidgets.QLabel(message, toast)
        lbl.setObjectName("toastText")
        layout.addWidget(lbl)

        toast.adjustSize()
        w = toast.width()
        x = (self.width() - w) // 2
        start_y = 26
        target_y = 48
        toast.move(x, start_y)

        # 挂载不透明度滤镜
        opacity_effect = QtWidgets.QGraphicsOpacityEffect(toast)
        toast.setGraphicsEffect(opacity_effect)
        opacity_effect.setOpacity(0.0)

        toast.show()
        self._toast_label = toast

        # 进入动画：位置下滑 + 不透明度淡入
        anim_pos = QPropertyAnimation(toast, b"pos", self)
        anim_pos.setDuration(220)
        anim_pos.setStartValue(QPoint(x, start_y))
        anim_pos.setEndValue(QPoint(x, target_y))
        anim_pos.setEasingCurve(QEasingCurve.OutCubic)

        anim_op = QPropertyAnimation(opacity_effect, b"opacity", self)
        anim_op.setDuration(220)
        anim_op.setStartValue(0.0)
        anim_op.setEndValue(1.0)

        anim_pos.start(QPropertyAnimation.DeleteWhenStopped)
        anim_op.start(QPropertyAnimation.DeleteWhenStopped)

        # 退出动画：延迟后位置微上滑 + 淡出并销毁
        def _fade_out():
            if not toast:
                return
            try:
                if not toast.isVisible():
                    return
                out_pos = QPropertyAnimation(toast, b"pos", self)
                out_pos.setDuration(240)
                out_pos.setStartValue(toast.pos())
                out_pos.setEndValue(QPoint(x, target_y - 10))
                out_pos.setEasingCurve(QEasingCurve.InCubic)

                out_op = QPropertyAnimation(opacity_effect, b"opacity", self)
                out_op.setDuration(240)
                out_op.setStartValue(1.0)
                out_op.setEndValue(0.0)
                out_op.finished.connect(toast.deleteLater)

                out_pos.start(QPropertyAnimation.DeleteWhenStopped)
                out_op.start(QPropertyAnimation.DeleteWhenStopped)
            except Exception:
                pass

        QtCore.QTimer.singleShot(duration, _fade_out)

    def set_status(self, msg, level="info"):
        """统一状态栏消息，按级别着色。
        level: ok(绿) | err(红) | warn(黄) | info(灰)"""
        c = THEMES.get(self.theme_name, THEMES["terminal"])
        color_map = {
            "ok": c.get("green", "#10b981"),
            "err": c.get("red", "#ef4444"),
            "warn": c.get("yellow", "#f59e0b"),
            "info": c.get("text_dim", "#64748b"),
        }
        color = color_map.get(level, color_map["info"])
        self.status.setText(msg)
        self.status.setStyleSheet(f"color: {color}; font-size: 12px; padding-top: 8px; "
                                 f"border-top: 1px solid {c['border']};")

    @QtCore.pyqtSlot(str, bool, int, str, str)
    def _on_test_done(self, name, ok, latency, msg, payload):
        # 窗口已关闭则跳过
        if self._closed:
            return
        try:
            self.btn_test.setEnabled(True)
        except RuntimeError:
            return
        self._loading_timer.stop()
        self.loading_dots.setVisible(False)
        self._testing = False
        # 反序列化模型信息
        model_infos = []
        try:
            model_infos = json.loads(payload) if payload else []
        except ValueError:
            model_infos = []
        icon = "✓" if ok else "✗"
        if ok:
            n = len(model_infos)
            self.set_status(f"{icon} {name}: {latency}ms · {msg} · 拉到 {n} 个模型", "ok")
            if model_infos:
                # 弹窗展示模型列表，并可一键导入到表格
                self._show_discovered_models(name, model_infos, latency)
        else:
            self.set_status(f"{icon} {name}: {latency}ms · {msg}", "err")

    def _show_discovered_models(self, name, model_infos, latency):
        """展示测速发现的模型（含能力信息），支持勾选导入到当前 provider。
        纯文本模型可直接在弹窗内挂接视觉插件。"""
        box = QtWidgets.QDialog(self)
        box.setWindowTitle(f"{name} · 连通性测试（{latency}ms）")
        box.resize(640, 480)
        lay = QtWidgets.QVBoxLayout(box)

        tip = QtWidgets.QLabel(
            f"端点可达，发现 {len(model_infos)} 个模型。勾选要导入的模型；"
            f"纯文本模型可在「视觉插件」列挂接视觉模型："
        )
        tip.setWordWrap(True)
        lay.addWidget(tip)

        # 用表格展示：勾选 | 模型 ID | 图片 | 上下文 | 视觉插件
        tbl = QtWidgets.QTableWidget(0, 5)
        tbl.setHorizontalHeaderLabels(["导入", "模型 ID", "图片", "上下文", "视觉插件"])
        tbl.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        tbl.verticalHeader().setVisible(False)
        tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        lay.addWidget(tbl)

        # 收集可选的视觉模型候选（跨所有 provider，含当前正在测试的模型）
        vision_candidates = self._collect_vision_candidates()

        # 填充表格
        for info in model_infos:
            mid = info.get("id", "")
            if not mid:
                continue
            r = tbl.rowCount()
            tbl.insertRow(r)
            # 勾选列
            chk = QtWidgets.QCheckBox()
            chk.setChecked(True)  # 默认全选
            w = QtWidgets.QWidget()
            wl = QtWidgets.QHBoxLayout(w)
            wl.addWidget(chk, 0, QtCore.Qt.AlignCenter)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setAlignment(QtCore.Qt.AlignCenter)
            tbl.setCellWidget(r, 0, w)
            # 模型 ID
            tbl.setItem(r, 1, QtWidgets.QTableWidgetItem(mid))
            # 图片能力
            inp = info.get("input")
            has_image = inp is not None and "image" in [str(x) for x in inp]
            img_txt = "🖼 支持" if has_image else ("? 未知" if inp is None else "仅文本")
            img_item = QtWidgets.QTableWidgetItem(img_txt)
            img_item.setTextAlignment(QtCore.Qt.AlignCenter)
            tbl.setItem(r, 2, img_item)
            # 上下文：优先端点返回，其次查已知对照表，都没有则显示“未知”
            ctx = info.get("contextWindow")
            if not ctx:
                ctx = lookup_context_window(mid)
                if ctx:
                    info["contextWindow"] = ctx  # 回填，方便导入
            ctx_txt = str(ctx) if ctx else "未知"
            ctx_item = QtWidgets.QTableWidgetItem(ctx_txt)
            ctx_item.setTextAlignment(QtCore.Qt.AlignCenter)
            tbl.setItem(r, 3, ctx_item)
            # 视觉插件列：仅纯文本模型开放；图片模型显示“无需”
            if has_image:
                vlabel = QtWidgets.QTableWidgetItem("—")
                vlabel.setTextAlignment(QtCore.Qt.AlignCenter)
                vlabel.setFlags(QtCore.Qt.ItemIsEnabled)
                tbl.setItem(r, 4, vlabel)
            else:
                vcombo = QtWidgets.QComboBox()
                vcombo.addItem("(不挂接)", "")
                for label, vstr in vision_candidates:
                    vcombo.addItem(label, vstr)
                vcombo.setFocusPolicy(QtCore.Qt.StrongFocus)
                tbl.setCellWidget(r, 4, vcombo)

        # 按钮行
        btn_row = QtWidgets.QHBoxLayout()
        btn_all = QtWidgets.QPushButton("全选")
        btn_none = QtWidgets.QPushButton("全不选")
        btn_probe = QtWidgets.QPushButton("🔍 探测选中能力")
        btn_import = QtWidgets.QPushButton("导入选中")
        btn_import.setObjectName("accentBtn")
        btn_all.clicked.connect(lambda: self._set_probe_checks(tbl, True))
        btn_none.clicked.connect(lambda: self._set_probe_checks(tbl, False))
        btn_probe.clicked.connect(lambda: self._probe_selected_models(name, tbl, model_infos))
        btn_import.clicked.connect(box.accept)
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addWidget(btn_probe)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_import)
        lay.addLayout(btn_row)

        # 样式
        c = COLORS
        box.setStyleSheet(f"""
            QDialog {{ background: {c['bg']}; }}
            QLabel {{ color: {c['text']}; font-size: 13px; }}
            QTableWidget {{ background: {c['panel']}; border: 1px solid {c['border']};
                            border-radius: 6px; color: {c['text']}; font-size: 12px; }}
            QHeaderView::section {{ background: {c['bg_alt']}; color: {c['text_dim']};
                                    border: none; padding: 4px 8px; font-size: 12px; }}
            QComboBox {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']};
                         border-radius: 4px; padding: 2px 6px; font-size: 12px; }}
            QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['text']};
                                            border: 1px solid {c['border']}; }}
            QPushButton {{ background: {c['panel']}; color: {c['text']}; border-radius: 6px;
                           padding: 8px 14px; font-size: 13px; }}
            QPushButton#accentBtn {{ background: {c['accent']}; color: {c['btn_text']}; font-weight: 600; }}
        """)

        if box.exec_() != QtWidgets.QDialog.Accepted:
            return

        # 读取勾选结果，导入
        imported = 0
        existing_ids = {m["id"] for m in self._read_model_table()}
        for r in range(tbl.rowCount()):
            cw = tbl.cellWidget(r, 0)
            chk = cw.findChild(QtWidgets.QCheckBox) if cw else None
            if not (chk and chk.isChecked()):
                continue
            mid = tbl.item(r, 1).text().strip() if tbl.item(r, 1) else ""
            if not mid or mid in existing_ids:
                continue
            # 从 model_infos 找对应能力
            info = {}
            for mi in model_infos:
                if mi.get("id") == mid:
                    info = mi
                    break
            inp = info.get("input")
            has_image = inp is not None and "image" in [str(x) for x in inp]
            input_types = "text,image" if has_image else "text"
            ctx = info.get("contextWindow", 128000)
            reasoning = bool(info.get("reasoning", False))
            max_think = get_max_thinking_level({"reasoning": reasoning}) if reasoning else "off"
            # 读取视觉插件选择
            vision_model = ""
            if not has_image:
                vw = tbl.cellWidget(r, 4)
                if vw and isinstance(vw, QtWidgets.QComboBox):
                    vision_model = vw.currentData() or ""
            self._add_model_row(
                mid, mid, reasoning, input_types, max_think, ctx, 16384,
                vision_model, "auto",
            )
            existing_ids.add(mid)
            imported += 1
        if imported:
            self.set_status(f"已导入 {imported} 个模型（含自动识别能力与视觉插件），记得点保存", "ok")

    def _collect_vision_candidates(self):
        """收集所有支持图像的模型作为视觉插件候选。返回 [(label, vision_str)]。"""
        candidates = []
        seen = set()
        for pname in self.store.provider_names():
            p = self.store.get_provider(pname)
            for m in p.get("models", []):
                inputs = m.get("input", ["text"])
                if "image" not in inputs:
                    continue
                mid = m.get("id", "")
                if not mid:
                    continue
                mname = m.get("name", mid)
                label = f"{pname} / {mname} ({mid})"
                vstr = f"{pname}/{mid}"
                if vstr not in seen:
                    seen.add(vstr)
                    candidates.append((label, vstr))
        return candidates

    def _set_probe_checks(self, tbl, checked):
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
        for r in range(tbl.rowCount()):
            cw = tbl.cellWidget(r, 0)
            chk = cw.findChild(QtWidgets.QCheckBox) if cw else None
            if chk:
                chk.setChecked(state)

    def _probe_selected_models(self, name, tbl, model_infos):
        """对勾选的模型逐个发带图片的最小请求，探测是否支持图片。
        异步探测：通过 QThread + pyqtSignal 逐个更新表格，避免阻塞 UI。"""
        base_url = self.ed_baseurl.text().strip()
        key = self.ed_apikey.text().strip()
        if not base_url:
            return
        # 收集勾选的模型 ID
        selected = []
        for r in range(tbl.rowCount()):
            cw = tbl.cellWidget(r, 0)
            chk = cw.findChild(QtWidgets.QCheckBox) if cw else None
            if chk and chk.isChecked():
                mid = tbl.item(r, 1).text().strip() if tbl.item(r, 1) else ""
                if mid:
                    selected.append((r, mid))
        if not selected:
            QtWidgets.QMessageBox.information(self, "提示", "请先勾选要探测的模型")
            return

        self.set_status(f"正在探测 {len(selected)} 个模型的能力...", "info")
        # 标记所有待探测行
        for r, _mid in selected:
            img_item = tbl.item(r, 2)
            if img_item:
                img_item.setText("⏳ 探测中...")

        # 异步探测 worker
        self._probe_worker = ProbeModelsWorker(base_url, key, selected)
        self._probe_tbl = tbl
        self._probe_model_infos = model_infos
        self._probe_selected = selected
        self._probe_worker.result_ready.connect(self._on_probe_result)
        self._probe_worker.finished.connect(self._on_probe_finished)
        self._probe_worker.start()

    @QtCore.pyqtSlot(int, str, bool, bool, str)
    def _on_probe_result(self, row, mid, ok, supports, msg):
        """单个模型探测完成，更新表格。"""
        tbl = self._probe_tbl
        img_item = tbl.item(row, 2)
        if img_item:
            img_item.setText("🖼 支持" if supports else "仅文本")
        # 上下文：先查已知对照表，再回退到端点已返回的值
        ctx_lookup = lookup_context_window(mid)
        ctx_from_endpoint = None
        for mi in self._probe_model_infos:
            if mi.get("id") == mid:
                mi["input"] = ["text", "image"] if supports else ["text"]
                ctx_from_endpoint = mi.get("contextWindow")
                break
        ctx_final = ctx_lookup or ctx_from_endpoint
        ctx_item = tbl.item(row, 3)
        if ctx_final:
            if ctx_item:
                ctx_item.setText(str(ctx_final))
            # 同步写入 model_infos
            for mi in self._probe_model_infos:
                if mi.get("id") == mid:
                    mi["contextWindow"] = ctx_final
                    break
        else:
            if ctx_item:
                ctx_item.setText("未知")
        self.set_status(
            f"{mid}: {'支持图片' if supports else '不支持图片'} · "
            f"上下文 {ctx_final if ctx_final else '未知'} ({msg})",
            "ok" if supports else "warn",
        )

    @QtCore.pyqtSlot()
    def _on_probe_finished(self):
        self.set_status(f"探测完成：{len(self._probe_selected)} 个模型", "ok")

    def current_name(self):
        item = self.list_widget.currentItem()
        return item.data(QtCore.Qt.UserRole) if item else None


# =============================================================================
# 系统托盘
# =============================================================================

class TrayApp(QtWidgets.QSystemTrayIcon):
    def __init__(self, icon, window: MainWindow, store: ConfigStore):
        super().__init__(icon)
        self.window = window
        self.store = store
        self.setToolTip("pi API Switcher")

        self.menu = QtWidgets.QMenu()
        self._build_menu()
        self.setContextMenu(self.menu)

        self.activated.connect(self.on_activated)

    def _build_menu(self):
        self.menu.clear()
        # 快速切换
        for name in self.store.provider_names():
            p = self.store.get_provider(name)
            models = p.get("models", [])
            is_default = name == self.store.default_provider()

            sub = self.menu.addMenu(f"{'★ ' if is_default else ''}{name}")
            if models:
                for m in models:
                    mid = m.get("id", "")
                    mname = m.get("name", mid)
                    is_cur = (name == self.store.default_provider()
                              and mid == self.store.default_model())
                    label = f"{'● ' if is_cur else ''}{mname}"
                    act = sub.addAction(label)
                    act.triggered.connect(
                        lambda _=False, n=name, mid2=mid: self._set_default(n, mid2)
                    )
            else:
                act = sub.addAction("(无模型)")
                act.setEnabled(False)

        self.menu.addSeparator()
        act_show = self.menu.addAction("打开主窗口")
        act_show.triggered.connect(self.show_window)
        act_quit = self.menu.addAction("退出")
        act_quit.triggered.connect(self.quit)

    def _set_default(self, name, model_id):
        if model_id:
            self.store.set_default(name, model_id)
            if self.window._save_store():
                self.showMessage("pi API Switcher", f"已切换默认: {name}/{model_id}")
            else:
                self.showMessage("pi API Switcher", "切换失败：配置文件异常，请在主窗口查看详情")
            self.window.refresh_list(select_name=name)
            self._build_menu()

    def on_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self.show_window()

    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def quit(self):
        QtWidgets.QApplication.quit()


# =============================================================================
# 入口
# =============================================================================

def main():
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("pi-api-switcher")

    # 单实例保护：防止两个实例并发写 models.json/auth.json/settings.json 互相覆盖
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(AGENT_DIR / "api-switcher.lock"))
    lock.setStaleLockTime(0)  # 永不认为锁过期，进程退出自动释放
    if not lock.tryLock():
        QtWidgets.QMessageBox.warning(
            None, "pi-api-switcher", "程序已在运行（请检查系统托盘）。"
        )
        sys.exit(0)

    # 图标
    icon_path = Path(__file__).parent / "icon.ico"
    if not icon_path.exists():
        generate_icon_ico(icon_path)
    icon = QtGui.QIcon(str(icon_path)) if icon_path.exists() else QtGui.QIcon()
    app.setWindowIcon(icon)

    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    bridge_status = install_vision_bridge()
    guard_status = install_cache_guard(AGENT_DIR, bundle_root)
    env_status = disable_optimizer_cache_key_fallback()
    store = ConfigStore()
    window = MainWindow(store)
    statuses = [bridge_status, guard_status, env_status]
    level = "ok" if all("失败" not in text and "未找到" not in text for text in statuses) else "warn"
    window.set_status(" · ".join(statuses), level)

    # 系统托盘
    tray = TrayApp(icon, window, store)
    tray.show()
    window.tray = tray  # 注入托盘引用，供增删后刷新菜单

    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
