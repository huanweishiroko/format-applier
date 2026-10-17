# -*- coding: utf-8 -*-
"""关于页：版本、简介、技术栈、目录一览。"""

from __future__ import annotations

import os

import customtkinter as ctk

# 绝对优先，理由见 preview.py 顶部注释（frozen 下 ui/core 是顶层包）
try:
    from ui import theme as th
    from core import config as cfg
except ImportError:  # pragma: no cover - 包内运行时
    from . import theme as th  # type: ignore
    from ..core import config as cfg  # type: ignore

INTRO = (
    "桃符：把「格式要求」（自然语言要求或样式模板）落到一份 .docx 上，"
    "正文内容不动，只调整字体、字号、标题层级、列表、表格、对齐、缩进、行距与页面设置。\n\n"
    "所有处理都在你自己的电脑上完成，文档不会上传；只有你主动使用「AI 解析」时，"
    "才会把格式要求那几句话发给你自己配置的接口。"
)

STACK = (
    ("界面", "customtkinter（浅色 / 深色可切换）"),
    ("拖放", "tkinterdnd2（把文件直接拖进窗口）"),
    ("文档", "python-docx（读写 .docx，不改原文件）"),
    ("解析", "本地规则解析 + 可选 AI 语义解析"),
    ("网络", "除 AI 解析外不联网；Key 只保存在本机"),
    ("版本状态", cfg.PHASE_LABEL),
)


class AboutPage(ctk.CTkFrame):
    def __init__(self, master, app):
        # 不透明页底（原来是 "transparent"）：见 home.py 同处注释（tkraise 叠放下防串页）。
        super().__init__(master, corner_radius=0, fg_color=th.BG_PAGE)
        self.app = app

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        # 封面
        hero = th.card(scroll)
        hero.grid(row=0, column=0, sticky="ew", padx=th.PAD_L, pady=(th.PAD_L, th.PAD))
        hero.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hero, text="桃符", font=th.font(24, "bold"), anchor="w").grid(
            row=0, column=0, sticky="w", padx=th.PAD_L, pady=(th.PAD_L, 2)
        )
        ctk.CTkLabel(
            hero, text=f"版本 v{cfg.APP_VERSION} · {cfg.PHASE_LABEL}",
            font=th.font(13), anchor="w", text_color=th.TEXT_SECOND,
        ).grid(row=1, column=0, sticky="w", padx=th.PAD_L)
        ctk.CTkLabel(
            hero, text=INTRO, font=th.font(13), anchor="w", justify="left",
            wraplength=620,
        ).grid(row=2, column=0, sticky="w", padx=th.PAD_L, pady=(th.PAD, th.PAD_L))

        # 技术栈
        stack = th.card(scroll)
        stack.grid(row=1, column=0, sticky="ew", padx=th.PAD_L, pady=(0, th.PAD))
        stack.grid_columnconfigure(1, weight=1)
        th.section_title(stack, "技术栈").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=th.PAD, pady=(th.PAD, th.PAD_S)
        )
        for i, (key, value) in enumerate(STACK, start=1):
            ctk.CTkLabel(stack, text=key, font=th.font(13, "bold"), anchor="w").grid(
                row=i, column=0, sticky="w", padx=(th.PAD, th.PAD), pady=2
            )
            ctk.CTkLabel(stack, text=value, font=th.font(13), anchor="w", justify="left",
                         wraplength=460).grid(row=i, column=1, sticky="w", pady=2)
        ctk.CTkLabel(stack, text="", height=4).grid(row=len(STACK) + 1, column=0)

        # 目录一览
        paths = th.card(scroll)
        paths.grid(row=2, column=0, sticky="ew", padx=th.PAD_L, pady=(0, th.PAD))
        paths.grid_columnconfigure(1, weight=1)
        th.section_title(paths, "目录一览").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=th.PAD, pady=(th.PAD, th.PAD_S)
        )
        rows = (
            ("程序目录", cfg.APP_DIR),
            ("内置预设", cfg.PRESETS_DIR),
            ("用户数据", cfg.user_data_dir()),
            ("用户配置", cfg.CONFIG_PATH),
            ("API 配置", _env_source()),
            ("用户预设", _user_presets_dir()),
            ("输出目录", getattr(app.settings, "output_dir", "") or cfg.default_output_dir()),
            ("Token 统计", cfg.usage_path()),
        )
        for i, (key, path) in enumerate(rows, start=1):
            ctk.CTkLabel(paths, text=key, font=th.font(13, "bold"), anchor="w").grid(
                row=i, column=0, sticky="w", padx=(th.PAD, th.PAD), pady=2
            )
            ctk.CTkLabel(paths, text=cfg.display_path(path),
                         font=ctk.CTkFont(family="Consolas", size=12),
                         anchor="w").grid(row=i, column=1, sticky="w", pady=2, padx=(0, th.PAD))
        ctk.CTkLabel(paths, text="", height=4).grid(row=len(rows) + 1, column=0)

        # 底部按钮
        bar = ctk.CTkFrame(scroll, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew", padx=th.PAD_L, pady=(0, th.PAD_L))
        th.ghost_button(bar, "打开程序目录", self._open_root, width=140, height=32).grid(
            row=0, column=0, sticky="w"
        )
        th.hint(bar, "所有处理都在本机完成；用户预设只写你的账户目录。").grid(
            row=0, column=1, sticky="w", padx=th.PAD
        )

    def _open_root(self) -> None:
        try:
            os.startfile(str(cfg.APP_DIR))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            self.app.log(f"打开程序目录失败：{exc}")


def _env_source() -> str:
    """API 配置的实际来源（设置页 / 老版 .env / 尚未配置）。"""
    try:
        return cfg.api_source_label()
    except Exception:  # noqa: BLE001
        return "尚未配置"


def _user_presets_dir() -> str:
    """用户预设目录（导入失败时不拖垮关于页）。"""
    try:
        from core import user_presets as up
    except ImportError:  # pragma: no cover - 包内运行时
        from ..core import user_presets as up  # type: ignore
    try:
        return str(up.get_user_preset_dir(create=False))
    except Exception:  # noqa: BLE001
        return "(不可用)"
