"""report.json / report.md writers.

The report is the *only* verification channel: the agent reads the short JSON
summary, never the document XML.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from . import schema as ruleschema

REPORT_VERSION = 1


def default_report_path(output_docx: str) -> str:
    """默认报告落点：系统临时目录下的 ``taofu-reports/``。

    绝不写进 exe 同级目录（Program Files 下会被拒绝，且为了写报告去要管理员
    权限会破坏 Windows 拖拽）。GUI 处理成功后会再把报告移到输出文件旁边。
    """
    folder = os.path.join(tempfile.gettempdir(), "taofu-reports")
    stem = os.path.splitext(os.path.basename(output_docx))[0] or "report"
    name = "%s-%d-%s.report.json" % (stem, os.getpid(),
                                     time.strftime("%Y%m%d-%H%M%S"))
    return os.path.join(folder, name)


def build_report(*, ok: bool,
                 target_docx: str,
                 output_docx: Optional[str],
                 report_json: str,
                 dry_run: bool,
                 source_info: Dict[str, Any],
                 rules: Dict[str, Any],
                 stats: Dict[str, Any],
                 text_before: Dict[str, Any],
                 text_after: Optional[Dict[str, Any]],
                 text_baseline: Optional[Dict[str, Any]] = None,
                 cleanup: Optional[Dict[str, Any]] = None,
                 structure: Optional[Dict[str, Any]] = None,
                 warnings: Optional[List[str]] = None,
                 errors: Optional[List[str]] = None,
                 llm: Optional[Dict[str, Any]] = None,
                 timings: Optional[Dict[str, Any]] = None,
                 partial: bool = False) -> Dict[str, Any]:
    # ``baseline`` is the text the formatting pass received: identical to the
    # original document unless an opt-in cleanup pass rewrote something.
    baseline = text_baseline or text_before
    cleanup_block = dict(cleanup or {})
    structure_block = dict(structure or {})
    report: Dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "plugin": "word-format-applier",
        "ok": bool(ok),
        "partial": bool(partial),
        "dry_run": bool(dry_run),
        "target_docx": target_docx,
        "output_docx": output_docx,
        "report_json": report_json,
        "source": {
            "kind": source_info.get("kind"),
            "resolved_path": source_info.get("resolved_path"),
            "used_preset": source_info.get("used_preset"),
            "preset_file": source_info.get("preset_file"),
            "preset_sha256": source_info.get("preset_sha256"),
            "sha256": source_info.get("sha256"),
            "cache_hit": bool(source_info.get("cache_hit")),
            "rule_cache_hit": bool(source_info.get("cache_hit")),
            "parsed_by": source_info.get("parsed_by"),
            "rule_count": ruleschema.ruleset_rule_count(rules),
        },
        "rules": {
            "version": rules.get("version", ruleschema.RULESET_VERSION),
            "page": rules.get("page") or {},
            "default_font": rules.get("default_font") or {},
            "roles": sorted((rules.get("styles") or {}).keys()),
            "role_attributes": {
                role: ruleschema.spec_keys(spec)
                for role, spec in sorted((rules.get("styles") or {}).items())
            },
            "cleanup_categories": ruleschema.cleanup_categories(rules),
            "structure_signals": ruleschema.structure_categories(rules),
        },
        "validation": {
            "text_unchanged": bool(text_after is None or baseline["sha256"] == text_after["sha256"]),
            "text_sha256_before": text_before["sha256"],
            "text_sha256_baseline": baseline["sha256"],
            "text_sha256_after": (text_after or baseline)["sha256"],
            "chars_before": text_before["chars"],
            "chars_baseline": baseline["chars"],
            "chars_after": (text_after or baseline)["chars"],
            "chars_removed_by_cleanup": (text_before["chars"] - baseline["chars"]),
            "paragraphs_before": text_before["paragraphs"],
            "paragraphs_baseline": baseline["paragraphs"],
            "paragraphs_after": (text_after or baseline)["paragraphs"],
        },
        "cleanup": cleanup_block,
        "structure": structure_block,
        "stats": stats,
        "applied_rules": stats.get("applied_rules", []),
        "skipped_rules": stats.get("skipped_rules", []),
        "conflicts": stats.get("conflicts", []),
        "unresolved": stats.get("unresolved", []),
        "llm": llm or {"calls": 0, "used": False, "reason": None},
        "warnings": list(warnings or []),
        "errors": list(errors or []),
        "timings_ms": timings or {},
    }
    return report


def short_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    """The compact JSON the agent is allowed to see (never the cleanup samples)."""
    stats = report.get("stats") or {}
    validation = report.get("validation") or {}
    cleanup = report.get("cleanup") or {}
    structure = report.get("structure") or {}
    return {
        "ok": bool(report.get("ok")),
        "output_docx": report.get("output_docx"),
        "report_json": report.get("report_json"),
        "used_preset": (report.get("source") or {}).get("used_preset"),
        "applied": stats.get("paragraphs_changed", 0),
        "skipped": stats.get("paragraphs_skipped", 0),
        "llm_calls": (report.get("llm") or {}).get("calls", 0),
        "text_unchanged": validation.get("text_unchanged", False),
        "text_cleaned": bool(cleanup.get("applied")),
        "cleanup": ({
            "categories": cleanup.get("categories") or [],
            "paragraphs_changed": cleanup.get("paragraphs_changed", 0),
            "paragraphs_removed": cleanup.get("paragraphs_removed", 0),
            "chars_removed": validation.get("chars_removed_by_cleanup", 0),
        } if cleanup.get("enabled") else None),
        "structure": ({
            "signals": structure.get("categories") or [],
            "headings_mapped": structure.get("headings_mapped", 0),
            "title_mapped": structure.get("title_mapped", 0),
            "by_level": structure.get("by_level") or {},
            "ladder": structure.get("ladder"),
        } if structure.get("enabled") else None),
        "warnings": list(report.get("warnings") or []),
        # 失败时必须把根因带给界面：以前这里只给 ok=false，Applier 把异常收进
        # report["errors"] 却没人读，界面只能显示「处理失败（退出码 1）」。
        "errors": list(report.get("errors") or []),
        "error": (list(report.get("errors") or [None]) or [None])[0],
        "report_error": report.get("report_error") or "",
        "partial": bool(report.get("partial")),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    source = report.get("source") or {}
    stats = report.get("stats") or {}
    validation = report.get("validation") or {}
    lines = [
        "# word-format-applier report",
        "",
        "- ok: `%s`%s" % (report.get("ok"), " (partial)" if report.get("partial") else ""),
        "- target: `%s`" % report.get("target_docx"),
        "- output: `%s`%s" % (report.get("output_docx"), " (dry-run, not written)" if report.get("dry_run") else ""),
        "- format source: `%s` (%s)" % (source.get("resolved_path"), source.get("kind")),
        "- used preset: `%s`" % (source.get("used_preset") or "-"),
        "- preset sha256: `%s`" % (source.get("preset_sha256") or "-"),
        "- rule count: %s" % source.get("rule_count"),
        "- parsed by: %s%s" % (source.get("parsed_by"), " (cache hit)" if source.get("cache_hit") else ""),
        "- llm calls: %s" % (report.get("llm") or {}).get("calls", 0),
        "",
    ]
    cleanup = report.get("cleanup") or {}
    if cleanup.get("enabled"):
        lines.extend([
            "## text cleanup",
            "",
            "- categories: %s" % ", ".join(cleanup.get("categories") or []),
            "- applied: %s" % cleanup.get("applied"),
            "- paragraphs rewritten: %s" % cleanup.get("paragraphs_changed", 0),
            "- paragraphs removed: %s" % cleanup.get("paragraphs_removed", 0),
            "- characters removed: %s" % validation.get("chars_removed_by_cleanup", 0),
            "- heading hints: %s" % cleanup.get("heading_hints", 0),
        ])
        if cleanup.get("keep_symbols"):
            lines.append("- kept symbols: `%s`" % cleanup["keep_symbols"])
        if cleanup.get("remove_symbols"):
            lines.append("- extra removed symbols: `%s`" % cleanup["remove_symbols"])
        lines.append("")
        for sample in (cleanup.get("samples") or [])[:20]:
            lines.append("- p%s: `%s` -> `%s`" % (sample.get("paragraph"),
                                                  sample.get("before"), sample.get("after")))
        lines.append("")

    structure = report.get("structure") or {}
    if structure.get("enabled"):
        lines.extend([
            "## structural preprocessing",
            "",
            "- signals: %s" % ", ".join(structure.get("categories") or []),
            "- numbering ladder: %s" % (structure.get("ladder") or "-"),
            "- applied: %s" % structure.get("applied"),
            "- paragraphs mapped to Word heading styles: %s" % structure.get("headings_mapped", 0),
            "- document title mapped to the Word Title style: %s (%s)"
            % (structure.get("title_mapped", 0), structure.get("title_assigned") or "-"),
            "- by level: %s" % (structure.get("by_level") or {}),
        ])
        if structure.get("bold_disabled"):
            lines.append("- 整段加粗 ignored: %s" % structure["bold_disabled"])
        lines.append("")
        for sample in (structure.get("samples") or [])[:20]:
            lines.append("- p%s: %s (%s) `%s`" % (sample.get("paragraph"),
                                                  sample.get("style") or ("Heading %s" % sample.get("level")),
                                                  sample.get("reason"),
                                                  sample.get("text_head")))
        lines.append("")

    lines.extend([
        "## applied",
        "",
        "- paragraphs changed: %s" % stats.get("paragraphs_changed", 0),
        "- paragraphs skipped: %s" % stats.get("paragraphs_skipped", 0),
        "- runs changed: %s" % stats.get("runs_changed", 0),
        "- properties applied: %s" % stats.get("properties_applied", 0),
        "- sections updated: %s" % stats.get("sections_updated", 0),
        "- text unchanged: %s" % validation.get("text_unchanged"),
        "",
    ])
    for title, key in (("applied rules", "applied_rules"),
                       ("skipped rules", "skipped_rules"),
                       ("conflicts", "conflicts"),
                       ("unresolved", "unresolved")):
        items = stats.get(key) or []
        if not items:
            continue
        lines.append("### %s" % title)
        lines.append("")
        for item in items[:40]:
            lines.append("- %s" % (json.dumps(item, ensure_ascii=False) if not isinstance(item, str) else item))
        if len(items) > 40:
            lines.append("- ... (%d more)" % (len(items) - 40))
        lines.append("")
    warnings = report.get("warnings") or []
    errors = report.get("errors") or []
    if warnings or errors:
        lines.append("## diagnostics")
        lines.append("")
        for item in errors:
            lines.append("- ERROR %s" % item)
        for item in warnings:
            lines.append("- WARN %s" % item)
        lines.append("")

    lines.append("## rule detail")
    lines.append("")
    lines.append("```")
    detail: List[str] = []
    for role in sorted((report.get("rules") or {}).get("role_attributes") or {}):
        attrs = report["rules"]["role_attributes"][role]
        detail.append("%s: %s" % (role, ", ".join(attrs)))
    lines.extend(detail[:60])
    if len(detail) > 60:
        lines.append("... (%d more roles)" % (len(detail) - 60))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def write_reports(report: Dict[str, Any], report_json: str,
                  markdown_path: Optional[str] = None) -> List[str]:
    written: List[str] = []
    folder = os.path.dirname(os.path.abspath(report_json))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    with open(report_json, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    written.append(report_json)
    if markdown_path:
        with open(markdown_path, "w", encoding="utf-8") as handle:
            handle.write(render_markdown(report))
        written.append(markdown_path)
    return written
