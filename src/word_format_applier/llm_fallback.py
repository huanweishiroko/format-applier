"""Optional LLM fallback - OFF by default, hard capped.

Policy enforced here (the only place in the package that can reach the network):

* only invoked when the deterministic text parser fails its coverage gate;
* at most :data:`DEFAULT_MAX_CALLS` (2) calls per process;
* ``max_tokens`` :data:`DEFAULT_MAX_TOKENS` (2000) per call;
* the payload is the *format requirement text* plus small summaries - never the
  target document body, never XML, never a diff;
* answers are cached by spec hash, so a repeated spec costs zero calls;
* a soft token budget (:data:`DEFAULT_SOFT_TOKEN_BUDGET`) stops the fallback to
  keep the local pipeline running instead of burning tokens.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import schema as ruleschema

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_MAX_CALLS = 2
DEFAULT_MAX_TOKENS = 2000
DEFAULT_SOFT_TOKEN_BUDGET = 30000
DEFAULT_TIMEOUT = 45

PROMPT_VERSION = "wfa-rules-v1"

SYSTEM_PROMPT = (
    "You convert a Word formatting requirement into JSON. "
    "Reply with JSON only, no prose, no markdown fence. "
    "Schema: {\"styles\": {<role>: {<attr>: <value>}}, \"page\": {<attr>: <value>}, "
    "\"default_font\": {<attr>: <value>}, \"unresolved\": [\"...\"]}. "
    "Allowed roles: normal, title, heading1..heading6, quote, caption, table_text, list, toc1..toc6. "
    "Allowed attrs: font_ascii, font_eastasia, font_hansi, size_pt (points, number), "
    "bold, italic, underline, strike (bool), color (RRGGBB hex), align "
    "(left|center|right|justify|distribute), line_spacing (number) with line_spacing_rule "
    "(multiple|exactly), space_before_pt, space_after_pt, first_line_indent_chars, "
    "left_indent_chars, right_indent_pt, outline_level (0-5), margin_top_cm, margin_bottom_cm, "
    "margin_left_cm, margin_right_cm, orientation (portrait|landscape). "
    "Map Chinese size names using: 初号42 小初36 一号26 小一24 二号22 小二18 三号16 小三15 "
    "四号14 小四12 五号10.5 小五9. Omit attributes the requirement does not mention."
)


class LLMBudget:
    """Process-local counter shared by all fallback calls."""

    def __init__(self, max_calls: int = DEFAULT_MAX_CALLS,
                 soft_token_budget: int = DEFAULT_SOFT_TOKEN_BUDGET) -> None:
        self.max_calls = max_calls
        self.soft_token_budget = soft_token_budget
        self.calls = 0
        self.estimated_tokens = 0
        self.exhausted_reason: Optional[str] = None

    def can_call(self, estimated: int) -> Tuple[bool, Optional[str]]:
        if self.calls >= self.max_calls:
            return False, "max_calls_reached"
        if self.estimated_tokens + estimated > self.soft_token_budget:
            return False, "soft_token_budget_reached"
        return True, None

    def charge(self, tokens: int) -> None:
        self.calls += 1
        self.estimated_tokens += max(0, tokens)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "calls": self.calls,
            "max_calls": self.max_calls,
            "estimated_tokens": self.estimated_tokens,
            "soft_token_budget": self.soft_token_budget,
            "exhausted_reason": self.exhausted_reason,
        }


def estimate_tokens(text: str) -> int:
    """Cheap, dependency-free estimate (CJK ~1 token/char, latin ~1/4 char)."""
    if not text:
        return 0
    cjk = len(re.findall(r"[\u3000-\u9fff\uff00-\uffef]", text))
    other = max(0, len(text) - cjk)
    return int(cjk + other / 4) + 1


def default_model_config() -> Dict[str, Any]:
    return {
        "base_url": os.environ.get("WORD_FORMAT_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "model": os.environ.get("WORD_FORMAT_LLM_MODEL", DEFAULT_MODEL),
        "api_key": (os.environ.get("WORD_FORMAT_LLM_API_KEY")
                    or os.environ.get("DEEPSEEK_API_KEY") or ""),
        "timeout": int(os.environ.get("WORD_FORMAT_LLM_TIMEOUT", DEFAULT_TIMEOUT)),
    }


def parse_llm_rules(text: str, *, source: Optional[Dict[str, Any]] = None,
                    budget: Optional[LLMBudget] = None,
                    context: Optional[Dict[str, Any]] = None,
                    cache_read=None, cache_write=None,
                    model_config: Optional[Dict[str, Any]] = None,
                    enabled: bool = False) -> Dict[str, Any]:
    """Attempt one LLM-assisted parse. Returns ``{used, rules, calls, reason}``.

    ``enabled=False`` (the default everywhere) makes this a no-op returning
    ``used=False`` so callers stay at **zero** LLM calls.
    """
    budget = budget or LLMBudget()
    result: Dict[str, Any] = {"used": False, "rules": None, "reason": "disabled",
                              "calls": 0, "cache_hit": False}
    if not enabled:
        return result

    config = dict(default_model_config())
    config.update({k: v for k, v in (model_config or {}).items() if v})
    if not config.get("api_key"):
        result["reason"] = "no_api_key"
        return result

    spec_text = (text or "").strip()
    if not spec_text:
        result["reason"] = "empty_spec"
        return result

    cache_key = None
    if cache_read is not None:
        cache_key = _cache_key_for(spec_text)
        cached = cache_read("llm", cache_key)
        if cached and isinstance(cached.get("rules"), dict):
            result.update({"used": True, "rules": cached["rules"], "reason": "cache_hit",
                           "calls": 0, "cache_hit": True})
            return result

    cache_key = _cache_key_for(spec_text)

    payload = {
        "spec_text": spec_text[:8000],
        "prompt_version": PROMPT_VERSION,
    }
    if context:
        # only small, pre-aggregated metadata ever travels (style counts, role names)
        payload["target_style_stats"] = context.get("target_style_stats")
        payload["paragraph_metadata_sample"] = (context.get("paragraph_metadata_sample") or [])[:40]
        payload["unresolved_roles"] = context.get("unresolved_roles")
        payload = {key: value for key, value in payload.items() if value}

    body_text = json.dumps(payload, ensure_ascii=False)
    estimated = estimate_tokens(SYSTEM_PROMPT) + estimate_tokens(body_text) + DEFAULT_MAX_TOKENS
    allowed, reason = budget.can_call(estimated)
    if not allowed:
        budget.exhausted_reason = reason
        result["reason"] = reason
        return result

    request_body = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": body_text},
        ],
        "max_tokens": DEFAULT_MAX_TOKENS,
        "temperature": 0,
        "stream": False,
    }
    request = urllib.request.Request(
        "%s/chat/completions" % config["base_url"],
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % config["api_key"],
        },
        method="POST",
    )
    budget.charge(estimated)
    result["calls"] = 1
    try:
        with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result["reason"] = "request_failed: %s" % exc
        return result
    except Exception as exc:  # pragma: no cover - defensive
        result["reason"] = "request_failed: %s" % exc
        return result

    try:
        decoded = json.loads(raw)
        content = decoded["choices"][0]["message"]["content"]
    except Exception as exc:
        result["reason"] = "bad_response: %s" % exc
        return result

    parsed = _extract_json(content)
    if not isinstance(parsed, dict):
        result["reason"] = "unparseable_json"
        return result

    rules = {
        "version": ruleschema.RULESET_VERSION,
        "source": dict(source or {}),
        "page": parsed.get("page") or {},
        "styles": parsed.get("styles") or {},
        "default_font": parsed.get("default_font") or {},
        "extras": {"parse": {"mode": "llm_fallback",
                             "unresolved": parsed.get("unresolved") or [],
                             "prompt_version": PROMPT_VERSION}},
    }
    rules = ruleschema.normalize_ruleset(rules)
    if cache_write is not None and rules.get("styles"):
        cache_write("llm", cache_key, {"rules": rules})
    result.update({"used": True, "rules": rules, "reason": "ok", "cache_hit": False})
    return result


def _cache_key_for(spec_text: str) -> str:
    return hashlib.sha256(("%s|%s" % (PROMPT_VERSION, spec_text)).encode("utf-8")).hexdigest()[:32]


def _extract_json(content: str) -> Optional[Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


def needs_fallback(rules: Dict[str, Any], *, threshold: float = 0.25) -> Tuple[bool, str]:
    """Coverage gate: only weak parses are allowed to reach the LLM."""
    from . import textparse

    styles = (rules or {}).get("styles") or {}
    if not styles:
        return True, "no_rules_parsed"
    if not any(role in styles for role in ("normal", "heading1", "title")):
        return True, "no_core_role"
    coverage = (rules.get("extras") or {}).get("parse", {}).get("coverage")
    if coverage is None:
        coverage = textparse.coverage_score(rules)
    if coverage < threshold:
        return True, "low_coverage:%.3f" % coverage
    return False, "coverage_ok:%.3f" % coverage


def paragraph_metadata_sample(document, *, limit: int = 20) -> List[Dict[str, Any]]:
    """Small paragraph metadata sample (index/style/first 20 chars/bold)."""
    from . import docxio

    sample: List[Dict[str, Any]] = []
    for index, paragraph in enumerate(docxio.iter_all_paragraphs(document)):
        if len(sample) >= limit:
            break
        text = docxio.paragraph_text(paragraph).strip()
        if not text:
            continue
        bold = None
        for run in paragraph.runs:
            if (run.text or "").strip():
                bold = bool(run.font.bold) if run.font.bold is not None else None
                break
        try:
            style_name = paragraph.style.name if paragraph.style is not None else None
        except Exception:
            style_name = None
        sample.append({
            "i": index,
            "style": style_name,
            "head": text[:20],
            "bold": bold,
        })
    return sample


def style_stats(document) -> Dict[str, int]:
    from . import docxio

    stats: Dict[str, int] = {}
    for paragraph in docxio.iter_all_paragraphs(document):
        try:
            name = paragraph.style.name if paragraph.style is not None else "(none)"
        except Exception:
            name = "(none)"
        stats[name] = stats.get(name, 0) + 1
    return dict(sorted(stats.items(), key=lambda item: -item[1])[:25])
