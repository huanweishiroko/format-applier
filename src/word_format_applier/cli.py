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
    ap.add_argument("--report", help="report.json path (default: <output>.report.json)")
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

    if not args.target:
        ap.error("--target is required (or use --list-presets / --print-rules)")
    if not format_source and inline_text is None:
        ap.error("one of --format/--preset is required")

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

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2 if args.pretty else None))
    else:
        print("ok=%s applied=%s skipped=%s llm_calls=%s text_unchanged=%s"
              % (summary["ok"], summary["applied"], summary["skipped"],
                 summary["llm_calls"], summary["text_unchanged"]))
        print("output: %s" % summary["output_docx"])
        print("report: %s" % summary["report_json"])
    return 0 if summary["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
