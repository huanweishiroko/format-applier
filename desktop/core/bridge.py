# -*- coding: utf-8 -*-
"""bridge —— 桌面外壳调用 word-format-applier 插件 CLI 的唯一出口。

设计要点
--------
* **双轨入口**（为 Phase 4 打包准备）::

      if getattr(sys, "frozen", False):
          cmd = [sys.executable, "--wfa-cli", ...]        # 打包后：调自身
      else:
          cmd = [sys.executable, "-m", "word_format_applier", ...]  # 开发：调 .venv

  两种情况下 ``sys.executable`` 都是"能跑插件 CLI 的那个解释器"。
* 一律加 ``--json``：CLI 把摘要打成**单行 JSON** 到 stdout，
  人类可读的日志走 stderr（``--json`` 时 CLI 不再往 stderr 打进度）。
* 超时 120s（``subprocess.TimeoutExpired`` → BridgeError）。
* 只读：本模块**不写** presets/ 下的任何文件；
  报告（``*.report.json``）缺省落 ``%TEMP%\\taofu-reports\\``，
  处理成功后由 GUI 移到输出文件旁边（exe 同级目录不再写任何用户文件）。
* 永不抛裸异常给界面：所有失败统一包装成 :class:`BridgeError`，
  并保留 ``stdout`` / ``stderr`` / ``returncode`` 供日志区展示。
"""

from __future__ import annotations

import json
import locale
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 绝对优先：冻结后 app.py 以 __main__ 直跑，core 是顶层包，
# `from . import config` 会越过顶层包；相对形式只留给包内运行兜底。
try:
    from core import config as cfg
except ImportError:  # pragma: no cover - 包内运行时
    from . import config as cfg  # type: ignore

#: 单次 CLI 调用最长等待时间（秒）
DEFAULT_TIMEOUT = 120.0

#: 列表类命令用更短的超时，避免界面启动被拖住
LIST_TIMEOUT = 20.0

#: 打包后自调用的隐藏 CLI 开关（Phase 4 的 exe 会识别它）
WFA_CLI_FLAG = "--wfa-cli"

#: 开发期的模块入口
CLI_MODULE = "word_format_applier"


# --------------------------------------------------------------------------- #
# 异常与结果
# --------------------------------------------------------------------------- #


class BridgeError(RuntimeError):
    """CLI 调用失败（超时、非零退出、JSON 无法解析、入口缺失…）。"""

    def __init__(self, message: str, *, returncode: int = -1, stdout: str = "",
                 stderr: str = "", argv: Optional[Sequence[str]] = None):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout or ""
        self.stderr = stderr or ""
        self.argv: List[str] = [str(a) for a in (argv or [])]

    @property
    def command_line(self) -> str:
        return " ".join(f'"{a}"' if " " in a else a for a in self.argv)

    @property
    def detail(self) -> str:
        """给弹窗/日志用的多行明细。"""
        parts = [f"命令：{self.command_line}", f"退出码：{self.returncode}"]
        if self.stderr.strip():
            parts.append("stderr：\n" + self.stderr.strip()[-4000:])
        if self.stdout.strip():
            parts.append("stdout：\n" + self.stdout.strip()[-2000:])
        return "\n\n".join(parts)


@dataclass
class ProcessResult:
    """一次 ``process()`` 的完整结果。"""

    ok: bool
    summary: Dict[str, Any] = field(default_factory=dict)
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    argv: List[str] = field(default_factory=list)
    error: str = ""

    @property
    def command_line(self) -> str:
        return " ".join(f'"{a}"' if " " in a else a for a in self.argv)

    @property
    def output_docx(self) -> Optional[str]:
        return self.summary.get("output_docx")

    @property
    def report_json(self) -> Optional[str]:
        return self.summary.get("report_json")

    @property
    def applied(self) -> int:
        return int(self.summary.get("applied") or 0)

    @property
    def skipped(self) -> int:
        return int(self.summary.get("skipped") or 0)

    @property
    def logs(self) -> List[str]:
        """stderr 里的 ``[wfa] ...`` 行，供日志区逐行展示。"""
        lines: List[str] = []
        for line in (self.stderr or "").splitlines():
            line = line.rstrip()
            if not line:
                continue
            lines.append(line[6:].strip() if line.startswith("[wfa]") else line)
        return lines

    def to_dict(self) -> Dict[str, Any]:
        payload = dict(self.summary)
        payload.setdefault("ok", self.ok)
        payload["_returncode"] = self.returncode
        payload["_argv"] = list(self.argv)
        payload["_stderr"] = self.stderr
        if self.error:
            payload["_error"] = self.error
        return payload


# --------------------------------------------------------------------------- #
# 命令构造
# --------------------------------------------------------------------------- #


def frozen() -> bool:
    """当前进程是否运行在 PyInstaller 之类的打包环境里。"""
    return bool(getattr(sys, "frozen", False))


def cli_argv() -> List[str]:
    """CLI 入口前缀（不含子命令参数）。

    * 打包后：``[<exe>, "--wfa-cli"]`` —— exe 自己识别该开关并转入插件 CLI。
    * 开发期：``[python, "-m", "word_format_applier"]``。
    """
    exe = sys.executable or "python"
    if frozen():
        return [exe, WFA_CLI_FLAG]
    return [exe, "-m", CLI_MODULE]


def build_command(*args: str, presets_dir: Optional[str] = None,
                  no_cache: bool = False) -> List[str]:
    """拼一条 CLI 命令；``presets_dir`` 为空表示使用插件内置 presets/。"""
    cmd = cli_argv()
    cmd.extend(str(a) for a in args if a is not None)
    if presets_dir:
        cmd.extend(["--presets-dir", str(presets_dir)])
    if no_cache:
        cmd.append("--no-cache")
    return cmd


def _run(argv: Sequence[str], timeout: float) -> Tuple[int, str, str]:
    """执行子进程，返回 (returncode, stdout, stderr)。异常一律转 BridgeError。"""
    try:
        proc = subprocess.run(
            list(argv),
            cwd=str(cfg.PROJECT_ROOT),
            env=cfg.cli_env(),
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeError(
            f"CLI 超时（超过 {timeout:.0f} 秒）", returncode=-1, argv=argv,
            stdout=_as_text(exc.stdout), stderr=_as_text(exc.stderr),
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise BridgeError(
            f"无法启动 CLI：{type(exc).__name__}: {exc}", returncode=-1, argv=argv
        ) from exc
    return proc.returncode, _decode_output(proc.stdout), _decode_output(proc.stderr)


def _decode_output(value: Any) -> str:
    """把子进程的原始输出解成 str。

    优先严格 UTF-8：开发期跑的是 ``python -m word_format_applier``，``cli_env()``
    已经把 ``PYTHONIOENCODING`` / ``PYTHONUTF8`` 设成 utf-8。

    失败再退回本机 ANSI 代码页：打包后的 **windowed** exe 走 PyInstaller 引导，
    不会按环境变量配置 stdio，stdout 实际是 cp936（本机 GBK）。以前固定用
    ``utf-8 + errors="replace"`` 去解，中文路径就整段变成 ``����``。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, (bytes, bytearray)):
        return str(value)
    data = bytes(value)
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gbk"):
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _as_text(value: Any) -> str:
    return _decode_output(value)


#: traceback 末尾异常行的样式：``PermissionError: [Errno 13] Permission denied: ...``
_EXC_LINE = re.compile(
    r"^([A-Za-z_][\w.]*(?:Error|Exception|Interrupt|Exit|Warning))\b(?::\s*(.*))?$"
)


def _stderr_error(stderr: str) -> str:
    """从 stderr 里挑出最像“根因”的一行。

    CLI 崩溃时 stdout 是空的，唯一有用的信息在 stderr 末尾，例如::

        Traceback (most recent call last):
          ...
        PermissionError: [Errno 13] Permission denied: '...report.json'

    优先顺序：CLI 约定的 ``error: ...`` → traceback 末尾的 ``XxxError: ...`` →
    最后一行非空输出（比首行更接近根因）。没有可用的行就返回空串。
    """
    lines = [(line[6:] if line.startswith("[wfa]") else line).strip()
             for line in (stderr or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    for line in lines:
        if line.startswith("error:"):
            return line[6:].strip()
    for line in reversed(lines):
        match = _EXC_LINE.match(line)
        if match:
            name, message = match.group(1), (match.group(2) or "").strip()
            return f"{name}: {message}" if message else name
    return lines[-1]


#: 判定 stderr 一行是否值得进错误详情（INFO/进度行不进来）
_STDERR_KEEP = re.compile(
    r"\[WARN\]|\[ERROR\]|Traceback|\berror\b|\bError\b|\bException\b|"
    r"PermissionError|WinError|Errno|denied|failed|失败|错误|拒绝|警告",
)


def _stderr_digest(stderr: str, max_lines: int = 40) -> str:
    """把 stderr 压成“可读的失败详情”：丢掉 INFO/进度，只留 ERROR/WARN 与异常栈。

    界面弹窗直接把返回值贴给用户，所以既不能只给一行（看不到上下文），也不能
    把几十行 ``[wfa] rules: 24`` 之类的进度噪音全塞进去。
    """
    kept: List[str] = []
    for raw in (stderr or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("[wfa]"):
            body = line[5:].strip()
            if not _STDERR_KEEP.search(body):
                continue          # 进度/INFO：日志区已经展示，不进错误详情
            line = body
        kept.append(line)
    if len(kept) > max_lines:
        kept = kept[-max_lines:]
    return "\n".join(kept)


def _summary_errors(summary: Dict[str, Any]) -> str:
    """CLI 自己报的根因（``errors`` 数组 / ``error`` 字段）优先于 stderr。"""
    items = [str(item).strip() for item in (summary.get("errors") or [])
             if str(item).strip()]
    return "\n".join(items[:8])



def _parse_json(stdout: str, argv: Sequence[str]) -> Dict[str, Any]:
    """从 stdout 里取 JSON 对象：先整体解析，失败再退回"最后一个 {...}"。"""
    text = (stdout or "").strip()
    if not text:
        raise BridgeError("CLI 没有输出任何内容", returncode=0, argv=argv)
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise BridgeError(
                f"CLI 输出不是 JSON：{text[:200]!r}", returncode=0, stdout=stdout, argv=argv
            )
        try:
            data = json.loads(text[start:end + 1])
        except ValueError as exc:
            raise BridgeError(
                f"CLI 输出 JSON 解析失败：{exc}", returncode=0, stdout=stdout, argv=argv
            ) from exc
    if not isinstance(data, dict):
        raise BridgeError("CLI 输出的 JSON 不是对象", returncode=0, stdout=stdout, argv=argv)
    return data


def _summary_or_error(stdout: str, argv: Sequence[str]) -> Dict[str, Any]:
    """``process()`` 用的解析：容忍 stdout 里混有非 JSON 的进度行。"""
    text = (stdout or "").strip()
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict):
                return data
    return _parse_json(text, argv)


# --------------------------------------------------------------------------- #
# 1. 列预设
# --------------------------------------------------------------------------- #


def list_presets(presets_dir: Optional[str] = None,
                 timeout: float = LIST_TIMEOUT) -> List[Dict[str, Any]]:
    """调 ``--list-presets-json``，返回 ``[{name, file, ext, size}, ...]``。

    ``presets_dir`` 给定时列出该目录下的预设（用户预设走这条路）。
    CLI 不可用时返回空列表（界面回落为目录扫描，不视为错误）。
    """
    argv = build_command("--list-presets-json", presets_dir=presets_dir)
    try:
        code, out, _err = _run(argv, timeout)
    except BridgeError:
        return []
    if code != 0:
        return []
    try:
        data = _parse_json(out, argv)
    except BridgeError:
        return []
    raw = data.get("presets")
    if not isinstance(raw, list):
        return []
    items: List[Dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("file"):
            continue
        items.append({
            "name": str(entry.get("name") or Path(str(entry["file"])).stem),
            "file": str(entry["file"]),
            "ext": str(entry.get("ext") or Path(str(entry["file"])).suffix),
            "size": int(entry.get("size") or 0),
            "presets_dir": data.get("presets_dir") or presets_dir or str(cfg.PRESETS_DIR),
        })
    return items


def list_builtin_presets(timeout: float = LIST_TIMEOUT) -> List[Dict[str, Any]]:
    """内置预设（不带 ``--presets-dir``，用插件自己的 presets/）。"""
    return list_presets(None, timeout)


def presets_dir_default() -> str:
    """插件内置 presets/ 目录（工作站上的绝对路径）。"""
    return str(cfg.PRESETS_DIR)


# --------------------------------------------------------------------------- #
# 2. 预览规则
# --------------------------------------------------------------------------- #


def print_rules(preset_name: str, presets_dir: Optional[str] = None,
                timeout: float = LIST_TIMEOUT) -> Dict[str, Any]:
    """调 ``--print-rules --preset NAME``，返回角色 → 属性列表的映射。

    返回结构（CLI 原样）::

        {"source": {...}, "rule_count": n, "roles": {"标题": ["align", "font", ...]},
         "cleanup": [...], "structure": [...], "default_font": {...}, "llm": {...}}

    失败时抛 :class:`BridgeError`（界面自行决定是提示还是降级）。
    """
    name = (preset_name or "").strip()
    if not name:
        raise BridgeError("没有指定预设名，无法预览规则")
    argv = build_command("--print-rules", "--preset",
                         _cli_preset_name(name, presets_dir), presets_dir=presets_dir)
    code, out, err = _run(argv, timeout)
    data: Dict[str, Any] = {}
    try:
        data = _parse_json(out, argv)
    except BridgeError:
        if code != 0:
            raise BridgeError(
                f"解析预设「{name}」失败（退出码 {code}）",
                returncode=code, stdout=out, stderr=err, argv=argv,
            )
        raise
    if data.get("ok") is False:
        raise BridgeError(
            f"解析预设「{name}」失败：{data.get('error')}",
            returncode=code, stdout=out, stderr=err, argv=argv,
        )
    return data


def role_table(rules: Dict[str, Any]) -> List[Tuple[str, str]]:
    """把 ``print_rules()`` 结果压成 ``[(角色, 属性摘要), ...]`` 供弹窗表格用。"""
    roles = (rules or {}).get("roles") or {}
    rows: List[Tuple[str, str]] = []
    for role in sorted(roles):
        attrs = roles[role] or []
        rows.append((str(role), "、".join(str(a) for a in attrs) or "（无）"))
    return rows


def cleanup_labels(rules: Dict[str, Any]) -> List[str]:
    items = (rules or {}).get("cleanup") or []
    return [str(x) for x in items]


def structure_labels(rules: Dict[str, Any]) -> List[str]:
    items = (rules or {}).get("structure") or []
    return [str(x) for x in items]


# --------------------------------------------------------------------------- #
# 3. 真正处理
# --------------------------------------------------------------------------- #


def process(target: str, preset: str, output: str,
            presets_dir: Optional[str] = None,
            report_path: Optional[str] = None,
            timeout: float = DEFAULT_TIMEOUT,
            no_cache: bool = False,
            dry_run: bool = False,
            extra_args: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """按预设处理一份 .docx，返回 CLI 的 JSON 摘要（读不到就抛 BridgeError）。

    摘要字段见插件 ``report.short_summary``：``ok / output_docx / report_json /
    applied / skipped / llm_calls / text_unchanged / text_cleaned / cleanup /
    structure / warnings / partial``。
    """
    target_path = Path(target)
    if not target_path.is_file():
        raise BridgeError(f"目标文件不存在：{target}", argv=[])
    name = (preset or "").strip()
    if not name:
        raise BridgeError("没有选择预设，无法处理", argv=[])
    out_path = Path(output)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BridgeError(f"输出目录不可用：{out_path.parent}（{exc}）", argv=[]) from exc

    args: List[str] = ["--target", str(target_path), "--preset",
                       _cli_preset_name(name, presets_dir),
                       "--output", str(out_path), "--json"]
    if report_path is None:
        # 报告先写到系统临时目录，绝不落到 exe 同级（Program Files 不可写）；
        # 处理成功后 GUI 再把它移到输出文件旁边给用户看。
        report_path = temp_report_path(str(out_path))
    if report_path:
        args.extend(["--report", str(report_path)])
    if dry_run:
        args.append("--dry-run")
    if extra_args:
        args.extend(str(a) for a in extra_args)
    argv = build_command(*args, presets_dir=presets_dir, no_cache=no_cache)

    code, out, err = _run(argv, timeout)
    # CLI 崩溃（traceback）时 stdout 是空的，真正的报错只在 stderr 末尾。
    # 先把它抽出来，避免界面只收到一句“没有输出任何内容”。
    reason = _stderr_error(err)
    digest = _stderr_digest(err)
    error = ""
    try:
        summary = _summary_or_error(out, argv)
    except BridgeError as exc:
        summary = {"ok": False}
        if code == 0 and not reason:
            raise
        error = digest or str(exc)
    if not summary.get("ok") and not error:
        # 退出码非 0 时界面必须看到真实原因：CLI 的 errors → error → 过滤后的
        # stderr（含 traceback）→ 最后才退回“退出码 N”。
        error = (_summary_errors(summary)
                 or str(summary.get("error") or "").strip()
                 or digest
                 or reason
                 or f"处理失败（退出码 {code}）")
    return ProcessResult(
        ok=bool(summary.get("ok")),
        summary=summary,
        returncode=code,
        stdout=out,
        stderr=err,
        argv=argv,
        error=error,
    ).to_dict()


def _first_error_line(stderr: str, stdout: str) -> str:
    """失败摘要：stderr 里的根因（含 traceback 末尾异常）优先，再退回 stdout。"""
    return _stderr_error(stderr) or (stdout or "").strip()[:200]


def _cli_preset_name(name: str, presets_dir: Optional[str]) -> str:
    """把展示名映射成 CLI 认的标识（去后缀的文件名）。

    用户预设的文件名形如 ``user_<时间戳>_<名字>.txt``，插件只认文件名去后缀；
    因此当 ``name`` 在 ``presets_dir`` 里找不到同名文件、却匹配到某个用户的
    ``stem`` 里包含该名字时，换成那个 stem。找不到就原样返回（让插件自己报错）。
    """
    clean = (name or "").strip()
    if not clean or not presets_dir:
        return clean
    base = Path(presets_dir)
    try:
        files = [p for p in base.iterdir() if p.is_file() and not p.name.startswith(".")]
    except OSError:
        return clean
    stems = [p.stem for p in files if p.suffix.lower() in (".txt", ".md", ".docx")]
    if clean in stems:
        return clean
    for stem in sorted(stems):
        if clean in stem:
            return stem
    return clean


# --------------------------------------------------------------------------- #
# 便捷：可用性探测
# --------------------------------------------------------------------------- #


def cli_available(timeout: float = LIST_TIMEOUT) -> bool:
    """插件 CLI 是否可用（能列出预设就算可用）。"""
    return bool(list_builtin_presets(timeout))


def describe_entry() -> str:
    """给界面/日志显示当前使用的 CLI 入口。"""
    mode = "打包 exe（--wfa-cli）" if frozen() else f"开发 .venv（-m {CLI_MODULE}）"
    return f"{mode} → {sys.executable}"


def temp_report_path(output_docx: str) -> str:
    """报告在系统临时目录里的落点：``%TEMP%\\taofu-reports\\<输出名>-<pid>-<时间>.report.json``。"""
    folder = Path(tempfile.gettempdir()) / "taofu-reports"
    stem = Path(output_docx).stem or "report"
    name = "%s-%d-%s.report.json" % (stem, os.getpid(),
                                     time.strftime("%Y%m%d-%H%M%S"))
    return str(folder / name)


def default_report_path(output_docx: str) -> str:
    """CLI 缺省的报告路径规则：系统临时目录（不再是输出文件旁边）。"""
    return temp_report_path(str(output_docx))
