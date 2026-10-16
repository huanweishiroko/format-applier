# -*- coding: utf-8 -*-
"""设置页：默认输出目录 / 主题 / API 配置 / 用户预设目录 / token 统计。

Phase 3 边界：
  * 用户预设目录：显示真实路径 + 「打开目录」；
  * 「测试 API 连接」：真发一次短请求（system 要求"只回复 OK"），
    成功显示往返延迟 + token 用量，失败显示原始错误；
  * token 统计：读 ``%APPDATA%\\WordFormatAssistant\\usage.json``（llm_parser 累加）。
"""

from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

# 绝对优先，理由见 preview.py 顶部注释（frozen 下 ui/core 是顶层包）
try:
    from ui import dialogs as dlg
    from ui import theme as th
    from core import config as cfg
    from core import user_presets as up
except ImportError:  # pragma: no cover - 包内运行时
    from . import dialogs as dlg  # type: ignore
    from . import theme as th  # type: ignore
    from ..core import config as cfg  # type: ignore
    from ..core import user_presets as up  # type: ignore


#: 「测试连接」用的短 prompt（成本最低，只验证连通性与鉴权）
TEST_PROMPT = "只回复 OK"


def _env_source_text() -> str:
    """API 配置的实际来源：.env 路径，或"环境变量"（都没配时给建议路径）。"""
    try:
        return cfg.env_source_label()
    except Exception:  # noqa: BLE001 - 展示用，绝不能拖垮页面
        return str(cfg.ENV_TARGET_PATH)


class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        # 不透明页底（原来是 "transparent"）：见 home.py 同处注释（tkraise 叠放下防串页）。
        super().__init__(master, corner_radius=0, fg_color=th.BG_PAGE)
        self.app = app
        self._testing = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(scroll, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=th.PAD_L, pady=(th.PAD_L, th.PAD_S))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="设置", font=th.font(22, "bold"), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        th.hint(head, f"改动即时生效，并写入 {cfg.CONFIG_PATH}").grid(
            row=1, column=0, sticky="w", pady=(2, 0)
        )

        # 卡片分行：输出+外观两张半宽卡并排，其余三张各自独占全宽
        _half, half_cols = self._card_row(scroll, 1, columns=2)
        wide, wide_cols = self._card_row(scroll, 2, columns=1)

        self._build_output_card(half_cols[0], col=0)
        self._build_theme_card(half_cols[1], col=1)
        self._build_user_preset_card(wide_cols[0])
        self._build_api_card(wide)
        self._build_token_card(wide_cols[0])

    # ------------------------------------------------------------------ #
    # 默认输出目录
    # ------------------------------------------------------------------ #

    def _build_output_card(self, master, col: int = 0) -> None:
        card = self._card(master, 0, "默认输出目录", col=col)
        card.grid_columnconfigure(0, weight=1)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=th.PAD, pady=(0, th.PAD_S))
        row.grid_columnconfigure(0, weight=1)

        self.out_var = tk.StringVar(value=self.app.settings.output_dir)
        th.entry(row, textvariable=self.out_var).grid(row=0, column=0, sticky="ew")
        th.ghost_button(row, "浏览", self._pick_output, width=64, height=34).grid(
            row=0, column=1, padx=(th.PAD_S, 0)
        )

        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="w", padx=th.PAD, pady=(0, th.PAD))
        th.ghost_button(bar, "保存", self._save_output, width=72, height=30).grid(row=0, column=0)
        th.ghost_button(bar, "打开目录", self._open_output, width=88, height=30).grid(
            row=0, column=1, padx=th.PAD_S
        )
        self.out_state = th.hint(bar, "")
        self.out_state.grid(row=0, column=2, padx=th.PAD_S)

        th.hint(card, "首次启动自动用「文档\\WordFormatAssistant」；改动后立即写入 "
                      f"{cfg.CONFIG_PATH}").grid(
            row=3, column=0, sticky="w", padx=th.PAD, pady=(0, th.PAD)
        )

    # ------------------------------------------------------------------ #
    # 主题
    # ------------------------------------------------------------------ #

    def _build_theme_card(self, master, col: int = 0) -> None:
        card = self._card(master, 0, "外观主题", col=col)
        card.grid_columnconfigure(0, weight=1)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=th.PAD, pady=(0, th.PAD))
        row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(row, text="主题", font=th.font(13), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        self.theme_var = tk.StringVar(value=self.app.settings.theme)
        th.segmented(
            row,
            values=list(cfg.THEME_CHOICES),
            variable=self.theme_var,
            command=self._on_theme,
        ).grid(row=0, column=1, sticky="w", padx=(th.PAD, 0))

    # ------------------------------------------------------------------ #
    # 用户预设目录
    # ------------------------------------------------------------------ #

    def _build_user_preset_card(self, master) -> None:
        card = self._card(master, 0, "用户预设目录")
        card.grid_columnconfigure(1, weight=1)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=th.PAD, pady=(0, th.PAD_S))
        row.grid_columnconfigure(0, weight=1)

        self.user_dir_var = tk.StringVar(value=str(up.get_user_preset_dir(create=False)))
        entry = th.entry(row, textvariable=self.user_dir_var)
        entry.configure(state="disabled")
        entry.grid(row=0, column=0, sticky="ew")
        th.ghost_button(row, "打开目录", self._open_user_dir, width=88, height=34).grid(
            row=0, column=1, padx=(th.PAD_S, 0)
        )
        th.ghost_button(row, "刷新", self._refresh_user_presets, width=64, height=34).grid(
            row=0, column=2, padx=(th.PAD_S, 0)
        )

        self.user_count = th.hint(card, "")
        self.user_count.grid(row=2, column=0, columnspan=3, sticky="w",
                             padx=th.PAD, pady=(0, th.PAD))
        self._refresh_user_presets()

    def _refresh_user_presets(self) -> None:
        base = up.get_user_preset_dir()
        self.user_dir_var.set(str(base))
        items = up.list_user_presets(base)
        detail = "、".join(f"{i.name}（{cfg.human_size(i.size)}）" for i in items[:6]) or "（空）"
        more = f" 等 {len(items)} 个" if len(items) > 6 else ""
        self.user_count.configure(
            text=f"目录里现有 {len(items)} 个用户预设：{detail}{more}\n"
                 f"命名规则 user_<时间戳>_<名字>.txt；内置 presets/ 不受影响。"
        )

    def _open_user_dir(self) -> None:
        target = up.get_user_preset_dir(create=True)
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
            self.app.log(f"已打开用户预设目录：{target}")
        except Exception as exc:  # noqa: BLE001
            dlg.error(self.app, "无法打开目录。", detail=f"{target}\n{exc}")

    # ------------------------------------------------------------------ #
    # API 配置（只读）
    # ------------------------------------------------------------------ #

    def _build_api_card(self, master) -> None:
        rows = cfg.env_field_rows()
        all_present = bool(rows) and all(present for _k, _l, _v, present in rows)
        card = self._card(
            master, 0, "API 配置（只读展示 .env 或环境变量）",
            badge=("已配置" if all_present else "未配置齐",
                   "success" if all_present else "danger"),
            span=3,
        )
        card.grid_columnconfigure(1, weight=1)

        self.env_rows = {}
        for i, (key, label, value, present) in enumerate(rows, start=1):
            ctk.CTkLabel(card, text=label, font=th.font(13), anchor="w").grid(
                row=i, column=0, sticky="w", padx=(th.PAD, th.PAD_S), pady=4
            )
            entry = th.entry(card)
            entry.insert(0, value)
            entry.configure(state="disabled")
            entry.grid(row=i, column=1, sticky="ew", padx=(0, th.PAD), pady=4)
            state = th.badge(card, "已设置" if present else "缺失",
                             tone="success" if present else "danger")
            state.grid(row=i, column=2, sticky="w", padx=(0, th.PAD), pady=4)
            self.env_rows[key] = (entry, state)

        foot = ctk.CTkFrame(card, fg_color="transparent")
        foot.grid(row=len(self.env_rows) + 1, column=0, columnspan=3, sticky="ew",
                  padx=th.PAD, pady=(th.PAD_S, th.PAD))
        foot.grid_columnconfigure(1, weight=1)

        th.ghost_button(foot, "测试 API 连接", self._test_api, width=th.BTN_W_XL, height=30).grid(
            row=0, column=0, sticky="w"
        )
        th.ghost_button(foot, "重新读取", self._reload_env, width=th.BTN_W_L, height=30).grid(
            row=0, column=1, sticky="w", padx=th.PAD_S
        )
        self.api_state = th.hint(foot, f"配置文件：{_env_source_text()}")
        self.api_state.grid(row=0, column=2, sticky="e")

        # 连接结果：3 行高的等宽小框
        self.api_detail = th.textbox(card, mono=True, height=72, wrap="word")
        self.api_detail.grid(row=len(self.env_rows) + 2, column=0, columnspan=3,
                             sticky="ew", padx=th.PAD, pady=(0, th.PAD))
        self.api_detail.insert("1.0", "尚未测试。")
        self.api_detail.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # Token 统计（读 usage.json）
    # ------------------------------------------------------------------ #

    def _build_token_card(self, master) -> None:
        card = self._card(master, 0, "Token 用量统计")
        card.grid_columnconfigure((1, 3), weight=1)

        self.token_values = {}
        specs = (("LLM 调用次数", "total_calls"), ("累计 token", "total_tokens"),
                 ("输入 token", "total_prompt_tokens"), ("输出 token", "total_completion_tokens"))
        for i, (label, key) in enumerate(specs):
            r, c = divmod(i, 2)
            ctk.CTkLabel(card, text=label, font=th.font(13), anchor="w").grid(
                row=r + 1, column=c * 2, sticky="w", padx=(th.PAD, th.PAD_S), pady=4
            )
            value = ctk.CTkLabel(card, text="0", font=th.font(14, "bold"), anchor="w")
            value.grid(row=r + 1, column=c * 2 + 1, sticky="w", pady=4)
            self.token_values[key] = value

        self.token_detail = ctk.CTkTextbox(
            card, font=ctk.CTkFont(family="Consolas", size=12), height=110,
            corner_radius=th.RADIUS, wrap="word",
        )
        self.token_detail.grid(row=3, column=0, columnspan=4, sticky="ew",
                               padx=th.PAD, pady=(th.PAD_S, 0))
        self.token_detail.configure(state="disabled")

        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.grid(row=4, column=0, columnspan=4, sticky="ew", padx=th.PAD,
                 pady=(th.PAD_S, th.PAD))
        bar.grid_columnconfigure(1, weight=1)
        th.ghost_button(bar, "刷新", self.refresh_usage, width=72, height=30).grid(
            row=0, column=0, sticky="w")
        th.ghost_button(bar, "清零", self._reset_usage, width=72, height=30).grid(
            row=0, column=1, sticky="w", padx=th.PAD_S)
        self.token_path_label = th.hint(bar, f"统计文件：{cfg.usage_path()}")
        self.token_path_label.grid(row=0, column=2, sticky="e")
        self.refresh_usage()

    def refresh_usage(self) -> None:
        """读 usage.json 刷新卡片。"""
        data = cfg.load_usage()
        for key, widget in self.token_values.items():
            widget.configure(text=f"{int(data.get(key) or 0):,}")
        lines = [f"统计文件：{cfg.usage_path()}",
                 f"最近一次调用：{data.get('last_call_at') or '（无）'}"]
        by_model = data.get("by_model") or {}
        if by_model:
            lines.append("按模型：")
            for model, bucket in sorted(by_model.items()):
                if not isinstance(bucket, dict):
                    continue
                lines.append(
                    f"  - {model}：{bucket.get('calls', 0)} 次 · "
                    f"{bucket.get('total_tokens', 0)} token"
                    f"（输入 {bucket.get('prompt_tokens', 0)} / 输出 {bucket.get('completion_tokens', 0)}）"
                    f" · 最近 {bucket.get('last_at', '-')}"
                )
        else:
            lines.append("按模型：（还没有调用记录）")
        lines.append("说明：桌面端的 AI 解析（上传格式要求 / 测试连接 / 预览）会计入这里；"
                     "插件 CLI 的处理过程若自身触发了 LLM 回退，不重复计入。")
        self.token_detail.configure(state="normal")
        self.token_detail.delete("1.0", "end")
        self.token_detail.insert("1.0", "\n".join(lines))
        self.token_detail.configure(state="disabled")

    def _reset_usage(self) -> None:
        if not dlg.confirm(self.app, "把 token 统计清零？", title="清零确认",
                           ok_text="清零", danger=True,
                           detail=str(cfg.usage_path())):
            return
        cfg.reset_usage()
        self.refresh_usage()
        self.app.log("token 统计已清零")

    # ------------------------------------------------------------------ #
    # 回调
    # ------------------------------------------------------------------ #

    def _card_row(self, master, row: int, columns: int):
        """一行卡片容器。返回 ``(容器, [各列可用 master])``。

        ``columns=2`` 时两列等宽（``uniform``），卡缝 8px、左右外沿 PAD_L。
        """
        container = ctk.CTkFrame(master, fg_color="transparent")
        container.grid(row=row, column=0, sticky="ew", pady=(0, th.SP.L))
        container.grid_columnconfigure(0, weight=0)
        if columns == 2:
            container.grid_columnconfigure(0, weight=1, uniform="cards")
            container.grid_columnconfigure(1, weight=1, uniform="cards")
            pads = ((th.PAD_L, th.PAD_S), (th.PAD_S, th.PAD_L))
        else:
            container.grid_columnconfigure(0, weight=1)
            pads = ((th.PAD_L, th.PAD_L),)

        cols = []
        for index in range(columns):
            holder = ctk.CTkFrame(container, fg_color="transparent")
            holder.grid(row=0, column=index, sticky="new", padx=pads[index])
            holder.grid_columnconfigure(0, weight=1)
            cols.append(holder)
        return container, cols

    def _card(self, master, row: int, title: str, col: int = 0,
              badge: tuple | None = None, span: int = 1) -> ctk.CTkFrame:
        """卡片本体。

        ``row`` 是本行容器内的行号（单卡行传 0）；``col`` 是卡在行容器里的列。
        ``span`` = 卡片内部字段占用的列数，徽章会落在其后一列（贴右沿），
        这样标题仍能独占前 ``span`` 列向左伸展，不会被徽章挤窄。
        """
        card = th.card(master)
        card.grid(row=row, column=col, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        if badge is None:
            th.section_title(card, title).grid(
                row=0, column=0, sticky="w", padx=th.PAD, pady=(th.PAD, th.PAD_S)
            )
            return card

        card.grid_columnconfigure(span, weight=1)
        text, tone = badge
        th.section_title(card, title).grid(
            row=0, column=0, columnspan=span, sticky="w",
            padx=th.PAD, pady=(th.PAD, th.PAD_S),
        )
        th.badge(card, text, tone=tone).grid(
            row=0, column=span, sticky="e", padx=(th.PAD_S, th.PAD),
            pady=(th.PAD, th.PAD_S),
        )
        return card

    @staticmethod
    def _apply_env_state(state, present: bool) -> None:
        """就地刷新字段状态徽章（``th.badge`` 返回的是裸 CTkLabel）。"""
        fg, fg_text = th.tone_colors("success" if present else "danger")
        state.configure(
            text=f"\u2002{'已设置' if present else '缺失'}\u2002",
            fg_color=fg, text_color=fg_text,
        )

    def _pick_output(self) -> None:
        path = filedialog.askdirectory(
            title="选择默认输出目录", initialdir=self.out_var.get() or None, parent=self.app
        )
        if path:
            self.out_var.set(path)
            self._save_output()

    def _save_output(self) -> None:
        target = self.out_var.get().strip()
        if not target:
            self.out_state.configure(text="目录不能为空")
            return
        ok = cfg.ensure_dir(target)
        self.app.set_output_dir(target)
        self.out_state.configure(text="已保存" if ok else "目录不可创建，已保存路径")
        self.app.log(f"默认输出目录 → {target}")

    def refresh_paths(self) -> None:
        """外部改了配置（如旧版文件迁移）后，把本页显示的路径重新读一遍。"""
        try:
            self.out_var.set(str(self.app.settings.output_dir or ""))
            self.api_state.configure(text=f"配置文件：{_env_source_text()}")
            self.token_path_label.configure(text=f"统计文件：{cfg.usage_path()}")
            self.refresh_usage()
        except Exception:  # noqa: BLE001 - 刷新失败不影响其它功能
            pass

    def _open_output(self) -> None:
        target = Path(self.out_var.get().strip() or ".")
        if not target.is_dir():
            self.out_state.configure(text="目录不存在")
            return
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            self.out_state.configure(text=f"打开失败：{exc}")

    def _on_theme(self, choice: str) -> None:
        self.app.apply_theme(choice)

    def _reload_env(self) -> None:
        for key, _label, value, present in cfg.env_field_rows():
            entry, state = self.env_rows[key]
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.insert(0, value)
            entry.configure(state="disabled")
            self._apply_env_state(state, present)
        self.api_state.configure(text=f"已重新读取：{_env_source_text()}")
        self.app.log("重新读取 .env 字段")

    def _test_api(self) -> None:
        """真发一次短请求（只回复 OK），显示延迟 + token 用量。"""
        if self._testing:
            self.api_state.configure(text="上一次测试还在进行中…")
            return

        lines = []
        rows = cfg.env_field_rows()
        present = {key: ok for key, _l, _v, ok in rows}
        for key, label, value, ok in rows:
            lines.append(f"· {label}（{key}）：{'✅ 已设置' if ok else '❌ 缺失'}"
                         + (f" → {value}" if ok and key != "OPENAI_API_KEY" else ""))
        if not all(present.values()):
            lines.append("")
            lines.append("结论：字段不齐，无法发起真实请求。请按下面的路径补齐后点「重新读取」。")
            lines.append(f"  · 配置文件（exe 同级）：{cfg.ENV_TARGET_PATH}")
            lines.append(f"  · 模板：{cfg.ENV_EXAMPLE_PATH}"
                         + ("（已附在程序目录里）" if cfg.ENV_EXAMPLE_PATH.is_file() else "（未找到，可手写三行 KEY=VALUE）"))
            lines.append("  · 也可以不建文件，直接设 OPENAI_BASE_URL / OPENAI_API_KEY / "
                         "OPENAI_MODEL 三个环境变量（环境变量优先级最高）。")
            self._show_api_detail("\n".join(lines))
            self.api_state.configure(text="缺少 API 配置")
            return

        self._testing = True
        self.api_state.configure(text="正在连接…")
        self.app.status("正在测试 API 连接…")
        self.app.log(f"测试 API 连接：{TEST_PROMPT!r}")
        self._show_api_detail("\n".join(lines) + "\n\n正在请求…")

        def worker() -> None:
            started = time.perf_counter()
            try:
                try:
                    from parser import llm_parser
                except ImportError:  # pragma: no cover - 包内运行时
                    from ..parser import llm_parser  # type: ignore

                conf = llm_parser.load_config()
                client = llm_parser.get_client(conf)
                try:
                    response = client.chat.completions.create(
                        model=conf.model,
                        messages=[
                            {"role": "system", "content": "你只回复 OK，不要输出任何其它内容。"},
                            {"role": "user", "content": TEST_PROMPT},
                        ],
                        temperature=0.0,
                    )
                    reply = llm_parser._extract_content(response)
                    usage = llm_parser.extract_usage(response)
                finally:
                    try:
                        client.close()
                    except Exception:  # noqa: BLE001
                        pass
                elapsed = (time.perf_counter() - started) * 1000
                if usage:
                    cfg.record_usage(
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens"),
                        model=conf.model, kind="api_test",
                    )
                self.after(0, lambda: self._on_test_ok(conf, reply, usage, elapsed))
            except Exception as exc:  # noqa: BLE001 - 失败细节要原样给用户看
                elapsed = (time.perf_counter() - started) * 1000
                self.after(0, lambda e=exc, ms=elapsed: self._on_test_fail(e, ms))

        threading.Thread(target=worker, name="wfa-api-test", daemon=True).start()

    def _on_test_ok(self, conf, reply: str, usage: dict, elapsed: float) -> None:
        self._testing = False
        body = [
            "结论：✅ 连接成功",
            f"地址：{conf.base_url}",
            f"模型：{conf.model}",
            f"往返延迟：{elapsed:.0f} ms",
            f"回复内容：{reply.strip()[:100]!r}",
        ]
        if usage:
            body.append(
                f"token：输入 {usage.get('prompt_tokens', 0)} · "
                f"输出 {usage.get('completion_tokens', 0)} · "
                f"合计 {usage.get('total_tokens', 0)}"
            )
        else:
            body.append("token：接口未返回 usage 字段，本次未计入统计")
        self._show_api_detail("\n".join(body))
        self.api_state.configure(text=f"连接成功 · {elapsed:.0f} ms")
        self.app.log(f"API 测试成功：{elapsed:.0f} ms，回复 {reply.strip()[:40]!r}")
        self.app.status(f"API 连接正常（{elapsed:.0f} ms）")
        self.refresh_usage()

    def _on_test_fail(self, exc: Exception, elapsed: float) -> None:
        self._testing = False
        detail = f"结论：❌ 连接失败（耗时 {elapsed:.0f} ms）\n{type(exc).__name__}: {exc}"
        self._show_api_detail(detail)
        self.api_state.configure(text="连接失败")
        self.app.log(f"API 测试失败：{type(exc).__name__}: {exc}")
        self.app.status("API 连接失败")
        dlg.error(self.app, "API 连接失败。", title="测试失败", detail=str(exc))

    def _show_api_detail(self, text: str) -> None:
        self.api_detail.configure(state="normal")
        self.api_detail.delete("1.0", "end")
        self.api_detail.insert("1.0", text)
        self.api_detail.configure(state="disabled")
