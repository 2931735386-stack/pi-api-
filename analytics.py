# -*- coding: utf-8 -*-
"""
Token & Request Analytics Engine for pi-api-switcher
Parses ~/.pi/agent/sessions/*.jsonl files to provide comprehensive statistics:
- Filter by: 'day' (24h), 'week' (7d), 'month' (30d), 'year' (all active)
- Daily Average metrics (Requests, Tokens, Estimated Cost)
- Total Requests (Success, Fail, Rate)
- Total Tokens (Input, Output, CacheRead, CacheWrite, Reasoning)
- Real-time RPM / TPM estimation
- Cache hit rate & Estimated total cost ($)
- GitHub/Vercel-style activity heatmaps (Tokens & Health timeline)
- Model breakdown stats
"""

import json
import datetime
from pathlib import Path
from collections import defaultdict


# 默认基础费率估算（每 1M Tokens 美元）：输入 $1.50, 输出 $2.00, 缓存读 $0.30
# 可被 ~/.pi/agent/api-switcher.json 中的 priceRates 配置覆盖
DEFAULT_PRICE_PER_M_INPUT = 1.50
DEFAULT_PRICE_PER_M_OUTPUT = 2.00
DEFAULT_PRICE_PER_M_CACHE_READ = 0.30


def _load_price_rates():
    """从应用配置 api-switcher.json 读取自定义费率，缺失时回退到默认值。
    配置示例：{"priceRates": {"input": 1.5, "output": 2.0, "cacheRead": 0.3}}"""
    cfg_path = Path.home() / ".pi" / "agent" / "api-switcher.json"
    rates = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
    try:
        cfg = json.loads(rates) if rates.strip() else {}
        pr = cfg.get("priceRates", {}) or {}
        return (
            float(pr.get("input", DEFAULT_PRICE_PER_M_INPUT)),
            float(pr.get("output", DEFAULT_PRICE_PER_M_OUTPUT)),
            float(pr.get("cacheRead", DEFAULT_PRICE_PER_M_CACHE_READ)),
        )
    except (ValueError, TypeError, json.JSONDecodeError):
        return (DEFAULT_PRICE_PER_M_INPUT, DEFAULT_PRICE_PER_M_OUTPUT, DEFAULT_PRICE_PER_M_CACHE_READ)


def _load_all_records(sessions_dir):
    """一次性读取并解析 sessions 目录下所有 JSONL 记录，返回规范化的 dict 列表。
    结果按文件路径+mtime 缓存，文件未改动时直接返回缓存，避免重复磁盘 I/O。
    """
    jsonl_files = list(sessions_dir.glob("**/*.jsonl"))
    # 检查缓存是否可复用：文件集合与 mtime 未变
    # mtime 的浮点秒精度不足以覆盖快速连续写入；同时记录纳秒时间和大小，
    # 避免日志在短时间内更新时误用旧解析结果。
    current_sig = {}
    for f in jsonl_files:
        try:
            stat = f.stat()
        except OSError:
            continue
        current_sig[str(f)] = (stat.st_mtime_ns, stat.st_size)
    cache = _RAW_RECORDS_CACHE.get(str(sessions_dir))
    if cache and cache["sig"] == current_sig:
        return cache["records"]

    records = []
    for f in jsonl_files:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    # Vision Bridge writes custom entries that do not enter LLM context.
                    # Input-hook nested usage is otherwise invisible to Pi; tool-result
                    # nested usage is already returned through Pi and is not added twice.
                    if data.get("type") == "custom" and data.get("customType") == "vision-bridge-usage-v1":
                        event = data.get("data")
                        if not isinstance(event, dict):
                            continue
                        usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
                        include = bool(event.get("includeInTotals"))
                        inp = (usage.get("input", 0) or 0) if include else 0
                        out = (usage.get("output", 0) or 0) if include else 0
                        cr = (usage.get("cacheRead", 0) or 0) if include else 0
                        cw = (usage.get("cacheWrite", 0) or 0) if include else 0
                        rea = (usage.get("reasoning", 0) or 0) if include else 0
                        total = (usage.get("totalTokens", inp + out) or (inp + out)) if include else 0
                        ts = event.get("timestamp") or data.get("timestamp")
                        epoch_s = _timestamp_to_epoch(ts)
                        vision_provider = event.get("visionProvider") or "unknown"
                        vision_model = event.get("visionModel") or "unknown"
                        records.append({
                            "kind": "vision",
                            "model": f"vision:{vision_provider}/{vision_model}",
                            "epoch_s": epoch_s,
                            "is_fail": event.get("status") == "failure",
                            "input": inp,
                            "output": out,
                            "cacheRead": cr,
                            "cacheWrite": cw,
                            "reasoning": rea,
                            "total": total,
                            "include_in_totals": include,
                            "vision_status": event.get("status", "unknown"),
                            "vision_cached": bool(event.get("cached")),
                            "vision_requested": bool(event.get("requested")),
                            "vision_latency_ms": event.get("latencyMs", 0) or 0,
                            "vision_image_bytes": event.get("imageBytes", 0) or 0,
                            "vision_image_count": event.get("imageCount", 0) or 0,
                        })
                        continue

                    msg = data.get("message", {})
                    if not isinstance(msg, dict):
                        continue
                    u = msg.get("usage")
                    if not isinstance(u, dict):
                        continue

                    model = msg.get("model") or msg.get("responseModel") or data.get("model") or "unknown"
                    ts = msg.get("timestamp") or data.get("timestamp")
                    epoch_s = _timestamp_to_epoch(ts)

                    stop_reason = msg.get("stopReason", "")
                    is_fail = stop_reason in ["error", "abort"] or "error" in data
                    inp = u.get("input", 0) or 0
                    out = u.get("output", 0) or 0
                    cr = u.get("cacheRead", 0) or 0
                    cw = u.get("cacheWrite", 0) or 0
                    rea = u.get("reasoning", 0) or 0
                    tot = u.get("totalTokens", inp + out) or (inp + out)

                    records.append({
                        "kind": "model",
                        "model": model,
                        "epoch_s": epoch_s,
                        "is_fail": is_fail,
                        "input": inp,
                        "output": out,
                        "cacheRead": cr,
                        "cacheWrite": cw,
                        "reasoning": rea,
                        "total": tot,
                        "include_in_totals": True,
                    })
        except Exception:
            continue

    _RAW_RECORDS_CACHE[str(sessions_dir)] = {"sig": current_sig, "records": records}
    return records


# 原始记录缓存：{目录路径: {"sig": {文件路径: mtime}, "records": [...]}}
_RAW_RECORDS_CACHE = {}


def _timestamp_to_epoch(value):
    if isinstance(value, (int, float)):
        return value / 1000.0 if value > 1e11 else float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def parse_session_records(sessions_dir=None, filter_mode="year"):
    """
    filter_mode: 'day' | 'week' | 'month' | 'year'
    """
    if sessions_dir is None:
        sessions_dir = Path.home() / ".pi" / "agent" / "sessions"
    else:
        sessions_dir = Path(sessions_dir)
        
    if not sessions_dir.exists():
        return _empty_result()

    now = datetime.datetime.now()
    cutoff_time = 0.0
    if filter_mode == "day":
        cutoff_time = (now - datetime.timedelta(days=1)).timestamp()
    elif filter_mode == "week":
        cutoff_time = (now - datetime.timedelta(days=7)).timestamp()
    elif filter_mode == "month":
        cutoff_time = (now - datetime.timedelta(days=30)).timestamp()
    else: # year / all
        cutoff_time = 0.0

    total_calls = 0
    success_calls = 0
    failed_calls = 0
    total_tokens = 0
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0
    total_reasoning = 0
    vision_calls = 0
    vision_success = 0
    vision_failures = 0
    vision_cache_hits = 0
    vision_latency_ms = 0
    vision_image_bytes = 0
    vision_image_count = 0

    daily_map = defaultdict(lambda: {
        "calls": 0, "tokens": 0, "input": 0, "output": 0,
        "cacheRead": 0, "cacheWrite": 0, "reasoning": 0,
        "success": 0, "fail": 0,
        "visionCalls": 0, "visionCacheHits": 0
    })
    model_map = defaultdict(lambda: {
        "calls": 0, "input": 0, "output": 0,
        "cacheRead": 0, "cacheWrite": 0, "reasoning": 0,
        "total": 0, "last_used": 0
    })

    timestamps = []

    # 一次性读入所有原始记录（P-1：避免切换 filter 时全量重扫文件）
    for rec in _load_all_records(sessions_dir):
        epoch_s = rec["epoch_s"]
        # 切换 filter 时只做聚合计算，不重复磁盘 I/O
        if cutoff_time > 0 and epoch_s > 0 and epoch_s < cutoff_time:
            continue

        model = rec["model"]
        is_fail = rec["is_fail"]
        is_vision = rec.get("kind") == "vision"
        if is_vision:
            status = rec.get("vision_status")
            if rec.get("vision_requested"):
                vision_calls += 1
                vision_latency_ms += rec.get("vision_latency_ms", 0) or 0
            if status == "success":
                vision_success += 1
            elif status == "failure":
                vision_failures += 1
            elif status == "cache_hit":
                vision_cache_hits += 1
            # Candidate fallback can emit multiple failure/skipped diagnostics
            # for one user image. Count image volume only for the final success
            # or a session-cache reuse, so dashboard totals are not multiplied.
            if status in ("success", "cache_hit"):
                vision_image_bytes += rec.get("vision_image_bytes", 0) or 0
                vision_image_count += rec.get("vision_image_count", 0) or 0

        # Tool-result usage is already included by Pi. Cache reuse and skipped
        # candidates carry no provider request usage. Keep their diagnostic
        # counters without double-counting requests/tokens/cost.
        if not rec.get("include_in_totals", True):
            if epoch_s > 0:
                dstr = datetime.datetime.fromtimestamp(epoch_s).strftime("%Y-%m-%d")
                if rec.get("vision_requested"):
                    daily_map[dstr]["visionCalls"] += 1
                if rec.get("vision_cached"):
                    daily_map[dstr]["visionCacheHits"] += 1
            continue

        inp = rec["input"]
        out = rec["output"]
        cr = rec["cacheRead"]
        cw = rec["cacheWrite"]
        rea = rec["reasoning"]
        tot = rec["total"]

        if epoch_s > 0:
            timestamps.append(epoch_s)

        total_calls += 1
        if is_fail:
            failed_calls += 1
        else:
            success_calls += 1

        total_tokens += tot
        total_input += inp
        total_output += out
        total_cache_read += cr
        total_cache_write += cw
        total_reasoning += rea

        model_map[model]["calls"] += 1
        model_map[model]["input"] += inp
        model_map[model]["output"] += out
        model_map[model]["cacheRead"] += cr
        model_map[model]["cacheWrite"] += cw
        model_map[model]["reasoning"] += rea
        model_map[model]["total"] += tot

        if epoch_s > model_map[model]["last_used"]:
            model_map[model]["last_used"] = epoch_s

        if epoch_s > 0:
            dt = datetime.datetime.fromtimestamp(epoch_s)
            dstr = dt.strftime("%Y-%m-%d")
            daily_map[dstr]["calls"] += 1
            daily_map[dstr]["tokens"] += tot
            daily_map[dstr]["input"] += inp
            daily_map[dstr]["output"] += out
            daily_map[dstr]["cacheRead"] += cr
            daily_map[dstr]["cacheWrite"] += cw
            daily_map[dstr]["reasoning"] += rea
            if is_fail:
                daily_map[dstr]["fail"] += 1
            else:
                daily_map[dstr]["success"] += 1
            if is_vision and rec.get("vision_requested"):
                daily_map[dstr]["visionCalls"] += 1
            if is_vision and rec.get("vision_cached"):
                daily_map[dstr]["visionCacheHits"] += 1

    # 日期范围
    if timestamps:
        min_dt = datetime.datetime.fromtimestamp(min(timestamps))
        max_dt = datetime.datetime.fromtimestamp(max(timestamps))
        date_range_str = f"{min_dt.strftime('%m/%d %H:%M')} - {max_dt.strftime('%m/%d %H:%M')}"
        active_days_span = max((max_dt.date() - min_dt.date()).days + 1, len(daily_map), 1)
    else:
        date_range_str = "无数据"
        active_days_span = 1

    # 热力图矩阵网格生成（根据筛选模式适配天数跨度）
    if filter_mode == "day":
        days_span = 28
    elif filter_mode == "week":
        days_span = 70
    elif filter_mode == "month":
        days_span = 140
    else:
        days_span = 210

    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=days_span - 1)
    
    heatmap_tokens = []
    heatmap_health = []
    daily_trend_tokens = []
    daily_trend_calls = []
    daily_trend_cache = []

    for i in range(days_span):
        curr = start_date + datetime.timedelta(days=i)
        curr_str = curr.strftime("%Y-%m-%d")
        dinfo = daily_map.get(curr_str, {
            "calls": 0, "tokens": 0, "input": 0, "output": 0,
            "cacheRead": 0, "cacheWrite": 0, "reasoning": 0,
            "success": 0, "fail": 0,
            "visionCalls": 0, "visionCacheHits": 0
        })
        
        heatmap_tokens.append({
            "date": curr_str,
            "tokens": dinfo["tokens"],
            "calls": dinfo["calls"],
            "input": dinfo["input"],
            "output": dinfo["output"],
            "cacheRead": dinfo["cacheRead"],
        })
        
        rate = 1.0
        if dinfo["calls"] > 0:
            rate = dinfo["success"] / dinfo["calls"]
        heatmap_health.append({
            "date": curr_str,
            "calls": dinfo["calls"],
            "success": dinfo["success"],
            "fail": dinfo["fail"],
            "rate": rate,
        })
        
        daily_trend_tokens.append(dinfo["tokens"])
        daily_trend_calls.append(dinfo["calls"])
        daily_trend_cache.append(dinfo["cacheRead"])

    # 成本估算（费率可从 api-switcher.json 的 priceRates 覆盖）
    price_in, price_out, price_cr = _load_price_rates()
    total_cost = (
        (total_input / 1_000_000.0) * price_in +
        (total_output / 1_000_000.0) * price_out +
        (total_cache_read / 1_000_000.0) * price_cr
    )
    
    # 每日平均指标
    avg_calls = total_calls / active_days_span if active_days_span > 0 else 0.0
    avg_tokens = total_tokens / active_days_span if active_days_span > 0 else 0.0
    avg_cost = total_cost / active_days_span if active_days_span > 0 else 0.0

    # 缓存读取率
    denom = total_input + total_cache_read
    cache_rate = (total_cache_read / denom * 100.0) if denom > 0 else 0.0

    # RPM / TPM 估算 (基于活跃小时数)
    active_hours = active_days_span * 24.0
    rpm = total_calls / (active_hours * 60.0) if active_hours > 0 else 0.0
    tpm = total_tokens / (active_hours * 60.0) if active_hours > 0 else 0.0

    # 成功率
    success_rate = (success_calls / total_calls * 100.0) if total_calls > 0 else 100.0

    return {
        "filter_mode": filter_mode,
        "date_range_str": date_range_str,
        "active_days_span": active_days_span,
        "total_calls": total_calls,
        "success_calls": success_calls,
        "failed_calls": failed_calls,
        "success_rate": success_rate,
        "total_tokens": total_tokens,
        "total_input": total_input,
        "total_output": total_output,
        "total_cache_read": total_cache_read,
        "total_cache_write": total_cache_write,
        "total_reasoning": total_reasoning,
        "total_cost": total_cost,
        "cache_rate": cache_rate,
        "rpm": rpm,
        "tpm": tpm,
        "avg_calls": avg_calls,
        "avg_tokens": avg_tokens,
        "avg_cost": avg_cost,
        "models": dict(model_map),
        "days": dict(daily_map),
        "heatmap_tokens": heatmap_tokens,
        "heatmap_health": heatmap_health,
        "daily_trend_tokens": daily_trend_tokens,
        "daily_trend_calls": daily_trend_calls,
        "daily_trend_cache": daily_trend_cache,
        "vision_calls": vision_calls,
        "vision_success": vision_success,
        "vision_failures": vision_failures,
        "vision_cache_hits": vision_cache_hits,
        "vision_avg_latency_ms": (vision_latency_ms / vision_calls) if vision_calls > 0 else 0.0,
        "vision_image_bytes": vision_image_bytes,
        "vision_image_count": vision_image_count,
    }


def _empty_result():
    return {
        "filter_mode": "year", "date_range_str": "无数据", "active_days_span": 0,
        "total_calls": 0, "success_calls": 0, "failed_calls": 0, "success_rate": 100.0,
        "total_tokens": 0, "total_input": 0, "total_output": 0,
        "total_cache_read": 0, "total_cache_write": 0, "total_reasoning": 0,
        "total_cost": 0.0, "cache_rate": 0.0, "rpm": 0.0, "tpm": 0.0,
        "avg_calls": 0.0, "avg_tokens": 0.0, "avg_cost": 0.0,
        "models": {}, "days": {}, "heatmap_tokens": [], "heatmap_health": [],
        "daily_trend_tokens": [], "daily_trend_calls": [], "daily_trend_cache": [],
        "vision_calls": 0, "vision_success": 0, "vision_failures": 0,
        "vision_cache_hits": 0, "vision_avg_latency_ms": 0.0,
        "vision_image_bytes": 0, "vision_image_count": 0,
    }


def format_number_compact(num):
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f}B"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.2f}M"
    elif num >= 1_000:
        return f"{num / 1_000:.1f}K"
    else:
        return f"{num:,.0f}" if isinstance(num, (int, float)) and num == int(num) else f"{num:.2f}"
