# -*- coding: utf-8 -*-
"""通用弹窗：信息/错误、确认、文本编辑、预设预览。

统一走 ModalWindow：圆角面板 + 居中 + 模态抓取 + ESC 关闭。
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import customtkinter as ctk

# 绝对优先，理由见 preview.py 顶部注释（frozen 下 ui/core 是顶层包）
try:
    from ui import theme as th
except ImportError:  # pragma: no cover - 包内运行时
    from . import theme as th  # type: ignore


class ModalWindow(ctk.CTkToplevel):
    """模态基类：面板 + 标题 + 关闭按钮。子类往 self.body 里塞内容。"""

    def __init__(self, master, title: str, size: Tuple[int, int] = (520, 360),
                 resizable: bool = False, icon: str = "", tone: str = "accent"):
        super().__init__(master)
        self.title(title)
        self.geometry(f"{size[0]}x{size[1]}")
        self.minsize(*size)
        self.resizable(resizable, resizable)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.grid_columnconfigure(0, weight=1)
        # 行次：0 头部 / 1 分隔线 / 2 内容区（weight=1）
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        c = 0
        if icon:
            # 只有调用方明确给了图标才放图标泡；表单类弹窗（重命名/复制预设）保持素净
            th.icon_bubble(header, icon, tone=tone, size=36).grid(
                row=0, column=c, padx=(th.PAD_L, th.PAD_S), pady=th.PAD_S
            )
            c += 1
        ctk.CTkLabel(header, text=title, font=th.font(th.FS.H3, "bold"), anchor="w").grid(
            row=0, column=c, sticky="w", padx=(th.PAD_L if c == 0 else 0, 0), pady=th.PAD
        )
        c += 1
        th.text_button(header, "✕", self.destroy, width=th.CTRL_H_S, height=th.CTRL_H_S,
                       text_color=th.TEXT_MUTED, hover_color=th.HOVER_FILL).grid(
            row=0, column=c, sticky="e", padx=(th.PAD_S, th.PAD_S), pady=th.PAD_S
        )
        th.divider(self).grid(row=1, column=0, sticky="ew")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=2, column=0, sticky="nsew", padx=th.PAD_L, pady=(th.PAD, th.PAD))
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(60, self._center_and_focus)

    def _center_and_focus(self) -> None:
        try:
            self.update_idletasks()
            parent = self.master
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            w, h = self.winfo_width(), self.winfo_height()
            x = px + max((pw - w) // 2, 0)
            y = py + max((ph - h) // 3, 0)
            self.geometry(f"+{x}+{y}")
            self.grab_set()
            self.lift()
            self.focus_force()
        except Exception:  # noqa: BLE001 - 居中失败不影响功能
            pass


# --------------------------------------------------------------------------- #
# 信息 / 错误 / 确认
# --------------------------------------------------------------------------- #


def _message(master, title: str, text: str, *, error: bool = False,
             detail: str = "", width: int = 480) -> None:
    # 头部图标泡与标题由 ModalWindow 统一渲染；正文只留一段说明 + 明细框
    win = ModalWindow(master, title, (width, 300),
                      icon="✕" if error else "ℹ", tone="danger" if error else "accent")

    ctk.CTkLabel(
        win.body, text=text, font=th.font(th.FS.LEAD), justify="left",
        wraplength=width - 80, anchor="w",
    ).grid(row=0, column=0, sticky="ew")

    win.body.grid_rowconfigure(1, weight=1)
    # 明细放进只读文本框：长路径 / 长命令不会溢出窗口边界（内容随窗口伸缩）
    box = th.textbox(win.body, mono=True, wrap="word", height=120)
    box.insert("1.0", detail or "")
    box.configure(state="disabled")
    box.grid(row=1, column=0, sticky="nsew", pady=(th.PAD_S, 0))
    if not detail:
        # 没有明细就把文本框收起来，窗口压矮一点（保留 row1 的 weight 以便有明细时伸缩）
        win.after(80, lambda: (box.grid_remove(), win.geometry(f"{width}x280")))

    th.primary_button(win.body, "知道了", win.destroy, width=th.BTN_W_XL).grid(
        row=2, column=0, pady=(th.PAD, 0)
    )


def info(master, text: str, title: str = "提示", detail: str = "") -> None:
    _message(master, title, text, error=False, detail=detail)


def error(master, text: str, title: str = "出错了", detail: str = "") -> None:
    _message(master, title, text, error=True, detail=detail)


def confirm(master, text: str, title: str = "请确认", *,
            ok_text: str = "确定", cancel_text: str = "取消",
            danger: bool = False, detail: str = "") -> bool:
    """模态确认框，返回 True/False。"""
    win = ModalWindow(master, title, (460, 250 if detail else 215),
                      icon="⚠", tone="warning")
    win.result = False

    ctk.CTkLabel(
        win.body, text=text, font=th.font(th.FS.LEAD), justify="left",
        wraplength=380, anchor="w",
    ).grid(row=0, column=0, sticky="ew", pady=(0, th.PAD_S))
    if detail:
        ctk.CTkLabel(
            win.body, text=detail, font=th.font(th.FS.SMALL), justify="left",
            wraplength=380, anchor="w", text_color=th.TEXT_SECOND,
        ).grid(row=1, column=0, sticky="ew")

    row = ctk.CTkFrame(win.body, fg_color="transparent")
    row.grid(row=3, column=0, pady=(th.PAD_L, 0))
    win.body.grid_rowconfigure(2, weight=1)

    def _ok() -> None:
        win.result = True
        win.destroy()

    th.ghost_button(row, cancel_text, win.destroy, width=th.BTN_W_L).grid(row=0, column=0, padx=6)
    # danger=True 直接由工厂切语义红；不能传 fg_color=None，那会把默认强调色覆盖成 CTk 蓝
    th.primary_button(row, ok_text, _ok, width=th.BTN_W_L, danger=danger).grid(
        row=0, column=1, padx=6
    )

    win.wait_window()
    return bool(win.result)


# --------------------------------------------------------------------------- #
# 文本编辑 / 预览
# --------------------------------------------------------------------------- #


def text_editor(master, title: str, content: str, *, editable: bool = True,
                on_save: Optional[Callable[[str], bool]] = None,
                size: Tuple[int, int] = (760, 560),
                note: str = "") -> None:
    """文本编辑/预览窗。editable=False 时只读。on_save 返回 True 表示已保存。"""
    win = ModalWindow(master, title, size, resizable=True,
                      icon="✎" if editable else "👁", tone="accent")
    win.body.grid_rowconfigure(1, weight=1)

    if note:
        th.hint(win.body, note).grid(row=0, column=0, sticky="ew", pady=(0, th.PAD_S))

    box = th.textbox(win.body, wrap="word")
    box.grid(row=1, column=0, sticky="nsew")
    box.insert("1.0", content)
    if not editable:
        box.configure(state="disabled")

    status = th.hint(win.body, f"共 {len(content)} 字符")
    status.grid(row=2, column=0, sticky="w", pady=(th.PAD_S, 0))

    if editable and on_save is not None:
        bar = ctk.CTkFrame(win.body, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="e", pady=(th.PAD_S, 0))

        def _save() -> None:
            text = box.get("1.0", "end-1c")
            if on_save(text):
                status.configure(text=f"已保存 · 共 {len(text)} 字符")
                win.after(400, win.destroy)
            else:
                error(win, "保存失败", detail="目标文件不可写。")

        th.ghost_button(bar, "取消", win.destroy, width=th.BTN_W_L).grid(row=0, column=0, padx=6)
        th.primary_button(bar, "保存", _save, width=th.BTN_W_L).grid(row=0, column=1, padx=6)


def table_preview(master, title: str, headers: List[str], rows: List[List[str]],
                  note: str = "", size: Tuple[int, int] = (680, 520)) -> None:
    """只读表格弹窗（预设规则/文件信息用）。"""
    win = ModalWindow(master, title, size, resizable=True, icon="📋", tone="muted")
    win.body.grid_rowconfigure(1, weight=1)

    if note:
        th.hint(win.body, note, wraplength=size[0] - 80).grid(
            row=0, column=0, sticky="ew", pady=(0, th.PAD_S)
        )

    holder = ctk.CTkScrollableFrame(win.body, corner_radius=th.RADIUS, border_width=1)
    holder.grid(row=1, column=0, sticky="nsew")
    for col in range(len(headers)):
        holder.grid_columnconfigure(col, weight=2 if col == 1 else 1)

    for col, head in enumerate(headers):
        ctk.CTkLabel(holder, text=head, font=th.font(13, "bold"), anchor="w").grid(
            row=0, column=col, sticky="ew", padx=th.PAD_S, pady=(th.PAD_S, 4)
        )
    if not rows:
        th.hint(holder, "（无数据）").grid(row=1, column=0, columnspan=len(headers),
                                          sticky="w", padx=th.PAD_S, pady=th.PAD_S)
    for r, row in enumerate(rows, start=1):
        for c, cell in enumerate(row):
            ctk.CTkLabel(
                holder, text=str(cell), font=th.font(12), anchor="w", justify="left",
                wraplength=280,
            ).grid(row=r, column=c, sticky="ew", padx=th.PAD_S, pady=2)

