# -*- coding: utf-8 -*-
"""上传格式要求（Phase 3）。

三条输入路径，全部接到 Phase 1 的 parser：

  ==================  ==========================================  ==========
  输入                处理                                        是否花钱
  ==================  ==========================================  ==========
  ``.txt``（已是 DSL）  ``txt_parser.parse_txt`` → 直接展示         否
  ``.txt``（自然语言）   ``txt_parser`` 判定 → ``llm_parser`` 转 DSL  是
  ``.docx``            ``docx_extractor`` 取样式指纹 → LLM 转 DSL    是
  粘贴的文本            按自然语言走 ``llm_parser``                 是
  ==================  ==========================================  ==========

拿到 DSL 后：弹窗里可**手工编辑** → [确认使用] → 询问是否存为用户预设 →
存则落盘到 ``%APPDATA%\\Taofu\\presets\\user_<时间戳>_<名字>.txt``，
并让首页刷新下拉框、自动选中新预设。

API Key 缺失：给明确提示 + 一个「打开设置」按钮。
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog
from typing import Callable, Optional, Tuple

import customtkinter as ctk

# 绝对优先，理由见 preview.py 顶部注释（frozen 下 ui/core 是顶层包）
try:
    from ui import dialogs as dlg
    from ui import theme as th
    from core import user_presets as up
except ImportError:  # pragma: no cover - 包内运行时
    from . import dialogs as dlg  # type: ignore
    from . import theme as th  # type: ignore
    from ..core import user_presets as up  # type: ignore


#: parser 包在 desktop/parser/ 下（Phase 1 交付），按需延迟 import
def _parser_modules():
    # 同样绝对优先：frozen 下 `from ..parser import ...` 会越过顶层包
    try:
        from parser import docx_extractor, llm_parser, txt_parser
    except ImportError:  # pragma: no cover - 包内运行时
        from ..parser import docx_extractor, llm_parser, txt_parser  # type: ignore
    return txt_parser, docx_extractor, llm_parser


FILE_TYPES = (("格式要求", "*.txt *.docx *.md"), ("文本要求", "*.txt *.md"),
              ("Word 模板", "*.docx"), ("所有文件", "*.*"))


@dataclass
class UploadResult:
    """上传流程的产出。"""

    dsl: str
    name: str = ""
    source: str = ""
    summary: str = ""
    saved_path: Optional[Path] = None
    tokens: int = 0


# --------------------------------------------------------------------------- #
# 1. 取源文本
# --------------------------------------------------------------------------- #


def _build_source_panel(parent):
    """选文件 / 粘贴文本的小面板。"""
    var_file = tk.StringVar(value="")

    box = ctk.CTkFrame(parent, fg_color="transparent")
    box.grid_columnconfigure(0, weight=1)

    th.section_title(box, "方式一：选择文件（.txt / .md / .docx）").grid(
        row=0, column=0, sticky="w", pady=(0, 4))
    row = ctk.CTkFrame(box, fg_color="transparent")
    row.grid(row=1, column=0, sticky="ew")
    row.grid_columnconfigure(0, weight=1)
    th.entry(row, textvariable=var_file).grid(row=0, column=0, sticky="ew")
    th.ghost_button(row, "浏览…", lambda: _pick(var_file), width=72, height=34).grid(
        row=0, column=1, padx=(th.PAD_S, 0))

    th.section_title(box, "方式二：直接粘贴自然语言要求").grid(
        row=2, column=0, sticky="w", pady=(th.PAD, 4))
    text_box = th.textbox(box, mono=True, height=110, wrap="word")
    text_box.grid(row=3, column=0, sticky="ew")
    th.hint(box, "例：标题黑体二号居中加粗；正文宋体小四，1.5 倍行距，首行缩进 2 字符").grid(
        row=4, column=0, sticky="w", pady=(4, 0))
    return box, var_file, text_box


def _pick(var_file: tk.StringVar) -> None:
    path = filedialog.askopenfilename(
        title="选择格式要求文件（.txt / .md / .docx）", filetypes=list(FILE_TYPES)
    )
    if path:
        var_file.set(path)


def _source_from_selection(file_path: str, pasted: str) -> Tuple[str, str]:
    """返回 (kind, payload)。kind ∈ {file_dsl, file_natural, docx, text}。"""
    file_path = (file_path or "").strip()
    pasted = (pasted or "").strip()
    if file_path:
        suffix = Path(file_path).suffix.lower()
        if suffix == ".docx":
            return "docx", file_path
        return "txt", file_path
    if pasted:
        return "text", pasted
    return "", ""


# --------------------------------------------------------------------------- #
# 2. 转 DSL
# --------------------------------------------------------------------------- #


def _ui_conf(app, llm_parser):
    """用设置页**内存里的**三项组装请求配置（不回读磁盘）。

    三项都没填时返回 ``None``，交给 ``llm_parser.load_config()`` 回落到
    config.json / 老版 .env（保持老用户行为）。
    """
    settings = getattr(app, "settings", None)
    if settings is None:
        return None
    raw = (getattr(settings, "api_base_url", ""),
           getattr(settings, "api_key", ""),
           getattr(settings, "api_model", ""))
    cleaned = [llm_parser.clean_value(v) for v in raw]
    if not any(cleaned):
        return None
    return llm_parser.config_from_values(*cleaned, source="设置页输入")


def _to_dsl(kind: str, payload: str, log: Callable[[str], None],
            conf=None) -> Tuple[str, str, int]:
    """把输入转成 DSL。返回 (dsl, 来源说明, 本次 token 数)。失败抛 llm_parser 的异常。

    ``conf`` 为设置页输入框组装好的配置；为 ``None`` 时由 llm_parser 自行回读磁盘。
    """
    txt_parser, docx_extractor, llm_parser = _parser_modules()

    if kind == "txt":
        parsed = txt_parser.parse_txt(payload)
        if parsed.is_dsl:
            log(f"上传：{Path(payload).name} 已是 DSL，跳过 AI 调用")
            return parsed.dsl_body(), f"本地判定为 DSL（编码 {parsed.encoding}，未调用 AI）", 0
        log(f"上传：{Path(payload).name} 判定为自然语言 → 调 LLM 转 DSL")
        result = llm_parser.natural_language_to_dsl(parsed.text, cfg=conf)
        return (result.dsl,
                f"自然语言 → AI 转换（{result.model}，{result.attempts} 次尝试）",
                result.total_tokens)

    if kind == "docx":
        log(f"上传：{Path(payload).name} 取样式指纹 → 调 LLM 归纳规则")
        fingerprint = docx_extractor.extract_fingerprint(payload)
        result = llm_parser.fingerprint_to_dsl(fingerprint.to_text(), cfg=conf)
        return (result.dsl,
                f"Word 样式指纹 → AI 归纳（{result.model}，{result.attempts} 次尝试）",
                result.total_tokens)

    log("上传：粘贴的自然语言 → 调 LLM 转 DSL")
    result = llm_parser.natural_language_to_dsl(payload, cfg=conf)
    return (result.dsl,
            f"自然语言 → AI 转换（{result.model}，{result.attempts} 次尝试）",
            result.total_tokens)


def _missing_config_message(exc: Exception) -> str:
    text = str(exc).strip() or "缺少 LLM 配置"
    return text


def _open_settings(master) -> None:
    app = getattr(master, "app", master)
    try:
        app.show_page("settings")
    except Exception:  # noqa: BLE001 - 兜底
        try:
            master.show_page("settings")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def _prompt_open_settings(master, message: str) -> None:
    """缺 API Key 时：明确提示 + 一个「打开设置」按钮。"""
    win = dlg.ModalWindow(master, "需要先在设置里配置 API", (560, 300),
                          icon="✕", tone="danger")
    win.body.grid_rowconfigure(1, weight=1)
    ctk.CTkLabel(
        win.body,
        text="这份格式要求需要用 AI 转成 DSL，但当前还没有配置 API。\n"
             "请到「设置 → API 配置」填入 API 地址、API 密钥、模型名称，点「保存配置」后重试。\n"
             "不知道去哪儿申请？设置页里有「如何获取 API Key？」按钮。",
        font=th.font(13), justify="left", anchor="w", wraplength=500,
    ).grid(row=0, column=0, sticky="ew")
    box = th.textbox(win.body, mono=True, wrap="word", height=80)
    box.insert("1.0", message)
    box.configure(state="disabled")
    box.grid(row=1, column=0, sticky="nsew", pady=(th.PAD_S, 0))

    bar = ctk.CTkFrame(win.body, fg_color="transparent")
    bar.grid(row=2, column=0, pady=(th.PAD, 0))

    def _go() -> None:
        win.destroy()
        _open_settings(master)

    th.ghost_button(bar, "取消", win.destroy, width=th.BTN_W_L).grid(row=0, column=0, padx=6)
    th.primary_button(bar, "打开设置", _go, width=th.BTN_W_XL).grid(row=0, column=1, padx=6)


# --------------------------------------------------------------------------- #
# 3. DSL 确认 + 保存
# --------------------------------------------------------------------------- #


class UploadDialog(dlg.ModalWindow):
    """第二步：展示/编辑 DSL，可存为用户预设。"""

    def __init__(self, master, dsl: str, source_note: str, origin: str = "",
                 on_saved: Optional[Callable[[str, Path], None]] = None):
        super().__init__(master, "上传格式要求 · 确认 DSL", (720, 620), resizable=True)
        self.result: Optional[UploadResult] = None
        self.on_saved = on_saved
        self.suggested = self._suggest_name(origin)
        self.body.grid_rowconfigure(2, weight=1)

        th.section_title(self.body, "解析结果（DSL，可手工修改）").grid(
            row=0, column=0, sticky="w")
        th.hint(self.body, source_note, wraplength=660).grid(
            row=1, column=0, sticky="ew", pady=(2, th.PAD_S))

        self.box = th.textbox(self.body, mono=True, wrap="word")
        self.box.grid(row=2, column=0, sticky="nsew")
        self.box.insert("1.0", dsl)

        # 注意：不要叫 self.state —— Tkinter 的 state() 是 widget 自带方法，
        # 被实例属性覆盖后，关窗时 destroy/protocol 路径会报
        # TypeError: 'CTkLabel' object is not callable（Phase 3 已踩过）。
        self.char_count_label = th.hint(self.body, f"共 {len(dsl)} 字符")
        self.char_count_label.grid(row=3, column=0, sticky="w", pady=(th.PAD_S, 0))

        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.grid(row=4, column=0, sticky="e", pady=(th.PAD_S, 0))
        th.ghost_button(bar, "取消", self.destroy, width=th.BTN_W_L).grid(row=0, column=0, padx=6)
        th.primary_button(bar, "确认使用", self._confirm, width=th.BTN_W_XL).grid(row=0, column=1, padx=6)

    # -- 动作 ------------------------------------------------------------ #

    @staticmethod
    def _suggest_name(origin: str) -> str:
        stem = Path(origin).stem if origin else ""
        return up.sanitize_name(stem or "我的格式")

    def _confirm(self) -> None:
        dsl = self.box.get("1.0", "end-1c").strip()
        if not dsl:
            dlg.error(self, "DSL 内容为空。", title="无法使用")
            return
        name = ""
        saved: Optional[Path] = None

        if dlg.confirm(
            self,
            "是否把它保存为新的用户预设？",
            title="保存预设",
            ok_text="保存为预设",
            cancel_text="仅本次使用",
            detail=("保存后会出现在首页下拉框的「👤」分组里，重开程序依然可选。\n"
                    f"保存位置：{up.get_user_preset_dir(create=False)}"),
        ):
            name = self._ask_name()
            if not name:
                return
            try:
                saved = up.save_user_preset(name, dsl)
            except (OSError, ValueError) as exc:
                dlg.error(self, "保存用户预设失败。", title="保存失败", detail=str(exc))
                return

        self.result = UploadResult(
            dsl=dsl,
            name=name or "本次上传的格式要求",
            source="user" if saved else "session",
            summary=(f"已保存为用户预设「{name}」（{up.rename_note(saved)}）"
                     if saved else "仅本次使用，未保存"),
            saved_path=saved,
        )
        if saved is not None and self.on_saved is not None:
            self.on_saved(name, saved)
        self.destroy()

    def _ask_name(self) -> str:
        win = dlg.ModalWindow(self, "预设名称", (420, 220))
        th.hint(win.body, "给这份格式要求起个名字（会作为文件名的一部分）").grid(
            row=0, column=0, sticky="ew", pady=(0, th.PAD_S))
        var = tk.StringVar(value=self.suggested)
        entry = th.entry(win.body, textvariable=var)
        entry.grid(row=1, column=0, sticky="ew")
        entry.focus_set()
        entry.select_range(0, "end")

        bar = ctk.CTkFrame(win.body, fg_color="transparent")
        bar.grid(row=2, column=0, pady=(th.PAD, 0))

        def _ok() -> None:
            win.destroy()

        th.ghost_button(bar, "取消", win.destroy, width=th.BTN_W_L).grid(row=0, column=0, padx=6)
        th.primary_button(bar, "确定", _ok, width=th.BTN_W_L).grid(row=0, column=1, padx=6)
        entry.bind("<Return>", lambda _e: _ok())
        win.bind("<Return>", lambda _e: _ok())
        win.wait_window()
        return up.sanitize_name(var.get()) if var.get().strip() else ""


# --------------------------------------------------------------------------- #
# 4. 第一步弹窗 + 总入口
# --------------------------------------------------------------------------- #


class SourceDialog(dlg.ModalWindow):
    """第一步：选文件或粘贴文本。"""

    def __init__(self, master):
        super().__init__(master, "上传格式要求", (640, 520), resizable=True)
        self.result: Optional[Tuple[str, str]] = None
        self.body.grid_rowconfigure(0, weight=1)
        panel, self.var_file, self.text_box = _build_source_panel(self.body)
        panel.grid(row=0, column=0, sticky="nsew")

        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="e", pady=(th.PAD_S, 0))
        th.ghost_button(bar, "取消", self.destroy, width=th.BTN_W_L).grid(row=0, column=0, padx=6)
        th.primary_button(bar, "解析", self._resolve, width=th.BTN_W_XL).grid(row=0, column=1, padx=6)

    def _resolve(self) -> None:
        pasted = self.text_box.get("1.0", "end-1c").strip()
        kind, payload = _source_from_selection(self.var_file.get(), pasted)
        if not kind:
            dlg.info(self, "请先选择一个文件，或粘贴一段格式要求。", title="还没有内容")
            return
        self.result = (kind, payload)
        self.destroy()


def open_upload_dialog(master) -> Optional[UploadResult]:
    """完整上传流程；取消返回 None。"""
    app = getattr(master, "app", master)
    log = getattr(app, "log", lambda _m: None)
    status = getattr(app, "status", lambda _m: None)

    first = SourceDialog(master)
    first.wait_window()
    if first.result is None:
        return None
    kind, payload = first.result

    status("正在解析格式要求…")
    log(f"上传格式要求：kind={kind} payload={payload if kind != 'text' else payload[:40] + '…'}")
    try:
        # 优先用设置页输入框里的三项（内存），这样「框里有值」就能直接发请求，
        # 不依赖 config.json 是否写得进去、也不会被旧的 .env 覆盖。
        _, _, llm_parser = _parser_modules()
        conf = _ui_conf(app, llm_parser)
        dsl, note, tokens = _to_dsl(kind, payload, log, conf=conf)
    except Exception as exc:  # noqa: BLE001 - 统一转成可读提示
        _, _, llm_parser = _parser_modules()
        if isinstance(exc, getattr(llm_parser, "LlmConfigError", ())) or "缺少 LLM 配置" in str(exc):
            log(f"上传失败：缺少 API 配置（{exc}）")
            _prompt_open_settings(master, _missing_config_message(exc))
        else:
            log(f"上传失败：{type(exc).__name__}: {exc}")
            dlg.error(master, f"解析失败：{exc}", title="解析失败")
        return None

    status("解析完成，请确认 DSL")
    log(f"解析完成：{note}" + (f" · token {tokens}" if tokens else " · 未消耗 token"))
    second = UploadDialog(master, dsl, note, origin=payload if kind in ("txt", "docx") else "")
    second.wait_window()
    if second.result is None:
        return None

    result = second.result
    result.source = note
    result.tokens = tokens
    origin = Path(payload).name if kind in ("txt", "docx") else "粘贴的自然语言"
    result.summary = f"{origin} → {note} → {result.summary}"
    log("上传流程结束：" + result.summary)
    return result
