"""Regenerate the shipped presets and samples (development helper, not shipped logic).

::

    python tools/make_samples.py

Idempotent: it rebuilds ``presets/格式要求*.docx``, ``presets/格式要求3.txt``,
``samples/target.docx`` and ``samples/format.docx`` from scratch so the repository
always carries a working example set. New presets never need code changes -
just drop a ``.docx``/``.txt``/``.md`` file into ``presets/``.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

import docx  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt  # noqa: E402

PRESETS = os.path.join(ROOT, "presets")
SAMPLES = os.path.join(ROOT, "samples")
CACHE = os.path.join(PRESETS, ".cache")


def set_font(run, ascii_font: str, eastasia: str, size_pt: float,
             bold: bool = False, color: str | None = None) -> None:
    run.font.name = ascii_font
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), ascii_font)
    rfonts.set(qn("w:hAnsi"), ascii_font)
    rfonts.set(qn("w:eastAsia"), eastasia)
    if color:
        from docx.shared import RGBColor

        run.font.color.rgb = RGBColor.from_string(color)


def style_paragraph(paragraph, ascii_font, eastasia, size_pt, bold=False,
                    align=None, line_spacing=None, first_line_chars=None,
                    space_before=None, space_after=None, color=None) -> None:
    for run in paragraph.runs:
        set_font(run, ascii_font, eastasia, size_pt, bold, color)
    if align is not None:
        paragraph.alignment = align
    fmt = paragraph.paragraph_format
    if line_spacing is not None:
        fmt.line_spacing = line_spacing
    if first_line_chars is not None:
        fmt.first_line_indent = Pt(first_line_chars * 12.0)
    if space_before is not None:
        fmt.space_before = Pt(space_before)
    if space_after is not None:
        fmt.space_after = Pt(space_after)


def build_preset_one(path: str) -> None:
    """Preset 1: Chinese official-document style (宋体/黑体, 首行缩进2字符, 1.5倍行距)."""
    document = docx.Document()
    document.styles["Normal"].font.name = "Times New Roman"
    document.styles["Normal"].font.size = Pt(12)
    section = document.sections[0]
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.17)
    section.right_margin = Cm(3.17)

    title = document.add_paragraph("文档标题样式示例", style="Title")
    style_paragraph(title, "Times New Roman", "方正小标宋简体", 22, bold=True,
                    align=WD_ALIGN_PARAGRAPH.CENTER, line_spacing=1.5,
                    space_before=0, space_after=18)

    for level, size in ((1, 16), (2, 14), (3, 12)):
        heading = document.add_paragraph("第 %d 级标题样式示例" % level, style="Heading %d" % level)
        style_paragraph(heading, "Times New Roman", "黑体", size, bold=True,
                        align=WD_ALIGN_PARAGRAPH.LEFT, line_spacing=1.5,
                        space_before=12, space_after=6)

    body = document.add_paragraph("正文段落样式示例。正文使用宋体小四，行距 1.5 倍，首行缩进 2 字符，两端对齐。")
    style_paragraph(body, "Times New Roman", "宋体", 12, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                    line_spacing=1.5, first_line_chars=2, space_before=0, space_after=0)

    quote = document.add_paragraph("引用段落样式示例。", style="Quote")
    style_paragraph(quote, "Times New Roman", "楷体", 12, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                    line_spacing=1.5, first_line_chars=2)

    caption = document.add_paragraph("图 1 题注样式示例", style="Caption")
    style_paragraph(caption, "Times New Roman", "黑体", 10.5, align=WD_ALIGN_PARAGRAPH.CENTER,
                    line_spacing=1.0)

    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "表头示例"
    table.cell(0, 1).text = "数值"
    for cell in table.rows[0].cells:
        for paragraph in cell.paragraphs:
            style_paragraph(paragraph, "Times New Roman", "宋体", 10.5,
                            align=WD_ALIGN_PARAGRAPH.CENTER, line_spacing=1.0)

    document.save(path)


def build_preset_two(path: str) -> None:
    """Preset 2: sans-serif screen-reading style (微软雅黑, 单倍行距, 无缩进)."""
    document = docx.Document()
    document.styles["Normal"].font.name = "Segoe UI"
    document.styles["Normal"].font.size = Pt(11)
    section = document.sections[0]
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

    title = document.add_paragraph("标题样式示例", style="Title")
    style_paragraph(title, "Segoe UI", "微软雅黑", 20, bold=True,
                    align=WD_ALIGN_PARAGRAPH.LEFT, line_spacing=1.15, space_after=10)

    for level, size in ((1, 15), (2, 13), (3, 11.5)):
        heading = document.add_paragraph("Heading %d sample" % level, style="Heading %d" % level)
        style_paragraph(heading, "Segoe UI", "微软雅黑", size, bold=True,
                        align=WD_ALIGN_PARAGRAPH.LEFT, line_spacing=1.15,
                        space_before=10, space_after=4, color="1F4E79")

    body = document.add_paragraph("Body paragraph sample with single line spacing and no indent.")
    style_paragraph(body, "Segoe UI", "微软雅黑", 11, align=WD_ALIGN_PARAGRAPH.LEFT,
                    line_spacing=1.15, first_line_chars=0, space_after=6)

    quote = document.add_paragraph("Quote sample.", style="Quote")
    style_paragraph(quote, "Segoe UI", "微软雅黑", 11, align=WD_ALIGN_PARAGRAPH.LEFT,
                    line_spacing=1.15, first_line_chars=0)

    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Header"
    table.cell(0, 1).text = "Value"
    for cell in table.rows[0].cells:
        for paragraph in cell.paragraphs:
            style_paragraph(paragraph, "Segoe UI", "微软雅黑", 10,
                            align=WD_ALIGN_PARAGRAPH.LEFT, line_spacing=1.15)

    document.save(path)


PRESET_THREE_TEXT = """# 格式要求3（纯文本预设，零 LLM 即可解析）

标题：黑体 二号 居中 段后18磅
标题1：黑体 三号 加粗 左对齐 段前12磅 段后6磅
标题2：黑体 四号 加粗 左对齐 段前6磅 段后3磅
正文：宋体 小四 1.5倍行距 首行缩进2字符 两端对齐
引用：楷体 小四 首行缩进2字符
题注：黑体 五号 居中
表格文字：宋体 五号 居中
"""


def build_target(path: str) -> None:
    """A deliberately 'unformatted' target document."""
    document = docx.Document()
    document.styles["Normal"].font.name = "Calibri"
    document.styles["Normal"].font.size = Pt(11)

    document.add_paragraph("2026 年度工作总结报告", style="Title")
    document.add_paragraph("第一部分 总体情况", style="Heading 1")
    document.add_paragraph("本年度整体运行平稳，各项核心指标均达到既定目标，收入同比增长百分之十二。")
    document.add_paragraph("团队规模保持稳定，交付节奏与前一年基本一致，客户满意度有所提升。")
    document.add_paragraph("第二部分 重点工作", style="Heading 1")
    document.add_paragraph("一是完成平台迁移；二是完成安全加固；三是建立常态化巡检机制。")
    document.add_paragraph("引用：数据说明一切。", style="Quote")
    document.add_paragraph("表 1 关键指标", style="Caption")
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "指标"
    table.cell(0, 1).text = "数值"
    table.cell(1, 0).text = "营业收入"
    table.cell(1, 1).text = "1200 万元"
    table.cell(2, 0).text = "客户满意度"
    table.cell(2, 1).text = "96%"
    document.save(path)


def main() -> int:
    os.makedirs(PRESETS, exist_ok=True)
    os.makedirs(SAMPLES, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)

    build_preset_one(os.path.join(PRESETS, "格式要求1.docx"))
    build_preset_two(os.path.join(PRESETS, "格式要求2.docx"))
    with open(os.path.join(PRESETS, "格式要求3.txt"), "w", encoding="utf-8") as handle:
        handle.write(PRESET_THREE_TEXT)

    build_preset_one(os.path.join(SAMPLES, "format.docx"))
    build_target(os.path.join(SAMPLES, "target.docx"))
    build_target(os.path.join(SAMPLES, "我的目标文档.docx"))

    print("presets: 格式要求1.docx, 格式要求2.docx, 格式要求3.txt")
    print("samples: target.docx, 我的目标文档.docx, format.docx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
