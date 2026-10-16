"""docx_extractor —— 把 .docx 的段落排版样式压成「指纹」文本，喂给 LLM 转 DSL。

每段输出一行，字段顺序固定::

    段落 1 | 全国人民代表大会常务委员会公报 | 中:黑体 英:Times New Roman | 22pt(二号) | 加粗 | 常规 | 居中 | 首行缩进:无 | 行距:1.5倍 | 样式:标题

规则：
  * 只取正文段落；**跳过表格、页眉页脚、文本框**里的段落。
  * 段落按文档顺序编号，从 1 开始；空段落也保留（文本显示为「(空)」）。
  * 每段的属性按「直接格式 → 段落样式 → 基样式 → 文档默认」逐级回退，
    取到的是**生效值**；同一段内多个 run 不一致时显示 ``混排(a/b)``。
  * 最多 200 段，超出则截断并在末尾标注。

命令行::

    python docx_extractor.py samples/target.docx
    python docx_extractor.py samples/target.docx --out fingerprint.txt --limit 200
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

#: 段落总数上限
DEFAULT_LIMIT = 200

#: 不参与的容器：表格、文本框、页眉、页脚、批注、脚注
SKIP_ANCESTORS = {
    qn("w:tbl"),
    qn("w:txbxContent"),
    qn("w:hdr"),
    qn("w:ftr"),
    qn("w:comment"),
    qn("w:footnote"),
    qn("w:endnote"),
}

#: 半磅 → 中文字号名
SIZE_NAMES: Dict[int, str] = {
    84: "初号", 72: "小初",
    52: "一号", 48: "小一",
    44: "二号", 36: "小二",
    32: "三号", 30: "小三",
    28: "四号", 24: "小四",
    21: "五号", 18: "小五",
    15: "六号", 13: "小六",
    11: "七号", 10: "八号",
}

_ALIGN_NAMES = {
    WD_ALIGN_PARAGRAPH.LEFT: "左对齐",
    WD_ALIGN_PARAGRAPH.CENTER: "居中",
    WD_ALIGN_PARAGRAPH.RIGHT: "右对齐",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "两端对齐",
    WD_ALIGN_PARAGRAPH.DISTRIBUTE: "分散对齐",
    WD_ALIGN_PARAGRAPH.JUSTIFY_MED: "两端对齐",
    WD_ALIGN_PARAGRAPH.JUSTIFY_HI: "两端对齐",
    WD_ALIGN_PARAGRAPH.JUSTIFY_LOW: "两端对齐",
    WD_ALIGN_PARAGRAPH.THAI_JUSTIFY: "两端对齐",
}

_TWIPS_PER_CM = 1440 / 2.54


# --------------------------------------------------------------------------- #
# 数据对象
# --------------------------------------------------------------------------- #


@dataclass
class ParagraphInfo:
    index: int
    text: str
    font_cn: str
    font_en: str
    size: str
    bold: str
    italic: str
    align: str
    first_line_indent: str
    line_spacing: str
    style_name: str

    def line(self) -> str:
        preview = " ".join(self.text.split())[:50]
        if len(self.text.strip()) > 50:
            preview += "…"
        return (
            f"段落 {self.index} | {preview or '(空)'} | "
            f"中:{self.font_cn} 英:{self.font_en} | {self.size} | {self.bold} | {self.italic} | "
            f"{self.align} | 首行缩进:{self.first_line_indent} | 行距:{self.line_spacing} | "
            f"样式:{self.style_name}"
        )


@dataclass
class DocxFingerprint:
    path: str
    total: int
    limit: int
    items: List[ParagraphInfo] = field(default_factory=list)
    style_counts: Dict[str, int] = field(default_factory=dict)

    @property
    def shown(self) -> int:
        return len(self.items)

    @property
    def truncated(self) -> bool:
        return self.total > self.shown

    def lines(self) -> List[str]:
        head = [
            f"# 文档样式指纹：{self.path}",
            f"# 段落总数 {self.total}（已跳过表格 / 页眉页脚 / 文本框），"
            f"共显示 {self.shown} 段，上限 {self.limit}",
            "# 样式分布：" + "、".join(
                f"{name}×{cnt}" for name, cnt in
                sorted(self.style_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ),
        ]
        body = [item.line() for item in self.items]
        if self.truncated:
            body.append(f"[已截断] 全文共 {self.total} 段，仅显示前 {self.shown} 段")
        return head + body

    def to_text(self) -> str:
        return "\n".join(self.lines())

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "total": self.total,
            "shown": self.shown,
            "limit": self.limit,
            "truncated": self.truncated,
            "style_counts": self.style_counts,
            "items": [vars(i) for i in self.items],
        }


# --------------------------------------------------------------------------- #
# 逐级回退的小工具
# --------------------------------------------------------------------------- #


def _style_chain(style) -> List:
    """段落样式 → 基样式 → ... 依次返回。"""
    chain, seen = [], set()
    while style is not None and id(style) not in seen:
        seen.add(id(style))
        chain.append(style)
        style = style.base_style
    return chain


def _first(seq: Iterable, default=None):
    for value in seq:
        if value is not None:
            return value
    return default


def _merge(values: Sequence[str], empty: str = "默认") -> str:
    """把同一段多个 run 的取值合成一个可读字符串。"""
    cleaned = [v for v in values if v]
    if not cleaned:
        return empty
    uniq = list(dict.fromkeys(cleaned))
    if len(uniq) == 1:
        return uniq[0]
    if len(uniq) <= 3:
        return "混排(" + "/".join(uniq) + ")"
    return f"混排({len(uniq)}种)"


def _rfonts(el) -> Optional[object]:
    if el is None:
        return None
    return el.find(qn("w:rFonts"))


def _rpr(el) -> Optional[object]:
    if el is None:
        return None
    if el.tag == qn("w:rPr"):
        return el
    return el.find(qn("w:rPr"))


def _doc_defaults(doc) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {"cn": None, "en": None, "size_pt": None}
    styles_el = doc.styles.element
    dd = styles_el.find(qn("w:docDefaults"))
    if dd is None:
        return out
    rpr = _rpr(dd.find(qn("w:rPrDefault")))
    fonts = _rfonts(rpr)
    if fonts is not None:
        out["cn"] = fonts.get(qn("w:eastAsia"))
        out["en"] = fonts.get(qn("w:ascii")) or fonts.get(qn("w:hAnsi"))
    if rpr is not None:
        sz = rpr.find(qn("w:sz"))
        if sz is not None and sz.get(qn("w:val")):
            out["size_pt"] = int(sz.get(qn("w:val"))) / 2
    return out


def _size_label(pt: Optional[float]) -> Optional[str]:
    if pt is None:
        return None
    name = SIZE_NAMES.get(round(pt * 2))
    return f"{pt:g}pt({name})" if name else f"{pt:g}pt"


# --------------------------------------------------------------------------- #
# 主提取
# --------------------------------------------------------------------------- #


def _has_skipped_ancestor(el) -> bool:
    parent = el.getparent()
    while parent is not None:
        if parent.tag in SKIP_ANCESTORS:
            return True
        parent = parent.getparent()
    return False


def _run_fonts(run) -> tuple[Optional[str], Optional[str]]:
    fonts = _rfonts(_rpr(run._element))
    if fonts is None:
        return None, None
    return fonts.get(qn("w:eastAsia")), (fonts.get(qn("w:ascii")) or fonts.get(qn("w:hAnsi")))


def _style_fonts(chain) -> tuple[Optional[str], Optional[str]]:
    for style in chain:
        fonts = _rfonts(_rpr(style.element))
        if fonts is not None:
            cn = fonts.get(qn("w:eastAsia"))
            en = fonts.get(qn("w:ascii")) or fonts.get(qn("w:hAnsi"))
            if cn or en:
                return cn, en
    return None, None


def _style_size(chain) -> Optional[float]:
    for style in chain:
        size = style.font.size
        if size is not None:
            return size.pt
    return None


def _indent_of(el) -> Optional[str]:
    """从一个 pPr（或样式元素）里读缩进，返回可读串或 None。"""
    if el is None:
        return None
    ppr = el if el.tag == qn("w:pPr") else el.find(qn("w:pPr"))
    if ppr is None:
        return None
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        return None
    chars = ind.get(qn("w:firstLineChars"))
    if chars is not None:
        return f"{int(chars) / 100:g}字符"
    hanging_chars = ind.get(qn("w:hangingChars"))
    if hanging_chars is not None:
        return f"悬挂{int(hanging_chars) / 100:g}字符"
    first_line = ind.get(qn("w:firstLine"))
    if first_line is not None:
        return f"{int(first_line) / _TWIPS_PER_CM:.2f}cm"
    hanging = ind.get(qn("w:hanging"))
    if hanging is not None:
        return f"悬挂{int(hanging) / _TWIPS_PER_CM:.2f}cm"
    return None


def _line_spacing_of(pf) -> Optional[str]:
    if pf is None:
        return None
    rule = pf.line_spacing_rule
    value = pf.line_spacing
    if rule == WD_LINE_SPACING.MULTIPLE and value is not None:
        return f"{float(value):g}倍"
    if rule == WD_LINE_SPACING.EXACTLY and value is not None:
        return f"固定值{value.pt:g}pt"
    if rule == WD_LINE_SPACING.AT_LEAST and value is not None:
        return f"最小值{value.pt:g}pt"
    if rule == WD_LINE_SPACING.SINGLE:
        return "单倍"
    if rule == WD_LINE_SPACING.DOUBLE:
        return "2倍"
    if value is not None:                      # rule 缺失但值在
        try:
            return f"{float(value):g}倍"
        except TypeError:
            return f"{value.pt:g}pt"
    return None


def _extract_paragraph(para: Paragraph, index: int, defaults: Dict[str, Optional[str]]) -> ParagraphInfo:
    chain = _style_chain(para.style)
    runs = [r for r in para.runs if r.text.strip()]

    # 字体
    run_cn = [cn for cn, _ in (_run_fonts(r) for r in runs) if cn]
    run_en = [en for _, en in (_run_fonts(r) for r in runs) if en]
    if run_cn or run_en:
        font_cn, font_en = _merge(run_cn), _merge(run_en)
    else:
        cn, en = _style_fonts(chain)
        font_cn = cn or defaults.get("cn") or "默认"
        font_en = en or defaults.get("en") or "默认"

    # 字号
    sizes = []
    for run in runs:
        if run.font.size is not None:
            sizes.append(_size_label(run.font.size.pt))
    if not sizes:
        style_pt = _style_size(chain)
        if style_pt is not None:
            sizes.append(_size_label(style_pt))
    if not sizes and defaults.get("size_pt"):
        sizes.append(_size_label(defaults["size_pt"]))
    size = _merge(sizes)

    # 加粗 / 斜体
    style_bold = _first([s.font.bold for s in chain], False)
    style_italic = _first([s.font.italic for s in chain], False)
    bold = _merge(["加粗" if (r.bold if r.bold is not None else style_bold) else "常规" for r in runs],
                  empty=("加粗" if style_bold else "常规"))
    italic = _merge(["斜体" if (r.italic if r.italic is not None else style_italic) else "常规" for r in runs],
                    empty=("斜体" if style_italic else "常规"))

    # 对齐
    align_value = para.alignment
    if align_value is None:
        align_value = _first([s.paragraph_format.alignment for s in chain])
    align = _ALIGN_NAMES.get(align_value, "默认")

    # 首行缩进
    indent = _indent_of(para._element)
    if indent is None:
        for style in chain:
            indent = _indent_of(style.element)
            if indent is not None:
                break
    first_line_indent = indent or "无"

    # 行距
    spacing = _line_spacing_of(para.paragraph_format)
    if spacing is None:
        for style in chain:
            spacing = _line_spacing_of(style.paragraph_format)
            if spacing is not None:
                break
    line_spacing = spacing or "默认"

    style_name = para.style.name if para.style is not None else "未知"
    return ParagraphInfo(
        index=index,
        text=para.text,
        font_cn=font_cn,
        font_en=font_en,
        size=size,
        bold=bold,
        italic=italic,
        align=align,
        first_line_indent=first_line_indent,
        line_spacing=line_spacing,
        style_name=style_name,
    )


def extract_fingerprint(path: str | Path, limit: int = DEFAULT_LIMIT) -> DocxFingerprint:
    """提取 .docx 的段落样式指纹。limit=0 表示不截断。"""
    doc = Document(str(path))
    defaults = _doc_defaults(doc)

    paragraphs: List[Paragraph] = []
    for p_el in doc.element.body.iter(qn("w:p")):
        if _has_skipped_ancestor(p_el):
            continue
        paragraphs.append(Paragraph(p_el, doc))

    total = len(paragraphs)
    keep = paragraphs if not limit else paragraphs[:limit]

    items: List[ParagraphInfo] = []
    counts: Dict[str, int] = {}
    for i, para in enumerate(keep, start=1):
        info = _extract_paragraph(para, i, defaults)
        items.append(info)
        counts[info.style_name] = counts.get(info.style_name, 0) + 1

    return DocxFingerprint(
        path=str(path),
        total=total,
        limit=limit or total,
        items=items,
        style_counts=counts,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="提取 .docx 段落样式指纹")
    ap.add_argument("path", help=".docx 文件路径")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="最多输出多少段（0=不限）")
    ap.add_argument("--out", help="把指纹写入该文本文件")
    args = ap.parse_args(argv)

    fp = extract_fingerprint(args.path, limit=args.limit)
    text = fp.to_text()
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"\n[已写入] {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
