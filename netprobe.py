# -*- coding: utf-8 -*-
"""网络探测与后台测速工作线程：
- test_endpoint: /models 连通性测试 + 模型/能力元数据发现
- probe_model_capability: 1x1 透明 PNG 探测模型是否支持图片输入
- lookup_context_window: 常见模型上下文窗口静态对照表
- TestEndpointWorker / ProbeModelsWorker / BatchEndpointTester
"""

import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PyQt5.QtCore import QThread, pyqtSignal


# =============================================================================
# 静态模型上下文窗口对照表
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

_KNOWN_CONTEXT_SORTED = sorted(KNOWN_CONTEXT.keys(), key=len, reverse=True)


def lookup_context_window(model_id: str):
    """根据模型 id 在已知对照表中查找上下文窗口，返回 int 或 None。"""
    if not model_id:
        return None
    low = model_id.lower()
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
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{png_b64}"},
                    },
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
                    ctx = None
                    for key in (
                        "contextWindow", "context_window", "contextLength",
                        "context_length", "maxContextTokens", "max_context_tokens",
                        "contextWindowTokens", "inputTokens", "context"
                    ):
                        if key in m and m[key] is not None:
                            ctx = m[key]
                            break
                    if ctx is not None:
                        try:
                            info["contextWindow"] = int(ctx)
                        except (TypeError, ValueError):
                            pass
                    inp = m.get("input") or m.get("inputTypes") or m.get("input_types")
                    if inp is None:
                        caps = m.get("capabilities") or {}
                        if isinstance(caps, dict):
                            inp = caps.get("input") or caps.get("modalities")
                    if inp is not None:
                        if isinstance(inp, str):
                            inp = [inp]
                        if isinstance(inp, list):
                            info["input"] = [str(x) for x in inp]
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
# 工作线程
# =============================================================================

# 批量测速时同时进行的网络请求上限：避免供应商很多时打爆本地临时端口或触发上游限流
MAX_CONCURRENT_PROBES = 8


class TestEndpointWorker(QThread):
    """异步测试端点连通性。"""
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
    """逐个探测模型能力（是否支持图片），每完成一个发信号更新表格。"""
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
    """并发测试全部端点（线程池限流，最多 MAX_CONCURRENT_PROBES 路）。"""
    result_ready = pyqtSignal(str, bool, int, str, str)  # name, ok, latency, msg, payload

    def __init__(self, targets, parent=None):
        super().__init__(parent)
        self.targets = targets  # [(name, base_url, api_key), ...]
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
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
                except Exception as e:
                    ok, latency, msg, model_infos = False, 0, f"错误: {e}", []
                payload = json.dumps(model_infos, ensure_ascii=False)
                self.result_ready.emit(name, ok, int(latency), msg, payload)
