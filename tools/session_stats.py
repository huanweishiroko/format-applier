#!/usr/bin/env python3
"""DSH session JSONL 统计器。

用法:
    python session_stats.py <session.jsonl> [--top-reads 20] [--timeline] [--json]

逐行流式读取，不把整个文件载入内存。只提取对比所需的聚合量。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict


_READ_SHOWING_RE = re.compile(r"\(Showing lines (\d+)-(\d+) of (\d+)")
_GREP_FOUND_RE = re.compile(r"Found (\d+) matches?")
_GREP_NONE_RE = re.compile(r"No matches found")


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def analyze(path, top_reads=20, timeline=False):
    event_counts = Counter()
    usage_sum = defaultdict(int)
    llm_calls = 0
    usage_series = []          # (step_no, input_tokens, cache_read, output_tokens, total)
    tool_calls = Counter()
    read_records = []          # dict(path, offset, limit, shown_lines, total_lines)
    grep_records = []          # dict(pattern, matches)
    call_meta = {}             # callId -> (name, arguments_dict)
    read_count_by_path = Counter()
    read_without_bounds = 0
    grep_over_20 = 0
    step_no = 0
    turn_no = 0
    first_time = None
    last_time = None
    compaction_events = 0

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                event_counts["<invalid-json>"] += 1
                continue

            etype = obj.get("type", "<none>")
            event_counts[etype] += 1
            data = obj.get("data") or {}
            t = obj.get("time")
            if isinstance(t, int):
                first_time = t if first_time is None else min(first_time, t)
                last_time = t if last_time is None else max(last_time, t)

            if etype == "turn/start":
                turn_no += 1
            elif etype == "step/start":
                step_no += 1

            elif etype == "assistant/message":
                usage = data.get("usage") or {}
                if usage:
                    llm_calls += 1
                    inp = _as_int(usage.get("inputTokens")) or 0
                    out = _as_int(usage.get("outputTokens")) or 0
                    cache_r = _as_int(usage.get("cacheReadTokens")) or 0
                    cache_w = _as_int(usage.get("cacheWriteTokens")) or 0
                    total = _as_int(usage.get("totalTokens")) or (inp + out + cache_r)
                    usage_sum["inputTokens"] += inp
                    usage_sum["outputTokens"] += out
                    usage_sum["cacheReadTokens"] += cache_r
                    usage_sum["cacheWriteTokens"] += cache_w
                    usage_sum["totalTokens"] += total
                    usage_series.append((step_no, inp, cache_r, out, total))
                # 压缩迹象：事件文本里出现 compaction
                blob = json.dumps(data, ensure_ascii=False)
                if "compaction" in blob.lower():
                    compaction_events += 1

            elif etype == "tool/call":
                name = data.get("name", "<unknown>")
                tool_calls[name] += 1
                args_raw = data.get("arguments") or "{}"
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                call_id = data.get("callId")
                if call_id:
                    call_meta[call_id] = (name, args)
                if name == "read":
                    fp = args.get("file_path") or "<no-file_path>"
                    offset = _as_int(args.get("offset"))
                    limit = _as_int(args.get("limit"))
                    read_count_by_path[fp] += 1
                    if offset is None and limit is None:
                        read_without_bounds += 1
                    read_records.append({"path": fp, "offset": offset, "limit": limit,
                                         "shown_lines": None, "total_lines": None})
                elif name == "grep":
                    pattern = args.get("pattern", "")
                    grep_records.append({"pattern": pattern, "matches": None})

            elif etype == "tool/result":
                call_id = data.get("callId")
                meta = call_meta.pop(call_id, (None, {})) if call_id else (None, {})
                name, _args = meta
                content = data.get("message", {}).get("content") or []
                text = ""
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text += block.get("text") or ""
                if name == "read" and read_records:
                    m = _READ_SHOWING_RE.search(text)
                    if m:
                        read_records[-1]["shown_lines"] = int(m.group(2)) - int(m.group(1)) + 1
                        read_records[-1]["total_lines"] = int(m.group(3))
                elif name == "grep" and grep_records:
                    m = _GREP_FOUND_RE.search(text)
                    if m:
                        n = int(m.group(1))
                        grep_records[-1]["matches"] = n
                        if n > 20:
                            grep_over_20 += 1
                    elif _GREP_NONE_RE.search(text):
                        grep_records[-1]["matches"] = 0

    total_input_side = usage_sum["inputTokens"] + usage_sum["cacheReadTokens"]
    cache_pct = (usage_sum["cacheReadTokens"] / total_input_side * 100.0) if total_input_side else 0.0
    duration_ms = (last_time - first_time) if (first_time and last_time) else 0

    # 上下文峰值 / 序列
    peak = max(usage_series, key=lambda r: r[1] + r[2], default=None)
    dips = []
    prev = None
    for row in usage_series:
        cur = row[1] + row[2]
        if prev is not None and prev > 10000 and cur < prev * 0.5:
            dips.append((row[0], prev, cur))
        prev = cur

    top_read_list = read_count_by_path.most_common(top_reads)

    return {
        "path": path,
        "event_counts": event_counts,
        "turns": turn_no,
        "steps": step_no,
        "llm_calls": llm_calls,
        "usage_sum": dict(usage_sum),
        "cache_read_pct_of_input": round(cache_pct, 2),
        "duration_ms": duration_ms,
        "tool_calls": tool_calls,
        "read_total": tool_calls.get("read", 0),
        "read_without_bounds": read_without_bounds,
        "read_unique_files": len(read_count_by_path),
        "read_top": top_read_list,
        "grep_total": tool_calls.get("grep", 0),
        "grep_over_20": grep_over_20,
        "grep_records": grep_records,
        "read_records": read_records,
        "peak_input_side": (peak[0], peak[1] + peak[2]) if peak else None,
        "input_dips": dips,
        "compaction_events": compaction_events,
        "usage_series": usage_series,
    }


def render(result, timeline=False):
    out = []
    out.append("=== 文件 ===")
    out.append("路径: %s" % result["path"])
    out.append("总事件数: %d" % sum(result["event_counts"].values()))
    out.append("")
    out.append("=== 事件类型 ===")
    for name, n in result["event_counts"].most_common():
        out.append("  %-32s %d" % (name, n))
    out.append("")
    out.append("=== 轮次与时长 ===")
    out.append("turn 数: %d   step 数: %d   LLM 调用: %d" % (
        result["turns"], result["steps"], result["llm_calls"]))
    out.append("总时长: %.1f 秒" % (result["duration_ms"] / 1000.0))
    out.append("")
    out.append("=== Token 汇总 ===")
    us = result["usage_sum"]
    out.append("inputTokens       : %d" % us.get("inputTokens", 0))
    out.append("outputTokens      : %d" % us.get("outputTokens", 0))
    out.append("cacheReadTokens   : %d" % us.get("cacheReadTokens", 0))
    out.append("cacheWriteTokens  : %d" % us.get("cacheWriteTokens", 0))
    out.append("totalTokens       : %d" % us.get("totalTokens", 0))
    out.append("cacheRead 占输入侧: %.2f%%" % result["cache_read_pct_of_input"])
    if result["peak_input_side"]:
        s, v = result["peak_input_side"]
        out.append("输入侧峰值       : %d (step %d)" % (v, s))
    if result["input_dips"]:
        out.append("疑似压缩/重灌     : %d 次" % len(result["input_dips"]))
        for s, a, b in result["input_dips"][:5]:
            out.append("    step %d: %d -> %d" % (s, a, b))
    if result["compaction_events"]:
        out.append("日志内 compaction 字样: %d 次" % result["compaction_events"])
    out.append("")
    out.append("=== 工具调用 ===")
    for name, n in result["tool_calls"].most_common():
        out.append("  %-20s %d" % (name, n))
    out.append("")
    out.append("=== read 行为 ===")
    out.append("read 总次数        : %d" % result["read_total"])
    out.append("read 不同文件数    : %d" % result["read_unique_files"])
    out.append("read 未带 offset/limit: %d" % result["read_without_bounds"])
    out.append("read 次数 top:")
    for fp, n in result["read_top"]:
        out.append("  %3d  %s" % (n, fp))
    out.append("")
    out.append("=== grep 行为 ===")
    out.append("grep 总次数        : %d" % result["grep_total"])
    out.append("匹配数 > 20 的次数 : %d" % result["grep_over_20"])
    for rec in result["grep_records"]:
        m = rec["matches"]
        out.append("  %-6s  %s" % ("?" if m is None else m, (rec["pattern"] or "")[:80]))
    if timeline:
        out.append("")
        out.append("=== 输入侧时间线（step, input, cacheRead, output）===")
        for s, inp, cr, outp, _t in result["usage_series"]:
            out.append("  step %-4d  in=%-8d cache=%-8d out=%-6d" % (s, inp, cr, outp))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="DSH session JSONL 统计器")
    ap.add_argument("session", help="session JSONL 文件路径")
    ap.add_argument("--top-reads", type=int, default=20, help="重复 read 榜单长度")
    ap.add_argument("--timeline", action="store_true", help="打印每次 LLM 调用的 token 时间线")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而不是文本报告")
    args = ap.parse_args()

    try:
        result = analyze(args.session, top_reads=args.top_reads, timeline=args.timeline)
    except OSError as exc:
        print("无法读取文件: %s" % exc, file=sys.stderr)
        return 1

    if args.json:
        payload = dict(result)
        payload["event_counts"] = dict(payload["event_counts"])
        payload["tool_calls"] = dict(payload["tool_calls"])
        payload["usage_series"] = [
            {"step": s, "input": i, "cache_read": c, "output": o, "total": t}
            for s, i, c, o, t in payload["usage_series"]
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(result, timeline=args.timeline))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())