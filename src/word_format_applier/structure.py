"""Structural preprocessing: heading levels from whole-paragraph bold + numbering.

Word documents that were written by hand (or pasted out of a chat window) usually
carry no heading styles at all: the visual hierarchy lives in the text itself, as
whole-paragraph bold and/or Chinese document numbering (``一、`` ``（一）`` ``1.``
``1.1`` ...). Role binding can only guess *one* level from such a document - the
old heuristic called every bold short line ``heading1``.

This module runs **before** role binding (and after the optional text cleanup) and
turns those two signals into real Word heading styles:

* **整段加粗** (``bold``) - every non-empty run of the paragraph is bold.
* **编号正则** (``numbering``) - the paragraph starts with a recognised numbering
  token; the token decides the level.

Both signals are opt-in: a rule set gets a ``structure`` block only when its
requirement text declares ``结构预处理：...``, so 格式要求2/3 and every other caller
stay untouched. The pass never writes text - it only sets ``paragraph.style``, so
the "text is never touched" guarantee (SHA-256 checked downstream) still holds.

Level ladders (auto-detected from the document, or forced by the requirement):

===============  ==================  ==============
token            official (公文)      decimal
===============  ==================  ==============
第一章 / 第一部分   1                   1
一、              1                   1
（一）            2                   2
1.1.1            5                   3
1.1              4                   2
1. / 1、          3                   1
（1）             4                   4
①                5                   5
===============  ==================  ==============

A document that uses ``1.1``-style numbering anywhere is read as *decimal*
(``1.`` = level 1); otherwise the 公文 ladder applies (``一、`` = level 1,
``1.`` = level 3). ``ladder`` can be pinned in the requirement text
(``小数编号`` / ``公文编号``).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from . import docxio

#: every signal, in report order.
STRUCTURE_CATEGORIES: Tuple[str, ...] = ("bold", "numbering", "lead_title", "centered")

CATEGORY_LABELS: Dict[str, str] = {
    "bold": "whole-paragraph bold",
    "numbering": "numbered heading regex",
    "lead_title": "first-paragraph title",
    "centered": "centred front-matter line",
}

#: the Word built-in style a detected document title gets; the preset's 标题 role
#: (黑体 三号 居中 加粗 in 格式要求1) is applied by the ordinary role binding.
TITLE_STYLE = "Title"
#: how far into the document the centred-line fallback looks for a title
CENTERED_WINDOW = 5

#: level ladders; ``auto`` picks one from the document itself.
LADDERS: Tuple[str, ...] = ("auto", "official", "decimal")

#: Word ships Heading 1..9; the plugin never styles deeper than the outline allows.
MAX_LEVEL = 6
#: a bold paragraph without any numbering is a top level heading
DEFAULT_BOLD_LEVEL = 1
#: long paragraphs are prose, never headings
MAX_HEADING_CHARS = 60
#: a document whose body is *globally* bold would otherwise turn into headings only
GLOBAL_BOLD_SHARE = 0.6
GLOBAL_BOLD_MIN_PARAGRAPHS = 4

#: pattern labels that carry a decimal depth ("1.1", "1.1.1"). Prose such as
#: "3.5 万元的预算已经批复" matches those, so they only count as an outline when
#: the same depth appears more than once (or the paragraph is whole bold).
DECIMAL_LABELS: Tuple[str, ...] = ("1.1", "1.1.1")
DECIMAL_MIN_OCCURRENCES = 2

_TRUE_WORDS = {"true", "yes", "on", "1", "是", "开", "启用"}
_FALSE_WORDS = {"false", "no", "off", "0", "否", "无", "不", "关", "关闭", "none"}

#: a heading never ends like a sentence ("要求如下：" is a label, so ``：`` is allowed)
_SENTENCE_TAIL = ("。", "！", "？", "；", "，", "、", ".", "!", "?", ";", ",")

#: ``(kind, pattern, official_level, decimal_level)``; first match wins.
#:
#: The dotted patterns demand whitespace before the text so that prose such as
#: "1.5倍行距说明" is not mistaken for a "1.5" heading; a *whole bold* paragraph may
#: drop the space (see :data:`_COMPACT_PATTERNS`).
_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]", int, int], ...] = (
    ("第X章", re.compile(r"^第\s*[一二三四五六七八九十百千零〇0-9]{1,4}\s*[章篇部]"), 1, 1),
    ("一、", re.compile(r"^[一二三四五六七八九十]{1,3}\s*[、.．]"), 1, 1),
    ("（一）", re.compile(r"^[（(][一二三四五六七八九十]{1,3}[）)]"), 2, 2),
    ("1.1.1", re.compile(r"^\d{1,2}(?:[.．]\d{1,2}){2}[ \t\u3000]+(?=\S)"), 5, 3),
    ("1.1", re.compile(r"^\d{1,2}[.．]\d{1,2}[ \t\u3000]+(?=\S)"), 4, 2),
    ("1.", re.compile(r"^\d{1,2}\s*[、.．]\s*(?=[^\d\s])"), 3, 1),
    ("（1）", re.compile(r"^[（(]\d{1,2}[）)]"), 4, 4),
    ("①", re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]"), 5, 5),
)

#: the same dotted patterns, but tolerant of a missing space: only ever consulted
#: for a paragraph that is entirely bold.
_COMPACT_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]", int, int], ...] = (
    ("1.1.1", re.compile(r"^\d{1,2}(?:[.．]\d{1,2}){2}(?=\S)"), 5, 3),
    ("1.1", re.compile(r"^\d{1,2}[.．]\d{1,2}(?=\S)"), 4, 2),
)

#: style names that already carry a heading level: never re-level those.
_HEADING_STYLE_RE = re.compile(r"^(?:heading\s*[1-9]|标题\s*[1-9一二三四五六]|h[1-6])$", re.I)
#: styles that own a paragraph outright (title / caption / TOC / table text).
_RESERVED_STYLE_RE = re.compile(r"^(?:title|标题|toc\s*[1-9]|目录\s*[1-9]|caption|题注)$", re.I)
#: the document already has a title-styled paragraph: never add a second one.
_TITLE_STYLE_RE = re.compile(r"^(?:title|标题|主标题|文档标题)$", re.I)

#: ``H1``-style markers Word itself puts in front of a numbered heading are not text
#: this module rewrites; the numbering regex reads the visible text only.


def _to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


def normalize_structure(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Coerce a raw ``structure`` block into the canonical JSON form.

    Like the cleanup block there are no implicit defaults: a signal is on only
    when the requirement named it, and an empty result means "pass disabled".
    """
    if not config:
        return {}
    raw = dict(config)
    out: Dict[str, Any] = {}
    for key in STRUCTURE_CATEGORIES:
        if key in raw:
            value = _to_bool(raw.get(key))
            if value is not None:
                out[key] = bool(value)
    ladder = str(raw.get("ladder") or "").strip().lower()
    if ladder in LADDERS:
        out["ladder"] = ladder
    has_signal = any(out.get(key) for key in STRUCTURE_CATEGORIES)
    enabled = _to_bool(raw.get("enabled"))
    if enabled is None:
        enabled = has_signal
    if not (bool(enabled) and has_signal):
        return {}
    out["enabled"] = True
    out.setdefault("ladder", "auto")
    return out


def structure_categories(rules_or_block: Optional[Dict[str, Any]]) -> List[str]:
    """Enabled signals, in canonical order (empty when the pass is off)."""
    block = rules_or_block or {}
    if not block.get("enabled"):
        return []
    return [key for key in STRUCTURE_CATEGORIES if block.get(key)]


# --------------------------------------------------------------------------- #
# signals
# --------------------------------------------------------------------------- #

def _style_name(paragraph) -> str:
    try:
        return str(paragraph.style.name or "")
    except Exception:  # pragma: no cover - defensive
        return ""


def is_heading_style(style_name: str) -> bool:
    return bool(_HEADING_STYLE_RE.match((style_name or "").strip()))


def is_reserved_style(style_name: str) -> bool:
    return bool(_RESERVED_STYLE_RE.match((style_name or "").strip()))


def is_title_style(style_name: str) -> bool:
    return bool(_TITLE_STYLE_RE.match((style_name or "").strip()))


def whole_paragraph_bold(paragraph) -> bool:
    """True when every non-empty run is bold (direct formatting or style)."""
    runs = [run for run in paragraph.runs if (run.text or "").strip()]
    if not runs:
        return False
    paragraph_bold: Optional[bool] = None
    try:
        paragraph_bold = paragraph.style.font.bold
    except Exception:  # pragma: no cover - defensive
        paragraph_bold = None
    for run in runs:
        bold = run.font.bold
        if bold is None:
            try:
                bold = run.style.font.bold
            except Exception:  # pragma: no cover - defensive
                bold = None
        if bold is None:
            bold = paragraph_bold
        if not bold:
            return False
    return True


def numbering_match(text: str, *, compact: bool = False) -> Optional[Tuple[int, int, str]]:
    """``(level_official, level_decimal, token_label)`` for a numbered line."""
    value = (text or "").lstrip()
    if not value:
        return None
    patterns = _PATTERNS + _COMPACT_PATTERNS if compact else _PATTERNS
    for label, pattern, official, decimal in patterns:
        if pattern.match(value):
            return official, decimal, label
    return None


def _text_looks_like_heading(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or len(stripped) > MAX_HEADING_CHARS:
        return False
    return not stripped.endswith(_SENTENCE_TAIL)


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #

def detect_levels(paragraphs: List[Any],
                  config: Optional[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Plan the Word style for every paragraph in ``paragraphs``.

    Returns ``(assignments, meta)``. An assignment is
    ``{"paragraph": ..., "style": "Heading 2" | "Title", "level": 2 | None,
    "reason": "structure:..."}``; ``level`` is ``None`` for the document title.
    Nothing is written here, so the caller owns style lookup and reporting.
    """
    block = normalize_structure(config)
    meta: Dict[str, Any] = {
        "scanned": len(paragraphs or []),
        "bold_paragraphs": 0,
        "bold_signal": bool(block.get("bold")),
        "ladder": block.get("ladder") or "auto",
        "ladder_source": "requirement" if (block.get("ladder") or "auto") != "auto" else "document",
        "skipped_table": 0,
        "skipped_styled": 0,
        "skipped_text": 0,
        "decimal_rejected": 0,
        "existing_title": False,
        "title_signal": [key for key in ("lead_title", "centered") if block.get(key)],
        "title_assigned": None,
        "candidates": 0,
    }
    if not block.get("enabled"):
        return [], meta

    use_numbering = bool(block.get("numbering"))
    use_bold = bool(block.get("bold"))

    scanned: List[Dict[str, Any]] = []
    for paragraph in paragraphs or []:
        text = docxio.paragraph_text(paragraph).strip()
        if not text:
            continue
        style_name = _style_name(paragraph)
        if is_heading_style(style_name) or is_reserved_style(style_name):
            meta["skipped_styled"] += 1
            if is_title_style(style_name):
                meta["existing_title"] = True
            continue
        if _in_table(paragraph):
            meta["skipped_table"] += 1
            continue
        bold = whole_paragraph_bold(paragraph) if use_bold else False
        if bold:
            meta["bold_paragraphs"] += 1
        match = numbering_match(text, compact=bold) if use_numbering else None
        scanned.append({"paragraph": paragraph, "text": text, "bold": bold, "numbering": match})

    # ---- ladder: a document using 1.1-style numbering is decimal, not 公文 ----
    if use_numbering:
        # "1.1" only reads as an outline depth when the document really uses one:
        # a single "3.5 万元的预算" is prose, not a heading (bold still wins).
        counts: Dict[str, int] = {}
        for item in scanned:
            match = item["numbering"]
            if match and match[2] in DECIMAL_LABELS:
                counts[match[2]] = counts.get(match[2], 0) + 1
        rejected = 0
        for item in scanned:
            match = item["numbering"]
            if not match or match[2] not in DECIMAL_LABELS:
                continue
            if counts.get(match[2], 0) < DECIMAL_MIN_OCCURRENCES and not item["bold"]:
                item["numbering"] = None
                rejected += 1
        meta["decimal_rejected"] = rejected

    if use_numbering and meta["ladder"] == "auto":
        decimal_used = any(
            item["numbering"] and item["numbering"][2] in DECIMAL_LABELS
            for item in scanned)
        meta["ladder"] = "decimal" if decimal_used else "official"
    if meta["ladder"] == "auto":
        meta["ladder"] = "official"

    # ---- a globally bold body carries no signal at all ----
    if use_bold and len(scanned) >= GLOBAL_BOLD_MIN_PARAGRAPHS:
        share = meta["bold_paragraphs"] / float(len(scanned))
        if share >= GLOBAL_BOLD_SHARE:
            use_bold = False
            meta["bold_signal"] = False
            meta["bold_disabled"] = "%.0f%% of paragraphs are entirely bold" % (share * 100)

    ladder_official = meta["ladder"] == "official"
    assignments: List[Dict[str, Any]] = []
    heading_positions = set()
    for position, item in enumerate(scanned):
        numbering = item["numbering"]
        if not _text_looks_like_heading(item["text"]):
            meta["skipped_text"] += 1
            continue
        if numbering:
            level = numbering[0] if ladder_official else numbering[1]
            label = numbering[2]
            reason = "structure:numbering:%s" % label
            if item["bold"] and use_bold:
                reason = "structure:bold+numbering:%s" % label
        elif item["bold"] and use_bold:
            level, reason = DEFAULT_BOLD_LEVEL, "structure:bold"
        else:
            continue
        level = max(1, min(MAX_LEVEL, int(level)))
        heading_positions.add(position)
        assignments.append({"paragraph": item["paragraph"], "style": "Heading %d" % level,
                            "level": level, "reason": reason, "text_head": item["text"][:20]})

    # ---- 文档标题：首段标题 / 居中短行 ------------------------------------- #
    # A document title carries neither numbering nor (usually) real bold: the
    # source only ever used markdown "**...**". At most ONE title is assigned,
    # and it goes to Word's built-in "Title" style, which the preset's 标题 role
    # then formats (黑体 三号 居中 加粗 in 格式要求1).
    if not meta["existing_title"]:
        title_item = None
        if block.get("lead_title") and scanned:
            first = scanned[0]
            # a numbered first line is a section heading, not the document title;
            # a bold one still counts as the title once 首段标题 was asked for
            if first["numbering"] is None and _text_looks_like_heading(first["text"]):
                title_item = (first, "structure:lead_title")
        if title_item is None and block.get("centered"):
            window = CENTERED_WINDOW
            if heading_positions:
                window = min(window, min(heading_positions))
            for position, item in enumerate(scanned[:window]):
                if item["numbering"] is not None:
                    continue
                if not _text_looks_like_heading(item["text"]):
                    continue
                if not docxio.paragraph_is_centered(item["paragraph"]):
                    continue
                title_item = (item, "structure:centered_title")
                break
        if title_item is not None:
            item, reason = title_item
            # the title wins over the heading level that same paragraph may have
            # been given by the bold signal
            assignments = [entry for entry in assignments
                           if entry["paragraph"] is not item["paragraph"]]
            assignments.insert(0, {"paragraph": item["paragraph"], "style": TITLE_STYLE,
                                   "level": None, "reason": reason,
                                   "text_head": item["text"][:20]})
            meta["title_assigned"] = reason

    meta["candidates"] = len(assignments)
    return assignments, meta


def _in_table(paragraph) -> bool:
    node = getattr(paragraph, "_p", None)
    while node is not None:
        tag = getattr(node, "tag", "")
        if tag.endswith("}tbl"):
            return True
        node = node.getparent()
    return False


def describe(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    block = normalize_structure(config)
    return {
        "categories": structure_categories(block),
        "category_labels": [CATEGORY_LABELS[key] for key in structure_categories(block)],
        "ladder": block.get("ladder"),
    }
