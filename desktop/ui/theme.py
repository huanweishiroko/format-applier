# -*- coding: utf-8 -*-
"""视觉基准：调色板、尺寸刻度、字体与公共控件工厂。

设计约束（改版时定下的三条，改这里之前先读）：
  1. **本文件是唯一的色值来源**。任何页面里都不许再写十六进制或 ``grayXX``；
     需要新颜色就先在这里加一个语义 token（``ACCENT`` / ``TEXT_MUTED`` …），
     再在页面里引用。颜色一律写成 ``(浅色, 深色)`` 二元组，交给 customtkinter
     自己按当前 appearance mode 取用，这样切主题不需要重建界面。
  2. **控件工厂的既有函数名与签名保持稳定**（``card`` / ``hint`` / ``entry`` /
     ``primary_button`` / ``ghost_button`` / ``small_button`` / ``section_title`` /
     ``dashed_border`` / ``bind_drop_target`` / ``parse_drop_event`` …）。
     它们被 8 个页面和弹窗模块调用，签名一变就是连锁故障。视觉升级只改函数体。
  3. **尺寸不许写死在页面里**。间距走 ``SP.*`` 刻度，圆角走 ``RADIUS_*``，
     按钮宽度走 ``BTN_W_*``，控件高度走 ``CTRL_H*``。

配色思路：中性色（近无彩的冷灰）当陪衬，让纯白卡片浮起来；强调色用靛蓝
（同一个蓝里偏紫，比标准蓝安静），副色用橙 —— 靛蓝管主流程，橙管"导入/上传"
这类输入型动作，两者是互补对，同屏不打架。成功/危险/警告各有实色与淡底两档。
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk

# --------------------------------------------------------------------------- #
# 调色板 —— 唯一色源
# --------------------------------------------------------------------------- #
# 每条都是 (浅色, 深色)。深色不是这次的主战场，但设置页有主题开关，
# 只定义浅色会让切过去变成"一半新一半旧"，所以成对给出。
PALETTE = {
    # 背景层：页面底比卡片深一档，卡片是纯白 —— 层次感来自明度差，不靠边框
    "bg_page":        ("#F7F8FA", "#0F1216"),
    "bg_surface":     ("#FFFFFF", "#181C22"),
    "bg_surface_alt": ("#F4F6F8", "#1F242C"),  # 输入框 / 日志框 / 图标泡
    "bg_sidebar":     ("#EFF1F5", "#141922"),
    "bg_statusbar":   ("#FFFFFF", "#12161B"),
    "bg_drop_idle":   ("#FBFCFD", "#171B21"),  # 拖拽区常态（比卡片再亮一档）
    "bg_stripe":      ("#FAFBFC", "#1B2027"),  # 斑马纹行
    "hover_fill":     ("#EDEFF4", "#232A34"),  # 导航/列表 hover 底
    "hover_fill_sub": ("#F2F4F7", "#1E242C"),  # 次级按钮 hover 底

    # 描边
    "border":         ("#E9ECF1", "#262C35"),
    "border_strong":  ("#D8DDE5", "#333B46"),
    "divider":        ("#E4E8EE", "#242A33"),

    # 文字
    "text":           ("#141A21", "#E9EDF3"),
    "text_second":    ("#5B6572", "#A5AEB9"),
    "text_muted":     ("#8A93A0", "#7A828D"),
    "text_on_accent": ("#FFFFFF", "#FFFFFF"),

    # 强调（靛蓝）
    "accent":         ("#4F46E5", "#8B87F5"),
    "accent_hover":   ("#4338CA", "#A5A2F8"),
    "accent_soft":    ("#EEF0FE", "#232441"),  # 选中底 / 徽章底 / 图标泡底
    "accent_text":    ("#4F46E5", "#A5A2F8"),  # 淡底上的强调文字

    # 副强调（橙）：上传 / 导入类动作
    "secondary":      ("#EA7317", "#FF9F45"),
    "secondary_soft": ("#FFF3E8", "#3A2A1A"),
    "secondary_text": ("#B45309", "#FFB86B"),

    # 状态
    "success":        ("#15803D", "#4ADE80"),
    "success_soft":   ("#E8F7EE", "#12301F"),
    "danger":         ("#DC2626", "#FF7B72"),
    "danger_hover":   ("#B91C1C", "#FF9A93"),
    "danger_soft":    ("#FDECEC", "#3A1D1D"),
    "warning":        ("#D97706", "#FBBF24"),
    "warning_soft":   ("#FEF3E2", "#3A2A14"),

    # 拖拽区
    "drop_border_idle":   ("#C4CBD6", "#39414D"),
    "drop_border_active": ("#4F46E5", "#8B87F5"),
    "drop_fill_active":   ("#EEF0FE", "#1B2A45"),
    "drop_border_ok":     ("#2FB344", "#4ADE80"),
    "drop_fill_ok":       ("#E9F9EC", "#14301C"),
    "drop_border_warn":   ("#D97706", "#FBBF24"),

    # 日志等宽区
    "log_bg":         ("#F4F6F8", "#12161B"),
    "log_text":       ("#3A424E", "#B8C0CC"),

    # 滚动条（跟随表面色，不用系统灰）
    "scroll_track":   ("#F2F4F7", "#1B2027"),
    "scroll_thumb":   ("#CFD6DF", "#39414D"),
    "scroll_hover":   ("#B4BECB", "#4B5563"),
}


# --------------------------------------------------------------------------- #
# 语义 token —— 页面只引用这些名字
# --------------------------------------------------------------------------- #
BG_PAGE = PALETTE["bg_page"]
BG_SURFACE = PALETTE["bg_surface"]
BG_SURFACE_ALT = PALETTE["bg_surface_alt"]
BG_SIDEBAR = PALETTE["bg_sidebar"]
BG_STATUSBAR = PALETTE["bg_statusbar"]
BG_STRIPE = PALETTE["bg_stripe"]
HOVER_FILL = PALETTE["hover_fill"]
HOVER_FILL_SUB = PALETTE["hover_fill_sub"]

BORDER = PALETTE["border"]
BORDER_STRONG = PALETTE["border_strong"]
DIVIDER = PALETTE["divider"]

TEXT = PALETTE["text"]
TEXT_SECOND = PALETTE["text_second"]
TEXT_MUTED = PALETTE["text_muted"]
TEXT_ON_ACCENT = PALETTE["text_on_accent"]

ACCENT = PALETTE["accent"]
ACCENT_HOVER = PALETTE["accent_hover"]
ACCENT_SOFT = PALETTE["accent_soft"]
ACCENT_TEXT = PALETTE["accent_text"]

SECONDARY = PALETTE["secondary"]
SECONDARY_SOFT = PALETTE["secondary_soft"]
SECONDARY_TEXT = PALETTE["secondary_text"]

SUCCESS = PALETTE["success"]
SUCCESS_SOFT = PALETTE["success_soft"]
DANGER = PALETTE["danger"]
DANGER_HOVER = PALETTE["danger_hover"]
DANGER_SOFT = PALETTE["danger_soft"]
WARNING = PALETTE["warning"]
WARNING_SOFT = PALETTE["warning_soft"]

DROP_BORDER_IDLE = PALETTE["drop_border_idle"]
DROP_BORDER_ACTIVE = PALETTE["drop_border_active"]
DROP_FILL_ACTIVE = PALETTE["drop_fill_active"]
DROP_FILL_OK = PALETTE["drop_fill_ok"]
DROP_BORDER_OK = PALETTE["drop_border_ok"]
DROP_FILL_IDLE = PALETTE["bg_drop_idle"]
DROP_BORDER_WARN = PALETTE["drop_border_warn"]

LOG_BG = PALETTE["log_bg"]
LOG_TEXT = PALETTE["log_text"]

SCROLL_TRACK = PALETTE["scroll_track"]
SCROLL_THUMB = PALETTE["scroll_thumb"]
SCROLL_HOVER = PALETTE["scroll_hover"]

TRANSPARENT = "transparent"  # customtkinter 专用关键字，不是颜色


def C(token) -> str:
    """把 token 或 ``(浅, 深)`` 二元组解成"当前主题下的单色"。

    只在必须单色的场合用（``tk.Canvas`` 的 ``itemconfigure``、
    ``CTkFrame._canvas`` 的 ``bg``）—— 这些底层画布不吃二元组。
    """
    value = PALETTE.get(token, token) if isinstance(token, str) else token
    if isinstance(value, (tuple, list)):
        return value[0] if ctk.get_appearance_mode() == "Light" else value[1]
    return str(value)


def is_light() -> bool:
    return ctk.get_appearance_mode() == "Light"


def apply_root_theme(root: tk.Misc) -> None:
    """把窗口底色统一到主题（customtkinter 的根窗口默认是灰的，会透边）。"""
    try:
        root.configure(fg_color=BG_PAGE)
    except Exception:  # noqa: BLE001 - 某些 tk 实现下根窗口不吃 fg_color
        pass


# --------------------------------------------------------------------------- #
# 尺寸刻度
# --------------------------------------------------------------------------- #
class SP:
    """间距刻度（4 的倍数为主，避免页面上出现 2/3/5 这种随手数字）。"""

    XXS = 2
    XS = 4
    S = 8
    M = 12
    L = 16
    XL = 20
    XXL = 24
    XXXL = 28
    HUGE = 32


class FS:
    """字号刻度。"""

    CAPTION = 11
    SMALL = 12
    BODY = 13
    LEAD = 14
    H3 = 15
    H2 = 22
    H1 = 26
    HERO = 30
    ICON = 24


# 圆角
RADIUS_S = 6      # 徽章 / 小按钮
RADIUS = 8        # 输入框 / 按钮
RADIUS_L = 12     # 卡片
RADIUS_XL = 16    # 拖拽区 / 弹窗面板
RADIUS_PILL = 999  # 胶囊（customtkinter 会按实际高度收敛）

# 控件高度
CTRL_H_S = 28
CTRL_H = 34       # 输入框 / 次级按钮
CTRL_H_L = 40     # 主按钮 / 导航项

# 按钮宽度（原先散落着 84/88/90/100/110/120 六种，收敛成两档 + 两个窄档）
BTN_W_S = 56      # 行内窄按钮（浏览、清空）
BTN_W_M = 72      # 工具条小按钮
BTN_W_L = 88      # 弹窗底部按钮
BTN_W_XL = 110    # 主操作按钮

# 内容区与卡片内边距
PAGE_PAD_X = SP.XXXL   # 内容区左右留白
PAGE_PAD_Y = SP.XXL    # 内容区上下留白
CARD_PAD = SP.L        # 卡片内边距

# 布局
SIDEBAR_WIDTH = 210
SIDEBAR_ITEM_H = CTRL_H_L
SIDEBAR_ACCENT_W = 4   # 选中态左侧强调竖条宽度
STATUSBAR_HEIGHT = 26

# --------------------------------------------------------------------------- #
# 兼容旧名（各页面仍在引用；语义与刻度对齐后逐步替换）
# --------------------------------------------------------------------------- #
PAD = SP.L          # 16
PAD_S = SP.S        # 8
PAD_L = SP.XL       # 20（原 22，对齐到 4 的倍数）

STATUS_TEXT = "就绪"
LOG_FONT_SIZE = FS.SMALL

#: 导航项：(key, 显示名, 图标字符)
NAV_ITEMS = (
    ("home", "首页", "🏠"),
    ("presets", "预设管理", "📋"),
    ("settings", "设置", "⚙"),
    ("about", "关于", "ℹ"),
)


# --------------------------------------------------------------------------- #
# 字体
# --------------------------------------------------------------------------- #

FONT_FAMILY = "Microsoft YaHei UI"  # 微软雅黑（UI 变体，回落到 Microsoft YaHei）
FONT_FALLBACK = "Microsoft YaHei"
MONO_FAMILY = "Consolas"            # 本机系统字体；Tk 会自动回落到等宽替代
MONO_FALLBACK = "Courier New"


def resolve_family(root: Optional[tk.Misc] = None) -> str:
    """确认本机有微软雅黑，否则回落到 TkDefaultFont 的家族。"""
    try:
        families = set(tk.font.families(root))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - tkinter 字体查询失败不影响启动
        return FONT_FAMILY
    for name in (FONT_FAMILY, FONT_FALLBACK):
        if name in families:
            return name
    try:
        return tk.font.nametofont("TkDefaultFont").actual("family")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return FONT_FAMILY


_FAMILY_CACHE: dict = {}


def family() -> str:
    if "name" not in _FAMILY_CACHE:
        _FAMILY_CACHE["name"] = resolve_family()
    return _FAMILY_CACHE["name"]


def resolve_mono(root: Optional[tk.Misc] = None) -> str:
    """等宽家族（日志、路径、命令）。不引入字体文件，只用系统已装的。"""
    try:
        families = set(tk.font.families(root))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return MONO_FAMILY
    for name in (MONO_FAMILY, MONO_FALLBACK):
        if name in families:
            return name
    return MONO_FAMILY


def font(size: int = FS.BODY, weight: str = "normal") -> ctk.CTkFont:
    """统一字体工厂。"""
    return ctk.CTkFont(family=family(), size=size, weight=weight)


def mono_font(size: int = FS.SMALL, weight: str = "normal") -> ctk.CTkFont:
    """等宽字体工厂 —— 替代四处硬写的 ``CTkFont(family="Consolas", ...)``。"""
    if "mono" not in _FAMILY_CACHE:
        _FAMILY_CACHE["mono"] = resolve_mono()
    return ctk.CTkFont(family=_FAMILY_CACHE["mono"], size=size, weight=weight)


# --------------------------------------------------------------------------- #
# 控件工厂
# --------------------------------------------------------------------------- #


def card(master, **kwargs) -> ctk.CTkFrame:
    """圆角卡片容器：纯白面 + 极浅描边（层次来自与页面底的明度差）。"""
    opts = dict(
        corner_radius=RADIUS_L,
        fg_color=BG_SURFACE,
        border_width=1,
        border_color=BORDER,
    )
    opts.update(kwargs)
    return ctk.CTkFrame(master, **opts)


def plain(master, **kwargs) -> ctk.CTkFrame:
    """透明排版层（行 / 栏），原先各页面手写的 ``CTkFrame(fg_color="transparent")``。"""
    opts = dict(fg_color=TRANSPARENT)
    opts.update(kwargs)
    return ctk.CTkFrame(master, **opts)


def divider(master, **kwargs) -> ctk.CTkFrame:
    """1px 分隔线。"""
    opts = dict(height=1, fg_color=DIVIDER)
    opts.update(kwargs)
    return ctk.CTkFrame(master, **opts)


def section_title(master, text: str, **kwargs) -> ctk.CTkLabel:
    opts = dict(font=font(FS.LEAD, "bold"), anchor="w", text_color=TEXT)
    opts.update(kwargs)
    return ctk.CTkLabel(master, text=text, **opts)


def page_title(master, text: str, **kwargs) -> ctk.CTkLabel:
    """页面主标题（H1）。"""
    opts = dict(font=font(FS.H1, "bold"), anchor="w", text_color=TEXT)
    opts.update(kwargs)
    return ctk.CTkLabel(master, text=text, **opts)


def hint(master, text: str, **kwargs) -> ctk.CTkLabel:
    """次要说明文字（小一号字 + 次文字色）。"""
    opts = dict(
        font=font(FS.SMALL),
        anchor="w",
        justify="left",
        text_color=TEXT_MUTED,
    )
    opts.update(kwargs)
    return ctk.CTkLabel(master, text=text, **opts)


#: 徽章色调 → (底色, 文字色)
TONE_COLORS = {
    "accent": (ACCENT_SOFT, ACCENT_TEXT),
    "secondary": (SECONDARY_SOFT, SECONDARY_TEXT),
    "success": (SUCCESS_SOFT, SUCCESS),
    "danger": (DANGER_SOFT, DANGER),
    "warning": (WARNING_SOFT, WARNING),
    "muted": (BG_SURFACE_ALT, TEXT_MUTED),
}


def tone_colors(tone: str):
    """取某个语义色调的 ``(底色, 文字色)``。"""
    return TONE_COLORS.get(tone, TONE_COLORS["accent"])


def badge(master, text: str, tone: str = "accent", **kwargs) -> ctk.CTkLabel:
    """胶囊标签：内置/用户、已配置/未配置、成功/失败。

    ``tone`` 见 ``TONE_COLORS``。CTkLabel 没有 padding 参数，
    留白用半角空格撑出来（徽章文字都是短的，够用且不会错位）。
    """
    fg, fg_text = tone_colors(tone)
    opts = dict(
        font=font(FS.CAPTION, "bold"),
        text_color=fg_text,
        fg_color=fg,
        corner_radius=RADIUS_S,
        text=f"\u2002{text}\u2002",  # EN SPACE 两侧留白
    )
    opts.update(kwargs)
    return ctk.CTkLabel(master, **opts)


def icon_bubble(master, glyph: str, tone: str = "accent", size: int = 40, **kwargs):
    """图标泡：一个圆角方块里放一个字符（弹窗头部、空状态）。

    返回容器 Frame，调用点只需要 ``.grid()``。
    """
    fg, fg_text = tone_colors(tone)
    opts = dict(corner_radius=RADIUS, fg_color=fg, width=size, height=size)
    opts.update(kwargs)
    box = ctk.CTkFrame(master, **opts)
    box.grid_propagate(False)
    box.grid_rowconfigure(0, weight=1)
    box.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(
        box, text=glyph, font=font(int(size * 0.5), "bold"), text_color=fg_text
    ).grid(row=0, column=0)
    return box


def primary_button(master, text: str, command: Callable[[], None],
                   danger: bool = False, **kwargs) -> ctk.CTkButton:
    """主操作按钮：实心强调色。``danger=True`` 时换成危险红（删除类确认）。"""
    opts = dict(
        font=font(FS.LEAD, "bold"),
        height=CTRL_H_L,
        corner_radius=RADIUS,
        fg_color=DANGER if danger else ACCENT,
        hover_color=DANGER_HOVER if danger else ACCENT_HOVER,
        text_color=TEXT_ON_ACCENT,
        width=BTN_W_XL,
    )
    opts.update(kwargs)
    return ctk.CTkButton(master, text=text, command=command, **opts)


def ghost_button(master, text: str, command: Callable[[], None],
                 width: Optional[int] = None, **kwargs) -> ctk.CTkButton:
    """次要按钮：透明填充 + 细描边，hover 才浮出底色。

    ``width`` 显式给出才固定宽度；不传则继承 CTk 的默认宽度逻辑，
    这样调用点写 ``grid(sticky="ew")`` 时按钮仍能横向拉伸（旧页面依赖这一点）。
    """
    opts = dict(
        font=font(FS.BODY),
        height=CTRL_H,
        corner_radius=RADIUS,
        fg_color=TRANSPARENT,
        hover_color=HOVER_FILL_SUB,
        border_width=1,
        border_color=BORDER_STRONG,
        text_color=TEXT_SECOND,
    )
    opts.update(kwargs)
    if width is not None:
        opts["width"] = width
    return ctk.CTkButton(master, text=text, command=command, **opts)


def text_button(master, text: str, command: Callable[[], None], **kwargs) -> ctk.CTkButton:
    """纯文字按钮：无填充无边框，hover 只轻微着色（列表行内操作用）。"""
    opts = dict(
        font=font(FS.SMALL),
        height=CTRL_H_S,
        corner_radius=RADIUS_S,
        fg_color=TRANSPARENT,
        hover_color=HOVER_FILL,
        text_color=TEXT_SECOND,
    )
    opts.update(kwargs)
    return ctk.CTkButton(master, text=text, command=command, **opts)


def small_button(master, text: str, command: Callable[[], None], **kwargs) -> ctk.CTkButton:
    """行内小按钮（保留旧名，改为无边框文字型，行内不再被色块打散）。"""
    opts = dict(width=BTN_W_S, height=CTRL_H_S, corner_radius=RADIUS_S)
    opts.update(kwargs)
    return text_button(master, text, command, **opts)


def entry(master, textvariable=None, **kwargs) -> ctk.CTkEntry:
    opts = dict(
        font=font(FS.BODY),
        height=CTRL_H,
        corner_radius=RADIUS,
        border_width=1,
        border_color=BORDER_STRONG,
        fg_color=BG_SURFACE,
        text_color=TEXT,
        placeholder_text_color=TEXT_MUTED,
    )
    opts.update(kwargs)
    if textvariable is not None:
        return ctk.CTkEntry(master, textvariable=textvariable, **opts)
    return ctk.CTkEntry(master, **opts)


def textbox(master, mono: bool = False, **kwargs) -> ctk.CTkTextbox:
    """只读/可编辑文本框：浅底 + 细描边，等宽可选。"""
    opts = dict(
        font=mono_font(FS.SMALL) if mono else font(FS.BODY),
        corner_radius=RADIUS,
        border_width=1,
        border_color=BORDER,
        fg_color=BG_SURFACE_ALT,
        text_color=LOG_TEXT if mono else TEXT,
    )
    opts.update(kwargs)
    return ctk.CTkTextbox(master, **opts)


def combo(master, values, variable=None, **kwargs) -> ctk.CTkComboBox:
    opts = dict(
        font=font(FS.BODY),
        dropdown_font=font(FS.BODY),
        height=CTRL_H,
        corner_radius=RADIUS,
        border_width=1,
        border_color=BORDER_STRONG,
        fg_color=BG_SURFACE,
        button_color=BG_SURFACE_ALT,
        button_hover_color=HOVER_FILL,
        text_color=TEXT,
        dropdown_fg_color=BG_SURFACE,
        dropdown_hover_color=ACCENT_SOFT,
        dropdown_text_color=TEXT,
        state="readonly",
    )
    opts.update(kwargs)
    if variable is not None:
        return ctk.CTkComboBox(master, values=values, variable=variable, **opts)
    return ctk.CTkComboBox(master, values=values, **opts)


def segmented(master, values, variable=None, command=None, **kwargs) -> ctk.CTkSegmentedButton:
    opts = dict(
        font=font(FS.BODY),
        height=CTRL_H,
        corner_radius=RADIUS,
        fg_color=BG_SURFACE_ALT,
        selected_color=ACCENT,
        selected_hover_color=ACCENT_HOVER,
        unselected_color=BG_SURFACE_ALT,
        unselected_hover_color=HOVER_FILL,
        text_color=TEXT_ON_ACCENT,
        text_color_disabled=TEXT_MUTED,
    )
    opts.update(kwargs)
    if variable is not None:
        return ctk.CTkSegmentedButton(master, values=values, variable=variable,
                                      command=command, **opts)
    return ctk.CTkSegmentedButton(master, values=values, command=command, **opts)


def progress(master, **kwargs) -> ctk.CTkProgressBar:
    opts = dict(
        height=6,
        corner_radius=3,
        fg_color=BG_SURFACE_ALT,
        progress_color=ACCENT,
        border_width=0,
    )
    opts.update(kwargs)
    bar = ctk.CTkProgressBar(master, **opts)
    bar.set(0)
    return bar


def scroll(master, page_level: bool = True, **kwargs) -> ctk.CTkScrollableFrame:
    """滚动容器。``page_level=True`` 用于整页（无边框），否则用于列表/表格（有边框）。

    滚动条也在这里收口 —— CTkScrollableFrame 会把滚动条参数透传给内部
    CTkScrollbar，不写就是出厂灰，和调色板不搭。
    """
    if page_level:
        opts = dict(corner_radius=0, fg_color=TRANSPARENT)
    else:
        opts = dict(corner_radius=RADIUS_L, border_width=1,
                    border_color=BORDER, fg_color=BG_SURFACE)
    opts.update(dict(
        scrollbar_fg_color=SCROLL_TRACK,
        scrollbar_button_color=SCROLL_THUMB,
        scrollbar_button_hover_color=SCROLL_HOVER,
    ))
    opts.update(kwargs)
    return ctk.CTkScrollableFrame(master, **opts)


# --------------------------------------------------------------------------- #
# 手绘：拖拽区虚线框
# --------------------------------------------------------------------------- #


def dashed_border(canvas: tk.Canvas, width: int, height: int, gap: int = 7,
                  color: str = "#C4CBD6", line_width: int = 1) -> None:
    """在 canvas 上画一圈虚线矩形（跨平台，不依赖 Tk 的 dash 支持差异）。

    ``gap`` 是每段实线的长度，``line_width`` 是线宽（拖拽悬停时会加粗）。
    颜色由调用方从 ``DROP_BORDER_*`` 取单色传入。
    """
    canvas.delete("dashborder")
    for x in range(0, width, gap * 2):
        x2 = min(x + gap, width)
        canvas.create_line(x, 0, x2, 0, fill=color, width=line_width,
                           tags=("dashborder", "_dnd_border"))
        canvas.create_line(x, height, x2, height, fill=color, width=line_width,
                           tags=("dashborder", "_dnd_border"))
    for y in range(0, height, gap * 2):
        y2 = min(y + gap, height)
        canvas.create_line(0, y, 0, y2, fill=color, width=line_width,
                           tags=("dashborder", "_dnd_border"))
        canvas.create_line(width, y, width, y2, fill=color, width=line_width,
                           tags=("dashborder", "_dnd_border"))


LAST_REGISTERED_COUNT = 0  # 上一次 bind_drop_target 成功注册的控件数（诊断用）


def _collect_widgets(root: tk.Misc) -> list:
    """收集 root 子树里的**真** tkinter 控件（含自定义控件内部的 canvas）。

    customtkinter 的复合控件（CTkFrame/CTkLabel/CTkButton）本体是普通 Frame，
    真正的绘制面是它自己的 ``_canvas``；两者都是独立的 tk 窗口（各自有 HWND）。
    """
    found = []
    seen = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        found.append(node)
        for attr in ("_canvas", "_parent_canvas"):  # CTk 内部画布
            canvas = getattr(node, attr, None)
            if canvas is not None and isinstance(canvas, tk.Misc):
                found.append(canvas)
        try:
            stack.extend(node.winfo_children())
        except tk.TclError:
            pass
    return found


def bind_drop_target(widget: ctk.CTkBaseClass, on_drop: Callable[[list], None]) -> bool:
    """给一个区域注册文件拖放，返回是否有控件注册成功。

    Phase 4 定位：tkdnd 在 Windows 上是**按控件（HWND）逐个**调 OLE 的
    ``RegisterDragDrop`` 的（tkdnd.tcl: ``_RegisterDragDrop $path``）。而
    customtkinter 的复合控件里，光标实际落在的是 CTk 内部的 Frame / Canvas / Label，
    它们是外层控件 ``_canvas`` 的**兄弟节点**，不是它的子节点。

    旧实现只注册了外层控件的 ``_canvas`` 这一个 HWND：拖拽区里几乎所有像素
    命中的都是没注册过的兄弟控件，OLE 自然拒绝（鼠标显示禁止光标）。
    实测（ole32!RevokeDragDrop 反查）：旧实现下拖拽区里除 ``_canvas`` 外的控件
    HWND 全部 ``E_NOTREGISTERED``。

    这里改为把整棵子树的每个真控件（含 CTk 内部 canvas）都注册一遍：
    无论光标落在区域内哪个像素，命中的控件本身就是已注册的 OLE drop target。
    重复调用是幂等的（同一个 HWND 再注册一次仍然成功）。
    """
    try:
        from tkinterdnd2 import DND_FILES  # noqa: WPS433 - 可选依赖，延迟导入
    except ImportError:
        return False

    global LAST_REGISTERED_COUNT

    ok = 0
    for node in _collect_widgets(widget):
        register = getattr(node, "drop_target_register", None)
        bind = getattr(node, "dnd_bind", None)
        if register is None or bind is None:
            continue  # tkinterdnd2 未注入（例如未 import）的控件
        try:
            register(DND_FILES)
            bind("<<Drop>>", on_drop)
            ok += 1
        except tk.TclError:
            continue
    LAST_REGISTERED_COUNT = ok  # 诊断用；注册数 0 即"整个区域都收不到拖放"
    return ok > 0


def last_registered_count() -> int:
    """上一次 bind_drop_target 成功注册的控件数（诊断用）。"""
    return LAST_REGISTERED_COUNT


def parse_drop_event(event) -> list:
    """把 <<Drop>> 事件的 data 解析成路径列表（Tk 的花括号转义在此处理）。"""
    data = getattr(event, "data", "") or ""
    try:
        parts = event.widget.tk.splitlist(data)  # type: ignore[attr-defined]
        return [str(p) for p in parts if str(p).strip()]
    except Exception:  # noqa: BLE001 - 极少数 tk 版本没有 splitlist
        cleaned = data.replace("{", "").replace("}", "")
        return [p for p in cleaned.split() if p.strip()]
