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
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets


# =============================================================================
# 配置路径
# =============================================================================

AGENT_DIR = Path.home() / ".pi" / "agent"
MODELS_PATH = AGENT_DIR / "models.json"
AUTH_PATH = AGENT_DIR / "auth.json"
SETTINGS_PATH = AGENT_DIR / "settings.json"

# 应用自身配置（保存主题/字体选择）
APP_CONFIG_PATH = AGENT_DIR / "api-switcher.json"

# pi 思考等级（从低到高），null 表示该等级不支持
THINKING_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]


# =============================================================================
# 多主题配色
# =============================================================================

THEMES = {
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
        # 优先匹配常见中文字体名
        for f in FONT_CANDIDATES:
            for fam in families:
                if fam.lower() == f.lower() or f in fam:
                    if fam not in available:
                        available.append(fam)
                    break
        # 补充几个常用于代码的英文等宽字体
        for f in ["Consolas", "Cascadia Code", "JetBrains Mono", "Segoe UI Mono"]:
            for fam in families:
                if fam.lower() == f.lower():
                    if fam not in available:
                        available.append(fam)
                    break
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


def validate_baseurl(url: str) -> bool:
    """校验 baseUrl 格式：必须以 http:// 或 https:// 开头。"""
    return re.match(r"^https?://", url.strip()) is not None


def read_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def write_json(path: Path, data) -> bool:
    """原子写入：先写临时文件再替换，防止写入中断导致数据损坏。"""
    tmp_path = path.with_suffix(".tmp")
    try:
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp_path.replace(path)  # 原子替换
        return True
    except (OSError, ValueError, json.JSONDecodeError):
        tmp_path.unlink(missing_ok=True)
        return False


# =============================================================================
# 数据模型
# =============================================================================

class ConfigStore:
    """封装对三个 JSON 文件的读写。"""

    def __init__(self):
        self.load()

    def load(self):
        self.models = read_json(MODELS_PATH)
        self.auth = read_json(AUTH_PATH)
        self.settings = read_json(SETTINGS_PATH)

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
        # 优先内嵌到 models.json 的 apiKey（与你现有 deepseek-v4-pro 的写法一致）
        p = self.get_provider(name)
        if p:
            p["apiKey"] = key
        # 同时同步 auth.json
        if key:
            self.auth[name] = {"type": "api_key", "key": key}
        elif name in self.auth:
            del self.auth[name]

    def default_provider(self):
        return self.settings.get("defaultProvider", "")

    def default_model(self):
        return self.settings.get("defaultModel", "")

    def save(self) -> bool:
        ok1 = write_json(MODELS_PATH, self.models)
        ok2 = write_json(AUTH_PATH, self.auth)
        ok3 = write_json(SETTINGS_PATH, self.settings)
        return ok1 and ok2 and ok3

    def set_default(self, provider, model_id):
        self.settings["defaultProvider"] = provider
        self.settings["defaultModel"] = model_id
        self.sync_enabled_models(provider)

    def sync_enabled_models(self, provider=None):
        """将 provider 的所有模型 ID 同步到 enabledModels 白名单。
        这是 pi /model 选择器能显示模型的必要条件。"""
        enabled = list(self.settings.get("enabledModels", []))
        if provider:
            models = self.get_provider(provider).get("models", [])
            for m in models:
                mid = m.get("id", "")
                if mid and mid not in enabled:
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
        if api_key:
            p["apiKey"] = api_key
        self.models.setdefault("providers", {})[name] = p
        if api_key:
            self.auth[name] = {"type": "api_key", "key": api_key}

    def remove_provider(self, name):
        # 先获取该 provider 的模型 ID 列表（用于清理 enabledModels）
        p = self.get_provider(name)
        model_ids = {m.get("id", "") for m in p.get("models", [])}

        self.models.get("providers", {}).pop(name, None)
        self.auth.pop(name, None)

        # 清理 settings.json 中的悬空引用
        if self.settings.get("defaultProvider") == name:
            self.settings["defaultProvider"] = ""
            self.settings["defaultModel"] = ""
        # 从 enabledModels 中移除属于该 provider 的模型
        enabled = self.settings.get("enabledModels", [])
        if model_ids:
            self.settings["enabledModels"] = [m for m in enabled if m not in model_ids]


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


def lookup_context_window(model_id: str):
    """根据模型 id 在已知对照表中查找上下文窗口，返回 int 或 None。"""
    if not model_id:
        return None
    low = model_id.lower()
    # 先精确/较长匹配，再短匹配（避免误命中）
    for key in sorted(KNOWN_CONTEXT.keys(), key=len, reverse=True):
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
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            pass
        low = body.lower()
        # 判定是否明确“不支持图片/视觉”
        unsupported_kw = ["image", "vision", "图片", "图像", "not support", "unsupported",
                          "does not support", "invalid", "multimodal"]
        if e.code in (400, 422) and any(k in low for k in unsupported_kw):
            return True, False, f"{e.code} 不支持图片（{int(latency)}ms）"
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
# 主窗口
# =============================================================================

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, store: ConfigStore):
        super().__init__()
        self.store = store
        self.tray = None  # 由 main() 注入，用于增删后刷新托盘菜单
        self._testing = False
        self._closed = False
        self.setWindowTitle("pi API Switcher")
        self.resize(900, 640)
        self.setMinimumSize(720, 480)

        # 应用配置：主题 + 字体
        self.app_config = _load_app_config()
        self.theme_name = self.app_config.get("theme", "terminal")
        self.font_family = self.app_config.get("font", "")
        self.font_size = int(self.app_config.get("font_size", 13))
        global COLORS
        COLORS = THEMES.get(self.theme_name, THEMES["terminal"])

        self._build_menu()  # 菜单栏（必须在 _build_ui 前）
        self._build_ui()
        self._apply_font()
        self._apply_style()
        self.refresh_list()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 左侧：provider 列表 ----
        left = QtWidgets.QWidget()
        left.setFixedWidth(260)
        left.setObjectName("sidebar")
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 12, 12)
        lv.setSpacing(8)

        title = QtWidgets.QLabel("API 供应商")
        title.setObjectName("sidebarTitle")
        lv.addWidget(title)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setObjectName("providerList")
        self.list_widget.currentItemChanged.connect(self.on_select)
        lv.addWidget(self.list_widget, 1)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton("＋ 添加")
        self.btn_del = QtWidgets.QPushButton("删除")
        self.btn_add.setObjectName("accentBtn")
        self.btn_del.setObjectName("dangerBtn")
        self.btn_add.clicked.connect(self.on_add)
        self.btn_del.clicked.connect(self.on_del)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_del)
        lv.addLayout(btn_row)

        root.addWidget(left)

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
        empty_icon = QtWidgets.QLabel("π")
        empty_icon.setObjectName("emptyIcon")
        empty_icon.setAlignment(QtCore.Qt.AlignCenter)
        empty_text = QtWidgets.QLabel("从左侧选择或添加供应商")
        empty_text.setObjectName("emptyText")
        empty_text.setAlignment(QtCore.Qt.AlignCenter)
        empty_sub = QtWidgets.QLabel("支持管理多个 API 端点，一键切换默认模型")
        empty_sub.setObjectName("emptySubText")
        empty_sub.setAlignment(QtCore.Qt.AlignCenter)
        empty_lay.addWidget(empty_icon)
        empty_lay.addWidget(empty_text)
        empty_lay.addWidget(empty_sub)
        rv.addWidget(self.empty_hint)

        # 表单
        form = QtWidgets.QGridLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)

        self.ed_baseurl = self._add_field(form, 0, "Base URL")

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
        self.model_table.horizontalHeader().setStretchLastSection(False)
        self.model_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.model_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.model_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self.model_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)  # 输入列：固定宽度
        self.model_table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.Fixed)
        self.model_table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.Fixed)
        self.model_table.horizontalHeader().setSectionResizeMode(6, QtWidgets.QHeaderView.Fixed)
        self.model_table.horizontalHeader().setSectionResizeMode(7, QtWidgets.QHeaderView.Fixed)
        # 固定列宽（列0/1 会自动伸缩填满剩余空间）
        self.model_table.setColumnWidth(2, 48)   # 推理
        self.model_table.setColumnWidth(3, 110)  # 输入
        self.model_table.setColumnWidth(4, 84)   # 思考上限
        self.model_table.setColumnWidth(5, 92)   # 上下文
        self.model_table.setColumnWidth(6, 84)   # 最大输出
        self.model_table.setColumnWidth(7, 150)  # 视觉模型
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
        self.model_table.verticalHeader().setDefaultSectionSize(34)
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

        root.addWidget(right, 1)

    def _add_field(self, form, row, label):
        lbl = QtWidgets.QLabel(label)
        lbl.setFixedWidth(90)
        form.addWidget(lbl, row, 0)
        ed = QtWidgets.QLineEdit()
        form.addWidget(ed, row, 1)
        return ed

    # ---- 样式 ----
    def _build_menu(self):
        """构建顶部菜单栏：外观（主题 + 字体）。"""
        bar = self.menuBar()
        bar.setObjectName("menuBar")

        # 外观菜单
        menu_view = bar.addMenu("外观")

        # 主题子菜单
        menu_theme = menu_view.addMenu("主题")
        theme_names = {
            "terminal": "Terminal（黑灰+暖橙）",
            "codex": "Codex（白色+绿调）",
            "claude": "Claude Code（橙赑+米色）",
            "deepseek": "DeepSeek（深蓝+青）",
            "teal": "青绿+錡蓝",
            "night": "GitHub Night（紫+蓝）",
            "light": "浅色（灰白）",
        }
        theme_group = QtWidgets.QActionGroup(self)
        theme_group.setExclusive(True)
        for key, label in theme_names.items():
            act = menu_theme.addAction(label)
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

    def _switch_theme(self, name):
        self.theme_name = name
        self.app_config["theme"] = name
        _save_app_config(self.app_config)
        global COLORS
        COLORS = THEMES.get(name, THEMES["terminal"])
        self._apply_style()
        self.status.setText(f"已切换主题：{name}")

    def _switch_font(self, family):
        self.font_family = family
        self.app_config["font"] = family
        _save_app_config(self.app_config)
        self._apply_font()
        self._apply_style()
        self.status.setText(f"已切换字体：{family or '跟随系统'}")

    def _switch_font_size(self, size):
        self.font_size = size
        self.app_config["font_size"] = size
        _save_app_config(self.app_config)
        self._apply_font()
        self._apply_style()
        self.status.setText(f"已切换字号：{size} px")

    def _apply_font(self):
        """统一设置全局字体。"""
        from PyQt5.QtGui import QFont
        fam = self.font_family or None
        font = QFont(fam, self.font_size)
        # 防止中文乱码：明确指定一个 fallback
        font.setStyleHint(QFont.SansSerif)
        QtWidgets.QApplication.instance().setFont(font)

    def _apply_style(self):
        c = THEMES.get(self.theme_name, THEMES["terminal"])
        bt = c["btn_text"]
        accent2_hover = c["accent_2"]
        # 计算半透明色用于微妙效果
        panel_dim = c["panel"]
        self.setStyleSheet(f"""
            /* === 全局 === */
            QMainWindow, QWidget {{ background: {c['bg']}; color: {c['text']}; }}
            QLabel {{ color: {c['text_dim']}; font-size: 13px; }}

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

            /* === 侧边栏 === */
            #sidebar {{ background: {c['bg_alt']};
                         border-right: 1px solid {c['border']}; }}
            #sidebarTitle {{ font-size: 15px; font-weight: 700; color: {c['accent']};
                              padding: 6px 4px 2px 4px; letter-spacing: 0.5px; }}
            #providerList {{ background: transparent; border: none; outline: none; font-size: 13px; }}
            #providerList::item {{ padding: 11px 10px; border-radius: 8px; margin: 1px 0;
                                    border-left: 3px solid transparent; }}
            #providerList::item:selected {{ background: {c['panel']}; color: {c['accent']};
                                             border-left: 3px solid {c['accent']}; font-weight: 600; }}
            #providerList::item:hover:!selected {{ background: {c['panel']}; }}

            /* === 右侧内容区 === */
            #content {{ background: {c['bg']}; }}
            #detailTitle {{ font-size: 24px; font-weight: 700; color: {c['text']};
                             padding: 2px 0 4px 0; letter-spacing: -0.3px; }}
            #sectionLabel {{ font-size: 13px; font-weight: 600; color: {c['text']};
                              margin-top: 8px; margin-bottom: 2px;
                              border-bottom: 1px solid {c['border']}; padding-bottom: 4px; }}

            /* === 空状态 === */
            #emptyHint {{ background: transparent; }}
            #emptyIcon {{ font-size: 64px; color: {c['border']}; font-weight: 300;
                           padding-bottom: 8px; }}
            #emptyText {{ color: {c['text_dim']}; font-size: 16px; font-weight: 500;
                           padding: 0; }}
            #emptySubText {{ color: {c['border']}; font-size: 13px; padding-top: 4px; }}

            /* === 模型表格 === */
            #modelTable {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px;
                           gridline-color: {c['border']}; color: {c['text']}; font-size: 13px; }}
            #modelTable::item {{ padding: 5px 8px; }}
            #modelTable::item:selected {{ background: {c['accent']}; color: {bt}; }}
            QHeaderView::section {{ background: {c['bg_alt']}; color: {c['text_dim']}; border: none;
                                    padding: 7px 10px; font-size: 12px; font-weight: 600; }}

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

            /* === 默认标记 & 状态栏 === */
            #defaultBadge {{ color: {c['green']}; font-size: 13px; font-weight: 600;
                              padding: 4px 0; }}
            #statusBar {{ color: {c['text_dim']}; font-size: 12px; padding-top: 8px;
                          border-top: 1px solid {c['border']}; }}
            #loadingDots {{ color: {c['accent']}; font-size: 14px; font-weight: 700;
                             padding-top: 8px; min-width: 24px; }}
        """)

    # ---- 数据刷新 ----
    def refresh_list(self, select_name=None):
        self.list_widget.clear()
        names = self.store.provider_names()
        default = self.store.default_provider()
        for name in names:
            marker = "★ " if name == default else "   "
            item = QtWidgets.QListWidgetItem(f"{marker}{name}")
            item.setData(QtCore.Qt.UserRole, name)
            self.list_widget.addItem(item)
        # 空状态：无 provider 时显示引导，隐藏表单
        has_any = len(names) > 0
        self.empty_hint.setVisible(not has_any)
        self.detail_title.setVisible(has_any)
        # 隐藏/显示表单区域
        for w in [self.ed_baseurl.parentWidget() or self.ed_baseurl,
                  self.ed_apikey.parentWidget() or self.ed_apikey,
                  self.model_table, self.btn_test, self.btn_save, self.btn_default,
                  self.lbl_default]:
            if w:
                w.setVisible(has_any)
        if select_name:
            for i in range(self.list_widget.count()):
                if self.list_widget.item(i).data(QtCore.Qt.UserRole) == select_name:
                    self.list_widget.setCurrentRow(i)
                    break
        elif names:
            self.list_widget.setCurrentRow(0)

    def _is_dirty(self) -> bool:
        """检测当前表单/表格是否有未保存的改动。"""
        name = self.current_name()
        if not name:
            return False
        p = self.store.get_provider(name)
        # Base URL
        if self.ed_baseurl.text().strip() != (p.get("baseUrl") or ""):
            return True
        # API Key（掩码比对：只看长度变化或前缀，避免明文存储）
        cur_key = self.ed_apikey.text().strip()
        saved_key = self.store.api_key(name)
        if cur_key != saved_key:
            return True
        # 显示名
        if self.ed_model_name.text().strip() != (p.get("name") or ""):
            return True
        # 模型表格：读取当前表格与存储的 models 对比
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
            # 思考上限对比
            if get_max_thinking_level(tm) != get_max_thinking_level(sm):
                return True
            # 上下文窗口 / 最大输出对比
            if tm.get("contextWindow", 128000) != sm.get("contextWindow", 128000):
                return True
            if tm.get("maxTokens", 16384) != sm.get("maxTokens", 16384):
                return True
            # 视觉插件对比
            if tm.get("visionModel", "") != sm.get("visionModel", ""):
                return True
        return False

    def _confirm_discard(self) -> bool:
        """有未保存改动时弹窗确认是否丢弃。返回 True 表示可以继续切换。"""
        if not self._is_dirty():
            return True
        ret = QtWidgets.QMessageBox.question(
            self, "未保存的改动",
            "当前供应商有未保存的修改，是否丢弃并切换？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return ret == QtWidgets.QMessageBox.Yes

    def on_select(self, current, _prev):
        if not current:
            return
        # 切换前检测未保存改动
        if self.current_name() and current.data(QtCore.Qt.UserRole) != self.current_name():
            if not self._confirm_discard():
                # 用户取消：选回原来的项
                prev_name = self.current_name()
                for i in range(self.list_widget.count()):
                    if self.list_widget.item(i).data(QtCore.Qt.UserRole) == prev_name:
                        # 防递归：暂时记录
                        pass
                return
        name = current.data(QtCore.Qt.UserRole)
        p = self.store.get_provider(name)
        self.detail_title.setText(name)
        self.ed_baseurl.setText(p.get("baseUrl", ""))
        self.ed_apikey.setText(self.store.api_key(name))
        self.ed_model_name.setText(p.get("name", ""))

        # 填充模型表格（多模型）
        self._fill_model_table(p.get("models", []))

        # 默认标记
        is_default = name == self.store.default_provider()
        if is_default:
            self.lbl_default.setText(f"✓ 当前默认 · {self.store.default_model()}")
        else:
            self.lbl_default.setText("")

    def _fill_model_table(self, models):
        """将模型列表填到表格中。"""
        self.model_table.setRowCount(0)
        for m in models:
            self._add_model_row(
                m.get("id", ""),
                m.get("name", ""),
                bool(m.get("reasoning", False)),
                ",".join(m.get("input", ["text"])),
                get_max_thinking_level(m),
                m.get("contextWindow", 128000),
                m.get("maxTokens", 16384),
                m.get("visionModel", ""),
            )
        # 若表格为空，加一行空行便于编辑
        if self.model_table.rowCount() == 0:
            self._add_model_row("", "", False, "text", "off", 128000, 16384, "")

    def _add_model_row(self, mid, name, reasoning, input_types, max_thinking="off",
                       context_window=128000, max_tokens=16384, vision_model=""):
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

        # 列5：上下文窗口（可编辑数字）
        item_ctx = QtWidgets.QTableWidgetItem(str(context_window))
        item_ctx.setData(QtCore.Qt.UserRole, context_window)
        item_ctx.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.model_table.setItem(row, 5, item_ctx)

        # 列6：最大输出 tokens（可编辑数字）
        item_max = QtWidgets.QTableWidgetItem(str(max_tokens))
        item_max.setData(QtCore.Qt.UserRole, max_tokens)
        item_max.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.model_table.setItem(row, 6, item_max)

        # 列7：视觉模型（纯文本模型可挂一个视觉插件）
        vision_btn = QtWidgets.QPushButton()
        vision_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        vision_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._update_vision_btn(vision_btn, vision_model, input_types, name or mid)
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

    # ---- 视觉模型（视觉插件） ----
    def _update_vision_btn(self, btn, vision_model, input_types, model_name=""):
        """更新视觉模型按钮文案与状态。所有模型都可点击选择视觉桥接。
        vision_model 格式：provider:modelId（可含多个，用 | 分隔）。
        model_name：当前模型自己的名称（用于自身支持图片时的标识）。"""
        has_image = "image" in [x.strip() for x in (input_types or "").split(",")]
        btn.setStyleSheet("""
            QPushButton {
                border: none; border-radius: 4px; padding: 2px 8px;
                font-size: 11px; background: transparent;
            }
            QPushButton:hover { background: rgba(128,128,128,0.15); }
            QPushButton:disabled { color: #888888; }
        """)
        if vision_model:
            # 已挂接视觉桥接
            short = self._short_vision_label(vision_model)
            btn.setText(f"🎯 {short}")
            btn.setEnabled(True)
            btn.setToolTip(f"视觉桥接：{vision_model}\n点击更换或清除")
            btn.setProperty("visionModel", vision_model)
        elif has_image:
            # 自身支持图片，但也可选择挂接其他视觉桥接
            label = model_name or "视觉"
            if len(label) > 14:
                label = label[:13] + "…"
            btn.setText(f"🖼 {label}")
            btn.setEnabled(True)
            btn.setToolTip(f"该模型自身支持图片（{model_name or '视觉模型'}）\n点击可选择挂接其他视觉桥接")
            btn.setProperty("visionModel", "")
        else:
            btn.setText("＋ 添加")
            btn.setEnabled(True)
            btn.setToolTip("为纯文本模型挂接一个视觉模型")
            btn.setProperty("visionModel", "")

    def _short_vision_label(self, vision_model):
        """把 provider:modelId 转成友好的视觉模型显示名（provider / 模型名）。
        优先用模型在 store 里的 name，回退到 modelId。"""
        if not vision_model:
            return ""
        # 取第一个（可能多个，用 | 分隔）
        first = vision_model.split("|")[0].strip()
        provider = ""
        model_id = first
        if ":" in first:
            provider, model_id = first.split(":", 1)
            provider = provider.strip()
            model_id = model_id.strip()
        # 从 store 查模型的真实 name
        display = model_id
        if provider:
            p = self.store.get_provider(provider)
            for m in p.get("models", []):
                if m.get("id") == model_id:
                    display = m.get("name") or model_id
                    break
        # 拼接 provider / name
        label = f"{provider} / {display}" if provider else display
        # 过长则截断
        return label if len(label) <= 22 else label[:21] + "…"

    def _vision_btn_at(self, row):
        """获取某行视觉模型按钮（兼容 cell widget 为容器的情况）。"""
        w = self.model_table.cellWidget(row, 7)
        if w is None:
            return None
        if isinstance(w, QtWidgets.QPushButton):
            return w
        # 容器内查找按钮
        return w.findChild(QtWidgets.QPushButton)

    def _on_input_changed(self, row, txt):
        """输入类型下拉变化时，更新该行视觉模型按钮状态。"""
        if row < 0:
            return
        btn = self._vision_btn_at(row)
        if btn:
            vision = btn.property("visionModel") or ""
            # 从表格取模型名称（列1 显示名，回退到列0 模型 ID）
            name_item = self.model_table.item(row, 1)
            id_item = self.model_table.item(row, 0)
            model_name = (name_item.text().strip() if name_item else "") or \
                         (id_item.text().strip() if id_item else "")
            self._update_vision_btn(btn, vision, txt, model_name)

    def _on_pick_vision_model(self, row):
        """为模型选择/更换视觉桥接（所有模型都可选择）。"""
        if row < 0:
            return

        # 收集所有可用的视觉模型（input 含 image 的模型），跨所有 provider
        candidates = []  # (label, vision_model_str)
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
                candidates.append((label, f"{pname}:{mid}"))

        if not candidates:
            QtWidgets.QMessageBox.information(
                self, "无可用视觉模型",
                "当前没有配置任何支持图像输入的模型。\n\n"
                "请先在某供应商下添加一个 input 为 text,image 的模型。"
            )
            return

        box = QtWidgets.QDialog(self)
        box.setWindowTitle("选择视觉模型（视觉插件）")
        box.resize(420, 380)
        lay = QtWidgets.QVBoxLayout(box)

        tip = QtWidgets.QLabel("为主模型挂接一个视觉模型，用于处理图片输入：")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        lst = QtWidgets.QListWidget()
        for label, _ in candidates:
            lst.addItem(label)
        lay.addWidget(lst)

        # 清除选项
        btn_clear = QtWidgets.QPushButton("清除视觉插件")
        btn_clear.setObjectName("dangerBtn")

        btn_row = QtWidgets.QHBoxLayout()
        btn_ok = QtWidgets.QPushButton("确定")
        btn_ok.setObjectName("accentBtn")
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_row.addWidget(btn_clear)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

        btn_ok.clicked.connect(box.accept)
        btn_cancel.clicked.connect(box.reject)
        btn_clear.clicked.connect(lambda: (lst.clearSelection(), box.done(2)))

        c = COLORS
        box.setStyleSheet(f"""
            QDialog {{ background: {c['bg']}; }}
            QLabel {{ color: {c['text']}; font-size: 13px; }}
            QListWidget {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px;
                           color: {c['text']}; font-size: 13px; }}
            QListWidget::item {{ padding: 6px 8px; }}
            QListWidget::item:selected {{ background: {c['accent']}; color: {c['btn_text']}; }}
            QPushButton {{ background: {c['panel']}; color: {c['text']}; border-radius: 6px;
                           padding: 8px 14px; font-size: 13px; }}
            QPushButton#accentBtn {{ background: {c['accent']}; color: {c['btn_text']}; font-weight: 600; }}
            QPushButton#dangerBtn {{ background: transparent; color: {c['red']}; border: 1px solid {c['red']}; }}
        """)

        ret = box.exec_()
        btn = self._vision_btn_at(row)
        if not btn:
            return

        # 获取当前行的输入类型与模型名（清除后需正确恢复显示）
        cw = self.model_table.cellWidget(row, 3)
        input_types = cw.currentText() if (cw and isinstance(cw, QtWidgets.QComboBox)) else "text"
        name_item = self.model_table.item(row, 1)
        id_item = self.model_table.item(row, 0)
        model_name = (name_item.text().strip() if name_item else "") or \
                     (id_item.text().strip() if id_item else "")

        if ret == 2:  # 清除
            self._update_vision_btn(btn, "", input_types, model_name)
            return
        if ret != QtWidgets.QDialog.Accepted:
            return

        sel = lst.currentRow()
        if sel < 0:
            return
        label, vision_str = candidates[sel]
        self._update_vision_btn(btn, vision_str, input_types, model_name)
        self.status.setText(f"已挂接视觉插件：{label}（记得点保存）")

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

            # 视觉模型
            vision_model = ""
            vbtn = self._vision_btn_at(row)
            if vbtn:
                vision_model = vbtn.property("visionModel") or ""

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
            # 纯文本模型挂视觉插件
            if vision_model:
                model["visionModel"] = vision_model
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
        self.store.save()
        self.refresh_list(select_name=name)
        self._refresh_tray()

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
        self.store.save()
        self.refresh_list()
        self._refresh_tray()
        self.status.setText(f"已删除 {name}")

    def _refresh_tray(self):
        if self.tray is not None:
            self.tray._build_menu()

    def on_save(self):
        name = self.current_name()
        if not name:
            self.status.setText("请先选择供应商")
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

        # 从表格读取多模型
        models = self._read_model_table()
        if not models:
            QtWidgets.QMessageBox.warning(self, "提示", "至少需要一个模型（请填写模型 ID）")
            return

        p["baseUrl"] = base_url
        p["name"] = self.ed_model_name.text().strip() or name
        p["models"] = models

        # 同步 enabledModels 白名单（让 pi /model 能显示这些模型）
        self.store.sync_enabled_models(name)

        # apiKey
        key = self.ed_apikey.text().strip()
        self.store.set_api_key(name, key)

        if self.store.save():
            self.status.setText(f"已保存 {name}（{len(models)} 个模型）· 重启 pi 或执行 /reload 生效")
            self.refresh_list(select_name=name)
            self._refresh_tray()
        else:
            self.status.setText("保存失败")

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
        self.store.save()
        self.status.setText(f"已将 {name}/{model_id} 设为默认（pi 下次启动生效）")
        self.refresh_list(select_name=name)
        self._refresh_tray()

    def _animate_loading(self):
        """动态省略号动画。"""
        self._loading_dots_count = (self._loading_dots_count + 1) % 4
        self.loading_dots.setText("." * (self._loading_dots_count + 1))

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
            self.status.setText("Base URL 为空")
            return
        self.status.setText(f"正在测试 {name}")
        self.loading_dots.setVisible(True)
        self._loading_dots_count = 0
        self._loading_timer.start()
        self.btn_test.setEnabled(False)
        self._testing = True

        def run():
            ok, latency, msg, model_infos = test_endpoint(base_url, key)
            # dict 列表无法直接用 Qt 信号传递，序列化为 JSON 字符串
            payload = json.dumps(model_infos, ensure_ascii=False)
            QtCore.QMetaObject.invokeMethod(
                self, "_on_test_done", QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, name), QtCore.Q_ARG(bool, ok),
                QtCore.Q_ARG(int, latency), QtCore.Q_ARG(str, msg),
                QtCore.Q_ARG(str, payload),
            )

        threading.Thread(target=run, daemon=True).start()

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
            self.status.setText(f"{icon} {name}: {latency}ms · {msg} · 拉到 {n} 个模型")
            if model_infos:
                # 弹窗展示模型列表，并可一键导入到表格
                self._show_discovered_models(name, model_infos, latency)
        else:
            self.status.setText(f"{icon} {name}: {latency}ms · {msg}")

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
            self._add_model_row(mid, mid, reasoning, input_types, max_think, ctx, 16384, vision_model)
            existing_ids.add(mid)
            imported += 1
        if imported:
            self.status.setText(f"已导入 {imported} 个模型（含自动识别能力与视觉插件），记得点保存")

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
                vstr = f"{pname}:{mid}"
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
        在弹窗内同步探测并直接更新表格（modal 弹窗无法用异步回调更新）。"""
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

        self.status.setText(f"正在探测 {len(selected)} 个模型的能力...")
        # 逐个探测，同步更新表格
        for r, mid in selected:
            img_item = tbl.item(r, 2)
            ctx_item = tbl.item(r, 3)
            if img_item:
                img_item.setText("⏳ 探测中...")
            QtWidgets.QApplication.processEvents()
            ok, supports, msg = probe_model_capability(base_url, key, mid)
            if img_item:
                img_item.setText("🖼 支持" if supports else "仅文本")
            # 上下文：先查已知对照表，再回退到端点已返回的值
            ctx_lookup = lookup_context_window(mid)
            ctx_from_endpoint = None
            for mi in model_infos:
                if mi.get("id") == mid:
                    mi["input"] = ["text", "image"] if supports else ["text"]
                    ctx_from_endpoint = mi.get("contextWindow")
                    break
            ctx_final = ctx_lookup or ctx_from_endpoint
            if ctx_final:
                if ctx_item:
                    ctx_item.setText(str(ctx_final))
                # 同步写入 model_infos
                for mi in model_infos:
                    if mi.get("id") == mid:
                        mi["contextWindow"] = ctx_final
                        break
            else:
                if ctx_item:
                    ctx_item.setText("未知")
            self.status.setText(
                f"{mid}: {'支持图片' if supports else '不支持图片'} · "
                f"上下文 {ctx_final if ctx_final else '未知'} ({msg})"
            )
            QtWidgets.QApplication.processEvents()
        self.status.setText(f"探测完成：{len(selected)} 个模型")

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
            self.store.save()
            self.showMessage("pi API Switcher", f"已切换默认: {name}/{model_id}")
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

    # 图标
    icon_path = Path(__file__).parent / "icon.ico"
    if not icon_path.exists():
        generate_icon_ico(icon_path)
    icon = QtGui.QIcon(str(icon_path)) if icon_path.exists() else QtGui.QIcon()
    app.setWindowIcon(icon)

    store = ConfigStore()
    window = MainWindow(store)

    # 系统托盘
    tray = TrayApp(icon, window, store)
    tray.show()
    window.tray = tray  # 注入托盘引用，供增删后刷新菜单

    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
