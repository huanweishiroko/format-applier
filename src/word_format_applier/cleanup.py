"""Opt-in text cleanup: strip markdown residue, invisible characters, junk symbols.

The plugin's headline promise is "formatting only, the text is never touched".
This module is the single, explicitly declared exception. When - and only when -
a rule set enables ``cleanup`` (written as ``清理：...`` in a text preset), the
applier runs one cleanup pass *before* formatting.

Design rules that keep this safe:

* **Opt-in, never implicit.** Every category has to be named by the caller, so
  格式要求2/3 and every existing caller keep byte-identical text.
* **Contextual, not global.** A decoration character is only dropped when it is
  a whole-paragraph ornament, a run of two or more, or an edge bullet/placeholder.
  A single ``·`` between two names, or a ``※`` inside a sentence, survives.
* **Auditable.** The pass returns counts plus a few short samples, so
  ``report.json`` stays the verification channel and never carries full text.
* **Guarded downstream.** After the pass, formatting must again leave the text
  byte-identical: the original SHA-256 check is retargeted at the post-cleanup
  baseline rather than switched off.

Only the ``w:r`` runs that ``python-docx`` exposes as ``paragraph.runs`` are
rewritten; hyperlinks, drawings, fields and everything else stay untouched.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

#: every category, in report order.
CLEANUP_CATEGORIES: Tuple[str, ...] = (
    "markdown", "invisible", "punctuation", "spaces", "decorations",
    "fragments", "blank_lines", "blank_all",
)

CATEGORY_LABELS: Dict[str, str] = {
    "markdown": "markdown residue",
    "invisible": "invisible characters",
    "punctuation": "duplicated / orphan punctuation",
    "spaces": "whitespace normalisation",
    "decorations": "decorative / placeholder symbols",
    "fragments": "fragment line merging",
    "blank_lines": "redundant blank paragraphs",
    "blank_all": "every blank paragraph",
}

#: meaning-bearing marks that are never treated as decoration.
DEFAULT_KEEP_SYMBOLS = "%‰°±℃℉§¶†‡"

# --------------------------------------------------------------------------- #
# character classes
# --------------------------------------------------------------------------- #

#: zero-width, bidi-control, replacement and C0/C1 control characters.
_INVISIBLE_RE = re.compile(
    "["
    "\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f"
    "\u00ad"
    "\u200b-\u200f"
    "\u202a-\u202e"
    "\u2060-\u2064"
    "\u2066-\u2069"
    "\ufeff\ufff9-\ufffb"
    "\ufffd"
    "]"
)

#: characters that are ornaments / bullets / placeholders in practice.
_DECOR_CHARS = (
    "■□▪▫▬▲△▼▽►◄◀▶◆◇◈○●◦◯"
    "★☆✦✧✩✪✫✬✭✮✯❖❑❒"
    "•·∙⦁⦿➤➢➣➔➜※"
)

# --------------------------------------------------------------------------- #
# block level markdown
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"^\s*(?:`{3,}|~{3,})")
_ATX_RE = re.compile(r"^\s{0,3}(#{1,6})(?:\s+(?P<body>.*?))?\s*#*\s*$")
_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}(?:>\s?)+")
_SETEXT_RE = re.compile(r"^\s{0,3}(={2,}|-{2,})\s*$")
_HR_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|(?P<number>\d{1,3})[.)])\s+")
_TASK_RE = re.compile(r"^\s*\[[ xX]\]\s*")

# --------------------------------------------------------------------------- #
# inline markdown
# --------------------------------------------------------------------------- #

_CODE_SPAN_RE = re.compile(r"``([^`]+)``|`([^`]+)`")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_LINK_REF_RE = re.compile(r"\[([^\]]*)\]\[[^\]]*\]")
_AUTOLINK_RE = re.compile(r"<((?:https?://|mailto:|ftp://)[^>\s]+)>")
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_UNDERSCORE_EMPH_RE = re.compile(
    r"(?<![A-Za-z0-9_])_(?=\S)([^_]+?)(?<=\S)_(?![A-Za-z0-9_])")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _underscore_emph_sub(match: "re.Match") -> str:
    """Leave ``_mm256_`` / ``__m256`` alone; only strip real ``_emphasis_``."""
    inner = match.group(1)
    if _IDENTIFIER_RE.match(inner):
        return match.group(0)
    return inner


_EMPH_PATTERNS: Tuple[Tuple[re.Pattern, Any], ...] = (
    (re.compile(r"\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*"), r"\1"),
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"), r"\1"),
    (re.compile(r"(?<![A-Za-z0-9*])\*(?=\S)([^*]+?)(?<=\S)\*(?![A-Za-z0-9*])"), r"\1"),
    (re.compile(r"___(?=\S)(.+?)(?<=\S)___"), r"\1"),
    (re.compile(r"__(?=\S)(.+?)(?<=\S)__"), r"\1"),
    (_UNDERSCORE_EMPH_RE, _underscore_emph_sub),
)
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!~|>])")
_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>")
_ENTITY_RE = re.compile(r"&(nbsp|amp|lt|gt|quot|apos|#39);", re.I)
_ENTITY_MAP = {"nbsp": " ", "amp": "&", "lt": "<", "gt": ">",
               "quot": '"', "apos": "'", "#39": "'"}
#: leftover unmatched emphasis / rule markers, e.g. a stray ``**`` or ``___``.
#: Only *runs of the same* marker: ``_*`` in ``_mm256_*`` is code, not markdown.
#: ``__m256`` is a type name, so a leading ``__`` followed by a word survives.
_MARKER_RUN_RE = re.compile(r"\*{2,}|#{2,}|~{2,}|={3,}|_{2,}(?![A-Za-z0-9_])")

# --------------------------------------------------------------------------- #
# punctuation / whitespace / orphan markers
# --------------------------------------------------------------------------- #

#: ``……`` and ``——`` are legitimate; only genuinely duplicated marks collapse.
#: ASCII ``:`` is not in the set: ``std::chrono`` is C++, not a typo.
_PUNCT_RUN_RE = re.compile(r"([，。；：、！？,;!?])\1+")
_DOT_RUN_RE = re.compile(r"\.{4,}")
_SPACE_RUN_RE = re.compile(r"[ \t\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+")
#: dangling marks at the edges of a paragraph: separators and markdown leftovers.
#: ``：`` is deliberately *not* in the trailing set — "要求如下：" is normal prose,
#: and the heading heuristic keys off a trailing colon. ``=`` and ``\`` are
#: deliberately not in either set: "=" is an equation fragment, a trailing "\"
#: is an empty table cell, and "*" in "_mm256_*" is code, not markdown.
_LEAD_JUNK_RE = re.compile(r"^[\s，,、；;：:|/~#]+")
_TRAIL_JUNK_RE = re.compile(r"[\s，,、；;/|~#]+$")
#: only the ASCII hyphen is a markdown leftover; ``——``/``––`` are real Chinese
#: punctuation (破折号) and trailing ``2020-`` is a range, so both are spared.
_LEAD_DASH_RE = re.compile(r"^-+(?![0-9])")
_TRAIL_DASH_RE = re.compile(r"(?<![0-9])-+$")

_TRUE_WORDS = {"true", "yes", "on", "1", "是", "开", "启用"}
_FALSE_WORDS = {"false", "no", "off", "0", "否", "无", "不", "关", "关闭", "none"}


def _char_class(chars: str) -> str:
    return "".join(re.escape(ch) for ch in chars)


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


def _code_sub(match: "re.Match") -> str:
    return match.group(1) if match.group(1) is not None else (match.group(2) or "")


def _entity_sub(match: "re.Match") -> str:
    return _ENTITY_MAP.get(match.group(1).lower(), match.group(0))


def symbol_set(raw: Optional[str]) -> str:
    """Normalise a keep/remove symbol list: whitespace dropped, order preserved."""
    if not raw:
        return ""
    seen: List[str] = []
    for char in str(raw):
        if char.isspace() or char in seen:
            continue
        seen.append(char)
    return "".join(seen)


# --------------------------------------------------------------------------- #
# the cleaner
# --------------------------------------------------------------------------- #

class TextCleaner:
    """Cleans one paragraph at a time, carrying fenced-code state across calls.

    ``clean`` returns ``(new_text, info)``; ``info`` carries the signals the
    applier needs to fix up roles and blank paragraphs:

    * ``heading`` - markdown heading level detected (``#`` .. ``######``)
    * ``setext``  - this paragraph is a ``===`` / ``---`` underline
    * ``fence``   - this paragraph was a ``` / ``~~~`` fence delimiter
    * ``list``    - this paragraph carried a list marker
    * ``numbering`` - the marker was kept because 结构预处理 reads document
      numbering (only ever set when ``preserve_numbering`` is on)
    * ``marker``  - the paragraph existed only to carry markdown syntax, so the
      applier may drop it entirely instead of leaving an empty paragraph behind
    * ``blank``   - the resulting text is empty
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 *, preserve_numbering: bool = False) -> None:
        self.config = normalize_cleanup(config or {})
        self.categories = [key for key in CLEANUP_CATEGORIES if self.config.get(key)]
        self.markdown = "markdown" in self.categories
        self.invisible = "invisible" in self.categories
        self.punctuation = "punctuation" in self.categories
        self.spaces = "spaces" in self.categories
        self.decorations = "decorations" in self.categories
        self.blank_lines = "blank_lines" in self.categories
        self.blank_all = "blank_all" in self.categories
        # ``结构预处理：编号正则`` makes document numbering meaningful, so an ordered
        # list marker ("1. 平台迁移") is a heading number, not markdown residue.
        self.preserve_numbering = bool(preserve_numbering)
        self.keep_symbols = symbol_set(self.config.get("keep_symbols")) or DEFAULT_KEEP_SYMBOLS
        self.remove_symbols = symbol_set(self.config.get("remove_symbols"))
        # an explicit 删除符号： list is unconditional, so it can name characters
        # that are not in the built-in decoration set at all.
        explicit = "".join(ch for ch in self.remove_symbols if ch not in self.keep_symbols)
        self._explicit_re = (
            re.compile("[%s]+" % _char_class(explicit)) if explicit else None
        )
        decor = "".join(
            ch for ch in _DECOR_CHARS
            if ch not in self.keep_symbols and ch not in self.remove_symbols
        )
        self._decor_re = _char_class(decor) if decor else ""
        self._decor_whole_re = (
            re.compile(r"^[\s\u3000%s]+$" % self._decor_re) if self._decor_re else None
        )
        self._decor_run_re = (
            re.compile(r"([%s])\1+" % self._decor_re) if self._decor_re else None
        )
        self._decor_lead_re = (
            re.compile(r"^\s*[%s]+[\s\u3000]*" % self._decor_re) if self._decor_re else None
        )
        self._decor_trail_re = (
            re.compile(r"[\s\u3000]*[%s]+\s*$" % self._decor_re) if self._decor_re else None
        )
        self.in_fence = False

    # ------------------------------------------------------------------ #

    @property
    def enabled(self) -> bool:
        return bool(self.categories) or bool(self._explicit_re)

    def clean(self, text: str) -> Tuple[str, Dict[str, Any]]:
        original = text or ""
        info: Dict[str, Any] = {"heading": None, "setext": None, "fence": False,
                                "list": False, "marker": False, "blank": False}
        value = original

        if self.invisible:
            value = _INVISIBLE_RE.sub("", value)

        if self.markdown:
            value, info = self._clean_block(value, info)

        # a fenced code block keeps its content verbatim; only the delimiters go
        if not self.in_fence:
            if self.markdown:
                value = self._clean_inline(value)

            if self._explicit_re:
                value = self._explicit_re.sub("", value)

            if self.decorations:
                value = self._clean_decorations(value)

            if self.punctuation:
                value = _PUNCT_RUN_RE.sub(r"\1", value)
                value = _DOT_RUN_RE.sub("...", value)

            if self.markdown or self.decorations:
                value = _LEAD_JUNK_RE.sub("", value)
                value = _LEAD_DASH_RE.sub("", value)
                value = _TRAIL_JUNK_RE.sub("", value)
                value = _TRAIL_DASH_RE.sub("", value)

        if self.spaces:
            value = _SPACE_RUN_RE.sub(" ", value).strip(" ")

        if not value.strip():
            info["blank"] = True
        return value, info

    # ------------------------------------------------------------------ #

    def _clean_block(self, text: str, info: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        stripped = text.strip()

        if _FENCE_RE.match(stripped):
            self.in_fence = not self.in_fence
            info["fence"] = True
            info["marker"] = True
            info["blank"] = True
            return "", info
        if self.in_fence:
            return text, info

        # setext underline / horizontal rule: both become an empty paragraph; the
        # applier decides whether the *previous* paragraph turns into a heading.
        if _SETEXT_RE.match(stripped):
            info["setext"] = 1 if stripped.lstrip().startswith("=") else 2
            info["marker"] = True
            info["blank"] = True
            return "", info
        if _HR_RE.match(stripped):
            info["marker"] = True
            info["blank"] = True
            return "", info

        value = text

        atx = _ATX_RE.match(value)
        if atx:
            info["heading"] = len(atx.group(1))
            value = atx.group("body") or ""

        value = _BLOCKQUOTE_RE.sub("", value)

        if _TABLE_ROW_RE.match(value):
            if _TABLE_SEP_RE.match(value.strip()):
                info["marker"] = True
                info["blank"] = True
                return "", info
            cells = [cell.strip() for cell in value.strip().strip("|").split("|")]
            value = " ".join(cell for cell in cells if cell)

        marker = _LIST_RE.match(value)
        if marker:
            if marker.group("number") and self.preserve_numbering:
                # the number is document numbering, not markdown syntax: keep the
                # text byte-identical and let 结构预处理 read the level from it
                info["numbering"] = True
            else:
                value = value[marker.end():]
            info["list"] = True
        value = _TASK_RE.sub("", value)

        return value, info

    # ------------------------------------------------------------------ #

    def _clean_inline(self, text: str) -> str:
        value = _CODE_SPAN_RE.sub(_code_sub, text)
        value = _IMAGE_RE.sub(lambda match: match.group(1).strip(), value)
        value = _AUTOLINK_RE.sub(r"\1", value)
        value = _LINK_RE.sub(r"\1", value)
        value = _LINK_REF_RE.sub(r"\1", value)
        value = _STRIKE_RE.sub(r"\1", value)
        for pattern, replacement in _EMPH_PATTERNS:
            value = pattern.sub(replacement, value)
        value = _ESCAPE_RE.sub(r"\1", value)
        value = _TAG_RE.sub("", value)
        value = _ENTITY_RE.sub(_entity_sub, value)
        value = _MARKER_RUN_RE.sub("", value)
        return value

    def _clean_decorations(self, text: str) -> str:
        if not self._decor_re:
            return text
        value = text
        if self._decor_whole_re and self._decor_whole_re.match(value):
            return ""
        if self._decor_run_re:
            value = self._decor_run_re.sub("", value)
        if self._decor_lead_re:
            value = self._decor_lead_re.sub("", value)
        if self._decor_trail_re:
            value = self._decor_trail_re.sub("", value)
        return value

    # ------------------------------------------------------------------ #

    def describe(self) -> Dict[str, Any]:
        return {
            "categories": list(self.categories),
            "category_labels": [CATEGORY_LABELS.get(key, key) for key in self.categories],
            "keep_symbols": self.keep_symbols,
            "remove_symbols": self.remove_symbols,
            "preserve_numbering": self.preserve_numbering,
        }


# --------------------------------------------------------------------------- #
# config normalisation
# --------------------------------------------------------------------------- #

def normalize_cleanup(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Coerce a raw cleanup block into the canonical JSON form.

    There are no implicit category defaults: a category is on only when it was
    named. That is what keeps every existing preset byte-for-byte unaffected.
    """
    if not config:
        return {}
    raw = dict(config)
    out: Dict[str, Any] = {}
    for key in CLEANUP_CATEGORIES:
        if key in raw:
            value = _to_bool(raw.get(key))
            if value is not None:
                out[key] = bool(value)
    keep = symbol_set(raw.get("keep_symbols"))
    remove = symbol_set(raw.get("remove_symbols"))
    if keep:
        out["keep_symbols"] = keep
    if remove:
        out["remove_symbols"] = remove
    has_categories = any(out.get(key) for key in CLEANUP_CATEGORIES)
    # an explicit removal list is a cleanup request on its own; a keep list is not
    enabled = _to_bool(raw.get("enabled"))
    if enabled is None:
        enabled = has_categories or bool(remove)
    out["enabled"] = bool(enabled) and (has_categories or bool(remove))
    if not out["enabled"]:
        out.pop("keep_symbols", None)
        out.pop("remove_symbols", None)
    return out
