"""Format-requirement parsing front door.

``parse_format_source`` turns any accepted ``format_source`` (path, preset name,
inline text) into one normalized rule set, using the on-disk cache and - only
when the deterministic parse fails its coverage gate and the caller opted in -
the LLM fallback.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

from . import docxio, llm_fallback, presets as presets_mod, schema as ruleschema, textparse


class FormatError(RuntimeError):
    pass


def parse_docx_template(path: str) -> Dict[str, Any]:
    rules = textparse.extract_rules_from_docx(path)
    if not (rules.get("styles") or rules.get("page")):
        raise FormatError("no usable formatting rules found in template: %s" % path)
    return rules


def parse_text_requirement(text: str, *, source: Optional[Dict[str, Any]] = None,
                           strict: bool = True) -> Dict[str, Any]:
    """Parse requirement text; ``strict=False`` returns an empty ruleset instead of raising."""
    try:
        rules = textparse.parse_text_rules(text, source=source)
    except Exception as exc:  # pragma: no cover - defensive
        if strict:
            raise FormatError("failed to parse the requirement text: %s" % exc) from exc
        rules = ruleschema.normalize_ruleset({"source": source or {}})
    if not (rules.get("styles") or rules.get("page") or rules.get("default_font")):
        if strict:
            raise FormatError(
                "could not parse any formatting rule from the requirement text "
                "(no font/size/spacing/alignment keywords were recognised)")
        rules.setdefault("extras", {}).setdefault("parse", {})["empty"] = True
    return rules


def parse_format_source(format_source: str,
                        *,
                        cwd: Optional[str] = None,
                        use_cache: bool = True,
                        presets_dir: Optional[str] = None,
                        llm_enabled: bool = False,
                        llm_budget: Optional[llm_fallback.LLMBudget] = None,
                        llm_context: Optional[Dict[str, Any]] = None,
                        llm_config: Optional[Dict[str, Any]] = None,
                        inline_text: Optional[str] = None,
                        raw_text: Optional[str] = None,
                        source_kind_hint: Optional[str] = None,
                        strict: bool = True,
                        logger: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Returns ``{"rules": ..., "source": {...}, "llm": {...}}``."""
    log = logger or (lambda message: None)
    llm_state: Dict[str, Any] = {"calls": 0, "used": False, "reason": "not_needed",
                                 "cache_hit": False}

    if raw_text is not None:
        info: Dict[str, Any] = {"kind": "text", "path": None, "used_preset": None,
                                "resolved_by": "inline_text"}
        text = raw_text
    else:
        info = presets_mod.resolve_format_source(format_source, cwd=cwd, presets_dir_arg=presets_dir)
        text = ""

    source_meta: Dict[str, Any] = {
        "kind": info["kind"],
        "resolved_path": info.get("path"),
        "used_preset": info.get("used_preset"),
        "preset_file": info.get("preset_file"),
        "resolved_by": info.get("resolved_by"),
        "parsed_by": None,
        "sha256": None,
        "preset_sha256": None,
    }
    # `cache_hit` deliberately lives *outside* the ruleset so that identical
    # inputs always produce an identical rule set (cache hit or not).
    cache_hit = False

    rules: Optional[Dict[str, Any]] = None
    cache_key = None
    if info.get("path"):
        file_path = info["path"]
        if not os.path.isfile(file_path):
            raise FormatError("format source file not found: %s" % file_path)
        info_hash = docxio.file_sha256(file_path)
        source_meta["sha256"] = info_hash
        if info["kind"].startswith("preset"):
            source_meta["preset_sha256"] = info_hash
        if use_cache:
            cache_key = presets_mod.parse_cache_key(file_path)
            cached = presets_mod.cache_read("rules", cache_key, presets_dir)
            if cached and isinstance(cached.get("rules"), dict):
                # always re-attach this run's source metadata: identical inputs
                # therefore always yield an identical ruleset
                rules = _strip_source(cached["rules"])
                cache_hit = True
                source_meta["parsed_by"] = cached.get("parsed_by") or "cache"
                log("rule cache hit for %s" % os.path.basename(file_path))
        if rules is None:
            if info["kind"] == "docx" or info["kind"] == "preset_docx":
                rules = parse_docx_template(file_path)
                source_meta["parsed_by"] = "docx_template"
            else:
                text = docxio.read_text_file(file_path)
                rules = parse_text_requirement(text, source={"kind": info["kind"]}, strict=strict)
                source_meta["parsed_by"] = "text_rules"
            if use_cache and cache_key:
                # the cache stores the rules only: `source` is per-run metadata
                # (cache_hit, resolved path) and must not be frozen into it.
                presets_mod.cache_write("rules", cache_key,
                                        {"rules": _strip_source(rules),
                                         "parsed_by": source_meta["parsed_by"]}, presets_dir)
    else:
        rules = parse_text_requirement(text, source={"kind": "text"}, strict=strict)
        source_meta["parsed_by"] = "text_rules"

    # ---- optional LLM fallback (default off, <=2 calls, 2000 max_tokens) ----
    if llm_enabled and info["kind"] in ("text", "preset_text"):
        want, reason = llm_fallback.needs_fallback(rules)
        if want:
            outcome = llm_fallback.parse_llm_rules(
                text, source=source_meta, budget=llm_budget, context=llm_context,
                cache_read=(lambda ns, key: presets_mod.cache_read(ns, key, presets_dir)),
                cache_write=(lambda ns, key, payload: presets_mod.cache_write(ns, key, payload, presets_dir)),
                model_config=llm_config, enabled=True)
            llm_state = {
                "calls": outcome.get("calls", 0),
                "used": bool(outcome.get("used")),
                "reason": outcome.get("reason"),
                "cache_hit": bool(outcome.get("cache_hit")),
                "gate": reason,
            }
            if outcome.get("used") and isinstance(outcome.get("rules"), dict):
                rules = _merge_rules(rules, outcome["rules"])
                source_meta["parsed_by"] = "llm_fallback"
                log("llm fallback merged (%s)" % outcome.get("reason"))
        else:
            llm_state["reason"] = "not_needed:%s" % reason
    elif llm_enabled:
        llm_state["reason"] = "not_applicable:%s" % info["kind"]
    else:
        llm_state["reason"] = "disabled"

    # the ruleset itself must stay byte-identical for identical inputs, so the
    # volatile `cache_hit` flag is attached only *after* normalization
    rules_source = dict(source_meta)
    rules["source"] = rules_source
    rules = ruleschema.normalize_ruleset(rules)
    source_meta["cache_hit"] = cache_hit
    return {"rules": rules, "source": source_meta, "llm": llm_state, "cache_hit": cache_hit}


def _strip_source(rules: Dict[str, Any]) -> Dict[str, Any]:
    """Cached ruleset copy without the per-run ``source`` metadata."""
    clean = dict(rules or {})
    clean.pop("source", None)
    return clean


def _merge_rules(local: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    """Local deterministic rules win; the LLM only fills gaps."""
    merged = dict(local)
    styles = dict(local.get("styles") or {})
    for role, spec in (fallback.get("styles") or {}).items():
        bucket = dict(styles.get(role) or {})
        for key, value in (spec or {}).items():
            bucket.setdefault(key, value)
        styles[role] = bucket
    merged["styles"] = styles
    page = dict(local.get("page") or {})
    for key, value in (fallback.get("page") or {}).items():
        page.setdefault(key, value)
    merged["page"] = page
    default_font = dict(local.get("default_font") or {})
    for key, value in (fallback.get("default_font") or {}).items():
        default_font.setdefault(key, value)
    if default_font:
        merged["default_font"] = default_font
    extras = dict(local.get("extras") or {})
    parse = dict(extras.get("parse") or {})
    parse["llm_unresolved"] = (fallback.get("extras") or {}).get("parse", {}).get("unresolved") or []
    extras["parse"] = parse
    merged["extras"] = extras
    return merged
