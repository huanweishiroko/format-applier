# -*- coding: utf-8 -*-
"""主题引擎：调色板、皮肤、尺寸刻度、字体与公共控件工厂。

设计约束（改版时定下的四条，改这里之前先读）：
  1. **本文件是唯一的色值来源**。任何页面里都不许再写十六进制或 ``grayXX``；
     需要新颜色就先在这里加一个语义 token（``ACCENT`` / ``TEXT_MUTED`` …），
     再在页面里引用。赛博黑是 dark-only，41 个 token 都写成 ``(hex, hex)``。
  2. **控件工厂的既有函数名与签名保持稳定**（``card`` / ``hint`` / ``entry`` /
     ``primary_button`` / ``ghost_button`` / ``small_button`` / ``section_title`` /
     ``dashed_border`` / ``bind_drop_target`` / ``parse_drop_event`` …）。
     它们被所有页面和弹窗模块调用，签名一变就是连锁故障。视觉升级只改函数体。
  3. **尺寸不许写死在页面里**。间距走 ``SP.*`` 刻度，圆角走 ``RADIUS_*``，
     按钮宽度走 ``BTN_W_*``，控件高度走 ``CTRL_H*``。
  4. **单皮肤**。当前只保留 ``cyber_noir``，固定深色；不做运行时换肤。

圆角用一个 ``Radius(int)`` 子类携带角色名。CTk 会把这个对象原样保存在
``corner_radius`` 里；赛博黑只用 S/M/L/XL 四档，不再有胶囊圆角。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional, Tuple

import customtkinter as ctk

# --------------------------------------------------------------------------- #
# 主题数据结构
# --------------------------------------------------------------------------- #

#: 41 个语义颜色 token。任何皮肤都必须完整提供，换肤映射也按这个顺序建立。
COLOR_TOKENS: Tuple[str, ...] = (
    "bg_page",
    "bg_surface",
    "bg_surface_alt",
    "bg_sidebar",
    "bg_statusbar",
    "bg_drop_idle",
    "bg_stripe",
    "hover_fill",
    "hover_fill_sub",
    "border",
    "border_strong",
    "divider",
    "text",
    "text_second",
    "text_muted",
    "text_on_accent",
    "accent",
    "accent_hover",
    "accent_soft",
    "accent_text",
    "secondary",
    "secondary_soft",
    "secondary_text",
    "success",
    "success_soft",
    "danger",
    "danger_hover",
    "danger_soft",
    "warning",
    "warning_soft",
    "drop_border_idle",
    "drop_border_active",
    "drop_fill_active",
    "drop_border_ok",
    "drop_fill_ok",
    "drop_border_warn",
    "log_bg",
    "log_text",
    "scroll_track",
    "scroll_thumb",
    "scroll_hover",
)


class Radius(int):
    """带角色名的圆角整数。

    CTk 内部把 ``corner_radius`` 原样保存，不做 ``int()`` 强转；因此这个
    子类能把 ``sm / md / lg / xl`` 的角色一路带到重绘阶段。
    """

    def __new__(cls, value: int, role: str):
        obj = super().__new__(cls, int(value))
        obj.role = role
        return obj


@dataclass(frozen=True)
class Skin:
    """一套皮肤：颜色、圆角与字体。"""

    key: str
    label: str
    description: str
    recommended_mode: str
    colors: Dict[str, Tuple[str, str]]
    radii: Dict[str, int]
    font_ui: str
    font_display: str
    font_mono: str

    def color(self, token: str) -> Tuple[str, str]:
        return self.colors[token]

    def radius(self, role: str) -> Radius:
        return Radius(self.radii[role], role)


# --------------------------------------------------------------------------- #
# 唯一皮肤
# --------------------------------------------------------------------------- #
# 约束：除下面三组语义别名外，同一套皮肤内不允许出现两条完全相同的色对。
# validate_skins() 会检查这一点，测试也会跑。

def _dark(value: str) -> Tuple[str, str]:
    """赛博黑是 dark-only：每个 token 都写成同一个值两次。"""
    return (value, value)


#: 41 token 的极暗冷峻色板。除别名外，每个 token 的色对都唯一。
_CYBER_NOIR = {
    "bg_page": _dark("#0A0B10"),
    "bg_surface": _dark("#181A26"),
    "bg_surface_alt": _dark("#161823"),
    "bg_sidebar": _dark("#161823"),
    "bg_statusbar": _dark("#0C0E16"),
    "bg_drop_idle": _dark("#0C0E14"),
    "bg_stripe": _dark("#0E1018"),
    "hover_fill": _dark("#1A2230"),
    "hover_fill_sub": _dark("#151B26"),
    "border": _dark("#2A3C4C"),
    "border_strong": _dark("#3E566B"),
    "divider": _dark("#17212B"),
    "text": _dark("#C8D0E0"),
    "text_second": _dark("#8B95A8"),
    "text_muted": _dark("#737F92"),
    "text_on_accent": _dark("#000000"),
    "accent": _dark("#00F0FF"),
    "accent_hover": _dark("#5CFFFF"),
    "accent_soft": _dark("#002233"),
    "accent_text": _dark("#7CF7FF"),
    "secondary": _dark("#FF0055"),
    "secondary_soft": _dark("#2A0A16"),
    "secondary_text": _dark("#FF6B8A"),
    "success": _dark("#00FF88"),
    "success_soft": _dark("#00281E"),
    "danger": _dark("#FF0055"),
    "danger_hover": _dark("#FF3377"),
    "danger_soft": _dark("#2A0A14"),
    "warning": _dark("#FF0055"),
    "warning_soft": _dark("#2B0A12"),
    "drop_border_idle": _dark("#22303D"),
    "drop_border_active": _dark("#00F0FF"),
    "drop_fill_active": _dark("#002B3B"),
    "drop_border_ok": _dark("#2BFFA6"),
    "drop_fill_ok": _dark("#002B20"),
    "drop_border_warn": _dark("#FF0055"),
    "log_bg": _dark("#080A0F"),
    "log_text": _dark("#A7B5C6"),
    "scroll_track": _dark("#0D1017"),
    "scroll_thumb": _dark("#263646"),
    "scroll_hover": _dark("#365068"),
}

SKINS: Dict[str, Skin] = {
    "cyber_noir": Skin(
        key="cyber_noir",
        label="赛博黑",
        description="极暗冷灰蓝、青色光刃与洋红故障色；单皮肤，固定深色。",
        recommended_mode="dark",
        colors=_CYBER_NOIR,
        radii={"sm": 2, "md": 4, "lg": 6, "xl": 8},
        font_ui="Microsoft YaHei UI",
        font_display="Microsoft YaHei UI",
        font_mono="Cascadia Mono",
    ),
}

DEFAULT_SKIN = "cyber_noir"
SKIN_KEYS = tuple(SKINS.keys())
SKIN_LABELS = {key: skin.label for key, skin in SKINS.items()}
SKIN_LABEL_TO_KEY = {skin.label: key for key, skin in SKINS.items()}
#: 允许共色的语义别名组。赛博黑里 secondary/danger/warning 统一为洋红。
CANONICAL_COLOR_ALIASES = (
    frozenset({"accent", "drop_border_active"}),
    frozenset({"secondary", "danger", "warning", "drop_border_warn"}),
    frozenset({"bg_surface_alt", "bg_sidebar"}),
)


def skin_label(key: str) -> str:
    return SKINS.get(key, SKINS[DEFAULT_SKIN]).label


def skin_key_for_label(label: str) -> str:
    return SKIN_LABEL_TO_KEY.get(label, DEFAULT_SKIN)


def validate_skins() -> None:
    """开发/测试用：校验 token 完整、颜色可逆、圆角角色唯一。"""
    base = set(COLOR_TOKENS)
    for skin in SKINS.values():
        if set(skin.colors) != base:
            missing = base - set(skin.colors)
            extra = set(skin.colors) - base
            raise ValueError(f"{skin.key}: token 不一致 missing={missing} extra={extra}")
        groups: Dict[Tuple[str, str], list] = {}
        for token, pair in skin.colors.items():
            if not (isinstance(pair, tuple) and len(pair) == 2):
                raise ValueError(f"{skin.key}.{token}: 必须是 (light, dark) 二元组")
            groups.setdefault(tuple(pair), []).append(token)
        for pair, tokens in groups.items():
            if len(tokens) <= 1:
                continue
            names = frozenset(tokens)
            if names not in CANONICAL_COLOR_ALIASES:
                raise ValueError(
                    f"{skin.key}: 非别名 token 共用色值 {pair}: {sorted(tokens)}"
                )
        for alias in CANONICAL_COLOR_ALIASES:
            if len({skin.colors[t] for t in alias}) != 1:
                raise ValueError(f"{skin.key}: 别名组不同色 {sorted(alias)}")
        values = list(skin.radii.values())
        if len(values) != 4 or len(set(values)) != 4:
            raise ValueError(f"{skin.key}: 四个圆角档必须互不相同: {values}")


# --------------------------------------------------------------------------- #
# 动态 token 导出
# --------------------------------------------------------------------------- #

ACTIVE_SKIN: Skin = SKINS[DEFAULT_SKIN]
PALETTE: Dict[str, Tuple[str, str]] = {}
TONE_COLORS: Dict[str, Tuple[Tuple[str, str], Tuple[str, str]]] = {}
FONT_FAMILY = ""
FONT_DISPLAY = ""
FONT_FALLBACK = "Microsoft YaHei"
MONO_FAMILY = ""
MONO_FALLBACK = "Consolas"

_FAMILY_CACHE: Dict[str, str] = {}


def _export_token(token: str, value: Tuple[str, str]) -> None:
    name = "DROP_FILL_IDLE" if token == "bg_drop_idle" else token.upper()
    globals()[name] = value


def set_skin(key: str) -> str:
    """应用唯一皮肤 ``cyber_noir`` 并同步所有模块级 token。

    单皮肤仍然保留这个入口，是为了让配置迁移和测试可以显式触发初始化；
    不再支持运行时切换。
    """
    global ACTIVE_SKIN, PALETTE, TONE_COLORS
    global FONT_FAMILY, FONT_DISPLAY, MONO_FAMILY

    skin = SKINS.get(key) or SKINS[DEFAULT_SKIN]
    ACTIVE_SKIN = skin
    PALETTE = dict(skin.colors)
    for token in COLOR_TOKENS:
        _export_token(token, PALETTE[token])

    # 圆角角色：2 / 4 / 6 / 8，不再提供 999 胶囊。
    globals()["RADIUS_S"] = skin.radius("sm")
    globals()["RADIUS"] = skin.radius("md")
    globals()["RADIUS_L"] = skin.radius("lg")
    globals()["RADIUS_XL"] = skin.radius("xl")
    globals().pop("RADIUS_PILL", None)

    # 赛博黑是 dark-only；强制深色，避免默认 Label 在浅色模式变黑。
    ctk.set_appearance_mode("dark")

    FONT_FAMILY = skin.font_ui
    FONT_DISPLAY = skin.font_display
    MONO_FAMILY = skin.font_mono
    _FAMILY_CACHE.clear()

    TONE_COLORS = {
        "accent": (PALETTE["accent_soft"], PALETTE["accent_text"]),
        "secondary": (PALETTE["secondary_soft"], PALETTE["secondary_text"]),
        "success": (PALETTE["success_soft"], PALETTE["success"]),
        "danger": (PALETTE["danger_soft"], PALETTE["danger"]),
        "warning": (PALETTE["warning_soft"], PALETTE["warning"]),
        "muted": (PALETTE["bg_surface_alt"], PALETTE["text_muted"]),
    }
    return skin.key


def active_skin() -> Skin:
    return ACTIVE_SKIN


def active_key() -> str:
    return ACTIVE_SKIN.key


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
# 字体
# --------------------------------------------------------------------------- #

class RoleFont(ctk.CTkFont):
    """带角色名的 CTkFont，换肤时据此决定 ui/display/mono 三套家族。"""

    def __init__(self, family: str, size: int, weight: str, role: str):
        super().__init__(family=family, size=size, weight=weight)
        self._wfa_role = role


def _pick_family(candidates: Iterable[str], root: Optional[tk.Misc] = None) -> str:
    candidates = [c for c in candidates if c]
    try:
        families = set(tkfont.families(root))
    except Exception:  # noqa: BLE001 - tk 字体查询失败不影响启动
        return candidates[0] if candidates else FONT_FALLBACK
    for name in candidates:
        if name in families:
            return name
    return candidates[0] if candidates else FONT_FALLBACK


def _family_candidates(role: str):
    skin = ACTIVE_SKIN
    ui = [skin.font_ui, FONT_FAMILY, "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"]
    display = [skin.font_display, skin.font_ui, "Microsoft YaHei UI", "Segoe UI"]
    mono = [skin.font_mono, "Cascadia Mono", "Cascadia Code", "Consolas", "Courier New"]
    return {"ui": ui, "display": display, "mono": mono}.get(role, ui)


def family(role: str = "ui") -> str:
    if role not in _FAMILY_CACHE:
        _FAMILY_CACHE[role] = _pick_family(_family_candidates(role))
    return _FAMILY_CACHE[role]


def resolve_family(root: Optional[tk.Misc] = None) -> str:
    """兼容旧调用：解析当前皮肤的 UI 家族。"""
    return _pick_family(_family_candidates("ui"), root)


def resolve_mono(root: Optional[tk.Misc] = None) -> str:
    """兼容旧调用：解析当前皮肤的等宽家族。"""
    return _pick_family(_family_candidates("mono"), root)


def font(size: int = 13, weight: str = "normal", role: str = "ui") -> ctk.CTkFont:
    """统一字体工厂。``role`` 可为 ``ui`` / ``display`` / ``mono``。"""
    return RoleFont(family(role), size, weight, role)


def mono_font(size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    """等宽字体工厂 —— 日志、路径、命令。"""
    return RoleFont(family("mono"), size, weight, "mono")


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
SIDEBAR_ACCENT_W = 2   # 选中态左侧强调竖条宽度
STATUSBAR_HEIGHT = 26

# --------------------------------------------------------------------------- #
# 兼容旧名（各页面仍在引用；语义与刻度对齐后逐步替换）
# --------------------------------------------------------------------------- #
PAD = SP.L          # 16
PAD_S = SP.S        # 8
PAD_L = SP.XL       # 20（原 22，对齐到 4 的倍数）

STATUS_TEXT = "就绪"
LOG_FONT_SIZE = FS.SMALL

TRANSPARENT = "transparent"  # customtkinter 专用关键字，不是颜色

#: HUD 装饰色。不进入 41 token 色板，只服务于网格/状态带/日志 tag。
HUD_DIM = "#0F3A40"
HUD_GRID = "#151A24"
LOG_WARN = "#C6A15B"     # 唯一低饱和琥珀，仅日志 [WARN] 使用
LOG_INFO = "#7E9AA3"     # 灰青，日志 [INFO]

#: 卡片中文标题 → 终端机读名。
HUD_TITLES = {
    "已选文件": "FILE_INFO",
    "处理参数": "ARGUMENTS",
    "运行日志": "SYSTEM_LOG",
    "技术栈": "STACK",
    "目录一览": "PATHS",
    "默认输出目录": "OUTPUT_DIR",
    "外观与动效": "APPEARANCE",
    "用户预设目录": "USER_PRESETS",
    "API 配置": "API_CONFIG",
    "Token 用量统计": "TOKEN_USAGE",
}

#: 导航项：(key, 显示名, 图标字符)
NAV_ITEMS = (
    ("home", "首页", "🏠"),
    ("presets", "预设管理", "📋"),
    ("settings", "设置", "⚙"),
    ("about", "关于", "ℹ"),
)

_CARD_SERIAL = 0


def _add_card_chrome(frame: ctk.CTkFrame) -> None:
    """卡片右上旧式窗口按钮 + 右下十六进制编号，纯静态。"""
    global _CARD_SERIAL
    _CARD_SERIAL += 1
    chrome = ctk.CTkFrame(frame, fg_color=TRANSPARENT)
    chrome.place(relx=1.0, y=6, x=-8, anchor="ne")
    for text, color in (("[-]", TEXT_MUTED), (" □ ", TEXT_MUTED),
                        ("×", SECONDARY)):
        ctk.CTkLabel(
            chrome, text=text, font=mono_font(8), text_color=color,
            fg_color=TRANSPARENT,
        ).pack(side="left")
    ctk.CTkLabel(
        frame, text=f"0x{_CARD_SERIAL:02X}", font=mono_font(8),
        text_color=TEXT_MUTED, fg_color=TRANSPARENT,
    ).place(relx=1.0, rely=1.0, x=-8, y=-4, anchor="se")


# --------------------------------------------------------------------------- #
# 控件工厂
# --------------------------------------------------------------------------- #
def card(master, **kwargs) -> ctk.CTkFrame:
    """卡片容器：面板色 + 1px 描边 + 终端窗口角标。"""
    chrome = kwargs.pop("chrome", True)
    opts = dict(
        corner_radius=RADIUS_L,
        fg_color=BG_SURFACE,
        border_width=1,
        border_color=BORDER,
    )
    opts.update(kwargs)
    frame = ctk.CTkFrame(master, **opts)
    frame._wfa_card = True  # 交给 effects.bind_tree() 绑 hover
    if chrome:
        _add_card_chrome(frame)
    return frame


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
    """卡片标题：已知中文标题自动转 ``[ TERMINAL_NAME ]``。"""
    code = HUD_TITLES.get(text)
    display = f"[ {code} ]" if code else text
    opts = dict(font=font(FS.LEAD, "bold", role="display"), anchor="w",
                text_color=TEXT)
    opts.update(kwargs)
    return ctk.CTkLabel(master, text=display, **opts)


def page_title(master, text: str, **kwargs) -> ctk.CTkLabel:
    """页面主标题（H1）。"""
    opts = dict(font=font(FS.H1, "bold", role="display"), anchor="w", text_color=TEXT)
    opts.update(kwargs)
    return ctk.CTkLabel(master, text=text, **opts)


# --------------------------------------------------------------------------- #
# HUD 静态装饰与 1s 共享 blink 总线
# --------------------------------------------------------------------------- #

_BLINK_PHASE = True
_BLINK_CALLBACKS = set()


def register_blink(callback) -> None:
    _BLINK_CALLBACKS.add(callback)


def unregister_blink(callback) -> None:
    _BLINK_CALLBACKS.discard(callback)


def tick_blink(phase: bool) -> None:
    """由 app 的唯一 1000ms 定时器调用；所有闪烁共享这一拍。"""
    global _BLINK_PHASE
    _BLINK_PHASE = bool(phase)
    for callback in tuple(_BLINK_CALLBACKS):
        try:
            callback(_BLINK_PHASE)
        except Exception:  # noqa: BLE001 - 控件销毁后自动摘除
            _BLINK_CALLBACKS.discard(callback)


class CursorBlock:
    """输入框左侧 2px 终端块；focus 后改为共享节拍的 ``_`` 闪烁。"""

    def __init__(self, host: ctk.CTkEntry, focus_widget: tk.Misc):
        self.host = host
        self.focus_widget = focus_widget
        self._focused = False
        self.canvas = tk.Canvas(
            host, width=8, height=14, bg=C(BG_SURFACE_ALT),
            highlightthickness=0, bd=0, takefocus=0,
        )
        self.canvas.place(x=4, rely=0.5, anchor="w")
        self.canvas.create_rectangle(
            3, 2, 5, 12, fill=C(ACCENT), width=0, tags="block")
        self.canvas.create_text(
            4, 7, text="_", fill=C(ACCENT), font=(MONO_FAMILY, 10),
            state="hidden", tags="cursor",
        )
        focus_widget.bind("<FocusIn>", self._on_focus, add="+")
        focus_widget.bind("<FocusOut>", self._on_blur, add="+")
        focus_widget.bind("<Destroy>", self._on_destroy, add="+")

    def _on_focus(self, _event=None) -> None:
        self._focused = True
        self.canvas.itemconfigure("block", state="hidden")
        register_blink(self._apply)
        self._apply(_BLINK_PHASE)

    def _on_blur(self, _event=None) -> None:
        self._focused = False
        unregister_blink(self._apply)
        try:
            self.canvas.itemconfigure("block", state="normal")
            self.canvas.itemconfigure("cursor", state="hidden")
        except tk.TclError:
            pass

    def _on_destroy(self, _event=None) -> None:
        unregister_blink(self._apply)

    def _apply(self, phase: bool) -> None:
        if not self._focused:
            return
        try:
            self.canvas.itemconfigure(
                "cursor", state="normal" if phase else "hidden")
        except tk.TclError:
            unregister_blink(self._apply)


def hud_band(master, version: str):
    """全局 HUD 状态带：静态遥测 + 一个由 app 驱动的光标。"""
    frame = ctk.CTkFrame(master, height=30, corner_radius=0,
                         fg_color=TRANSPARENT)
    frame.grid_propagate(False)
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(0, weight=1)
    left = ctk.CTkFrame(frame, fg_color=TRANSPARENT)
    left.grid(row=0, column=0, sticky="w", padx=(PAD, 0))
    segments = (
        ("SYS::", HUD_DIM), (f"TAOFU_v{version}", ACCENT),
        (" // ", HUD_DIM), ("MODE:", HUD_DIM), ("ACTIVE", ACCENT),
        (" // ", HUD_DIM), ("MEM:", HUD_DIM), ("32.4MB", ACCENT),
        (" // ", HUD_DIM), ("UPTIME:", HUD_DIM), ("00:12:45", ACCENT),
    )
    for text, color in segments:
        ctk.CTkLabel(
            left, text=text, font=mono_font(9), text_color=color,
            fg_color=TRANSPARENT,
        ).pack(side="left")
    cursor = ctk.CTkLabel(
        left, text="_", width=8, font=mono_font(9),
        text_color=ACCENT, fg_color=TRANSPARENT,
    )
    cursor.pack(side="left", padx=(2, 0))
    stream = ctk.CTkLabel(
        frame, text="|||///|||", font=mono_font(9),
        text_color=HUD_DIM, fg_color=TRANSPARENT,
    )
    stream.grid(row=0, column=1, sticky="e", padx=(0, PAD))
    ctk.CTkFrame(frame, height=1, fg_color=BORDER).grid(
        row=1, column=0, columnspan=2, sticky="ew")
    return frame, cursor, stream


def hud_rail(master) -> tk.Canvas:
    """8px 静态扫描刻度边轨；只画一次，不做 Configure 重绘。"""
    canvas = tk.Canvas(
        master, width=8, bg=C(BG_PAGE), highlightthickness=0,
        bd=0, takefocus=0,
    )
    for index, y in enumerate(range(0, 3000, 12)):
        length = 5 if index % 3 == 0 else 2
        color = C(ACCENT) if index % 9 == 0 else HUD_DIM
        canvas.create_line(4, y, 4, y + length, fill=color)
    return canvas


def _grid_canvas(host: tk.Misc) -> None:
    """在 host 内部铺一张一次性网格，压在其背景 canvas 之上、内容之下。"""
    if getattr(host, "_wfa_grid", False):
        return
    host._wfa_grid = True
    canvas = tk.Canvas(
        host, bg=C(BG_PAGE), highlightthickness=0, bd=0, takefocus=0,
    )
    canvas.place(x=0, y=0, relwidth=1, relheight=1)
    background = getattr(host, "_canvas", None)
    try:
        if background is not None:
            tk.Misc.lift(canvas, background)
        else:
            tk.Misc.lower(canvas)
    except tk.TclError:
        pass
    width = max(4000, host.winfo_screenwidth() + 200)
    height = max(3000, host.winfo_screenheight() + 200)
    for index, x in enumerate(range(0, width, 20)):
        major = index % 5 == 0
        canvas.create_line(
            x, 0, x, height, fill=HUD_DIM if major else HUD_GRID,
            **(dict(dash=(1, 7)) if major else {}),
        )
    for index, y in enumerate(range(0, height, 20)):
        major = index % 5 == 0
        canvas.create_line(
            0, y, width, y, fill=HUD_DIM if major else HUD_GRID,
            **(dict(dash=(1, 7)) if major else {}),
        )


def install_grid(page: tk.Misc) -> None:
    """每页铺一次网格。

    CTkScrollableFrame 的内容层被包在内部 Canvas 里，直接铺在页面
    或外层容器上会被视口背景盖住；必须铺进滚动内容帧本身。
    """
    scroll_hosts = [node for node in _walk(page)
                    if isinstance(node, ctk.CTkScrollableFrame)]
    if scroll_hosts:
        for host in scroll_hosts:
            _grid_canvas(host)
        return
    _grid_canvas(page)


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


def tone_colors(tone: str):
    """取某个语义色调的 ``(底色, 文字色)``。"""
    return TONE_COLORS.get(tone, TONE_COLORS["accent"])


def badge(master, text: str, tone: str = "accent", **kwargs) -> ctk.CTkLabel:
    """小方角标签：内置/用户、已配置/未配置、成功/失败。

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
    """主操作按钮：普通态深底青边青字，hover 才填青底黑字。

    ``danger=True`` 保留洋红实心 + 黑字，危险操作需要重量感，不参与退火。
    """
    opts = dict(
        font=font(FS.LEAD, "bold"),
        height=CTRL_H_L,
        corner_radius=RADIUS,
        fg_color=DANGER if danger else BG_SURFACE_ALT,
        hover_color=DANGER_HOVER if danger else ACCENT,
        text_color=TEXT_ON_ACCENT if danger else ACCENT,
        text_color_disabled=TEXT_MUTED,
        border_width=0 if danger else 1,
        border_color=DANGER if danger else ACCENT,
        width=BTN_W_XL,
    )
    opts.update(kwargs)
    button = ctk.CTkButton(master, text=text, command=command, **opts)
    if not danger:
        def _hover_in(_event=None) -> None:
            button.configure(text_color=TEXT_ON_ACCENT,
                             border_color=ACCENT_HOVER)

        def _hover_out(_event=None) -> None:
            button.configure(text_color=ACCENT, border_color=ACCENT)

        targets = [button]
        canvas = getattr(button, "_canvas", None)
        if canvas is not None:
            targets.append(canvas)
        for target in targets:
            target.bind("<Enter>", _hover_in, add="+")
            target.bind("<Leave>", _hover_out, add="+")
    return button


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
        border_color=BORDER,
        fg_color=BG_SURFACE_ALT,
        text_color=TEXT,
        placeholder_text_color=TEXT_MUTED,
    )
    opts.update(kwargs)
    if textvariable is not None:
        widget = ctk.CTkEntry(master, textvariable=textvariable, **opts)
    else:
        widget = ctk.CTkEntry(master, **opts)
    widget._wfa_focusable = True
    focus_widget = getattr(widget, "_entry", None)
    if focus_widget is not None:
        widget._wfa_cursor = CursorBlock(widget, focus_widget)
    return widget


def textbox(master, mono: bool = False, **kwargs) -> ctk.CTkTextbox:
    """只读/可编辑文本框：暗底 + 细描边，等宽可选。"""
    opts = dict(
        font=mono_font(FS.SMALL) if mono else font(FS.BODY),
        corner_radius=RADIUS,
        border_width=1,
        border_color=BORDER,
        fg_color=BG_SURFACE_ALT,
        text_color=LOG_TEXT if mono else TEXT,
    )
    opts.update(kwargs)
    widget = ctk.CTkTextbox(master, **opts)
    widget._wfa_focusable = True
    return widget


def combo(master, values, variable=None, **kwargs) -> ctk.CTkComboBox:
    opts = dict(
        font=font(FS.BODY),
        dropdown_font=font(FS.BODY),
        height=CTRL_H,
        corner_radius=RADIUS,
        border_width=1,
        border_color=BORDER,
        fg_color=BG_SURFACE_ALT,
        button_color=BG_SURFACE,
        button_hover_color=HOVER_FILL,
        text_color=TEXT,
        dropdown_fg_color=BG_SURFACE,
        dropdown_hover_color=ACCENT_SOFT,
        dropdown_text_color=TEXT,
        state="readonly",
    )
    opts.update(kwargs)
    if variable is not None:
        widget = ctk.CTkComboBox(master, values=values, variable=variable, **opts)
    else:
        widget = ctk.CTkComboBox(master, values=values, **opts)
    widget._wfa_focusable = True
    focus_widget = getattr(widget, "_entry", None)
    if focus_widget is not None:
        widget._wfa_cursor = CursorBlock(widget, focus_widget)
    return widget


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
        height=4,
        corner_radius=2,
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
# 默认文字色修正
# --------------------------------------------------------------------------- #

#: CTk 出厂默认的 Label/Entry 文字色。页面里很多 Label 没显式写 text_color。
_DEFAULT_TEXT_PAIR = ("gray10", "#DCE4EE")


def _as_pair(value) -> Optional[Tuple[str, str]]:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return (str(value[0]), str(value[1]))
    return None


def _walk(root: tk.Misc):
    """深度优先遍历控件树，包含 Toplevel 弹窗。"""
    stack = [root]
    seen = set()
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        yield node
        try:
            stack.extend(node.winfo_children())
        except tk.TclError:
            continue


def normalize_default_text(root: tk.Misc) -> None:
    """把没写 text_color 的 CTk 控件从出厂灰归到赛博黑 TEXT。"""
    target = {
        "text_color": ACTIVE_SKIN.colors["text"],
        "placeholder_text_color": ACTIVE_SKIN.colors["text_muted"],
    }
    for widget in _walk(root):
        for option, color in target.items():
            try:
                value = widget.cget(option)
            except Exception:  # noqa: BLE001
                continue
            if _as_pair(value) == _DEFAULT_TEXT_PAIR:
                try:
                    widget.configure(**{option: color})
                except Exception:  # noqa: BLE001
                    pass


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
    """收集 root 子树里的**真** tkinter 控件（含自定义控件内部的 canvas）。"""
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
    """给一个区域注册文件拖放，返回是否有控件注册成功。"""
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
            continue
        try:
            register(DND_FILES)
            bind("<<Drop>>", on_drop)
            ok += 1
        except tk.TclError:
            continue
    LAST_REGISTERED_COUNT = ok
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


# 初始化默认皮肤（必须放在所有定义之后，确保 globals 已就绪）。
set_skin(DEFAULT_SKIN)
