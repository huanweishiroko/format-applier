# -*- coding: utf-8 -*-
"""预设管理页：列表 + 查看 / 编辑 / 复制 / 删除。

Phase 2 边界：预设列表、查看、编辑（纯文本）、复制、删除都是真的文件操作；
**不解析规则、不调用处理逻辑**（"查看"只展示文件原文与基本信息）。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Optional

import customtkinter as ctk

# 绝对优先，理由见 preview.py 顶部注释（frozen 下 ui/core 是顶层包）
try:
    from ui import dialogs as dlg
    from ui import theme as th
    from core import config as cfg
    from core import preset_loader as pl
except ImportError:  # pragma: no cover - 包内运行时
    from . import dialogs as dlg  # type: ignore
    from . import theme as th  # type: ignore
    from ..core import config as cfg  # type: ignore
    from ..core import preset_loader as pl  # type: ignore

#: 行卡的逻辑列（名称 / 来源 / 修改时间 / 操作）；Step 5 第二轮后不再画表头，
#: 这四项由卡内元素承担，常量只用于空状态提示的 columnspan。
COLUMNS = ((0, "预设名", 3), (1, "来源", 1), (2, "修改时间", 2), (3, "操作", 3))

#: 写 presets/ 被系统拒绝时的统一说明
WRITE_BLOCKED_HINT = (
    "该目录对当前进程只读（Windows 返回 Access Denied）。\n"
    "· 内置预设放在程序目录下的 presets\\ 里：请用文件资源管理器手动复制或删除；\n"
    "· 也可以改用「用户预设」——它保存在你自己的账户目录下，无需管理员权限。"
)


class PresetManagerPage(ctk.CTkFrame):
    """预设列表页。删除/复制后只刷新本页与首页下拉，不改任何预设内容。"""

    def __init__(self, master, app):
        # 不透明页底（原来是 "transparent"）：见 home.py 同处注释（tkraise 叠放下防串页）。
        super().__init__(master, corner_radius=0, fg_color=th.BG_PAGE)
        self.app = app
        self.presets: List[pl.Preset] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_toolbar()
        self._build_table()
        self.reload()

    # ------------------------------------------------------------------ #
    # 结构
    # ------------------------------------------------------------------ #

    def _build_header(self) -> None:
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=th.PAD_L, pady=(th.PAD_L, th.PAD_S))
        head.grid_columnconfigure(0, weight=1)

        th.page_title(head, "预设管理").grid(row=0, column=0, sticky="w")
        self.count_label = th.hint(head, "正在读取 presets/ …")
        self.count_label.grid(row=1, column=0, sticky="w", pady=(2, 0))

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=th.PAD_L, pady=(0, th.PAD_S))
        bar.grid_columnconfigure(0, weight=1)

        self.path_label = th.hint(bar, f"目录：{pl.presets_dir()}")
        self.path_label.grid(row=0, column=0, sticky="w")

        th.ghost_button(bar, "打开目录", self.open_dir, width=88, height=30).grid(
            row=0, column=1, padx=(0, th.PAD_S)
        )
        th.ghost_button(bar, "刷新", self.reload, width=72, height=30).grid(row=0, column=2)

    def _build_table(self) -> None:
        # 列表容器走工厂：容器底 = BG_SURFACE（纯白）+ BORDER 描边 + 调色板滚动条。
        # 行卡与分隔线都画在这层纯白底上（原来靠斑马纹分行，用户实测太淡已弃用）。
        self.table = th.scroll(self, page_level=False)
        self.table.grid(row=2, column=0, sticky="nsew", padx=th.PAD_L, pady=(0, th.PAD_L))
        self.table.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------ #
    # 数据
    # ------------------------------------------------------------------ #

    def reload(self) -> None:
        self.presets = pl.load_all_presets()
        self.app.set_presets(self.presets)
        builtin = sum(1 for p in self.presets if not p.is_user)
        user = len(self.presets) - builtin
        self.count_label.configure(
            text=f"共 {len(self.presets)} 个预设 · 内置 {builtin}（presets/）· "
                 f"用户 {user}（{pl.user_presets_dir()}）"
        )
        self._render()

    def _render(self) -> None:
        for child in self.table.winfo_children():
            child.destroy()

        if not self.presets:
            th.hint(self.table, "presets/ 下没有找到 .txt / .docx / .md 预设文件。").grid(
                row=0, column=0, columnspan=len(COLUMNS), sticky="w", padx=th.PAD, pady=th.PAD
            )
            return

        # 行卡：一行一个预设，不再用表头 + 网格（表头信息由卡内徽章/时间承担）。
        # 行与行之间用 1px 分隔线（th.divider）而不是斑马纹 —— BG_STRIPE 浅色 #FAFBFC
        # 与 BG_SURFACE #FFFFFF 只差 5/255（与页面底 #F7F8FA 更是只差 3/255），实测看不出来。
        # 分隔线挂在外层 plain 上而不是卡内：卡有 RADIUS_S 圆角，画在卡内会被圆角截短。
        # 外层的 padx 与卡一致，分隔线才能与卡左右沿齐平。
        for i, preset in enumerate(self.presets, start=1):
            holder = th.plain(self.table)
            holder.grid(row=i, column=0, sticky="ew", padx=th.SP.S)
            holder.grid_columnconfigure(0, weight=1)

            row = th.card(holder, corner_radius=th.RADIUS_S)
            row.grid(row=0, column=0, sticky="ew", pady=(th.SP.XS, 0))
            row.grid_columnconfigure(0, weight=1)

            # -- 顶部：预设名 + 来源胶囊 + 修改时间 ----------------------------
            top = th.plain(row)
            top.grid(row=0, column=0, sticky="ew", padx=th.PAD_S, pady=(th.SP.S, 2))
            top.grid_columnconfigure(0, weight=1)   # 名称列吃掉空隙 → 徽章贴右沿
            ctk.CTkLabel(top, text=preset.name, font=th.font(13, "bold"), anchor="w").grid(
                row=0, column=0, sticky="w"
            )
            th.badge(top, "👤 用户" if preset.is_user else "📦 内置",
                     tone="success" if preset.is_user else "muted").grid(
                row=0, column=1, padx=(th.PAD_S, 0)
            )
            th.hint(top, preset.mtime_label).grid(
                row=0, column=2, padx=(th.PAD_S, 0)
            )

            # -- 底部：文件信息 + 行内操作 -------------------------------------
            bottom = th.plain(row)
            bottom.grid(row=1, column=0, sticky="ew", padx=th.PAD_S, pady=(0, th.SP.S))
            bottom.grid_columnconfigure(0, weight=1)
            th.hint(bottom, f"{preset.file} · {preset.size_label} · {preset.ext_label}").grid(
                row=0, column=0, sticky="w"
            )

            actions = th.plain(bottom)
            actions.grid(row=0, column=1, sticky="e", padx=(th.PAD_S, 0))
            specs = (
                ("查看", lambda p=preset: self.view(p), {}),
                ("编辑", lambda p=preset: self.edit(p), {}),
                ("复制", lambda p=preset: self.copy(p), {}),
                # 行内危险操作：按 NOTES 口径走工厂透传，不用 danger= 实心底
                ("删除", lambda p=preset: self.delete(p),
                 {"text_color": th.DANGER, "hover_color": th.DANGER_SOFT}),
            )
            for c, (text, cmd, opts) in enumerate(specs):
                th.text_button(actions, text, cmd, width=th.BTN_W_S, **opts).grid(
                    row=0, column=c, padx=2
                )

            th.divider(holder).grid(row=1, column=0, sticky="ew", pady=(th.SP.S, 0))

    # ------------------------------------------------------------------ #
    # 操作
    # ------------------------------------------------------------------ #

    def view(self, preset: pl.Preset) -> None:
        body = pl.read_preview(preset)
        note = (f"文件：{preset.file} · {preset.size_label} · 修改于 {preset.mtime_label}\n"
                f"以下为文件的原始内容：")
        dlg.text_editor(self.app, f"查看预设 · {preset.name}", body,
                        editable=False, note=note)
        self.app.log(f"查看预设：{preset.file}")

    def edit(self, preset: pl.Preset) -> None:
        if preset.path is None or not preset.exists:
            dlg.error(self.app, "预设文件不存在。", detail=str(preset.path))
            return
        if preset.ext.lower() not in (".txt", ".md"):
            dlg.info(
                self.app,
                f"「{preset.name}」是 {preset.ext} 二进制模板，不能在文本框里直接编辑。",
                title="请用 Word 打开",
                detail="已为你用系统默认程序打开该文件；保存后回到本页点「刷新」即可。",
            )
            self.open_external(preset.path)
            return

        original = pl.read_preview(preset, limit=10 ** 7)
        readonly = not os.access(preset.path, os.W_OK)
        if readonly:
            dlg.info(
                self.app,
                f"当前对 {preset.file} 没有写权限，先以只读方式打开。",
                title="只读打开",
                detail=WRITE_BLOCKED_HINT,
            )

        def _save(text: str) -> bool:
            try:
                assert preset.path is not None
                preset.path.write_text(text, encoding="utf-8")
            except PermissionError as exc:
                self.app.log(f"保存被拒：{exc}")
                dlg.error(
                    self.app,
                    f"没有权限写入 {preset.file}。",
                    title="保存失败",
                    detail=WRITE_BLOCKED_HINT,
                )
                return False
            except OSError as exc:
                self.app.log(f"保存失败：{exc}")
                return False
            self.app.log(f"已保存预设：{preset.file}（{len(text)} 字符）")
            self.app.status(f"已保存预设 {preset.name}")
            self.after(500, self.reload)
            return True

        dlg.text_editor(self.app, f"编辑预设 · {preset.name}", original,
                        editable=not readonly, on_save=None if readonly else _save,
                        note=f"直接编辑 {preset.file}（UTF-8 保存）。解析缓存不自动清理，"
                             f"删除时可勾选一并清理。")

    def copy(self, preset: pl.Preset) -> None:
        if preset.path is None or not preset.exists:
            dlg.error(self.app, "预设文件不存在。", detail=str(preset.path))
            return
        if not os.access(pl.presets_dir(), os.W_OK):
            dlg.error(
                self.app,
                f"当前环境对 {pl.presets_dir()} 没有写权限，无法新建预设。",
                title="无法复制",
                detail=WRITE_BLOCKED_HINT,
            )
            self.app.log("复制预设被拒：presets/ 目录不可写")
            return
        new_name = self._ask_name(preset)
        if not new_name:
            return
        target = pl.presets_dir() / f"{new_name}{preset.ext}"
        if target.exists():
            dlg.error(self.app, f"「{target.name}」已存在，换一个名字。", title="重名")
            return
        try:
            shutil.copy2(preset.path, target)
        except PermissionError:
            dlg.error(self.app, "没有权限在该目录新建文件。", title="复制失败",
                      detail=WRITE_BLOCKED_HINT)
            return
        except OSError as exc:
            dlg.error(self.app, "复制失败。", detail=str(exc))
            return
        self.app.log(f"已复制预设：{preset.file} → {target.name}")
        self.app.status(f"已复制为 {target.name}")
        self.reload()

    def delete(self, preset: pl.Preset) -> None:
        if preset.path is None or not preset.exists:
            dlg.error(self.app, "预设文件不存在。", detail=str(preset.path))
            return
        cache = cfg.PRESETS_DIR / ".cache"
        cache_hint = "，并清理 presets/.cache 解析缓存" if cache.is_dir() else ""
        if not dlg.confirm(
            self.app,
            f"删除预设「{preset.name}」？",
            title="删除确认",
            ok_text="删除",
            danger=True,
            detail=f"将删除文件 {preset.file}{cache_hint}。此操作不可撤销。",
        ):
            return
        try:
            preset.path.unlink()
        except PermissionError:
            dlg.error(self.app, f"没有权限删除 {preset.file}。", title="删除失败",
                      detail=WRITE_BLOCKED_HINT)
            return
        except OSError as exc:
            dlg.error(self.app, "删除失败。", detail=str(exc))
            return

        cleared = 0
        if cache.is_dir():
            for item in cache.glob("*.json"):
                try:
                    item.unlink()
                    cleared += 1
                except OSError:
                    pass
        self.app.log(f"已删除预设：{preset.file}；清理解析缓存 {cleared} 个文件")
        self.app.status(f"已删除预设 {preset.name}")
        self.reload()

    # ------------------------------------------------------------------ #
    # 小工具
    # ------------------------------------------------------------------ #

    def _ask_name(self, preset: pl.Preset) -> Optional[str]:
        win = dlg.ModalWindow(self.app, "复制预设", (420, 230))
        win.body.grid_rowconfigure(2, weight=1)

        th.hint(win.body, f"以「{preset.name}」为模板创建一个新预设").grid(
            row=0, column=0, sticky="ew", pady=(th.PAD_S, th.PAD_S)
        )
        var = ctk.StringVar(value=f"{preset.name} - 副本")
        entry = th.entry(win.body, textvariable=var)
        entry.grid(row=1, column=0, sticky="ew")
        entry.focus_set()
        entry.select_range(0, "end")

        bar = ctk.CTkFrame(win.body, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="e", pady=(th.PAD, 0))

        def _ok() -> None:
            win.destroy()

        th.ghost_button(bar, "取消", win.destroy, width=88).grid(row=0, column=0, padx=6)
        th.primary_button(bar, "复制", _ok, width=88).grid(row=0, column=1, padx=6)
        win.bind("<Return>", lambda _e: _ok())
        entry.bind("<Return>", lambda _e: _ok())
        win.wait_window()
        return var.get().strip() or None

    def open_dir(self) -> None:
        self.open_external(pl.presets_dir())

    def open_external(self, path: Path) -> None:
        try:
            import os

            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows 专用
            self.app.log(f"已用系统默认程序打开：{path}")
        except Exception as exc:  # noqa: BLE001
            self.app.log(f"打开失败：{exc}")
            dlg.error(self.app, "无法打开。", detail=str(exc))
