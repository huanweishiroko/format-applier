# -*- coding: utf-8 -*-
"""轻量微动效：拖拽区代码雨、卡片 hover、输入框 focus、单次 glitch。

设计底线（改这里之前先读）：
  * 代码雨只在首页拖拽区，最多 30 个字符、80ms/帧（12fps），
    没有可见区域时不得保留定时器。
  * 没有全局常驻循环、没有扫描线/呼吸灯/外发光。
  * hover / focus 只在事件发生时创建一次性 ``after``；每个控件同时最多一个。
  * glitch 只做颜色，100ms 内走 ``accent -> secondary -> 原色``，不改尺寸/位置。
  * 关闭窗口或关闭“界面动效”时，所有未完成定时器都要取消。
"""

from __future__ import annotations

import random
import tkinter as tk
from typing import Callable, List, Optional

try:  # pragma: no cover - 兼容包内/脚本两种导入
    from ui import theme as th
except ImportError:  # pragma: no cover
    from . import theme as th  # type: ignore


# --------------------------------------------------------------------------- #
# 基础颜色插值
# --------------------------------------------------------------------------- #

def _solid(value) -> str:
    """把 ``(hex, hex)`` 或单 hex 统一成单 hex。"""
    if isinstance(value, (tuple, list)):
        return str(value[0])
    return str(value)


def _hex_to_rgb(value: str) -> tuple:
    text = _solid(value).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        *(max(0, min(255, int(round(c)))) for c in rgb)
    )


def _blend(start: str, end: str, t: float) -> str:
    a, b = _hex_to_rgb(start), _hex_to_rgb(end)
    return _rgb_to_hex(a[i] + (b[i] - a[i]) * t for i in range(3))


def _configure(widget: tk.Misc, option: str, value) -> None:
    try:
        widget.configure(**{option: value})
    except (tk.TclError, ValueError):
        pass


def _cancel_job(widget: tk.Misc) -> None:
    job = getattr(widget, "_wfa_motion_job", None)
    if job is not None:
        try:
            widget.after_cancel(job)
        except (tk.TclError, ValueError):
            pass
        widget._wfa_motion_job = None


def _animate(widget: tk.Misc, option: str, target, duration: int = 150,
             steps: int = 5, done: Optional[Callable[[], None]] = None) -> None:
    """在 duration 内把某个颜色属性线性过渡到 target；每个控件只保留一个。"""
    _cancel_job(widget)
    try:
        start = _solid(widget.cget(option))
    except (tk.TclError, ValueError):
        return
    end = _solid(target)
    if start.lower() == end.lower():
        return
    interval = max(16, int(duration / max(steps, 1)))

    def step(index: int) -> None:
        if not widget.winfo_exists():
            return
        t = min(index / steps, 1.0)
        _configure(widget, option, _blend(start, end, t))
        if index < steps:
            widget._wfa_motion_job = widget.after(
                interval, lambda: step(index + 1))
        else:
            widget._wfa_motion_job = None
            if done is not None:
                done()

    step(1)


# --------------------------------------------------------------------------- #
# 全局开关与绑定
# --------------------------------------------------------------------------- #

_MOTION_ENABLED = True
_BOUND_WIDGETS: List[tk.Misc] = []


def set_motion_enabled(enabled: bool) -> None:
    global _MOTION_ENABLED
    _MOTION_ENABLED = bool(enabled)
    if not _MOTION_ENABLED:
        stop_all_motion()


def stop_all_motion() -> None:
    for widget in list(_BOUND_WIDGETS):
        _cancel_job(widget)


def bind_card_hover(widget: tk.Misc) -> None:
    """卡片 hover：边框 border -> border_strong，150ms，尺寸不动。

    CTkFrame 的可视面由内部 canvas + 子控件组成，只绑外层 Frame 时鼠标
    停在文字上不会触发。这里把整棵子树都绑上，并用 30ms 的离场延迟吃掉
    “父 Frame Leave → 子 Label Enter”的交叉事件，避免 hover 闪烁。
    """
    if getattr(widget, "_wfa_hover_bound", False):
        return
    widget._wfa_hover_bound = True
    _BOUND_WIDGETS.append(widget)
    base = th.C(th.BORDER)
    hover = th.C(th.BORDER_STRONG)
    state = {"depth": 0, "leave_job": None}

    def cancel_leave() -> None:
        job = state["leave_job"]
        if job is not None:
            try:
                widget.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
            state["leave_job"] = None

    def enter(_event=None) -> None:
        state["depth"] += 1
        cancel_leave()
        if _MOTION_ENABLED:
            _animate(widget, "border_color", hover, 150)
        else:
            _configure(widget, "border_color", hover)

    def settle_leave() -> None:
        state["leave_job"] = None
        if state["depth"] > 0:
            return
        if _MOTION_ENABLED:
            _animate(widget, "border_color", base, 150)
        else:
            _configure(widget, "border_color", base)

    def leave(_event=None) -> None:
        state["depth"] = max(0, state["depth"] - 1)
        cancel_leave()
        try:
            state["leave_job"] = widget.after(30, settle_leave)
        except (tk.TclError, ValueError):
            settle_leave()

    targets = [widget]
    stack = list(widget.winfo_children())
    while stack:
        child = stack.pop()
        targets.append(child)
        try:
            stack.extend(child.winfo_children())
        except tk.TclError:
            pass
    def cleanup(_event=None) -> None:
        cancel_leave()
        _cancel_job(widget)

    for target in targets:
        target.bind("<Enter>", enter, add="+")
        target.bind("<Leave>", leave, add="+")
        target.bind("<Destroy>", cleanup, add="+")


def bind_focus_ring(widget: tk.Misc) -> None:
    """输入框 focus：border -> accent，140ms；失焦回 border。"""
    if getattr(widget, "_wfa_focus_bound", False):
        return
    widget._wfa_focus_bound = True
    _BOUND_WIDGETS.append(widget)
    base = th.C(th.BORDER)
    focus = th.C(th.ACCENT)

    def on_focus(_event=None) -> None:
        if _MOTION_ENABLED:
            _animate(widget, "border_color", focus, 140)
        else:
            _configure(widget, "border_color", focus)

    def on_blur(_event=None) -> None:
        if _MOTION_ENABLED:
            _animate(widget, "border_color", base, 140)
        else:
            _configure(widget, "border_color", base)

    # CTkEntry/CTkTextbox 的焦点在内部 Entry/Text 上，不冒泡到外层 Frame。
    focus_target = (
        getattr(widget, "_entry", None)
        or getattr(widget, "_textbox", None)
        or widget
    )
    focus_target.bind("<FocusIn>", on_focus, add="+")
    focus_target.bind("<FocusOut>", on_blur, add="+")
    focus_target.bind("<Destroy>", lambda _e: _cancel_job(widget), add="+")


def bind_tree(root: tk.Misc) -> None:
    """遍历控件树，给带标记的卡片/输入框绑一次性微动效。"""
    if getattr(root, "_wfa_card", False):
        bind_card_hover(root)
    if getattr(root, "_wfa_focusable", False):
        bind_focus_ring(root)
    try:
        children = root.winfo_children()
    except tk.TclError:
        return
    for child in children:
        bind_tree(child)


# --------------------------------------------------------------------------- #
# 首页拖拽区代码雨
# --------------------------------------------------------------------------- #

class CodeRain:
    """拖拽区底层的极暗代码雨：30 字符、12fps、仅 idle 时运行。"""

    MAX_GLYPHS = 30
    INTERVAL_MS = 80
    INSET = 8
    DELAY_MS = 150
    DIM_COLOR = "#0F3A40"
    BRIGHT_COLOR = "#00F0FF"
    GLYPHS = "01<>/\\[]{}#$%&*+=-_"

    def __init__(self, root: tk.Misc, parent: tk.Misc, above: tk.Misc,
                 on_click: Optional[Callable[[], None]] = None,
                 on_drop: Optional[Callable] = None):
        self.root = root
        self.parent = parent
        self.above = above
        self._job: Optional[str] = None
        self._delay_job: Optional[str] = None
        self._enabled = True
        self._drop_idle = True
        self._page_active = False
        self._size = (0, 0)
        self.items: List[dict] = []

        self.canvas = tk.Canvas(
            parent,
            bg=th.C(th.DROP_FILL_IDLE),
            highlightthickness=0,
            bd=0,
            takefocus=0,
        )
        self.canvas.place_forget()
        if on_click is not None:
            self.canvas.bind("<Button-1>", lambda _e: on_click(), add="+")
        if on_drop is not None:
            try:
                th.bind_drop_target(self.canvas, on_drop)
            except Exception:  # noqa: BLE001 - 原生 DnD 已覆盖，失败不拦
                pass
        parent.bind("<Configure>", self._on_resize, add="+")

    def _eligible(self) -> bool:
        if not _MOTION_ENABLED or not self._enabled:
            return False
        if not self._drop_idle or not self._page_active:
            return False
        try:
            return (self.parent.winfo_exists()
                    and self.parent.winfo_width() >= 80
                    and self.parent.winfo_height() >= 80)
        except tk.TclError:
            return False

    def _cancel_timers(self) -> None:
        for attr in ("_job", "_delay_job"):
            job = getattr(self, attr)
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
                setattr(self, attr, None)

    def _refresh(self) -> None:
        if not self._eligible():
            self.stop()
            return
        if self._job is not None or self._delay_job is not None:
            return
        # 等 120ms 底色过渡走完再显示，避免拖拽区重新回到 idle 时闪一块矩形。
        self._delay_job = self.root.after(self.DELAY_MS, self._start)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if self._enabled:
            self._refresh()
        else:
            self.stop()

    def set_drop_idle(self, idle: bool) -> None:
        self._drop_idle = bool(idle)
        if self._drop_idle:
            self._refresh()
        else:
            self.stop()

    def set_page_active(self, active: bool) -> None:
        self._page_active = bool(active)
        if self._page_active:
            self._refresh()
        else:
            self.stop()

    def _on_resize(self, _event=None) -> None:
        try:
            size = (self.parent.winfo_width(), self.parent.winfo_height())
        except tk.TclError:
            return
        if size == self._size:
            return
        self._size = size
        if self._job is not None:
            self._cancel_timers()
            self._show()
            self._tick()

    def _start(self) -> None:
        self._delay_job = None
        if not self._eligible():
            self.stop()
            return
        self._show()
        self._tick()

    def _show(self) -> None:
        try:
            width = max(0, self.parent.winfo_width() - self.INSET * 2)
            height = max(0, self.parent.winfo_height() - self.INSET * 2)
        except tk.TclError:
            return
        if width < 80 or height < 60:
            self.stop()
            return
        self.canvas.place(x=self.INSET, y=self.INSET, width=width, height=height)
        if self.above is not None:
            try:
                tk.Misc.lower(self.canvas, self.above)
            except tk.TclError:
                pass
        current = getattr(self, "_canvas_size", (0, 0))
        if not self.items or current != (width, height):
            self._canvas_size = (width, height)
            self._build_items(width, height)

    def _build_items(self, width: int, height: int) -> None:
        self.canvas.delete("rain")
        self.items = []
        columns = max(1, min(10, width // 26))
        for index in range(self.MAX_GLYPHS):
            column = index % columns
            x = (column + 0.5) * (width / columns)
            x += random.uniform(-6, 6)
            y = random.uniform(-height * 0.4, height)
            speed = random.uniform(1.4, 3.8)
            char = random.choice(self.GLYPHS)
            color = self.BRIGHT_COLOR if index % 4 == 0 else self.DIM_COLOR
            item_id = self.canvas.create_text(
                x, y, text=char, fill=color, anchor="n",
                font=(th.MONO_FAMILY, 10), tags=("rain",),
            )
            self.items.append({
                "id": item_id, "x": x, "y": y,
                "speed": speed, "column": column,
            })

    def _tick(self) -> None:
        if not self._eligible() or not self.items:
            self.stop()
            return
        width, height = getattr(self, "_canvas_size", (0, 0))
        if width < 80 or height < 60:
            self.stop()
            return
        columns = max(1, min(10, width // 26))
        try:
            for index, item in enumerate(self.items):
                item["y"] += item["speed"]
                if item["y"] > height + 10:
                    item["y"] = random.uniform(-30, -4)
                    item["x"] = (item["column"] + 0.5) * (width / columns)
                    item["x"] += random.uniform(-6, 6)
                    self.canvas.itemconfigure(
                        item["id"], text=random.choice(self.GLYPHS))
                self.canvas.coords(item["id"], item["x"], item["y"])
        except tk.TclError:
            self.stop()
            return
        try:
            self._job = self.root.after(self.INTERVAL_MS, self._tick)
        except tk.TclError:
            self.stop()

    def stop(self) -> None:
        self._cancel_timers()
        try:
            self.canvas.place_forget()
        except tk.TclError:
            pass

    def shutdown(self) -> None:
        self.stop()


class GlitchPlayer:
    """100ms 单次 RGB 色差：只改目标控件的文字或边框颜色。"""

    def __init__(self, root: tk.Misc):
        self.root = root
        self._timers: List[str] = []
        self._generation = 0
        self._target: Optional[tk.Misc] = None
        self._option: str = ""
        self._original = None

    def _cancel(self, restore: bool = True) -> None:
        self._generation += 1
        for timer in self._timers:
            try:
                self.root.after_cancel(timer)
            except (tk.TclError, ValueError):
                pass
        self._timers.clear()
        if restore and self._target is not None and self._original is not None:
            _configure(self._target, self._option, self._original)
        self._target = None
        self._original = None

    def flash(self, target: Optional[tk.Misc], option: str = "text_color",
              duration: int = 100) -> None:
        """点击主按钮 / 控制台报错时调用；不阻塞命令本身。"""
        if not _MOTION_ENABLED or target is None:
            return
        try:
            if not target.winfo_exists():
                return
            original = target.cget(option)
        except (tk.TclError, ValueError):
            return

        self._cancel(restore=True)
        self._target = target
        self._option = option
        self._original = original
        generation = self._generation

        def paint(color) -> None:
            if generation != self._generation:
                return
            _configure(target, option, color)

        paint(th.C(th.ACCENT))
        half = max(30, int(duration / 2))
        self._timers.append(self.root.after(
            half, lambda: paint(th.C(th.SECONDARY))))
        self._timers.append(self.root.after(
            duration, lambda: self._finish(generation)))

    def _finish(self, generation: int) -> None:
        if generation != self._generation:
            return
        if self._target is not None and self._original is not None:
            _configure(self._target, self._option, self._original)
        self._target = None
        self._original = None
        self._timers.clear()

    def stop_all(self) -> None:
        self._cancel(restore=True)


class MotionBinder:
    """app 持有的轻量门面：绑定页面控件 + 播放 glitch。"""

    def __init__(self, app):
        self.app = app
        self.enabled = bool(getattr(app.settings, "motion_enabled", True))
        self.glitch = GlitchPlayer(app)
        self.rain: Optional[CodeRain] = None
        set_motion_enabled(self.enabled)

    def bind_tree(self, root: tk.Misc) -> None:
        bind_tree(root)

    def attach_rain(self, parent: tk.Misc, above: tk.Misc,
                    on_click: Optional[Callable[[], None]] = None,
                    on_drop: Optional[Callable] = None) -> CodeRain:
        self.rain = CodeRain(
            self.app, parent, above, on_click=on_click, on_drop=on_drop)
        self.rain.set_enabled(self.enabled)
        return self.rain

    def on_page_changed(self, key: str) -> None:
        if self.rain is not None:
            self.rain.set_page_active(key == "home")

    def flash(self, target: Optional[tk.Misc], option: str = "text_color") -> None:
        self.glitch.flash(target, option)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        set_motion_enabled(self.enabled)
        if self.rain is not None:
            self.rain.set_enabled(self.enabled)
        if not self.enabled:
            self.glitch.stop_all()

    def stop_all(self) -> None:
        self.glitch.stop_all()
        stop_all_motion()
        if self.rain is not None:
            self.rain.shutdown()
