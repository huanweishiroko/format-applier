"""Command line interface - the zero-token path.

::

    python -m word_format_applier --list-presets
    python -m word_format_applier --target 目标.docx --preset 格式要求1 --output 输出.docx
    python -m word_format_applier --target 目标.docx --format ./samples/我的格式.docx --json
    python -m word_format_applier --print-rules --preset 格式要求1

Exit codes: 0 ok, 1 failure (report path is still printed), 2 bad arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from . import __version__, applier, docxio, llm_fallback, parser, presets as presets_mod
from . import schema as ruleschema


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="word_format_applier",
        description="Apply Word formatting requirements to a .docx. Text is preserved "
                    "unless the requirement declares a 清理: (cleanup) pass; a "
                    "结构预处理: (structure) pass only assigns Word heading styles.",
    )
    ap.add_argument("--target", help="target .docx to reformat (never modified in place)")
    ap.add_argument("--format", "--format-source", dest="format_source",
                    help="format requirement: path (.docx/.txt/.md), preset name, 'preset:NAME', or inline text")
    ap.add_argument("--preset", help="preset name from presets/ (equivalent to --format preset:NAME)")
    ap.add_argument("--output", help="output .docx path (default: <target>_formatted.docx)")
    ap.add_argument("--report", help="report.json path (default: %%TEMP%%\\taofu-reports\\<output>.report.json)")
    ap.add_argument("--markdown-report", help="also write a human readable .md report")
    ap.add_argument("--dry-run", action="store_true", help="only produce the report, write no document")
    ap.add_argument("--list-presets", action="store_true", help="list discovered preset names and exit")
    ap.add_argument("--list-presets-json", action="store_true", help="list presets as JSON and exit")
    ap.add_argument("--print-rules", action="store_true", help="parse the format source and print the rule summary")
    ap.add_argument("--presets-dir", help="override the presets directory")
    ap.add_argument("--no-cache", action="store_true", help="ignore and do not update the parse cache")
    ap.add_argument("--llm-fallback", action="store_true",
                    help="allow up to 2 LLM calls when the local text parser cannot cover the requirement")
    ap.add_argument("--llm-model", help="override the fallback model name")
    ap.add_argument("--no-page-setup", action="store_true", help="skip page setup rules")
    ap.add_argument("--no-heading-heuristic", action="store_true", help="disable heuristic heading detection")
    ap.add_argument("--json", action="store_true", help="print the short JSON summary")
    ap.add_argument("--pretty", action="store_true", help="pretty print JSON output")
    ap.add_argument("--probe-write", metavar="DIR",
                    help="只做最小写探测：往 DIR（或该文件所在目录）落一个临时文件再删掉，"
                         "打印 JSON 后退出；用来确认输出目录到底能不能写")
    ap.add_argument("--no-write-probe", action="store_true",
                    help="跳过处理前对输出目录的自动写探测")
    ap.add_argument("--version", action="version", version="word-format-applier %s" % __version__)
    return ap


def _print_presets(as_json: bool, presets_dir: Optional[str]) -> int:
    entries = presets_mod.list_preset_entries(presets_dir)
    table = presets_mod.preset_table(presets_dir)
    if as_json:
        print(json.dumps({
            "presets_dir": presets_mod.presets_dir(presets_dir),
            "count": len(table),
            "presets": [
                {"name": name, "file": entry["filename"], "ext": entry["ext"], "size": entry["size"]}
                for name, entry in table.items()
            ],
            "shadowed": [
                {"name": entry["name"], "file": entry["filename"]}
                for entry in entries if table.get(entry["name"], {}).get("path") != entry["path"]
            ],
        }, ensure_ascii=False, indent=2))
        return 0
    names = list(table.keys())
    print("presets dir: %s" % presets_mod.presets_dir(presets_dir))
    if not names:
        print("(no presets found - drop .docx/.txt/.md files into that folder)")
        return 0
    for name in names:
        entry = table[name]
        print("%-24s %s" % (name, entry["filename"]))
    return 0


def _print_rules(format_source: str, presets_dir: Optional[str], inline_text: Optional[str],
                 no_cache: bool, llm_enabled: bool) -> int:
    parsed = parser.parse_format_source(
        format_source or "", presets_dir=presets_dir, use_cache=not no_cache,
        llm_enabled=llm_enabled, llm_budget=llm_fallback.LLMBudget(), raw_text=inline_text)
    rules = parsed["rules"]
    print(json.dumps({
        "source": {
            "kind": parsed["source"].get("kind"),
            "used_preset": parsed["source"].get("used_preset"),
            "path": parsed["source"].get("resolved_path"),
            "cache_hit": parsed.get("cache_hit"),
            "parsed_by": parsed["source"].get("parsed_by"),
        },
        "rule_count": ruleschema.ruleset_rule_count(rules),
        "pages": sorted((rules.get("page") or {}).keys()),
        "default_font": rules.get("default_font") or {},
        "cleanup": ruleschema.cleanup_categories(rules),
        "structure": ruleschema.structure_categories(rules),
        "roles": {role: sorted(spec.keys()) for role, spec in sorted((rules.get("styles") or {}).items())},
        "llm": parsed["llm"],
    }, ensure_ascii=False, indent=2))
    return 0


def probe_output_dir(path: str) -> Dict[str, Any]:
    """最小写探测：在目标目录里真的落一个临时文件再删掉。

    ``E:\\桃符测试`` 这类“看起来完全可写”的目录仍可能报 PermissionError
    (WinError 5)：进程被降权（低完整性级别 / 沙箱）、杀软拦截、或目标文件被
    Word 占用。只有真的写一次才能区分“目录权限”与“进程被限制”。
    """
    folder = os.path.abspath(path or os.getcwd())
    if not os.path.isdir(folder):
        parent = os.path.dirname(folder)
        if os.path.basename(folder).lower().endswith(".docx") or not os.path.isdir(parent):
            folder = parent or os.getcwd()
    probe = os.path.join(folder, ".wfa-write-probe-%d.tmp" % os.getpid())
    result: Dict[str, Any] = {"ok": False, "dir": folder, "probe": probe,
                              "error": "", "winerror": None, "writable": False}
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        with open(probe, "wb") as handle:
            handle.write(b"word-format-applier write probe\n")
        os.remove(probe)
        result.update(ok=True, writable=True)
    except OSError as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        result["winerror"] = getattr(exc, "winerror", None)
        result["writable"] = os.access(folder, os.W_OK)
        try:
            os.remove(probe)  # 半截文件也不留
        except OSError:
            pass
    return result


def unwritable_message(probe: Dict[str, Any]) -> str:
    message = "输出目录不可写：%s（%s）" % (probe["dir"], probe["error"] or "未知原因")
    if probe.get("writable"):
        message += ("。目录权限本身是允许写入的，说明是当前进程被限制："
                    "低完整性级别/沙箱、杀毒软件拦截，或目标文件正被 Word 占用。")
    return message


def _report_failure(summary: Dict[str, Any]) -> int:
    """把 summary 里的根因同时写到 stderr（GUI 只解析 stderr 也有东西可看）。"""
    reasons = [str(item) for item in (summary.get("errors") or []) if str(item).strip()]
    if summary.get("error"):
        reasons.insert(0, str(summary["error"]))
    if not reasons:
        reasons.append("处理失败，但插件没有返回任何错误信息")
    first = reasons[0]
    if not first.startswith("error:"):
        print("error: %s" % first, file=sys.stderr)
    for item in reasons[1:4]:
        print("[wfa] ERROR %s" % item, file=sys.stderr)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    if args.list_presets or args.list_presets_json:
        return _print_presets(args.list_presets_json, args.presets_dir)

    format_source = args.format_source
    inline_text = None
    if args.preset:
        format_source = presets_mod.PRESET_PREFIX + args.preset
    elif format_source and not os.path.isfile(format_source) \
            and not format_source.lower().startswith(presets_mod.PRESET_PREFIX) \
            and not presets_mod._looks_like_path(format_source):
        # a bare string that is neither a path nor a known preset name is inline text
        try:
            presets_mod.resolve_preset(format_source, args.presets_dir)
        except presets_mod.PresetError:
            inline_text = format_source
            format_source = None

    if args.print_rules:
        if not format_source and inline_text is None:
            ap.error("--print-rules needs --format/--preset")
        try:
            return _print_rules(format_source or "", args.presets_dir, inline_text,
                                args.no_cache, args.llm_fallback)
        except (presets_mod.PresetError, parser.FormatError, docxio.DocxError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1

    # 最小写探测：不处理文档，只回答“这个目录到底能不能写”。放在 --target
    # 校验之前，方便用户单独验证输出目录。
    if args.probe_write:
        probe = probe_output_dir(args.probe_write)
        probe["message"] = "" if probe["ok"] else unwritable_message(probe)
        print(json.dumps(probe, ensure_ascii=False))
        if not probe["ok"]:
            print("error: %s" % probe["message"], file=sys.stderr)
            return 1
        return 0

    if not args.target:
        ap.error("--target is required (or use --list-presets / --print-rules)")
    if not format_source and inline_text is None:
        ap.error("one of --format/--preset is required")

    # 处理前先做一次最小写探测：目录/permission 问题要在几十毫秒内暴露成一条
    # 可读的错误，而不是跑了整轮排版后只回一个 ok=false。
    output_path = presets_mod.default_output_path(args.target, args.output)
    if not args.dry_run and not args.no_write_probe:
        probe = probe_output_dir(output_path)
        if not probe["ok"]:
            message = unwritable_message(probe)
            print(json.dumps({"ok": False, "error": message, "probe": probe},
                             ensure_ascii=False))
            print("error: %s" % message, file=sys.stderr)
            return 1

    budget = llm_fallback.LLMBudget()
    llm_config = {}
    if args.llm_model:
        llm_config["model"] = args.llm_model

    try:
        summary = applier.apply_format(
            args.target,
            format_source or "",
            args.output,
            dry_run=args.dry_run,
            report_path=args.report,
            markdown_report_path=args.markdown_report,
            presets_dir=args.presets_dir,
            cwd=os.getcwd(),
            use_cache=not args.no_cache,
            llm_fallback_enabled=bool(args.llm_fallback),
            llm_budget=budget,
            llm_config=llm_config or None,
            inline_text=inline_text,
            apply_page=not args.no_page_setup,
            heading_heuristic=not args.no_heading_heuristic,
            logger=(None if args.json else (lambda message: print("[wfa] %s" % message, file=sys.stderr))),
        )
    except PermissionError as exc:
        # 输出目录没有写权限（只读 / 文件被占用 / 杀软拦截）：给界面一条能行动的
        # 标准 JSON，而不是让 traceback 直接崩到 stderr、让 GUI 只看到“没有输出”。
        raw = "%s: %s" % (type(exc).__name__, exc)
        print(json.dumps({
            "ok": False,
            "error": "目标目录没有写入权限，请更换输出目录或关闭被占用的文件（%s）" % raw,
        }, ensure_ascii=False))
        print("error: %s" % raw, file=sys.stderr)
        return 1
    except (presets_mod.PresetError, parser.FormatError, applier.FormatError, docxio.DocxError) as exc:
        payload = {"ok": False, "error": str(exc), "partial": True,
                   "report_json": os.path.abspath(args.report) if args.report else None}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print("error: %s" % exc, file=sys.stderr)
            if isinstance(exc, presets_mod.PresetError):
                print("available presets: %s" % ", ".join(presets_mod.list_presets(args.presets_dir)),
                      file=sys.stderr)
        return 1

    if summary.get("report_error"):
        # 报告只是附属产物：docx 已经保存成功时，报告写/移失败只算 WARN，
        # 不能把整次处理拖成退出码 1。
        print("[WARN] 报告文件移动失败，已跳过", file=sys.stderr)
        print("[wfa] WARN %s" % summary["report_error"], file=sys.stderr)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2 if args.pretty else None))
    else:
        print("ok=%s applied=%s skipped=%s llm_calls=%s text_unchanged=%s"
              % (summary["ok"], summary["applied"], summary["skipped"],
                 summary["llm_calls"], summary["text_unchanged"]))
        print("output: %s" % summary["output_docx"])
        print("report: %s" % summary["report_json"])
    if not summary.get("ok"):
        return _report_failure(summary)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
