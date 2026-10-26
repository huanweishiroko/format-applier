# -*- coding: utf-8 -*-
"""桃符 · 桌面外壳（Phase 2：GUI 骨架 + 假数据）。

运行：
    .venv\\Scripts\\python.exe desktop\\app.py

Phase 2 边界：界面、导航、拖拽、预设列表是真的；预览 / 处理 / 上传一律占位。
不 import 任何处理逻辑，也不调用插件 CLI 的处理命令。
"""

from __future__ import annotations

import os
import sys
import time

# --------------------------------------------------------------------------- #
# Phase 4 · 打包入口：exe 自调用时不进 GUI，直接转交插件 CLI
# --------------------------------------------------------------------------- #
# PyInstaller 打完包后 bridge.py 走的是 `[sys.executable, "--wfa-cli", ...]`
# （见 core/bridge.py 的 cli_argv()），也就是让 exe 调自己。
# 这个分支必须在本文件 import customtkinter / tkinter 之前判断并退出：
#   * 否则窗口模式（--windowed）的 exe 会白白初始化一次 Tk；
#   * 也让 `python desktop/app.py --wfa-cli ...` 在开发期能以同样方式自测。
# 窗口模式 exe 的 sys.stdout / sys.stderr 是 None，CLI 一 print 就会
# AttributeError；而 GUI 要靠 stdout 的管道收 JSON 摘要，所以这里临时把
# 它们接到重定向后的真实管道上，跑完再把原值放回去。
if len(sys.argv) > 1 and sys.argv[1] == "--wfa-cli":
    # 剥离自己这个开关，剩下的 argv 原样交给插件 CLI
    sys.argv = [sys.argv[0]] + sys.argv[2:]

    def _restore_standard_streams():
        """窗口模式（sys.stdout is None）下把标准流重定向到管道的还原函数。"""
        if sys.stdout is not None and sys.stderr is not None:
            return lambda: None
        saved = (sys.stdout, sys.stderr)
        originals = (sys.__stdout__, sys.__stderr__)
        for name in ("stdout", "stderr", "stdin"):
            stream = getattr(sys, name, None)
            if stream is None:
                stream = getattr(sys, "__" + name + "__", None)
            if stream is None:
                continue
            try:
                setattr(sys, name, stream)
            except (AttributeError, TypeError):  # pragma: no cover - 极端只读场景
                pass

        def restore():
            sys.stdout, sys.stderr = saved
            sys.__stdout__, sys.__stderr__ = originals

        return restore

    _restore_streams = _restore_standard_streams()
    try:
        from word_format_applier.cli import main as cli_main

        _exit_code = cli_main()
    except SystemExit as exc:  # argparse 的 --version/报错 走这里
        _exit_code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException as exc:  # noqa: BLE001 - 子进程必须拿到可读原因
        try:
            print(f"[wfa] 打包入口 --wfa-cli 失败：{type(exc).__name__}: {exc}",
                  file=sys.stderr)
        except Exception:  # noqa: BLE001 - 标准流不可用时静默退出
            pass
        _exit_code = 1
    finally:
        try:
            _restore_streams()
        except Exception:  # noqa: BLE001
            pass
    # 不用 raise SystemExit：v3.4+ 的 PyInstaller 引导脚本会在退出时
    # 打印 "Failed to execute script"，那行会被 GUI 的 _parse_json 当成脏输出。
    sys.exit(_exit_code)

import tkinter as tk
from pathlib import Path
from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# 启动引导：让 `python desktop/app.py` 与 `python -m desktop.app` 都能跑
# --------------------------------------------------------------------------- #
# 直跑脚本时 __package__ 为空，包内相对导入会失效。这里给 desktop/ 注册一个
# 合成包名 `_wfa_desktop`，把 <desktop>/.. 放进 sys.path，然后把本模块自己
# 以该包名登记进 sys.modules —— 之后子模块里的 `from ..core import ...` 就有
# 了合法的父包，两种启动方式走同一套导入路径。
_DESKTOP_DIR = Path(__file__).resolve().parent
if str(_DESKTOP_DIR) not in sys.path:
    sys.path.insert(0, str(_DESKTOP_DIR))

_PACKAGE_NAME = __package__ or "_wfa_desktop"
# frozen（PyInstaller）下 __file__ 指向的 _internal\app.py 根本不存在，合成包一定
# 注册失败；而冻结产物里 core/ui 本来就是顶层包，用不着这层伪装。所以直接跳过，
# 免得每次启动都往 stderr 吐一行误导性的"[warn] 包引导失败"。
# 保留 desktop/__init__.py 的合成注册只为开发期 `python desktop/app.py` 服务。
if not getattr(sys, "frozen", False) and _PACKAGE_NAME == "_wfa_desktop" \
        and _PACKAGE_NAME not in sys.modules:
    _root_dir = str(_DESKTOP_DIR.parent)
    if _root_dir not in sys.path:
        sys.path.insert(0, _root_dir)
    try:
        import importlib.util

        _spec = importlib.util.spec_from_file_location(
            _PACKAGE_NAME, str(_DESKTOP_DIR / "__init__.py"),
            submodule_search_locations=[str(_DESKTOP_DIR)],
        )
        if _spec is not None and _spec.loader is not None:
            _package = importlib.util.module_from_spec(_spec)
            sys.modules[_PACKAGE_NAME] = _package
            _spec.loader.exec_module(_package)
            sys.modules[f"{_PACKAGE_NAME}.__main__"] = sys.modules["__main__"]
    except Exception as exc:  # noqa: BLE001 - 引导失败时退化为顶层导入
        print(f"[warn] 包引导失败，改用顶层导入：{exc}", file=sys.stderr)
        _PACKAGE_NAME = ""

from core import bridge as br  # noqa: E402
from core import config as cfg  # noqa: E402
from core import preset_loader as pl  # noqa: E402
from ui import dialogs as dlg  # noqa: E402
from ui import theme as th  # noqa: E402

import customtkinter as ctk  # noqa: E402 - 必须在 DnD 注入前先导入

#: 切页时是否整页强制重绘（默认关）。开 = 切换更"原子"但每次多阻塞 ~70ms；
#: 关 = 保持 ~17ms，重绘留给事件循环以每帧 ~50ms 渐进完成。
#: 对比用：`$env:WFA_PAGE_FULL_REPAINT="1"` 后重开程序。
_FULL_REPAINT_ON_SWITCH = os.environ.get("WFA_PAGE_FULL_REPAINT", "").lower() in (
    "1", "true", "yes", "on")

#: 切页时把「遮罩盖住 → 撤掉」的耗时打到 stdout（默认关）。
#: 对比用：`$env:WFA_PAGE_TRACE="1"` 后重开程序，每次切页会多打一行。
_PAGE_TRACE = os.environ.get("WFA_PAGE_TRACE", "").lower() in ("1", "true", "yes", "on")

#: 切页过渡遮罩开关（默认开）。关掉 = 退回"直接换页"的老行为，
#: 观感上还会看到两页混合，但每次切页少 ~26ms。
#: 对比用：`$env:WFA_PAGE_MASK="0"` 后重开程序。
_MASK_ON_SWITCH = os.environ.get("WFA_PAGE_MASK", "1").lower() not in (
    "0", "false", "no", "off")

WFA_CLI_DETECT_HOOK = "--wfa-cli"


# --------------------------------------------------------------------------- #
# 拖放能力（tkinterdnd2 与 customtkinter 的兼容点）
# --------------------------------------------------------------------------- #
# 背景：tkinterdnd2 的标准用法是以 TkinterDnD.Tk() 作为根窗口，但本程序的根是
# customtkinter 的 CTk。实测表明不必改 MRO、也不必自己写根类：
#   * DnDWrapper 把 drop_target_register / dnd_bind 挂在 tkinter.BaseWidget 上，
#     所以 CTk 的任何内部 canvas 天然带这两个方法；
#   * 缺的只是"加载 tkdnd 扩展"这一步（TkinterDnD.Tk.__init__ 里做的 _require）。
# 因此建完根窗口后手工调一次 TkinterDnD._require(root)，拖放即全部可用。
# 实测环境：Tcl/Tk 8.6.12 + tkdnd 2.10.2。


def dnd_ready() -> bool:
    """tkdnd 扩展是否已加载（加载成功后 drop_target_register 才真正生效）。"""
    try:
        from tkinterdnd2 import TkinterDnD

        return bool(TkinterDnD.TkdndVersion)
    except Exception:  # noqa: BLE001
        return False


def enable_dnd(root) -> bool:
    """在任意 tkinter 根窗口上加载 tkdnd。失败返回 False（拖放降级为点击选择）。"""
    if dnd_ready():
        from tkinterdnd2 import TkinterDnD

        print(f"[dnd] tkdnd 已就绪，版本 {TkinterDnD.TkdndVersion}", file=sys.stderr)
        return True
    try:
        from tkinterdnd2 import TkinterDnD

        version = TkinterDnD._require(root)  # 正常返回版本号字符串
        ok = dnd_ready()
        print(f"[dnd] TkinterDnD._require() -> {version!r}，dnd_ready={ok}", file=sys.stderr)
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] tkdnd 加载失败，拖放降级为点击选择：{type(exc).__name__}: {exc}",
              file=sys.stderr)
        return False


def wfa_cli_detect() -> Optional[str]:
    """探测插件 CLI 入口（Phase 3 生效）。

    * 打包后：exe 自己实现 ``--wfa-cli``，这里只回报入口形态，不发子进程。
    * 开发期：真正调一次 ``--list-presets-json`` 验证 .venv + src 可用。
    """
    if br.frozen():
        return "已启用（内置）"
    if br.cli_available():
        return "已启用（开发模式）"
    return None


# --------------------------------------------------------------------------- #
# 主窗口
# --------------------------------------------------------------------------- #


class FormatApp(ctk.CTk):
    """主窗口：左侧导航 + 内容区 + 底部状态栏。"""

    def __init__(self) -> None:
        super().__init__()

        # 窗口/任务栏图标（v2.0.0）：只读资源，frozen 走 _MEIPASS、开发期走 desktop/assets。
        # 图标缺失或 Tk 不认这个 .ico 都不该拦住启动，所以整体吞异常，只把结果记进启动日志。
        # 日志里只说"成没成"，不打印本机绝对路径（用户看了也没用）。
        self.icon_status = "未设置"
        try:
            _icon = cfg.asset_path("taofu.ico")
            if _icon.is_file():
                self.iconbitmap(str(_icon))
                self.icon_status = "已加载"
            else:
                self.icon_status = "未找到图标文件"
        except Exception as exc:  # noqa: BLE001 - 图标失败不影响主流程
            self.icon_status = f"加载失败（{type(exc).__name__}）"

        # 先备好 log() 依赖的容器：万一下面写配置文件失败，log() 不能反过来炸
        self.presets: List[pl.Preset] = []
        self.pages: Dict[str, ctk.CTkFrame] = {}
        self.nav_buttons: Dict[str, ctk.CTkButton] = {}
        self.nav_accents: Dict[str, ctk.CTkFrame] = {}
        self.current_key: str = ""
        self.dnd_available = False
        self._legacy_checked = False
        #: 最近一次 save_settings() 的真实失败原因/落点（给设置页展示具体错误）
        self.last_save_error: str = ""
        self.last_save_path = cfg.CONFIG_PATH
        #: 所有配置目录都写不进时只弹一次提示，避免每次改设置都弹
        self._save_error_notified = False

        self.settings = cfg.load_settings()
        # 所有候选目录都写不进时，即使不是首次启动也强制走一次保存，
        # 让 save_settings() 弹出“配置文件无法保存”的提示（只弹一次）。
        if cfg.pick_writable_data_dir() is None:
            self.settings.first_run = True
        # 输出目录落实：config.json 里没有（首次启动）→ 用户文档目录并落盘
        self.settings.output_dir = cfg.ensure_output_dir(self.settings.output_dir)
        if self.settings.first_run:
            self.settings.first_run = False
            self.save_settings()
        self.cli_entry = wfa_cli_detect()

        self.title(f"{cfg.APP_NAME} · v{cfg.APP_VERSION}")
        self.geometry(self.settings.window_size)
        self.minsize(860, 600)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        ctk.set_appearance_mode(self.settings.ctk_appearance)
        ctk.set_default_color_theme("blue")
        th.apply_root_theme(self)
        self.dnd_available = enable_dnd(self)

        self._build_sidebar()
        self._build_content()
        self._build_statusbar()
        self._build_pages()

        # 切页过渡遮罩（NOTES「十」）：必须建在 4 页**之后** —— 兄弟控件的层级按创建顺序，
        # 建在前面会被页面盖住。同一格常驻 + tkraise 已经消掉了 190ms 的 unmap/map，
        # 但 Windows 上 Tk 的重绘是分帧提交的，`update()` 强制不了"旧页像素、新页像素"
        # 同帧上屏，中间那几帧就是用户看到的"两页混合"。遮罩把这些混合帧换成一块纯色。
        self._mask = ctk.CTkFrame(self.content, corner_radius=0, fg_color=th.BG_PAGE)
        self.mask_ms: List[float] = []          # 每次切页的遮罩停留耗时（自检脚本读）
        self.mask_hold_ms: List[float] = []     # 遮罩真正在屏的时长（place → place_forget）

        self.show_page("home")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Control-q>", lambda _e: self.on_close())

        self.after(80, self._boot)
        self.log(f"{cfg.APP_NAME} v{cfg.APP_VERSION} · {cfg.PHASE_LABEL}")
        self.log(f"窗口图标：{self.icon_status}")
        self.log(f"拖放能力：{'已注入' if self.dnd_available else '不可用（降级为点击选择）'}")
        self.log(f"文档处理引擎：{self.cli_entry or '不可用（只读预览）'}")
        self.log(f"AI 解析配置：{cfg.api_source_label()}")

    # ------------------------------------------------------------------ #
    # 布局
    # ------------------------------------------------------------------ #

    def _build_sidebar(self) -> None:
        bar = ctk.CTkFrame(
            self, width=th.SIDEBAR_WIDTH, corner_radius=0, fg_color=th.BG_SIDEBAR
        )
        bar.grid(row=0, column=0, rowspan=2, sticky="nsw")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_rowconfigure(len(th.NAV_ITEMS) + 2, weight=1)

        brand = th.plain(bar)
        brand.grid(row=0, column=0, sticky="ew", padx=th.PAD, pady=(th.PAD_L, th.PAD))
        ctk.CTkLabel(brand, text="▸ 桃符", font=th.font(th.FS.H2, "bold"),
                     text_color=th.TEXT, anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(brand, text="桌面版外壳", font=th.font(th.FS.SMALL), anchor="w",
                     text_color=th.TEXT_MUTED).grid(row=1, column=0, sticky="w")

        th.divider(bar).grid(
            row=1, column=0, sticky="ew", padx=th.PAD_S, pady=(0, th.PAD_S)
        )

        self._nav_font = th.font(th.FS.LEAD)
        self._nav_font_active = th.font(th.FS.LEAD, "bold")
        for i, (key, label, icon) in enumerate(th.NAV_ITEMS, start=2):
            row = th.plain(bar)
            row.grid(row=i, column=0, sticky="ew")
            row.grid_columnconfigure(0, weight=1)

            # 选中态的左侧强调竖条：贴侧栏最左沿，用 place 定位，不参与 grid
            accent = ctk.CTkFrame(
                row,
                width=th.SIDEBAR_ACCENT_W,
                height=th.SIDEBAR_ITEM_H - th.SP.L,
                corner_radius=th.SP.XXS,
                fg_color=th.ACCENT,
            )

            button = ctk.CTkButton(
                row,
                text=f"  {icon}  {label}",
                font=self._nav_font,
                anchor="w",
                height=th.SIDEBAR_ITEM_H,
                corner_radius=th.RADIUS,
                fg_color=th.TRANSPARENT,
                hover_color=th.HOVER_FILL,
                text_color=th.TEXT_SECOND,
                command=lambda k=key: self.show_page(k),
            )
            button.grid(row=0, column=0, sticky="ew", padx=th.PAD_S, pady=th.SP.XXS)
            self.nav_buttons[key] = button
            self.nav_accents[key] = accent

        footer = ctk.CTkFrame(bar, fg_color=th.BG_SURFACE_ALT, corner_radius=th.RADIUS_S)
        footer.grid(row=len(th.NAV_ITEMS) + 3, column=0, sticky="ew", padx=th.PAD, pady=th.PAD)
        ctk.CTkLabel(footer, text=f"v{cfg.APP_VERSION}", font=th.font(th.FS.CAPTION), anchor="w",
                     text_color=th.TEXT_MUTED).grid(row=0, column=0, sticky="w",
                                                    padx=th.PAD_S, pady=(th.SP.XS, 0))
        ctk.CTkLabel(footer, text=cfg.PHASE_LABEL, font=th.font(th.FS.CAPTION), anchor="w",
                     text_color=th.TEXT_MUTED).grid(row=1, column=0, sticky="w",
                                                    padx=th.PAD_S, pady=(0, th.SP.XS))

    def _build_content(self) -> None:
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(
            self, height=th.STATUSBAR_HEIGHT, corner_radius=0, fg_color=th.BG_STATUSBAR
        )
        bar.grid(row=1, column=1, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)
        bar.grid_rowconfigure(1, weight=1)

        th.divider(bar, fg_color=th.BORDER).grid(row=0, column=0, columnspan=3, sticky="ew")

        self.status_label = ctk.CTkLabel(
            bar, text=th.STATUS_TEXT, font=th.font(th.FS.SMALL), anchor="w",
            text_color=th.TEXT_SECOND,
        )
        self.status_label.grid(row=1, column=0, sticky="w", padx=th.PAD)

        self.progress = th.progress(bar, width=180)
        self.progress.grid(row=1, column=1, sticky="e", padx=th.PAD_S)
        self.progress.set(0)

        self.phase_label = ctk.CTkLabel(
            bar, text=cfg.PHASE_LABEL, font=th.font(th.FS.CAPTION), anchor="e",
            text_color=th.TEXT_MUTED,
        )
        self.phase_label.grid(row=1, column=2, sticky="e", padx=th.PAD)

    def _build_pages(self) -> None:
        """按当前包环境动态取页面类（三种启动方式都要能跑）。

        候选顺序（见文件顶部引导注释）：
          * ``desktop.app``   → ``desktop.ui.home``
          * 脚本直跑 / frozen → 顶层 ``ui.home``（frozen 走的正是这一条）
          * 合成包 ``_wfa_desktop``（开发期回退）
        逐个 try 而不是先判断 ``_PACKAGE_NAME``：后者一旦猜错就是
        "ModuleNotFoundError: No module named '_wfa_desktop.ui'"，且没有退路。
        """
        import importlib

        roots = [r for r in (__package__, _PACKAGE_NAME, "ui") if r]

        def load(module: str, attr: str):
            last: Optional[BaseException] = None
            for root in roots:
                try:
                    mod = importlib.import_module(f"{root}.{module}")
                except ImportError as exc:  # 换下一个候选
                    last = exc
                    continue
                return getattr(mod, attr)
            raise last if last is not None else ImportError(f"找不到页面模块 {module}")

        def page(module: str, attr: str):
            """返回一个"构造页面实例"的无参函数（先解析类，再实例化）。"""
            cls = load(module, attr)
            return lambda: cls(self.content, self)

        factories = (
            ("home", page("home", "HomePage")),
            ("presets", page("preset_manager", "PresetManagerPage")),
            ("settings", page("settings", "SettingsPage")),
            ("about", page("about", "AboutPage")),
        )
        # 焦点治理用的缓存：页 → 目标控件（构建期扫一次；页面重建内容后会置脏重扫）
        self._page_inputs: Dict[str, list] = {}     # 真正的输入控件（Entry/Text/Combobox）
        self._page_buttons: Dict[str, list] = {}    # CTk 按钮的自绘画布
        self._focus_dirty: set = set()              # 内容被重建、缓存需要重扫的页

        for key, factory in factories:
            page = factory()
            # 4 页全部映射到**同一格**（同 row/column/sticky），靠 tkraise 决定谁在最上层。
            # 不再 grid_remove()：Tk 每做一次 unmap→map，子树里每个 widget 都要重跑一遍
            # 默认值配置 + CTk canvas 全量重绘。实测同样 176 个控件的页面，重新映射一次
            # ≈190ms（其中几何传播 ~137ms + 画像素 ~150ms），而同样 4 页常驻、只 tkraise
            # 只要 ~22ms。这是「切页时控件一块一块冒出来」的根因（2026-10-08 实测）。
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
            self._collect_focus_targets(key, page)

    #: 真正吃键盘输入的控件类（Tk 默认让它们可聚焦，takefocus='' 即可）
    _INPUT_CLASSES = frozenset({"Entry", "Text", "TCombobox"})

    def _collect_focus_targets(self, key: str, page) -> None:
        """扫一遍页面，缓存两类焦点目标（只做一次，切页时不再遍历全树）。

        为什么不能按外层控件的 ``winfo_class()`` 过滤：CTk 的 ``CTkEntry`` /
        ``CTkButton`` 都报 ``Frame``，它们各自把真控件放在内层 ——
        ``CTkEntry._entry`` 是 ``Entry``，而 ``CTkButton`` **没有内层按钮**，
        它把文字画在自己的 canvas 上。所以按钮要进 Tab 链，只能对那个 canvas 设
        ``takefocus=1``（实测：不设则 ``tk_focusNext`` 完全跳过它；设了才进链）。

        ⚠️ 那个 canvas 的 ``winfo_class()`` 是 ``Canvas`` 但**真实类型是 ``CTkCanvas``**
        （CTk 自绘控件都用它），全页 186 个 Canvas 类控件里只有 4 个是普通 ``Canvas``，
        且没有一个 ``Canvas`` 是 ``CTkButton``（按钮本体是 ``Frame``）——
        所以判据必须是 ``CTkCanvas`` 且父控件是 ``CTkButton``。
        照 ``winfo_class()=="Canvas"`` 去找按钮会**一个都找不到**（实测踩过）。
        """
        inputs, buttons = [], []
        stack = [page]
        while stack:
            widget = stack.pop()
            try:
                cls = str(widget.winfo_class())
                if cls in self._INPUT_CLASSES:
                    inputs.append(widget)
                elif cls == "Button" and not isinstance(widget, ctk.CTkBaseClass):
                    buttons.append(widget)          # 真 tk 按钮（本项目暂无，留个口子）
                elif isinstance(widget, ctk.CTkCanvas) and isinstance(
                        getattr(widget, "master", None), ctk.CTkButton):
                    buttons.append(widget)          # CTk 按钮的自绘画布（唯一可治理面）
                stack.extend(widget.winfo_children())
            except Exception:  # noqa: BLE001 - 控件异常/正在销毁 → 跳过
                continue
        self._page_inputs[key] = inputs
        self._page_buttons[key] = buttons

    # ------------------------------------------------------------------ #
    # 导航
    # ------------------------------------------------------------------ #

    def show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        # 过渡遮罩（NOTES「十」）：先盖住内容区并**立刻上屏**，再换页、重绘、撤遮罩。
        # 目的是把"旧页像素 / 新页像素"混合的那几帧换成一块纯色帧 ——
        # Windows 上 Tk 的重绘分帧提交，`update()` 保证不了两页同帧上屏。
        # 停留时长就是下面几步的自然耗时，**不加 after 延迟**（那只会让切页变慢）。
        #
        # ⚠️ 这里必须是 `update()` 而不是 `update_idletasks()`：实测（抓真实屏幕帧）
        # 遮罩的底色是 CTkFrame 的 canvas 在自己的 WM_PAINT 里画的，而 WM_PAINT
        # 走的是 **window 事件**；`update_idletasks()` 只处理 idle 队列，遮罩
        # winfo_ismapped() 已经 =1 但屏幕上一个像素都没画出来（与旧页逐像素相同）。
        _t0 = time.perf_counter()
        if _MASK_ON_SWITCH:
            self._mask.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._mask.lift()
            self.update()                       # 遮罩真正上屏（几帧纯色）
        # 4 页始终映射（见 _build_pages），切页只是把目标页提到最上层。
        # tkraise() 不动几何 → 实测 ~22ms（原来是 unmap/map 的 ~190ms）。
        self.pages[key].tkraise()
        # ⚠️ `tkraise()` 会把新页提到**遮罩之上**（两者是 content 的兄弟），
        # 只 lift 一次的话遮罩会被压回去、屏幕上完全看不到（实测：tkraise 之后
        # 内容区与"新页"参照逐像素相同）。所以换页后必须**再 lift 一次**。
        if _MASK_ON_SWITCH:
            self._mask.lift()
        # 可选：整页强制重绘。raise 后 Tk 只重绘"新暴露/脏"区域，其余沿用旧像素，
        # 极端情况下会看到"新页只画了一角、其余还是旧页"。标脏整页能消除这个中间态，
        # **但代价是 show_page 从 ~17ms 变成 ~86ms**（这 86ms 就是整页重绘本身，
        # 原来它以 ~50ms/帧的形式散在 show_page 返回之后）。
        # 默认关 → 保持现状；要看对比就设环境变量 WFA_PAGE_FULL_REPAINT=1。
        if _FULL_REPAINT_ON_SWITCH:
            try:
                self.pages[key].update_idletasks()
                tk.Misc.event_generate(self.pages[key], "<Expose>", when="tail")
            except Exception:  # noqa: BLE001 - 事件合成失败不影响切页
                pass
        for other, button in self.nav_buttons.items():
            active = other == key
            accent = self.nav_accents.get(other)
            if accent is not None:
                if active:
                    accent.place(x=0, rely=0.5, anchor="w")
                else:
                    accent.place_forget()
            button.configure(
                fg_color=th.ACCENT_SOFT if active else th.TRANSPARENT,
                text_color=th.ACCENT_TEXT if active else th.TEXT_SECOND,
                hover_color=th.HOVER_FILL_SUB if active else th.HOVER_FILL,
                font=self._nav_font_active if active else self._nav_font,
            )
        self.current_key = key
        # 页面常驻映射后，<Configure> 不再随切页发生 → 需要显式通知目标页"你现在露脸了"
        # （home 的滚动视口拉伸靠这个补算）。本方法属可选钩子，页面没实现就跳过。
        on_shown = getattr(self.pages[key], "on_shown", None)
        if callable(on_shown):
            on_shown()
        # Tab 焦点链：把非当前页整个摘出去，否则隐藏页的输入框仍在 Tab 顺序里
        self._sync_page_focus(key)
        label = dict((k, l) for k, l, _i in th.NAV_ITEMS).get(key, key)
        self.status(f"当前页面：{label}")
        # tkraise 只改 Z 序，**像素重绘是延后的**：这里同步刷一次，把新页在遮罩底下画完。
        # 遮罩紧跟着撤掉，屏幕上是"旧页 → 一块纯色 → 新页"；不刷的话撤掉遮罩时
        # 新页还没画完，混合帧照样露出来。
        self.update()
        _hold = 0.0
        if _MASK_ON_SWITCH:
            self._mask.place_forget()
            _hold = (time.perf_counter() - _t0) * 1000.0    # 遮罩在屏时间
            # 撤遮罩 = 把内容区整块暴露出来，Windows 会给下面的新页补一次重绘。
            # 再刷一次让它**在这次调用里**画完，否则那一次重绘会落到 show_page 返回之后，
            # 又变成"撤了遮罩、新页一块一块冒出来"。代价是这段重绘从异步变同步，
            # 总耗时不变（本来就要画），只是从"返回后 ~50ms/帧"挪到返回前一次做完。
            self.update()
        _ms = (time.perf_counter() - _t0) * 1000.0
        self.mask_hold_ms.append(_hold)
        self.mask_ms.append(_ms)
        if _PAGE_TRACE:
            print(f"[page] {key:<9} 遮罩在屏 {_hold:6.1f} ms · 方法总阻塞 {_ms:6.1f} ms",
                  flush=True)

    def _sync_page_focus(self, key: str) -> None:
        """把非当前页整个摘出 Tab 链，当前页的按钮则补进链。

        实证（2026-10-08，见 NOTES「十」）：
          * 未映射的控件 Tk 会自动跳过 —— 所以旧的 grid_remove 方案本来没这问题；
            改成 4 页常驻映射后，被压在下面的页面里的 ``Entry`` **会被 Tab 到**，
            这是 tkraise 方案必须付的税。
          * ``CTkButton`` 默认**不在**链里（它没有内层按钮，文字画在 canvas 上），
            要 ``takefocus=1`` 设到 ``CTkButton._canvas`` 上才会进链。
          * 对 CTk 外层控件 ``configure(takefocus=…)`` 会直接 ValueError，
            所以两个名单都在 ``_collect_focus_targets`` 里预先扫好。
        """
        for page_key in self.pages:
            if page_key in self._focus_dirty:       # 页面内容被重建过 → 缓存重扫
                self._collect_focus_targets(page_key, self.pages[page_key])
                self._focus_dirty.discard(page_key)
            active = page_key == key
            targets = ([(w, 0) for w in self._page_inputs.get(page_key, [])]
                       + [(w, 1 if active else 0)
                          for w in self._page_buttons.get(page_key, [])])
            for widget, flag in targets:
                try:
                    widget.configure(takefocus=flag)
                except Exception:  # noqa: BLE001 - 控件已销毁/不支持 → 跳过
                    continue

        # 焦点原本落在别的页面上 → 收回本页第一个输入控件，
        # 否则 Tk 会把焦点丢回主窗口，后续 Ctrl-Q 之类绑定失效。
        try:
            focused = self.focus_get()
        except Exception:  # noqa: BLE001
            return
        if not self._belongs_to_page(focused, self.pages[key]):
            self.focus_first_on_page(self.pages[key])

    @staticmethod
    def _belongs_to_page(widget, page) -> bool:
        node = widget
        while node is not None:
            if node is page:
                return True
            node = getattr(node, "master", None)
        return False

    def focus_first_on_page(self, page) -> None:
        """把焦点交给某页的第一个输入控件（依次退化为：按钮 → 主窗口）。"""
        for widget in self._focus_candidates(page):
            try:
                widget.focus_set()
                return
            except Exception:  # noqa: BLE001
                continue
        try:
            self.focus_set()
        except Exception:  # noqa: BLE001 - 抢焦点失败不影响功能
            pass

    def _focus_candidates(self, page):
        """某页内按优先级排好的焦点候选（输入控件优先，其次按钮 canvas）。"""
        for key, known in self.pages.items():
            if known is page:
                return (list(self._page_inputs.get(key, []))
                        + list(self._page_buttons.get(key, [])))
        return []

    # ------------------------------------------------------------------ #
    # 对外接口（页面用）
    # ------------------------------------------------------------------ #

    def status(self, text: str, progress: Optional[float] = None) -> None:
        self.status_label.configure(text=text)
        if progress is not None:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(max(0.0, min(1.0, progress)))

    def progress_mode(self, mode: str) -> None:
        """mode: 'determinate' | 'indeterminate'。"""
        if mode == "indeterminate":
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)

    def log(self, text: str) -> None:
        page = self.pages.get("home")
        if page is not None and hasattr(page, "append_log"):
            page.append_log(text)

    def toast(self, text: str, ms: int = 2200) -> None:
        self.status(text)
        self.after(ms, lambda: self.status(th.STATUS_TEXT))

    def set_presets(self, presets: List[pl.Preset]) -> None:
        self.presets = list(presets)
        home = self.pages.get("home")
        if home is not None and hasattr(home, "refresh_presets"):
            home.refresh_presets(self.presets)

    def reload_presets(self, select: Optional[str] = None) -> None:
        """重新合并「内置 + 用户」预设，刷新首页下拉与预设管理页。

        ``select`` 给定时自动选中该预设（上传新预设后调用）。
        """
        page = self.pages.get("presets")
        if page is not None and hasattr(page, "reload"):
            page.reload()          # 内部会再调 set_presets → 首页刷新
            # PresetManagerPage.reload() 会销毁并重建所有行卡 → 行内按钮全是新对象，
            # 旧的焦点目标缓存作废（不重扫的话新按钮不在 Tab 链里，实测 22 个只进 21 个）。
            self._focus_dirty.add("presets")
        else:                      # 预设页尚未建好时的退化路径
            self.set_presets(pl.load_all_presets())
        shadowed = pl.shadowed_names(self.presets)
        if shadowed:
            self.log(f"注意：{len(shadowed)} 个用户预设与内置同名并已覆盖 → "
                     f"{'、'.join(shadowed)}")
        if select:
            self.select_preset(select)

    def select_preset(self, name: str) -> None:
        """在首页下拉框里选中指定预设（按展示名匹配）。"""
        home = self.pages.get("home")
        if home is None:
            return
        for display, mapped in getattr(home, "_display_to_name", {}).items():
            if mapped == name:
                home.preset_var.set(display)
                self.set_last_preset(name)
                return

    def user_preset_dir(self) -> str:
        from core import user_presets as up  # 局部导入：避免启动期循环

        return str(up.get_user_preset_dir())

    def set_last_preset(self, name: str) -> None:
        self.settings.last_preset = name
        self.save_settings()

    def set_output_dir(self, path: str) -> None:
        self.settings.output_dir = path
        self.save_settings()

    def set_api_config(self, base_url: str, api_key: str, model: str) -> None:
        """设置页「保存配置」：三项 API 配置先记在内存，落盘由 save_settings 完成。"""
        self.settings.api_base_url = (base_url or "").strip()
        self.settings.api_key = (api_key or "").strip()
        self.settings.api_model = (model or "").strip()

    def apply_theme(self, theme: str) -> None:
        if theme not in cfg.THEME_CHOICES:
            return
        self.settings.theme = theme
        ctk.set_appearance_mode(self.settings.ctk_appearance)
        th.apply_root_theme(self)
        self.save_settings()
        self.log(f"主题切换 → {theme}")
        self.status(f"主题已切换为「{theme}」")

    def save_settings(self, notify: bool = True) -> bool:
        """写 config.json；失败时记录真实原因，必要时弹一次提示。

        候选目录 A→D 全写不进时，弹窗文案统一用
        ``cfg.CONFIG_UNWRITABLE_MESSAGE``（设置页自己会弹详细版时传
        ``notify=False``，避免弹两次）。
        """
        ok, target, error = cfg.save_settings_ex(self.settings)
        self.last_save_path = target
        self.last_save_error = error
        if not ok:
            self.log(f"配置保存失败：{error}")
            self.status(f"配置保存失败：{cfg.display_path(target)}")
            if notify and not self._save_error_notified:
                self._save_error_notified = True
                try:
                    dlg.error(self, cfg.CONFIG_UNWRITABLE_MESSAGE,
                              title="配置无法保存", detail=error)
                except Exception as exc:  # noqa: BLE001 - 弹窗失败不能反过来炸主流程
                    self.log(f"配置失败提示弹窗打不开：{type(exc).__name__}: {exc}")
            return False
        if target != cfg.CONFIG_PATH:
            where = cfg.config_location_label(target)
            self.log(f"主位置不可写，配置已改存到 {cfg.display_path(target)}（{where}）")
            # 状态栏说人话：用户不需要看懂 %APPDATA% 还是 dist 目录
            self.status(f"已存至{where}（主位置不可写，配置已自动改存）")
        return True

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    def _boot(self) -> None:
        """启动后的第一件事：读真实预设列表（内置 + 用户）。"""
        self.status("正在读取预设列表…")
        self.progress_mode("indeterminate")
        presets = pl.load_all_presets()
        self.set_presets(presets)
        self.progress_mode("determinate")
        builtin = [p for p in presets if not p.is_user]
        user = [p for p in presets if p.is_user]
        if presets:
            names = "、".join(p.name for p in presets)
            self.log(f"已加载 {len(presets)} 个预设（内置 {len(builtin)} · 用户 {len(user)}）：{names}")
            shadowed = pl.shadowed_names(presets)
            if shadowed:
                self.log(f"同名覆盖：{'、'.join(shadowed)}（用户预设生效）")
            self.status(f"就绪 · {len(presets)} 个预设 · 拖入 .docx 开始")
        else:
            self.log("没有找到可用预设（presets/ 与用户预设目录都是空的）")
            self.status("就绪 · 未找到预设")
        self.log(f"用户预设目录：{cfg.display_path(pl.user_presets_dir())}")
        active_cfg = cfg.active_config_path()
        if active_cfg != cfg.CONFIG_PATH:
            # 降级不是错误，别让用户以为配置丢了：说清楚“存哪了、还能用”
            label = cfg.config_location_label(active_cfg)
            self.log(f"配置来自{label}：{cfg.display_path(active_cfg)}"
                     "（主位置不可写，已自动改存）")
            prefix = f"就绪 · {len(presets)} 个预设" if presets else "就绪"
            self.status(f"{prefix} · 配置已存至{label}")
        self.check_legacy_files()

    # ------------------------------------------------------------------ #
    # 一次性迁移（旧版把 .env / config.json / output\ 放在 _internal\ 里）
    # ------------------------------------------------------------------ #

    def check_legacy_files(self) -> None:
        """检测旧版用户文件，问一次是否搬到新位置。只复制、不删除。"""
        if self._legacy_checked:
            return
        self._legacy_checked = True
        try:
            items = cfg.legacy_items(self.settings.output_dir)
        except Exception as exc:  # noqa: BLE001 - 检测失败不该拦住启动
            self.log(f"旧版文件检测跳过：{type(exc).__name__}: {exc}")
            return
        if not items:
            return

        labels = {"env": "API 配置 .env", "config": "用户配置 config.json", "output": "输出文件"}
        detail = "\n".join(
            f"{labels.get(i['kind'], i['kind'])}：{i['source']}  →  {i['target']}" for i in items
        )
        if not dlg.confirm(
            self, "检测到旧版程序目录里的用户文件：",
            title="迁移旧版文件", ok_text="复制到新位置", cancel_text="暂不",
            detail=detail + "\n（旧文件保留在原处，不会删除）",
        ):
            self.log("旧版文件未迁移（旧文件仍在 _internal\\ 里，程序仍能读到 .env）")
            return

        done, errors = cfg.apply_migration(items)
        self.log(f"旧版文件迁移：复制 {done} 个文件"
                 + (f"，{len(errors)} 个失败" if errors else ""))
        for line in errors[:5]:
            self.log(f"  迁移失败：{line}")
        if done:
            dlg.info(self, f"已复制 {done} 个文件到新位置。", title="迁移完成",
                     detail="\n".join(f"{i['kind']} → {i['target']}" for i in items))
            self.refresh_paths()

    def refresh_paths(self) -> None:
        """路径变动后刷新各页显示（设置页的输出目录、API 来源等）。"""
        page = self.pages.get("settings")
        if page is not None and hasattr(page, "refresh_paths"):
            page.refresh_paths()

    def on_close(self) -> None:
        try:
            self.settings.window_size = f"{self.winfo_width()}x{self.winfo_height()}"
            self.save_settings()
        finally:
            import dnd as _dnd  # 还原窗口过程，避免 Tk 销毁后仍有回调

            _dnd.unhook()
            self.destroy()


# --------------------------------------------------------------------------- #
# 自检（隐藏开关：--selftest，跑一遍界面关键路径后退出）
# --------------------------------------------------------------------------- #


def run_selftest() -> int:
    """把界面关键路径跑一遍（含弹窗），最后自动退出。

    会在**用户预设目录**（%APPDATA%\\Taofu\\presets）里真实创建并删除
    一个名为「自检临时预设」的文件，用于验证保存/可见/删除路径；
    项目里的 presets/ 只读不写。
    """
    import threading

    app = FormatApp()
    results: List[str] = []

    def schedule_escape(delay: float = 0.6) -> None:
        """弹窗是模态的，用后台定时器发 ESC 把它关掉，避免自检卡死。"""
        def worker() -> None:
            import time as _t

            _t.sleep(delay)
            try:
                app.event_generate("<Escape>", when="tail")
            except Exception:  # noqa: BLE001 - 关不掉就算了，有兜底超时
                pass

        threading.Thread(target=worker, daemon=True).start()

    def finish(code: int = 0) -> None:
        print("\n".join(results))
        print(f"RESULT: {'SELFTEST_OK' if code == 0 else 'SELFTEST_FAIL'}")
        app.destroy()
        if code != 0:
            raise SystemExit(code)

    def step_nav() -> None:
        for key in ("presets", "settings", "about", "home"):
            app.show_page(key)
            app.update()
            ok = app.current_key == key and app.pages[key].winfo_ismapped()
            results.append(f"nav {key}: {'OK' if ok else 'FAIL'}")
        app.after(60, step_presets)

    def step_presets() -> None:
        home = app.pages["home"]
        names = list(home.preset_menu.cget("values"))
        results.append(f"presets: {len(names)} 个 → {names}")
        results.append(f"preset_selected: {home.preset_var.get()}")
        results.append(f"tkdnd: {app.dnd_available}")
        app.after(60, step_file)

    def step_file() -> None:
        sample = cfg.PROJECT_ROOT / "samples"
        docx = next((p for p in sorted(sample.glob("*.docx"))), None)
        if docx is None:
            results.append("file: 跳过（samples/ 下没有 .docx）")
            app.after(60, step_dialogs)
            return
        app.pages["home"].load_file(docx)
        app.update()
        app.update_idletasks()

        def check() -> None:
            home = app.pages["home"]
            label = home.file_name.cget("text")
            meta = {k: v.cget("text") for k, v in home.file_meta_labels.items()}
            results.append(f"file: {label} · {meta}")
            app.after(60, step_dialogs)

        app.after(700, check)

    def step_dialogs() -> None:
        """预览 / 上传 / 处理三条入口：按当前是否有文件与预设，走真实路径或提示弹窗。"""
        home = app.pages["home"]
        for name, opener in (
            ("preview", home.preview),
            ("upload-format", home.upload_format),
            ("start-process", home.start_process),
        ):
            schedule_escape()
            try:
                opener()
                results.append(f"dialog {name}: OK")
            except Exception as exc:  # noqa: BLE001
                results.append(f"dialog {name}: FAIL {type(exc).__name__}: {exc}")
            app.update()
        results.append(f"ready: file={bool(home.selected_file)} preset={bool(home.current_preset())}")
        app.after(200, step_preset_io)

    def step_preset_io() -> None:
        """用户预设目录的 保存 → 可见 → 删除（不碰项目里的 presets/）。"""
        from core import user_presets as up

        probe = "自检临时预设"
        try:
            path = up.save_user_preset(probe, "标题：黑体 二号 居中\n正文：宋体 小四\n")
        except (OSError, ValueError) as exc:
            results.append(f"user preset save: FAIL {type(exc).__name__}: {exc}")
            app.after(60, step_final)
            return
        results.append(f"user preset save: OK → {path.name}")

        app.reload_presets()
        app.update()
        visible = [p for p in app.presets if p.is_user and p.name == probe]
        results.append(f"user preset visible: {'OK' if visible else 'FAIL'}"
                       f"（下拉 {len(app.pages['home'].preset_menu.cget('values'))} 项）")

        try:
            up.delete_user_preset(probe)
            gone = True
        except (OSError, FileNotFoundError) as exc:
            gone = False
            results.append(f"user preset delete: FAIL {exc}")
        app.reload_presets()
        app.update()
        still = any(p.is_user and p.name == probe for p in app.presets)
        if gone:
            results.append(f"user preset delete: {'OK' if not still else 'FAIL'}")
        app.after(60, step_final)

    def step_final() -> None:
        home = app.pages["home"]
        home.toggle_log()
        app.update()
        home.toggle_log()
        app.apply_theme("深色" if app.settings.theme == "浅色" else "浅色")
        app.update()
        app.apply_theme("浅色")
        app.update()
        results.append("theme toggle: OK")
        results.append(f"preset page rows: {len(app.pages['presets'].presets)}")
        results.append(f"window: {app.title()} {app.winfo_width()}x{app.winfo_height()} "
                       f"(minsize 860x600)")
        results.append(f"status bar: {app.status_label.cget('text')}")
        failed = [r for r in results if "FAIL" in r]
        finish(1 if failed else 0)

    app.after(300, step_nav)
    # 兜底：任何一步卡死都不至于挂住终端
    app.after(60000, lambda: finish(1))
    app.mainloop()
    return 0


def _claim_taskbar_identity() -> None:
    """给本进程一个独立的 AppUserModelID，任务栏才会认我们的窗口图标。

    不设的话，开发期直接跑 ``python.exe desktop\\app.py`` 时 Windows 按 python.exe
    的身份分组，任务栏按钮显示的是 python 的图标而不是桃符的 —— 与 .ico 本身无关。
    打包成 exe 后图标来自 exe 资源，本来就没这个问题；这里是为了让开发期也能验。
    纯 stdlib（ctypes），失败一律吞掉，不影响启动。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Taofu.Desktop")
    except Exception:  # noqa: BLE001 - 拿不到身份就算了
        pass


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    # 越早越好：必须在创建任何顶层窗口之前，任务栏才会按新身份归组
    _claim_taskbar_identity()

    # v2.0.0 一次性迁移：旧版 %APPDATA%\WordFormatAssistant → %APPDATA%\Taofu。
    # 必须排在**任何 load_settings() 之前**；只复制不删旧目录，失败也只记一行、不拦启动。
    _migrate_note = cfg.migrate_legacy_data()

    if "--selftest" in args:
        return run_selftest()
    app = FormatApp()
    if _migrate_note:
        app.log(_migrate_note)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
