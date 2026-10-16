"""Rule schema for word_format_applier.

Everything is plain JSON-serializable data (dict/list/str/num/bool/None) on
purpose: the rules travel between the parser, the on-disk cache, the applier
and the report without any extra (de)serialization layer, and pydantic is not
required at runtime.

Terminology
-----------
*role*  a semantic slot of a document: ``normal``, ``heading1`` ... ``heading6``,
        ``title``, ``quote``, ``caption``, ``table_text``, ``list``, ``toc1`` ...
        ``default_font`` is not a paragraph role, it is the document default font.
*spec*  a flat dict of formatting attributes (font, size, alignment, ...).
*rule set*  ``{"version": 1, "source": {...}, "page": {...},
        "styles": {role: spec}, "cleanup": {...}, "structure": {...},
        "extras": {...}}``

``cleanup`` is absent unless the requirement explicitly asked for a text cleanup
pass (see :mod:`word_format_applier.cleanup`); an absent block means the text is
guaranteed to survive byte-identical, which is the historical behaviour.

``structure`` is absent unless the requirement asked for the structural
preprocessing pass (see :mod:`word_format_applier.structure`); an absent block
means role binding reads the document exactly as it always did.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .cleanup import CLEANUP_CATEGORIES, normalize_cleanup
from .structure import STRUCTURE_CATEGORIES, normalize_structure

RULESET_VERSION = 3

# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #

ROLES: Tuple[str, ...] = (
    "normal",
    "title",
    "heading1",
    "heading2",
    "heading3",
    "heading4",
    "heading5",
    "heading6",
    "quote",
    "caption",
    "table_text",
    "list",
    "toc1",
    "toc2",
    "toc3",
    "toc4",
    "toc5",
    "toc6",
)

#: English / Chinese style-name aliases -> role. Lower-cased, spaces stripped.
ROLE_ALIASES: Dict[str, str] = {
    # normal
    "normal": "normal",
    "bodytext": "normal",
    "body": "normal",
    "default": "normal",
    "正文": "normal",
    "普通": "normal",
    "基本正文": "normal",
    # title
    "title": "title",
    "documenttitle": "title",
    "标题": "title",
    "题目": "title",
    "文章标题": "title",
    # heading1-6 (en + zh)
    "heading1": "heading1", "heading 1": "heading1", "h1": "heading1",
    "标题1": "heading1", "标题一": "heading1", "一级标题": "heading1",
    "heading2": "heading2", "heading 2": "heading2", "h2": "heading2",
    "标题2": "heading2", "标题二": "heading2", "二级标题": "heading2",
    "heading3": "heading3", "heading 3": "heading3", "h3": "heading3",
    "标题3": "heading3", "标题三": "heading3", "三级标题": "heading3",
    "heading4": "heading4", "heading 4": "heading4", "h4": "heading4",
    "标题4": "heading4", "标题四": "heading4", "四级标题": "heading4",
    "heading5": "heading5", "heading 5": "heading5", "h5": "heading5",
    "标题5": "heading5", "标题五": "heading5", "五级标题": "heading5",
    "heading6": "heading6", "heading 6": "heading6", "h6": "heading6",
    "标题6": "heading6", "标题六": "heading6", "六级标题": "heading6",
    # quote
    "quote": "quote",
    "intensequote": "quote",
    "blockquote": "quote",
    "引用": "quote",
    "引文": "quote",
    "名言": "quote",
    # caption
    "caption": "caption",
    "figurecaption": "caption",
    "题注": "caption",
    "图注": "caption",
    "表注": "caption",
    # table text
    "tabletext": "table_text",
    "table": "table_text",
    "表格文字": "table_text",
    "表格文本": "table_text",
    "表内文字": "table_text",
    # list
    "list": "list",
    "listparagraph": "list",
    "listbullet": "list",
    "listnumber": "list",
    "列表": "list",
    "列表文字": "list",
    "项目符号": "list",
    "编号": "list",
}

_TOC_RE = re.compile(r"^(?:toc|目录)\s*([1-9])$")
_HEADING_RE = re.compile(
    r"^(?:heading|标题|h)\s*([1-6])$"
)

# --------------------------------------------------------------------------- #
# Attributes
# --------------------------------------------------------------------------- #

FONT_ATTRS = ("font_ascii", "font_eastasia", "font_hansi", "font_cs")

TEXT_ATTRS = (
    "font_ascii",
    "font_eastasia",
    "font_hansi",
    "font_cs",
    "size_pt",
    "bold",
    "italic",
    "underline",
    "strike",
    "all_caps",
    "color",
    "highlight",
    "character_spacing_pt",
    "vertical_align",
)

PARA_ATTRS = (
    "align",
    "line_spacing",
    "line_spacing_rule",
    "space_before_pt",
    "space_after_pt",
    "first_line_indent_chars",
    "first_line_indent_pt",
    "left_indent_chars",
    "left_indent_pt",
    "right_indent_pt",
    "keep_with_next",
    "page_break_before",
    "widow_control",
    "snap_to_grid",
    "outline_level",
)

PAGE_ATTRS = (
    "margin_top_cm",
    "margin_bottom_cm",
    "margin_left_cm",
    "margin_right_cm",
    "page_width_cm",
    "page_height_cm",
    "orientation",
)

ALL_SPEC_ATTRS = TEXT_ATTRS + PARA_ATTRS

ALIGN_VALUES = ("left", "center", "right", "justify", "distribute", "both")

#: char -> point factor used by Word for "首行缩进 N 字符".
CHARS_TO_PT = 12.0
PT_TO_TWIPS = 20.0

# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

_TRUE_WORDS = {"true", "yes", "on", "1", "是", "加粗", "斜体", "bold", "italic"}
_FALSE_WORDS = {"false", "no", "off", "0", "否", "无", "不", "none"}

_ALIGN_MAP = {
    "left": "left", "左": "left", "左对齐": "left", "居左": "left", "start": "left",
    "center": "center", "centre": "center", "中": "center", "居中": "center",
    "中间": "center", "中心": "center", "centre ": "center",
    "right": "right", "右": "right", "右对齐": "right", "居右": "right", "end": "right",
    "justify": "justify", "两端": "justify", "两端对齐": "justify", "分散对齐": "distribute",
    "distribute": "distribute", "both": "justify",
}

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
_HEX3_RE = re.compile(r"^#?([0-9a-fA-F]{3})$")

_NAMED_COLORS = {
    "black": "000000", "黑": "000000", "黑色": "000000", "自动": "auto", "auto": "auto",
    "white": "FFFFFF", "白": "FFFFFF", "白色": "FFFFFF",
    "red": "FF0000", "红": "FF0000", "红色": "FF0000",
    "blue": "0000FF", "蓝": "0000FF", "蓝色": "0000FF",
    "green": "008000", "绿": "008000", "绿色": "008000",
    "gray": "808080", "grey": "808080", "灰": "808080", "灰色": "808080",
    "yellow": "FFFF00", "黄": "FFFF00", "黄色": "FFFF00",
}


def to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return None
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


def to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def to_align(value: Any) -> Optional[str]:
    if value is None:
        return None
    key = str(value).strip().lower().replace(" ", "")
    if not key:
        return None
    return _ALIGN_MAP.get(key) or _ALIGN_MAP.get(str(value).strip())


def to_color(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    low = text.lower()
    if low in _NAMED_COLORS:
        return _NAMED_COLORS[low]
    match = _HEX_RE.match(text)
    if match:
        return match.group(1).upper()
    match = _HEX3_RE.match(text)
    if match:
        return "".join(ch * 2 for ch in match.group(1)).upper()
    return None


def normalize_spec(spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Coerce a raw spec into the canonical JSON form (drops unknown/empty keys)."""
    if not spec:
        return {}
    out: Dict[str, Any] = {}
    for key, raw in spec.items():
        if raw is None:
            continue
        if key in FONT_ATTRS:
            text = str(raw).strip()
            if text:
                out[key] = text
        elif key == "size_pt":
            value = to_float(raw)
            if value and value > 0:
                out[key] = round(value, 2)
        elif key in ("bold", "italic", "underline", "strike", "all_caps",
                     "keep_with_next", "page_break_before", "widow_control", "snap_to_grid"):
            value = to_bool(raw)
            if value is not None:
                out[key] = value
        elif key == "color":
            value = to_color(raw)
            if value:
                out[key] = value
        elif key == "highlight":
            text = str(raw).strip()
            if text:
                out[key] = text
        elif key in ("character_spacing_pt", "space_before_pt", "space_after_pt",
                     "first_line_indent_pt", "left_indent_pt", "right_indent_pt"):
            value = to_float(raw)
            if value is not None:
                out[key] = round(value, 2)
        elif key in ("first_line_indent_chars", "left_indent_chars"):
            value = to_float(raw)
            if value is not None:
                out[key] = round(value, 2)
        elif key == "line_spacing":
            value = to_float(raw)
            if value and value > 0:
                out[key] = round(value, 3)
        elif key == "line_spacing_rule":
            text = str(raw).strip().lower()
            if text in ("multiple", "exactly", "atleast", "at_least", "single", "one_point_five", "double"):
                out[key] = text
        elif key == "align":
            value = to_align(raw)
            if value:
                out[key] = value
        elif key == "outline_level":
            value = to_float(raw)
            if value is not None:
                out[key] = int(value)
        elif key == "vertical_align":
            text = str(raw).strip().lower()
            if text in ("superscript", "subscript", "baseline", "上标", "下标"):
                out[key] = {"上标": "superscript", "下标": "subscript"}.get(text, text)
        elif key in PAGE_ATTRS:
            if key == "orientation":
                text = str(raw).strip().lower()
                if text in ("portrait", "landscape", "纵向", "横向"):
                    out[key] = {"纵向": "portrait", "横向": "landscape"}.get(text, text)
            else:
                value = to_float(raw)
                if value is not None:
                    out[key] = round(value, 3)
    return out


def normalize_ruleset(rules: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rules = rules or {}
    styles_in = rules.get("styles") or {}
    styles: Dict[str, Any] = {}
    for role, spec in styles_in.items():
        key = canonical_role(role)
        if key is None:
            continue
        clean = normalize_spec(spec)
        if clean:
            styles[key] = clean
    out: Dict[str, Any] = {
        "version": RULESET_VERSION,
        "source": deepcopy(rules.get("source") or {}),
        "page": normalize_spec(rules.get("page") or {}),
        "styles": styles,
        "extras": deepcopy(rules.get("extras") or {}),
    }
    default_font = normalize_spec(rules.get("default_font") or {})
    if default_font:
        out["default_font"] = default_font
    cleanup_block = normalize_cleanup(rules.get("cleanup") or {})
    if cleanup_block.get("enabled"):
        out["cleanup"] = cleanup_block
    structure_block = normalize_structure(rules.get("structure") or {})
    if structure_block.get("enabled"):
        out["structure"] = structure_block
    return out


def canonical_role(role: str) -> Optional[str]:
    """Map any style-name-ish string onto one of :data:`ROLES` (or ``None``)."""
    if not role:
        return None
    raw = str(role).strip()
    low = raw.lower()
    if low in ROLES:
        return low
    compact = low.replace(" ", "").replace("_", "").replace("-", "")
    if compact in ROLES:
        return compact
    if compact in ROLE_ALIASES:
        return ROLE_ALIASES[compact]
    match = _TOC_RE.match(compact)
    if match:
        return "toc%s" % match.group(1)
    match = _HEADING_RE.match(compact)
    if match:
        return "heading%s" % match.group(1)
    # fall back to a loose prefix match for localized style names such as
    # "标题 1 字符" or "Heading 2 Char".
    for alias, target in ROLE_ALIASES.items():
        if compact.startswith(alias) and len(alias) >= 3:
            return target
    return None


def role_from_style_name(style_name: Optional[str]) -> Optional[str]:
    """Best effort style-name -> role mapping (used for template extraction)."""
    return canonical_role(style_name or "")


def role_from_style_id(style_id: Optional[str]) -> Optional[str]:
    """``Heading1`` / ``1`` style ids from Word's built-in style set."""
    if not style_id:
        return None
    text = str(style_id).strip()
    match = re.match(r"^[Hh]eading\s*([1-9])$", text)
    if match:
        return "heading" + match.group(1)
    return canonical_role(text)


def infer_role(style_name: Optional[str] = None,
               style_id: Optional[str] = None,
               outline_level: Optional[int] = None,
               in_table: bool = False,
               paragraph_text: str = "") -> Tuple[str, str]:
    """Heuristic role inference; returns ``(role, reason)``.

    Order matters: explicit style name/id wins, then the outline level, then the
    structural context (table cell), then the paragraph text shape, then normal.
    """
    if in_table:
        role = role_from_style_name(style_name) or role_from_style_id(style_id)
        if role in (None, "normal", "list", "table_text"):
            return "table_text", "in_table"
    for candidate in (style_name, style_id):
        role = role_from_style_name(candidate) or role_from_style_id(candidate)
        if role:
            return role, "style_name:%s" % (style_name or style_id)
    if outline_level is not None:
        if outline_level == 0:
            return "heading1", "outline_level:0"
        if 0 < outline_level <= 5:
            return "heading%s" % (outline_level + 1), "outline_level:%s" % outline_level
    if in_table:
        return "table_text", "in_table"
    stripped = (paragraph_text or "").strip()
    if stripped and len(stripped) <= 40 and not stripped.endswith(("。", ".", "；", ";", "，", ",")):
        return "normal", "heuristic:short_line"
    return "normal", "default"


def merge_specs(base: Optional[Dict[str, Any]], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """``override`` wins key by key; used to layer role spec over ``normal``."""
    out: Dict[str, Any] = dict(base or {})
    for key, value in (override or {}).items():
        if value is not None:
            out[key] = value
    return out


def spec_keys(spec: Optional[Dict[str, Any]]) -> List[str]:
    return sorted((spec or {}).keys())


def ruleset_rule_count(rules: Optional[Dict[str, Any]]) -> int:
    """Number of concrete formatting rules (page + per-role attributes)."""
    rules = rules or {}
    count = len(rules.get("page") or {})
    for spec in (rules.get("styles") or {}).values():
        count += len(spec or {})
    count += len(rules.get("default_font") or {})
    count += len(cleanup_categories(rules))
    count += len(structure_categories(rules))
    return count


def cleanup_categories(rules: Optional[Dict[str, Any]]) -> List[str]:
    """Enabled cleanup categories, in canonical order (empty when cleanup is off)."""
    block = (rules or {}).get("cleanup") or {}
    if not block.get("enabled"):
        return []
    return [key for key in CLEANUP_CATEGORIES if block.get(key)]


def cleanup_enabled(rules: Optional[Dict[str, Any]]) -> bool:
    return bool(cleanup_categories(rules))


def structure_categories(rules: Optional[Dict[str, Any]]) -> List[str]:
    """Enabled structure signals, in canonical order (empty when the pass is off)."""
    block = (rules or {}).get("structure") or {}
    if not block.get("enabled"):
        return []
    return [key for key in STRUCTURE_CATEGORIES if block.get(key)]


def structure_enabled(rules: Optional[Dict[str, Any]]) -> bool:
    return bool(structure_categories(rules))


def iter_rule_lines(rules: Optional[Dict[str, Any]], limit: int = 200) -> Iterable[str]:
    """Human readable one-line-per-rule rendering (report/CLI helpers)."""
    rules = rules or {}
    produced = 0
    for key, value in sorted((rules.get("page") or {}).items()):
        yield "page.%s = %s" % (key, value)
        produced += 1
    for key, value in sorted((rules.get("default_font") or {}).items()):
        yield "default_font.%s = %s" % (key, value)
        produced += 1
    for key in cleanup_categories(rules):
        yield "cleanup.%s = true" % key
        produced += 1
    for key in structure_categories(rules):
        yield "structure.%s = true" % key
        produced += 1
    for role in sorted((rules.get("styles") or {})):
        for key, value in sorted(rules["styles"][role].items()):
            if produced >= limit:
                yield "... (%d+ rules truncated)" % limit
                return
            yield "%s.%s = %s" % (role, key, value)
            produced += 1
