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
import os
import time
import datetime
from pathlib import Path
from collections import defaultdict


# 默认基础费率估算（每 1M Tokens 美元）：输入 $1.50, 输出 $2.00, 缓存读 $0.30
PRICE_PER_M_INPUT = 1.50
PRICE_PER_M_OUTPUT = 2.00
PRICE_PER_M_CACHE_READ = 0.30


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

    jsonl_files = list(sessions_dir.glob("**/*.jsonl"))
    
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

    daily_map = defaultdict(lambda: {
        "calls": 0, "tokens": 0, "input": 0, "output": 0,
        "cacheRead": 0, "cacheWrite": 0, "reasoning": 0,
        "success": 0, "fail": 0
    })
    model_map = defaultdict(lambda: {
        "calls": 0, "input": 0, "output": 0,
        "cacheRead": 0, "cacheWrite": 0, "reasoning": 0,
        "total": 0, "last_used": 0
    })

    timestamps = []

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
                        
                    msg = data.get("message", {})
                    if not isinstance(msg, dict):
                        continue
                    u = msg.get("usage")
                    if not isinstance(u, dict):
                        continue

                    model = msg.get("model") or msg.get("responseModel") or data.get("model") or "unknown"
                    ts = msg.get("timestamp") or data.get("timestamp")
                    
                    epoch_s = 0.0
                    if ts:
                        if isinstance(ts, (int, float)):
                            epoch_s = ts / 1000.0 if ts > 1e11 else float(ts)
                        elif isinstance(ts, str):
                            try:
                                dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                                epoch_s = dt.timestamp()
                            except Exception:
                                pass

                    if cutoff_time > 0 and epoch_s > 0 and epoch_s < cutoff_time:
                        continue

                    if epoch_s > 0:
                        timestamps.append(epoch_s)

                    stop_reason = msg.get("stopReason", "")
                    is_fail = stop_reason in ["error", "abort"] or "error" in data
                    
                    inp = u.get("input", 0) or 0
                    out = u.get("output", 0) or 0
                    cr = u.get("cacheRead", 0) or 0
                    cw = u.get("cacheWrite", 0) or 0
                    rea = u.get("reasoning", 0) or 0
                    tot = u.get("totalTokens", inp + out) or (inp + out)

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
        except Exception:
            continue

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
            "success": 0, "fail": 0
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

    # 成本估算
    total_cost = (
        (total_input / 1_000_000.0) * PRICE_PER_M_INPUT +
        (total_output / 1_000_000.0) * PRICE_PER_M_OUTPUT +
        (total_cache_read / 1_000_000.0) * PRICE_PER_M_CACHE_READ
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
