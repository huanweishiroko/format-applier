# -*- coding: utf-8 -*-
"""预览弹窗（Phase 3：方案二 —— 按真实输出预览）。

流程（不做任何"预测式"推断，一切以真实处理结果为准）：

    1. ``tempfile.mkdtemp()`` 建临时目录；
    2. ``bridge.process(...)`` 真把目标文档处理到 ``tmp/preview.docx``；
    3. 用 python-docx 读回 ``preview.docx``，提取
         上：标题结构（段落序号 + 样式名 + 文本前 40 字）
         下：前 3 段的字体 / 字号 / 对齐 / 缩进 / 行距
    4. ``bridge.print_rules(preset)`` 拿角色 → 属性映射（中）；
    5. 弹窗展示，底部 [取消] [确认处理]；
    6. 无论成功失败，``shutil.rmtree`` 清理临时目录。
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import customtkinter as ctk

# 导入顺序：**绝对优先**。冻结（PyInstaller）后 app.py 是以 __main__ 直跑的，
# ui/core 都是顶层包，`from ..core import ...` 会越过顶层包报
# "attempted relative import beyond top-level package"；相对形式只留给
# `python -m desktop.app` / 导入 desktop.* 的场景兜底。
try:
    from ui import dialogs as dlg
    from ui import theme as th
    from core import bridge
    from core import config as cfg
except ImportError:  # pragma: no cover - 包内运行时
    from . import dialogs as dlg  # type: ignore
    from . import theme as th  # type: ignore
    from ..core import bridge  # type: ignore
    from ..core import config as cfg  # type: ignore

#: 文本预览截断长度
TEXT_LIMIT = 40

#: 取前几段做"效果"展示
EFFECT_PARAGRAPHS = 3

_EMU_PER_PT = 12700.0
_CHAR_UNITS_PER_PT = 100.0


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #


@dataclass
class ParagraphPreview:
    """一段的现状（全部来自处理后的真实文档）。"""

    index: int
    style: str
    text: str
    font: str = "—"
    size: str = "—"
    bold: bool = False
    align: str = "—"
    first_indent: str = "—"
    left_indent: str = "—"
    line_spacing: str = "—"
    space_before: str = "—"
    space_after: str = "—"

    @property
    def label(self) -> str:
        head = f"#{self.index} · {self.style}"
        return f"{head} · {self.text}" if self.text else f"{head} · （空段）"


@dataclass
class DocxView:
    """一份 .docx 的预览视图。"""

    total: int = 0
    nonempty: int = 0
    headings: List[ParagraphPreview] = field(default_factory=list)
    effects: List[ParagraphPreview] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 读回处理后文档
# --------------------------------------------------------------------------- #

_ALIGN_LABELS = {
    "LEFT": "左对齐", "CENTER": "居中", "RIGHT": "右对齐",
    "JUSTIFY": "两端对齐", "DISTRIBUTE": "分散对齐",
}


def _pt(value) -> str:
    try:
        return f"{float(value.pt):g}pt"
    except Exception:  # noqa: BLE001 - 无值/异常类型一律当"未设置"
        return "—"


def _emu(value) -> str:
    try:
        return f"{float(value) / _EMU_PER_PT:g}pt"
    except Exception:  # noqa: BLE001
        return "—"


def _char_unit(value) -> str:
    try:
        return f"{float(value) / _CHAR_UNITS_PER_PT:g}字符"
    except Exception:  # noqa: BLE001
        return "—"


def _run_font(paragraph) -> Tuple[str, str]:
    """从第一个有字体的 run 里取 (中文字体, 字号pt)。找不到给 "—"。"""
    for run in getattr(paragraph, "runs", []) or []:
        font = getattr(run, "font", None)
        if font is None:
            continue
        name = font.name
        if name:
            return str(name), _pt(font.size)
    return "—", "—"


def _line_spacing(paragraph) -> str:
    pf = getattr(paragraph, "paragraph_format", None)
    if pf is None:
        return "—"
    rule = getattr(pf, "line_spacing_rule", None)
    spacing = getattr(pf, "line_spacing", None)
    rule_name = getattr(rule, "name", "") or str(rule or "")
    if spacing is None:
        return "—"
    try:
        multiple = float(spacing)
        if "MULTIPLE" in rule_name or rule_name in ("ONE_POINT_FIVE", "DOUBLE", "SINGLE"):
            return f"{multiple:g}倍行距"
        if "EXACTLY" in rule_name or "AT_LEAST" in rule_name:
            return f"{'固定值' if 'EXACTLY' in rule_name else '最小值'}{multiple:g}pt"
        return f"{multiple:g}"
    except (TypeError, ValueError):
        return str(spacing)


def _align(paragraph) -> str:
    value = getattr(getattr(paragraph, "alignment", None), "name", None)
    if not value:
        return "—"
    return _ALIGN_LABELS.get(str(value).upper(), str(value))


def describe_paragraph(paragraph, index: int) -> ParagraphPreview:
    """把一段的现状读成 :class:`ParagraphPreview`。"""
    text = (paragraph.text or "").strip()
    shown = text[:TEXT_LIMIT] + ("…" if len(text) > TEXT_LIMIT else "")
    pf = getattr(paragraph, "paragraph_format", None)
    style = getattr(getattr(paragraph, "style", None), "name", "") or "默认"
    name, size = _run_font(paragraph)
    bold = any(bool(getattr(getattr(r, "font", None), "bold", False))
               for r in (getattr(paragraph, "runs", []) or []))
    return ParagraphPreview(
        index=index,
        style=style,
        text=shown,
        font=name,
        size=size,
        bold=bold,
        align=_align(paragraph),
        first_indent=_char_unit(getattr(pf, "first_line_indent", None)) if pf else "—",
        left_indent=_char_unit(getattr(pf, "left_indent", None)) if pf else "—",
        line_spacing=_line_spacing(paragraph),
        space_before=_pt(getattr(pf, "space_before", None)) if pf else "—",
        space_after=_pt(getattr(pf, "space_after", None)) if pf else "—",
    )


def _is_heading(paragraph) -> bool:
    style = (getattr(getattr(paragraph, "style", None), "name", "") or "").lower()
    return ("heading" in style) or ("标题" in style) or ("title" in style)


def read_docx_view(path: Path, effects: int = EFFECT_PARAGRAPHS) -> DocxView:
    """读回一份 .docx，抽标题结构与前 N 段的格式。"""
    from docx import Document

    document = Document(str(path))
    paragraphs = list(document.paragraphs)
    view = DocxView(
        total=len(paragraphs),
        nonempty=sum(1 for p in paragraphs if (p.text or "").strip()),
    )
    for i, para in enumerate(paragraphs):
        if (para.text or "").strip() and _is_heading(para):
            view.headings.append(describe_paragraph(para, i))
    picked = 0
    for i, para in enumerate(paragraphs):
        if not (para.text or "").strip():
            continue
        view.effects.append(describe_paragraph(para, i))
        picked += 1
        if picked >= effects:
            break
    return view


# --------------------------------------------------------------------------- #
# 采一次真实预览
# --------------------------------------------------------------------------- #


def run_preview(target: Path, preset_name: str, presets_dir: Optional[str],
                tmp_dir: Path) -> Tuple[dict, DocxView, dict]:
    """真跑一次处理到临时目录，返回 (摘要, 读回的视图, 规则表)。"""
    out = tmp_dir / "preview.docx"
    summary = bridge.process(
        str(target), preset_name, str(out), presets_dir=presets_dir,
        report_path=str(tmp_dir / "preview.report.json"),
    )
    if not summary.get("ok"):
        raise bridge.BridgeError(summary.get("_error") or "预览处理失败",
                                 returncode=int(summary.get("_returncode") or -1),
                                 stdout=summary.get("_stderr") or "",
                                 argv=summary.get("_argv") or [])
    if not out.is_file():
        raise bridge.BridgeError("预览处理没有产出文件", argv=summary.get("_argv") or [])
    try:
        rules = bridge.print_rules(preset_name, presets_dir)
    except bridge.BridgeError:
        rules = {}
    return summary, read_docx_view(out), rules


# --------------------------------------------------------------------------- #
# 弹窗
# --------------------------------------------------------------------------- #


class PreviewDialog(dlg.ModalWindow):
    """三段式预览：标题结构 / 角色映射 / 前 3 段效果。"""

    def __init__(self, master, target: Path, preset_name: str, summary: dict,
                 view: DocxView, rules: dict, on_confirm: Optional[Callable[[], None]] = None):
        super().__init__(master, f"预览 · {target.name}", (880, 720), resizable=True,
                         icon="👁")
        self.on_confirm = on_confirm
        self._confirmed = False
        self.body.grid_rowconfigure(1, weight=3)
        self.body.grid_rowconfigure(3, weight=2)
        self.body.grid_rowconfigure(5, weight=3)
        self.body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.body,
            text=f"预设「{preset_name}」· 真实输出预览（临时目录中处理，未写入你的输出目录）",
            font=th.font(13, "bold"), anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self._build_headings(view)
        self._build_roles(rules)
        self._build_effects(view)
        self._build_footer(summary)

    # -- 上：标题结构 ---------------------------------------------------- #

    def _build_headings(self, view: DocxView) -> None:
        box = ctk.CTkScrollableFrame(self.body, corner_radius=th.RADIUS, border_width=1,
                                     border_color=th.BORDER, fg_color=th.BG_SURFACE)
        box.grid(row=1, column=0, sticky="nsew")
        box.grid_columnconfigure(0, weight=1)
        title = f"① 标题结构（共 {len(view.headings)} 个标题 / 全文 {view.total} 段，非空 {view.nonempty} 段）"
        th.section_title(box, title).grid(row=0, column=0, sticky="w", padx=th.PAD_S, pady=(th.PAD_S, 2))
        if not view.headings:
            th.hint(box, "处理后没有识别到 Word 标题样式段落（可能这份文档本来就没有标题层级，"
                         "或预设里没有启用结构预处理）。").grid(
                row=1, column=0, sticky="w", padx=th.PAD_S, pady=(0, th.PAD_S))
            return
        for i, para in enumerate(view.headings, start=1):
            ctk.CTkLabel(box, text=f"{para.label}", font=th.font(12), anchor="w",
                         justify="left", wraplength=780).grid(
                row=i, column=0, sticky="ew", padx=th.PAD_S, pady=1)

    # -- 中：角色映射 ---------------------------------------------------- #

    def _build_roles(self, rules: dict) -> None:
        box = ctk.CTkScrollableFrame(self.body, corner_radius=th.RADIUS, border_width=1,
                                     border_color=th.BORDER, fg_color=th.BG_SURFACE)
        box.grid(row=3, column=0, sticky="nsew", pady=(th.PAD_S, 0))
        box.grid_columnconfigure(1, weight=1)
        rows = bridge.role_table(rules)
        head = f"② 预设角色映射（{len(rows)} 个角色"
        if rules:
            head += f" · 规则 {rules.get('rule_count', '?')} 条"
            source = (rules.get("source") or {}).get("parsed_by")
            if source:
                head += f" · 解析方式 {source}"
        head += "）"
        th.section_title(box, head).grid(row=0, column=0, columnspan=2, sticky="w",
                                        padx=th.PAD_S, pady=(th.PAD_S, 2))
        if not rows:
            th.hint(box, "拿不到规则表（--print-rules 未返回角色）。").grid(
                row=1, column=0, columnspan=2, sticky="w", padx=th.PAD_S, pady=(0, th.PAD_S))
            return
        for i, (role, attrs) in enumerate(rows, start=1):
            ctk.CTkLabel(box, text=role, font=th.font(12, "bold"), anchor="w").grid(
                row=i, column=0, sticky="nw", padx=(th.PAD_S, th.PAD_S), pady=1)
            ctk.CTkLabel(box, text=attrs, font=th.font(12), anchor="w", justify="left",
                         wraplength=620).grid(row=i, column=1, sticky="ew", pady=1)
        extras: List[str] = []
        cleanup = bridge.cleanup_labels(rules)
        structure = bridge.structure_labels(rules)
        if cleanup:
            extras.append("清理：" + "、".join(cleanup))
        if structure:
            extras.append("结构预处理：" + "、".join(structure))
        if extras:
            th.hint(box, " | ".join(extras)).grid(
                row=len(rows) + 1, column=0, columnspan=2, sticky="w",
                padx=th.PAD_S, pady=(4, th.PAD_S))

    # -- 下：前 3 段效果 -------------------------------------------------- #

    def _build_effects(self, view: DocxView) -> None:
        box = ctk.CTkScrollableFrame(self.body, corner_radius=th.RADIUS, border_width=1,
                                     border_color=th.BORDER, fg_color=th.BG_SURFACE)
        box.grid(row=5, column=0, sticky="nsew", pady=(th.PAD_S, 0))
        for col, weight in ((0, 2), (1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1)):
            box.grid_columnconfigure(col, weight=weight)
        th.section_title(box, f"③ 前 {len(view.effects)} 段处理后的实际格式").grid(
            row=0, column=0, columnspan=7, sticky="w", padx=th.PAD_S, pady=(th.PAD_S, 2))
        if not view.effects:
            th.hint(box, "文档里没有非空段落。").grid(
                row=1, column=0, columnspan=7, sticky="w", padx=th.PAD_S, pady=(0, th.PAD_S))
            return
        headers = ("段落", "字体", "字号", "字形", "对齐", "首行缩进", "行距")
        for c, text in enumerate(headers):
            ctk.CTkLabel(box, text=text, font=th.font(12, "bold"), anchor="w").grid(
                row=1, column=c, sticky="ew", padx=th.PAD_S, pady=(2, 2))
        for r, para in enumerate(view.effects, start=2):
            cells = (
                f"#{para.index} {para.style}：{para.text}",
                para.font,
                para.size,
                "加粗" if para.bold else "常规",
                para.align,
                para.first_indent,
                para.line_spacing,
            )
            for c, text in enumerate(cells):
                ctk.CTkLabel(
                    box, text=text, font=th.font(12), anchor="w", justify="left",
                    wraplength=300 if c == 0 else 90,
                ).grid(row=r, column=c, sticky="ew", padx=th.PAD_S, pady=2)

    # -- 底部 ------------------------------------------------------------ #

    def _build_footer(self, summary: dict) -> None:
        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.grid(row=6, column=0, sticky="ew", pady=(th.PAD_S, 0))
        bar.grid_columnconfigure(0, weight=1)
        info = (f"试处理：改动 {summary.get('applied', 0)} 段 · 跳过 {summary.get('skipped', 0)} 段 · "
                f"LLM {summary.get('llm_calls', 0)} 次")
        th.hint(bar, info).grid(row=0, column=0, sticky="w")

        def _confirm() -> None:
            self._confirmed = True
            callback = self.on_confirm
            master = self.master
            self.destroy()
            if callback is not None:
                # 弹窗销毁后再触发处理，避免模态窗口与后台线程抢焦点
                try:
                    master.after(80, callback)
                except Exception:  # noqa: BLE001 - 主窗口已关闭时直接同步调用
                    callback()

        th.ghost_button(bar, "取消", self.destroy, width=th.BTN_W_L).grid(row=0, column=1, padx=(0, th.PAD_S))
        th.primary_button(bar, "确认处理", _confirm, width=th.BTN_W_XL).grid(row=0, column=2)


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #


def show_preview(master, file_path: Optional[Path], preset_name: str, output_dir: str = "",
                 presets_dir: Optional[str] = None,
                 on_confirm: Optional[Callable[[], None]] = None,
                 log: Optional[Callable[[str], None]] = None) -> bool:
    """真实输出预览。返回 True 表示用户点了「确认处理」。"""
    logger = log or (lambda _m: None)
    if file_path is None:
        dlg.info(master, "请先选择一个 .docx 文件，再点「预览效果」。", title="还没有文件")
        return False
    if not preset_name:
        dlg.error(master, "请先选择一个格式要求预设。", title="还没有预设")
        return False

    logger(f"预览：临时处理 {file_path.name} → {Path(tempfile.gettempdir()) / 'wfa-preview-*'}")
    tmp_dir = Path(tempfile.mkdtemp(prefix="wfa-preview-"))
    try:
        try:
            summary, view, rules = run_preview(file_path, preset_name, presets_dir, tmp_dir)
        except bridge.BridgeError as exc:
            logger(f"预览失败：{exc}")
            dlg.error(master, str(exc), title="预览失败", detail=exc.detail)
            return False
        except Exception as exc:  # noqa: BLE001 - 坏文档不该弄崩界面
            logger(f"预览失败：{type(exc).__name__}: {exc}")
            dlg.error(master, f"预览失败：{type(exc).__name__}: {exc}", title="预览失败")
            return False

        logger(f"预览就绪：标题 {len(view.headings)} 个 · 角色 {len(bridge.role_table(rules))} 个 · "
               f"改动 {summary.get('applied', 0)} 段")
        dialog = PreviewDialog(master, file_path, preset_name, summary, view, rules,
                               on_confirm=on_confirm)
        dialog.wait_window()
        return bool(getattr(dialog, "_confirmed", False))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger(f"已清理预览临时目录：{tmp_dir}")


def show_placeholder(master) -> None:
    """兼容旧调用：没有文件/预设时的提示。"""
    dlg.info(master, "请先选择文件和预设，再点「预览效果」。", title="预览效果")
