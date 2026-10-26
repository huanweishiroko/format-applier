"""Deterministic format-requirement parser.

Two inputs, one output shape:

* a ``.docx`` style template -> page setup + style definitions
  (``extract_rules_from_docx``), and
* free text (``.txt`` / ``.md`` / inline string) -> regex + keyword rules
  (``parse_text_rules``).

The text parser is intentionally generous: it understands the phrasings people
actually write in Chinese and English formatting specs, and it reports a
``coverage`` score so the caller can decide whether an LLM fallback is worth it.
It never sends anything anywhere by itself.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from . import docxio
from . import schema as ruleschema
from .cleanup import CLEANUP_CATEGORIES
from .structure import STRUCTURE_CATEGORIES

# --------------------------------------------------------------------------- #
# units / vocabularies
# --------------------------------------------------------------------------- #

CN_SIZE_TO_PT: Dict[str, float] = {
    "初号": 42, "小初": 36, "一号": 26, "小一": 24, "二号": 22, "小二": 18,
    "三号": 16, "小三": 15, "四号": 14, "小四": 12, "五号": 10.5, "小五": 9,
    "六号": 7.5, "小六": 6.5, "七号": 5.5, "八号": 5,
}

_CN_SIZE_ALT = re.compile(r"^[初小]?[一二三四五六七八九]号?$")

#: fonts people name in a spec; not exhaustive, just a strong hint list.
KNOWN_FONTS = {
    "宋体", "新宋体", "仿宋", "仿宋_gb2312", "黑体", "楷体", "楷体_gb2312", "微软雅黑",
    "等线", "方正小标宋简体", "方正仿宋简体", "方正黑体简体", "方正楷体简体", "华文中宋",
    "华文仿宋", "华文楷体", "华文宋体", "幼圆", "隶书", "思源宋体", "思源黑体", "苹方",
    "冬青黑体", "方正书宋", "方正兰亭黑", "汉仪旗黑", "文泉驿微米黑",
    "arial", "calibri", "times new roman", "cambria", "georgia", "verdana", "tahoma",
    "segoe ui", "helvetica", "courier new", "consolas", "roboto", "simsun", "simhei",
    "kaiti", "fangsong", "microsoft yahei", "dengxian", "garamond", "book antiqua",
}

#: token separators inside one clause: "宋体，小四 1.5倍行距"
_TOKEN_SPLIT = re.compile(r"[，,、;；\s]+")

#: (regex, pt) for "1.5 倍行距" style values.
_MULTIPLE_WORDS = {
    "单倍": 1.0, "single": 1.0, "1倍": 1.0, "1.0倍": 1.0,
    "1.5倍": 1.5, "一倍半": 1.5, "1.5": 1.5, "oneandahalf": 1.5,
    "双倍": 2.0, "2倍": 2.0, "2.0倍": 2.0, "two": 1.0, "double": 2.0,
}

_SECTION_RE = re.compile(
    r"^(?P<name>[^：:]{1,24}?)(?:部分|段落|样式|格式|文本)?\s*[：:]\s*(?P<body>.*)$"
)

_TARGET_PATTERNS: List[Tuple[re.Pattern, List[str]]] = [
    (re.compile(r"(?:第?\s*([1-6])\s*级|([一二三四五六])级)\s*标题|标题\s*([1-6])|标题([一二三四五六])|heading\s*([1-6])|^h([1-6])$", re.I), ["heading*"]),
    (re.compile(r"^(?:文档)?标题$|文章标题|题目|^title$", re.I), ["title"]),
    (re.compile(r"正文|bodytext|body\s*text|^normal$|普通段落|段落正文", re.I), ["normal"]),
    (re.compile(r"引用|引文|名言|^quote$|blockquote", re.I), ["quote"]),
    (re.compile(r"题注|图注|表注|^caption$", re.I), ["caption"]),
    (re.compile(r"表格(?:内)?(?:的)?文字|表内文字|表格文本|^table$", re.I), ["table_text"]),
    (re.compile(r"列表|项目符号|编号列表|^list$", re.I), ["list"]),
    (re.compile(r"(?:目录|toc)\s*([1-9])", re.I), ["toc*"]),
    (re.compile(r"全文|整篇|所有(?:的)?(?:文字|文本|段落)|统一|默认", re.I), ["__global__"]),
]

_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _target_from_groups(groups: Tuple[Optional[str], ...], kind: str) -> Optional[str]:
    for group in groups:
        if not group:
            continue
        if str(group).isdigit():
            return "%s%s" % (kind, group)
        if group in _CN_DIGITS:
            return "%s%s" % (kind, _CN_DIGITS[group])
    return None

_FONT_RE = re.compile(
    r"(?:字体|字形|typeface|font(?:\s*family)?)\s*(?:为|:|：|=|是)?\s*"
    r"[\"“'‘]?\s*([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff \-_.]{0,30}?)"
    r"\s*[\"”'’]?\s*(?=$|[，,。;；)）]|(?:\d|[一二三四五六七八九十])号|加粗|斜体|字号|颜色)",
    re.I,
)

#: "宋体 12pt" / "Arial 小四" - a bare font name directly followed by a size.
_BARE_FONT_SIZE_RE = re.compile(
    r"([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff \-_.]{0,30}?)\s+"
    r"(?:\d+(?:\.\d+)?\s*(?:pt|磅|点)|[初小]?[一二三四五六七八九]号)"
)


def _looks_like_font_token(token: str, known_only: bool = False) -> bool:
    """Font-like token: known font name, "XX体", or a Latin multi-word name."""
    token = token.strip().strip("\"'“”‘’")
    if not token or len(token) > 32:
        return False
    if token in CN_SIZE_TO_PT or _CN_SIZE_ALT.match(token):
        return False
    if re.match(r"^\d", token):
        return False
    if re.fullmatch(r"(?:字体|字形|字号|颜色|行距|行间距|段前|段后|首行缩进|左缩进|右缩进|"
                    r"缩进|对齐|居中|加粗|斜体|下划线|删除线|标题|正文|引用|题注|表格文字|"
                    r"列表|目录|全文|统一)", token):
        return False
    low = token.lower()
    if low in KNOWN_FONTS or token in KNOWN_FONTS:
        return True
    if not known_only and re.fullmatch(r"[\u4e00-\u9fff]{2,8}体", token):
        return True
    if not known_only and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", token) and len(token) >= 3:
        return True
    return False

_CN_FONT_RE = re.compile(r"(?:中文字体|中文|汉字)\s*(?:为|:|：|=|是)?\s*[\"“']?\s*([A-Za-z\u4e00-\u9fff][A-Za-z0-9 \-_.]{0,30}?)\s*[\"”']?\s*(?=$|[，,。;；)）])")
_EN_FONT_RE = re.compile(r"(?:西文字体|英文字体|西文|英文|ascii)\s*(?:为|:|：|=|是)?\s*[\"“']?\s*([A-Za-z][A-Za-z0-9 \-_.]{0,30}?)\s*[\"”']?\s*(?=$|[，,。;；)）])")

_SIZE_RE = re.compile(
    r"(?:(?:字号|字体大小|大小)\s*(?:为|:|：|=|是)?\s*)?"
    r"(\d+(?:\.\d+)?)\s*(?:pt|磅|点)"
    r"|(?:(?:(?:字号|字体大小|大小)\s*(?:为|:|：|=|是)?\s*)?)([初小]?[一二三四五六七八九]号?)",
    re.I,
)

_BOLD_RE = re.compile(r"加粗|粗体|bold|字重\s*(?:为)?\s*bold", re.I)
_ITALIC_RE = re.compile(r"斜体|italic", re.I)
_UNDERLINE_RE = re.compile(r"下划线|underline", re.I)
_STRIKE_RE = re.compile(r"删除线|strikethrough", re.I)
_ALL_CAPS_RE = re.compile(r"全部大写|全大写|uppercase|all\s*caps", re.I)
_NOT_RE = re.compile(r"不|禁止|取消|without|no\s")

_COLOR_RE = re.compile(
    r"(?:字体颜色|文字颜色|颜色|color)\s*(?:为|:|：|=|是)?\s*"
    r"(#[0-9a-fA-F]{3,6}|[A-Za-z]{3,20}|[\u4e00-\u9fff]{1,4}色?)", re.I)
_HEX_INLINE_RE = re.compile(r"#[0-9a-fA-F]{6}\b")
_RGB_INLINE_RE = re.compile(r"RGB\s*\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)", re.I)

_ALIGN_RE = re.compile(r"两端对齐|居中|居中对齐|左对齐|右对齐|分散对齐|center|justify|left|right", re.I)

_LINE_SPACING_RE = re.compile(
    r"(?:(?:行距|行间距|line\s*spacing|line\s*height)\s*(?:为|:|：|=|是)?\s*)?"
    r"(单倍|双倍|一倍半|1\.5\s*倍|1\s*倍|2\s*倍|1\.5|2\.0|double|single)"
    r"|(?:行距|行间距)\s*(?:为|:|：|=|是)?\s*(\d+(?:\.\d+)?)\s*(?:pt|磅|点)",
    re.I,
)

_SPACE_RE = re.compile(r"(段前|段后|段间距|space\s*before|space\s*after)\s*(?:为|:|：|=|是)?\s*(\d+(?:\.\d+)?)\s*(?:pt|磅|点|行)?", re.I)

_INDENT_RE = re.compile(
    r"(首行缩进|左缩进|右缩进|悬挂缩进|indent(?:ation)?)\s*(?:为|:|：|=|是)?\s*"
    r"(\d+(?:\.\d+)?)\s*(?:字符|个字|字|char(?:acter)?s?|pt|磅|点|厘米|cm|英寸|inch)?",
    re.I,
)

_PAGE_RE = re.compile(
    r"(上边距|下边距|左边距|右边距|页边距|top\s*margin|bottom\s*margin|left\s*margin|right\s*margin)"
    r"\s*(?:为|:|：|=|是)?\s*(\d+(?:\.\d+)?)\s*(?:cm|厘米|mm|毫米|pt|磅|inch|英寸)?", re.I)

_ORIENT_RE = re.compile(r"横向|纵向|landscape|portrait", re.I)

#: attributes that count towards the coverage score.
_COVERAGE_ATTRS = (
    "font_eastasia", "font_ascii", "size_pt", "bold", "italic", "color",
    "align", "line_spacing", "space_before_pt", "space_after_pt",
    "first_line_indent_chars", "outline_level",
)


def _size_pt(raw: Optional[str], cn: Optional[str]) -> Optional[float]:
    if cn:
        return CN_SIZE_TO_PT.get(cn.strip())
    if raw:
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _cm(value: float, unit: Optional[str]) -> float:
    unit = (unit or "cm").lower()
    if unit in ("mm", "毫米"):
        return value / 10.0
    if unit in ("pt", "磅"):
        return value / 28.3465
    if unit in ("inch", "英寸"):
        return value * 2.54
    return value


def strip_leading_marker(line: str) -> str:
    return re.sub(r"^\s*(?:[-*+•·>]|\(?\d+[.)、]|[（(]\d+[）)]|[一二三四五六七八九十]+[、.)])\s*", "", line)


# --------------------------------------------------------------------------- #
# cleanup directives ("清理：markdown 不可见字符 ...")
#
# These lines are pulled out *before* the clause parser runs. That matters: a
# clause like "清理：markdown 空行" would otherwise be read as a font clause
# (``markdown`` looks like a Latin font name) and quietly set font_ascii.
# --------------------------------------------------------------------------- #

_KEEP_SYMBOLS_RE = re.compile(
    r"^\s*(?:保留符号|保留字符|保留|keep\s*symbols?|keep)\s*[：:]\s*(?P<body>.*)$", re.I)
_REMOVE_SYMBOLS_RE = re.compile(
    r"^\s*(?:删除符号|去除符号|移除符号|remove\s*symbols?)\s*[：:]\s*(?P<body>.*)$", re.I)
_CLEANUP_HEAD_RE = re.compile(
    r"^\s*(?:清理|清除|cleanup|clean)\s*[：:]\s*(?P<body>.*)$", re.I)

_CLEANUP_TOKEN_MAP = {
    # markdown residue
    "markdown": "markdown", "md": "markdown", "标记": "markdown", "残留": "markdown",
    "残留标记": "markdown", "语法": "markdown", "markdown残留": "markdown",
    # invisible characters
    "不可见": "invisible", "不可见字符": "invisible", "零宽": "invisible",
    "零宽字符": "invisible", "隐形字符": "invisible", "invisible": "invisible",
    # punctuation
    "标点": "punctuation", "标点符号": "punctuation", "重复标点": "punctuation",
    "孤立标点": "punctuation", "punctuation": "punctuation",
    # whitespace
    "空白": "spaces", "空白规范": "spaces", "空格": "spaces", "多余空格": "spaces",
    "spaces": "spaces", "whitespace": "spaces",
    # decoration / placeholder symbols
    "装饰": "decorations", "装饰符号": "decorations", "符号": "decorations",
    "占位": "decorations", "占位符号": "decorations", "无意义符号": "decorations",
    "decorations": "decorations", "symbols": "decorations",
    # split-line fragments / inline formulas (merge before formatting)
    "碎片": "fragments", "碎片合并": "fragments", "行内碎片": "fragments",
    "段落碎片": "fragments", "合并碎片": "fragments", "短行合并": "fragments",
    "fragments": "fragments", "fragment": "fragments",
    # blank paragraphs
    "空段落": "blank_lines", "空行": "blank_lines", "合并空段落": "blank_lines",
    "多余空段落": "blank_lines", "blank": "blank_lines", "blank_lines": "blank_lines",
    # *every* blank paragraph, including a single separator line
    "删除空段落": "blank_all", "空段落全删": "blank_all", "全部空段落": "blank_all",
    "无空段落": "blank_all", "去空段落": "blank_all", "清空空段落": "blank_all",
    "不要空段落": "blank_all", "不留空段落": "blank_all", "blank_all": "blank_all",
    # everything
    "全部": "__all__", "所有": "__all__", "all": "__all__",
}
_CLEANUP_NONE_TOKENS = {"无", "不用", "不清理", "关闭", "none", "off", "no", "false"}


def _cleanup_tokens(body: str) -> Tuple[bool, List[str], List[str]]:
    """``(disabled, categories, unrecognised)`` for one ``清理：`` directive."""
    text = (body or "").strip().strip("。.；;")
    if not text:
        return False, [], []
    parts = [part for part in re.split(r"[，,、;；/|\s]+", text) if part]
    categories: List[str] = []
    unknown: List[str] = []
    for part in parts:
        low = part.lower()
        if low in _CLEANUP_NONE_TOKENS:
            return True, [], []
        target = _CLEANUP_TOKEN_MAP.get(low) or _CLEANUP_TOKEN_MAP.get(part)
        if target == "__all__":
            categories = list(CLEANUP_CATEGORIES)
            break
        if target:
            if target not in categories:
                categories.append(target)
        else:
            unknown.append(part)
    return False, categories, unknown


def extract_cleanup_directives(lines: List[str]) -> Tuple[List[str], Dict[str, Any], List[str]]:
    """Split the ``清理：`` / ``保留符号：`` / ``删除符号：`` lines out of a spec.

    Returns ``(remaining_lines, cleanup_block, unrecognised_tokens)``.
    """
    cleanup: Dict[str, Any] = {}
    keep: List[str] = []
    remove: List[str] = []
    unknown: List[str] = []
    remaining: List[str] = []
    disabled = False

    for line in lines:
        body = line.strip()
        match = _KEEP_SYMBOLS_RE.match(body)
        if match:
            keep.append(match.group("body").strip())
            continue
        match = _REMOVE_SYMBOLS_RE.match(body)
        if match:
            remove.append(match.group("body").strip())
            continue
        match = _CLEANUP_HEAD_RE.match(body)
        if match:
            is_disabled, categories, unrecognised = _cleanup_tokens(match.group("body"))
            if is_disabled:
                disabled = True
                cleanup = {}
                continue
            for category in categories:
                cleanup[category] = True
            unknown.extend(unrecognised)
            continue
        remaining.append(line)

    if disabled:
        return remaining, {}, unknown
    if keep:
        cleanup["keep_symbols"] = "".join(keep)
    if remove:
        cleanup["remove_symbols"] = "".join(remove)
    if cleanup and not any(cleanup.get(key) for key in CLEANUP_CATEGORIES) \
            and not cleanup.get("remove_symbols"):
        # only a keep list was given: nothing would ever be cleaned
        unknown.extend(["keep_symbols without a 清理： line"])
        cleanup = {}
    return remaining, cleanup, unknown


# --------------------------------------------------------------------------- #
# structural preprocessing directives ("结构预处理：整段加粗 编号正则")
#
# Like the cleanup lines these are pulled out before the clause parser runs:
# "整段加粗" would otherwise be read as a bold attribute of the current target.
# --------------------------------------------------------------------------- #

_STRUCTURE_HEAD_RE = re.compile(
    r"^\s*(?:结构预处理|结构识别|标题结构|结构分析|structure|struct)\s*[：:]\s*(?P<body>.*)$", re.I)

_STRUCTURE_TOKEN_MAP = {
    # whole-paragraph bold
    "bold": "bold", "加粗": "bold", "整段加粗": "bold", "粗体": "bold",
    "整段粗体": "bold", "通篇加粗": "bold",
    # document numbering
    "numbering": "numbering", "编号": "numbering", "编号正则": "numbering",
    "序号": "numbering", "自动编号": "numbering", "标题编号": "numbering",
    # document title: first paragraph / centred front-matter line
    "lead_title": "lead_title", "首段标题": "lead_title", "首行标题": "lead_title",
    "首段作标题": "lead_title", "首段为标题": "lead_title", "文档标题": "lead_title",
    "centered": "centered", "居中短行": "centered", "居中标题": "centered",
    "居中行": "centered",
    # explicit level ladder (optional)
    "公文编号": "@official", "公文": "@official", "official": "@official",
    "小数编号": "@decimal", "十进制编号": "@decimal", "decimal": "@decimal",
    # everything
    "全部": "@all", "所有": "@all", "all": "@all",
}
_STRUCTURE_NONE_TOKENS = {"无", "不用", "不启用", "不预处理", "关闭", "none", "off", "no", "false"}


def _structure_tokens(body: str) -> Tuple[bool, List[str], Optional[str], List[str]]:
    """``(disabled, signals, ladder, unrecognised)`` for one ``结构预处理：`` line."""
    text = (body or "").strip().strip("。.；;")
    if not text:
        return False, [], None, []
    parts = [part for part in re.split(r"[，,、;；/|\s]+", text) if part]
    signals: List[str] = []
    ladder: Optional[str] = None
    unknown: List[str] = []
    for part in parts:
        low = part.lower()
        if low in _STRUCTURE_NONE_TOKENS:
            return True, [], None, []
        target = _STRUCTURE_TOKEN_MAP.get(low) or _STRUCTURE_TOKEN_MAP.get(part)
        if target == "@all":
            signals = list(STRUCTURE_CATEGORIES)
            break
        if target in ("@official", "@decimal"):
            ladder = "official" if target == "@official" else "decimal"
            continue
        if target:
            if target not in signals:
                signals.append(target)
            continue
        unknown.append(part)
    return False, signals, ladder, unknown


def extract_structure_directives(lines: List[str]) -> Tuple[List[str], Dict[str, Any], List[str]]:
    """Split ``结构预处理：`` lines out of a spec.

    Returns ``(remaining_lines, structure_block, unrecognised_tokens)``.
    """
    block: Dict[str, Any] = {}
    unknown: List[str] = []
    remaining: List[str] = []
    disabled = False

    for line in lines:
        match = _STRUCTURE_HEAD_RE.match(line.strip())
        if not match:
            remaining.append(line)
            continue
        is_disabled, signals, ladder, unrecognised = _structure_tokens(match.group("body"))
        if is_disabled:
            disabled = True
            block = {}
            continue
        for signal in signals:
            block[signal] = True
        if ladder:
            block["ladder"] = ladder
        unknown.extend(unrecognised)

    if disabled:
        return remaining, {}, unknown
    if block and not any(block.get(key) for key in STRUCTURE_CATEGORIES):
        # only a ladder was named: no signal would ever be detected
        unknown.extend(["ladder without a signal"])
        block = {}
    return remaining, block, unknown


def _match_targets(text: str) -> List[str]:
    targets: List[str] = []
    for pattern, roles in _TARGET_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        template = roles[0]
        if template.endswith("*"):
            kind = template[:-1]
            resolved = _target_from_groups(match.groups(), kind)
            if resolved is None:
                continue
            role = resolved
        else:
            role = template
        if role not in targets:
            targets.append(role)
    # most specific first: drop the generic "__global__" when real roles matched
    real = [item for item in targets if item != "__global__"]
    return real or targets


def _parse_sizes(text: str) -> List[float]:
    out: List[float] = []
    for match in _SIZE_RE.finditer(text):
        value = _size_pt(match.group(1), match.group(2))
        if value:
            out.append(value)
    return out


def _apply_clause(spec: Dict[str, Any], text: str) -> Tuple[Dict[str, Any], List[str]]:
    """Extract every recognized attribute from one clause into ``spec``."""
    notes: List[str] = []
    before = dict(spec)

    sizes = _parse_sizes(text)
    if sizes:
        spec["size_pt"] = sizes[0]

    cn_font = _CN_FONT_RE.search(text)
    if cn_font:
        spec["font_eastasia"] = cn_font.group(1).strip()
    en_font = _EN_FONT_RE.search(text)
    if en_font:
        spec["font_ascii"] = en_font.group(1).strip()

    explicit_fonts: List[str] = []
    for match in _FONT_RE.finditer(text):
        name = match.group(1).strip()
        if name and ruleschema.to_float(name) is None and not re.match(
                r"^(加粗|斜体|下划线|居中|左对齐|右对齐|两端对齐|颜色|字号|标题|正文)$", name):
            explicit_fonts.append(name)
    if not explicit_fonts:
        for match in _BARE_FONT_SIZE_RE.finditer(text):
            candidate = match.group(1).strip()
            if _looks_like_font_token(candidate):
                explicit_fonts.append(candidate)
                break
    if not explicit_fonts:
        tokens = [token for token in _TOKEN_SPLIT.split(text.strip()) if token]
        # a Latin font name is unambiguous; a bare CJK token only counts when it
        # is a recognised font name (so prose never turns into a font rule)
        for index, token in enumerate(tokens):
            if _looks_like_font_token(token, known_only=(index == 0)):
                explicit_fonts.append(token.strip("\"'“”‘’"))
                break
    if explicit_fonts:
        spec.setdefault("font_eastasia", explicit_fonts[0])
        spec.setdefault("font_ascii", explicit_fonts[0])
        for extra in explicit_fonts[1:]:
            if re.fullmatch(r"[\u4e00-\u9fff].*", extra):
                spec.setdefault("font_eastasia", extra)
            else:
                spec.setdefault("font_ascii", extra)

    negative = bool(_NOT_RE.search(text))
    if _BOLD_RE.search(text):
        spec["bold"] = not negative
    if _ITALIC_RE.search(text):
        spec["italic"] = not negative
    if _UNDERLINE_RE.search(text):
        spec["underline"] = not negative
    if _STRIKE_RE.search(text):
        spec["strike"] = not negative
    if _ALL_CAPS_RE.search(text):
        spec["all_caps"] = not negative

    rgb = _RGB_INLINE_RE.search(text)
    if rgb:
        spec["color"] = "%02X%02X%02X" % tuple(min(255, int(g)) for g in rgb.groups())
    else:
        hex_inline = _HEX_INLINE_RE.search(text)
        if hex_inline:
            spec["color"] = hex_inline.group(0).lstrip("#").upper()
        else:
            color_match = _COLOR_RE.search(text)
            if color_match:
                value = ruleschema.to_color(color_match.group(1))
                if value:
                    spec["color"] = value

    spacing = _LINE_SPACING_RE.search(text)
    if spacing:
        if spacing.group(2):
            spec["line_spacing"] = float(spacing.group(2))
            spec["line_spacing_rule"] = "exactly"
        elif spacing.group(1):
            token = spacing.group(1).replace(" ", "")
            value = _MULTIPLE_WORDS.get(token)
            if value is None:
                value = ruleschema.to_float(token)
            if value:
                spec["line_spacing"] = float(value)
                spec["line_spacing_rule"] = "multiple"
        else:
            spec["line_spacing"] = 1.5
            spec["line_spacing_rule"] = "multiple"

    for match in _SPACE_RE.finditer(text):
        key = "space_before_pt" if match.group(1).startswith(("段前", "space before", "space_before")) or "前" in match.group(1) else "space_after_pt"
        spec[key] = float(match.group(2))

    for match in _INDENT_RE.finditer(text):
        label = match.group(1)
        value = float(match.group(2))
        unit_match = re.search(r"(字符|个字|字|char|pt|磅|点|厘米|cm|英寸|inch)", text[match.end(2):match.end(2) + 8], re.I)
        unit = (unit_match.group(1).lower() if unit_match else "字符")
        if label.startswith(("首行缩进", "indent")):
            if unit in ("字符", "个字", "字", "char", "chars", "character"):
                spec["first_line_indent_chars"] = value
                spec.pop("first_line_indent_pt", None)
            else:
                spec["first_line_indent_pt"] = value * 28.3465 if unit in ("厘米", "cm") else value
        elif label.startswith("悬挂缩进"):
            spec["first_line_indent_chars"] = -value
        elif label.startswith("左缩进"):
            if unit in ("字符", "个字", "字", "char", "chars", "character"):
                spec["left_indent_chars"] = value
            else:
                spec["left_indent_pt"] = value * 28.3465 if unit in ("厘米", "cm") else value
        elif label.startswith("右缩进"):
            spec["right_indent_pt"] = value * 28.3465 if unit in ("厘米", "cm") else value

    align = _ALIGN_RE.search(text)
    if align:
        spec["align"] = ruleschema.to_align(align.group(0))

    for match in _PAGE_RE.finditer(text):
        label = match.group(1).lower()
        value = _cm(float(match.group(2)),
                    re.search(r"(cm|厘米|mm|毫米|pt|磅|inch|英寸)", text[match.end(2):match.end(2) + 6], re.I).group(1)
                    if re.search(r"(cm|厘米|mm|毫米|pt|磅|inch|英寸)", text[match.end(2):match.end(2) + 6], re.I) else "cm")
        if "上" in label or "top" in label:
            spec["margin_top_cm"] = round(value, 3)
        elif "下" in label or "bottom" in label:
            spec["margin_bottom_cm"] = round(value, 3)
        elif "左" in label or "left" in label:
            spec["margin_left_cm"] = round(value, 3)
        elif "右" in label or "right" in label:
            spec["margin_right_cm"] = round(value, 3)
        elif "页边距" in label:
            for key in ("margin_top_cm", "margin_bottom_cm", "margin_left_cm", "margin_right_cm"):
                spec[key] = round(value, 3)

    orient = _ORIENT_RE.search(text)
    if orient:
        spec["orientation"] = "landscape" if orient.group(0).lower() in ("横向", "landscape") else "portrait"

    if spec != before:
        notes.append("clause matched")
    return spec, notes


def parse_text_rules(text: str, *, source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Parse a natural-language formatting spec into a rule set.

    Returns a rule set (see :mod:`word_format_applier.schema`) with
    ``extras.parse`` describing match quality.
    """
    styles: Dict[str, Dict[str, Any]] = {}
    page: Dict[str, Any] = {}
    global_defaults: Dict[str, Any] = {}
    matched_lines = 0
    total_lines = 0
    notes: List[str] = []

    paragraphs: List[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        # "# ..." documents a preset; without this the clause parser reads the
        # prose and, for example, turns a stray "LLM" into a font name.
        if not line or line.startswith("#"):
            continue
        paragraphs.append(line)

    # "清理：..." lines describe a text-cleanup pass, not formatting attributes,
    # so they are consumed here rather than by the clause parser below.
    paragraphs, cleanup_block, cleanup_unknown = extract_cleanup_directives(paragraphs)
    if cleanup_block:
        notes.append("cleanup categories: %s"
                     % ", ".join(key for key in CLEANUP_CATEGORIES if cleanup_block.get(key)))
    for token in cleanup_unknown:
        notes.append("unrecognised cleanup token: %s" % token)

    # "结构预处理：..." lines describe the heading-level pass that runs before role
    # binding, so they are consumed here too.
    paragraphs, structure_block, structure_unknown = extract_structure_directives(paragraphs)
    if structure_block:
        notes.append("structure signals: %s"
                     % ", ".join(key for key in STRUCTURE_CATEGORIES if structure_block.get(key)))
    for token in structure_unknown:
        notes.append("unrecognised structure token: %s" % token)

    current_targets: List[str] = ["__global__"]
    group: List[str] = []

    def flush_group() -> None:
        nonlocal matched_lines, group
        if not group:
            return
        blob = " ".join(group)
        for target in current_targets:
            spec: Dict[str, Any] = {}
            _apply_clause(spec, blob)
            if not spec:
                continue
            if target == "__global__":
                global_defaults.update(spec)
            else:
                styles.setdefault(target, {}).update(spec)
            matched_lines += 1
        group = []

    def commit(targets: List[str], body: str) -> None:
        nonlocal matched_lines
        spec: Dict[str, Any] = {}
        _apply_clause(spec, body)
        if not spec:
            return
        for target in targets:
            if target == "__global__":
                global_defaults.update(spec)
            else:
                styles.setdefault(target, {}).update(spec)
        matched_lines += 1

    for line in paragraphs:
        total_lines += 1
        body = strip_leading_marker(line)
        # 1) "标题1：黑体三号居中" — the head names the target, the tail carries attributes
        head, sep, tail = body.partition("：")
        if not sep:
            head, sep, tail = body.partition(":")
        named = _match_targets(head) if sep and tail.strip() else []
        if named:
            flush_group()
            current_targets = named
            rest = tail.strip()
            inline = _match_targets(rest)
            if inline:
                commit(inline, rest)
            else:
                group.append(rest)
            continue
        # 2) a bare section header ("正文部分") switches the current target
        if len(body) <= 16:
            candidates = _match_targets(body)
            if candidates:
                flush_group()
                current_targets = candidates
                continue
        # 3) plain clause line: attributes apply to the current target(s)
        if body:
            group.append(body)

    flush_group()

    rules: Dict[str, Any] = {
        "version": ruleschema.RULESET_VERSION,
        "source": dict(source or {}),
        "page": ruleschema.normalize_spec(page),
        "styles": {},
        "default_font": {},
        "extras": {"parse": {"matched_lines": matched_lines, "total_lines": total_lines,
                             "notes": notes, "mode": "text_rules"}},
    }
    if cleanup_block:
        rules["cleanup"] = cleanup_block
        if cleanup_unknown:
            rules["extras"]["parse"]["cleanup_unrecognised"] = cleanup_unknown
    if structure_block:
        rules["structure"] = structure_block
        if structure_unknown:
            rules["extras"]["parse"]["structure_unrecognised"] = structure_unknown
    if global_defaults:
        default_font = {key: value for key, value in global_defaults.items()
                        if key in ruleschema.FONT_ATTRS}
        para_defaults = {key: value for key, value in global_defaults.items()
                         if key not in ruleschema.FONT_ATTRS}
        if default_font:
            rules["default_font"] = ruleschema.normalize_spec(default_font)
        if para_defaults:
            current = styles.setdefault("normal", {})
            merged = dict(para_defaults)
            merged.update(current)
            styles["normal"] = merged

    rules["styles"] = {role: ruleschema.normalize_spec(spec) for role, spec in styles.items()}
    rules = ruleschema.normalize_ruleset(rules)

    coverage = coverage_score(rules)
    rules["extras"]["parse"]["coverage"] = coverage
    return rules


def coverage_score(rules: Dict[str, Any]) -> float:
    """0..1 estimate of how much of a real formatting spec was captured."""
    styles = (rules or {}).get("styles") or {}
    core_roles = [role for role in ("normal", "heading1", "heading2", "title", "quote")
                  if role in styles]
    if not core_roles:
        return 0.0
    filled = 0
    for role in core_roles:
        spec = styles.get(role) or {}
        filled += sum(1 for attr in _COVERAGE_ATTRS if attr in spec)
    page_bonus = 0.15 if (rules.get("page") or {}) else 0.0
    return round(min(1.0, filled / float(len(core_roles) * len(_COVERAGE_ATTRS)) + page_bonus), 3)


# --------------------------------------------------------------------------- #
# .docx style template extraction
# --------------------------------------------------------------------------- #

_PT_PER_TWIP = 1.0 / 20.0
_CM_PER_TWIP = 2.54 / 1440.0


def _run_char_spec(run) -> Dict[str, Any]:
    spec: Dict[str, Any] = {}
    font = run.font
    if font is not None:
        if font.name:
            spec["font_ascii"] = font.name
            spec["font_hansi"] = font.name
        if font.size is not None:
            spec["size_pt"] = round(font.size.pt, 2)
        if font.bold is not None:
            spec["bold"] = bool(font.bold)
        if font.italic is not None:
            spec["italic"] = bool(font.italic)
        if font.underline is not None:
            spec["underline"] = bool(font.underline)
        if font.strike is not None and font.strike:
            spec["strike"] = True
        if font.all_caps:
            spec["all_caps"] = True
        try:
            if font.color is not None and font.color.rgb is not None:
                spec["color"] = str(font.color.rgb).upper()
        except Exception:
            pass
    try:
        rpr = run._element.find(docxio.qn("w:rPr"))
        if rpr is not None:
            rfonts = rpr.find(docxio.qn("w:rFonts"))
            if rfonts is not None:
                eastasia = rfonts.get(docxio.qn("w:eastAsia"))
                if eastasia:
                    spec["font_eastasia"] = eastasia
                ascii_font = rfonts.get(docxio.qn("w:ascii"))
                if ascii_font and "font_ascii" not in spec:
                    spec["font_ascii"] = ascii_font
    except Exception:
        pass
    return ruleschema.normalize_spec(spec)


def _paragraph_style_ident(paragraph) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    style_name = None
    style_id = None
    outline = None
    try:
        style = paragraph.style
        if style is not None:
            style_name = style.name
            style_id = style.style_id
        ppr = paragraph._p.find(docxio.qn("w:pPr"))
        if ppr is not None:
            outline_el = ppr.find(docxio.qn("w:outlineLvl"))
            if outline_el is not None:
                value = outline_el.get(docxio.qn("w:val"))
                if value is not None and str(value).isdigit():
                    outline = int(value)
    except Exception:
        pass
    return style_name, style_id, outline


def _paragraph_para_spec(paragraph) -> Dict[str, Any]:
    spec: Dict[str, Any] = {}
    fmt = paragraph.paragraph_format
    try:
        if fmt.alignment is not None:
            align = str(fmt.alignment).split(" ")[0].split(".")[-1].lower()
            spec["align"] = ruleschema.to_align(align) or align
    except Exception:
        pass
    try:
        if fmt.line_spacing is not None:
            if isinstance(fmt.line_spacing, float) or isinstance(fmt.line_spacing, int):
                spec["line_spacing"] = round(float(fmt.line_spacing), 3)
                spec["line_spacing_rule"] = "multiple"
            else:
                spec["line_spacing"] = round(float(fmt.line_spacing.pt), 2)
                spec["line_spacing_rule"] = "exactly"
    except Exception:
        pass
    for attr, key in (("space_before", "space_before_pt"), ("space_after", "space_after_pt")):
        try:
            value = getattr(fmt, attr)
            if value is not None:
                spec[key] = round(float(value.pt), 2)
        except Exception:
            pass
    for attr, key in (("first_line_indent", "first_line_indent_pt"),
                      ("left_indent", "left_indent_pt"),
                      ("right_indent", "right_indent_pt")):
        try:
            value = getattr(fmt, attr)
            if value is not None:
                spec[key] = round(float(value.pt), 2)
        except Exception:
            pass
    return ruleschema.normalize_spec(spec)


def _convert_char_indents(spec: Dict[str, Any], size_pt: Optional[float]) -> Dict[str, Any]:
    """Express first-line/left indents that are whole multiples of the font size as chars."""
    if not size_pt:
        return spec
    for src, dst in (("first_line_indent_pt", "first_line_indent_chars"),
                     ("left_indent_pt", "left_indent_chars")):
        if src not in spec:
            continue
        ratio = spec[src] / size_pt
        rounded = round(ratio)
        if rounded and abs(ratio - rounded) < 0.06 and abs(rounded) <= 8:
            spec.pop(src, None)
            spec[dst] = float(rounded)
    return spec


def _page_spec(section) -> Dict[str, Any]:
    spec: Dict[str, Any] = {}
    try:
        spec["margin_top_cm"] = round(section.top_margin.cm, 3)
        spec["margin_bottom_cm"] = round(section.bottom_margin.cm, 3)
        spec["margin_left_cm"] = round(section.left_margin.cm, 3)
        spec["margin_right_cm"] = round(section.right_margin.cm, 3)
        spec["page_width_cm"] = round(section.page_width.cm, 3)
        spec["page_height_cm"] = round(section.page_height.cm, 3)
        spec["orientation"] = "landscape" if section.orientation == docxio.WD_ORIENT.LANDSCAPE else "portrait"
    except Exception:
        pass
    return ruleschema.normalize_spec(spec)


def extract_rules_from_docx(path: str, *, max_paragraphs: int = 400) -> Dict[str, Any]:
    """Read a .docx style template into a rule set.

    Page setup comes from the first section, per-role specs from the first
    representative paragraph of each mapped role (runs -> paragraph -> document
    defaults), plus ``default_font`` from the ``Normal`` style.
    """
    document = docxio.open_document(path)
    rules: Dict[str, Any] = {
        "version": ruleschema.RULESET_VERSION,
        "source": {"kind": "docx"},
        "page": {},
        "styles": {},
        "default_font": {},
        "extras": {"parse": {"mode": "docx_template"}},
    }
    if document.sections:
        rules["page"] = _page_spec(document.sections[0])

    default_font: Dict[str, Any] = {}
    try:
        normal = document.styles["Normal"]
        if normal is not None and normal.font is not None:
            if normal.font.name:
                default_font["font_ascii"] = normal.font.name
                default_font["font_hansi"] = normal.font.name
            if normal.font.size is not None:
                default_font["size_pt"] = round(normal.font.size.pt, 2)
            rpr = getattr(normal.element, "find", lambda tag: None)(docxio.qn("w:rPr"))
            if rpr is not None:
                rfonts = rpr.find(docxio.qn("w:rFonts"))
                if rfonts is not None:
                    eastasia = rfonts.get(docxio.qn("w:eastAsia"))
                    if eastasia:
                        default_font["font_eastasia"] = eastasia
    except Exception:
        pass
    rules["default_font"] = ruleschema.normalize_spec(default_font)

    roles_seen: Dict[str, int] = {}
    for paragraph in docxio.iter_all_paragraphs(document)[:max_paragraphs]:
        text = docxio.paragraph_text(paragraph).strip()
        style_name, style_id, outline = _paragraph_style_ident(paragraph)
        role = ruleschema.role_from_style_name(style_name) or ruleschema.role_from_style_id(style_id)
        if role is None and outline is not None and 0 <= outline <= 5:
            role = "heading%s" % (outline + 1)
        if role is None:
            continue
        if roles_seen.get(role, 0) >= 3:
            continue
        spec: Dict[str, Any] = {}
        for run in paragraph.runs:
            if not (run.text or "").strip():
                continue
            spec.update(_run_char_spec(run))
            break
        para_spec = _paragraph_para_spec(paragraph)
        spec.update(para_spec)
        if role.startswith("heading") and outline is not None:
            spec["outline_level"] = outline
        size = spec.get("size_pt") or (rules["default_font"] or {}).get("size_pt")
        spec = _convert_char_indents(spec, size)
        merged = dict(rules["styles"].get(role) or {})
        for key, value in spec.items():
            merged.setdefault(key, value)
        rules["styles"][role] = merged
        roles_seen[role] = roles_seen.get(role, 0) + 1

    rules = ruleschema.normalize_ruleset(rules)
    rules["extras"]["parse"]["roles_seen"] = roles_seen
    rules["extras"]["parse"]["coverage"] = coverage_score(rules)
    return rules
