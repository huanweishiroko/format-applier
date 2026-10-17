# -*- coding: utf-8 -*-
"""预设列表读取（内置 + 用户，合并展示）。

数据来源：

  1. **内置**：首选插件 CLI ``python -m word_format_applier --list-presets-json``
     （带 UTF-8 环境，超时 8s；失败不影响界面），
     回落为直接扫项目里的 ``presets/`` 目录。
  2. **用户**：``%APPDATA%\\Taofu\\presets\\``（见 :mod:`user_presets`），
     经 CLI ``--list-presets-json --presets-dir <该目录>`` 读取；
     这条 CLI 不可用时回落为扫目录。

合并规则：**同名时用户预设覆盖内置预设**（并在 :func:`load_all_presets` 的返回里
同时保留被覆盖的内置项，source 标为 ``builtin``，由界面决定是否提示）。

本模块只读列表，不解析规则、不写任何预设文件。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 绝对优先：冻结后 app.py 以 __main__ 直跑，core 是顶层包，
# `from . import ...` 会越过顶层包；相对形式只留给包内运行兜底。
try:
    from core import config as cfg
    from core import user_presets as up
except ImportError:  # pragma: no cover - 包内运行时
    from . import config as cfg  # type: ignore
    from . import user_presets as up  # type: ignore

#: 预设目录里被识别为预设的后缀；其余文件（含 .cache/）忽略
PRESET_SUFFIXES = (".txt", ".docx", ".md")

CLI_TIMEOUT = 8.0


@dataclass
class Preset:
    """一条预设记录（name/file/ext/size 与 CLI JSON 对齐）。

    ``name`` 是展示名（用户预设为「用户输入的名字」），
    ``cli_name`` 是**插件 CLI 认的标识**（内置=name，用户=文件名去后缀，
    例如 ``user_20261005_234252_我的格式``）。调 CLI 时必须用 ``cli_name``。
    """

    name: str
    file: str
    ext: str
    size: int
    mtime: float = 0.0
    path: Optional[Path] = None
    source: str = "builtin"  # builtin | user
    via: str = "scan"        # cli | scan（怎么读到的）
    cli_name: str = ""

    def __post_init__(self) -> None:
        if not self.cli_name:
            # 内置预设：文件名去后缀 == 展示名；用户预设走 file 的 stem
            self.cli_name = Path(self.file).stem if self.file else self.name

    @property
    def exists(self) -> bool:
        return self.path is not None and self.path.is_file()

    @property
    def is_user(self) -> bool:
        return self.source == "user"

    @property
    def source_label(self) -> str:
        return "我的预设" if self.is_user else "内置预设"

    @property
    def display_name(self) -> str:
        """下拉框里的展示名：📦 内置 / 👤 用户。"""
        return f"{'👤' if self.is_user else '📦'} {self.name}"

    @property
    def size_label(self) -> str:
        return cfg.human_size(self.size)

    @property
    def ext_label(self) -> str:
        return {"txt": "文本要求", "docx": "Word 模板", "md": "Markdown"}.get(
            self.ext.lstrip(".").lower(), self.ext or "未知"
        )

    @property
    def mtime_label(self) -> str:
        return cfg.fmt_mtime(self.path) if self.path else "-"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "cli_name": self.cli_name,
            "file": self.file,
            "ext": self.ext,
            "size": self.size,
            "mtime": self.mtime_label,
            "source": self.source,
            "via": self.via,
            "path": str(self.path) if self.path else "",
            "display": self.display_name,
        }

    # 便于把 Preset 当只读字典用（p["source"]）
    def __getitem__(self, key: str) -> Any:
        try:
            return self.to_dict()[key]
        except KeyError as exc:  # pragma: no cover
            raise KeyError(key) from exc


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #


def presets_dir() -> Path:
    return cfg.PRESETS_DIR


# --------------------------------------------------------------------------- #
# 路径 1：CLI
# --------------------------------------------------------------------------- #


def _cli_argv() -> Optional[List[str]]:
    python = cfg.venv_python()
    if python is None:
        return None
    return [str(python), "-m", "word_format_applier", "--list-presets-json"]


def discover_via_cli(timeout: float = CLI_TIMEOUT) -> Optional[List[Preset]]:
    """调 CLI 列预设。任何异常（缺解释器/超时/非零退出/JSON 坏了）返回 None。"""
    argv = _cli_argv()
    if argv is None:
        return None
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cfg.PROJECT_ROOT),
            env=cfg.cli_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None

    raw_items = data.get("presets")
    if not isinstance(raw_items, list):
        return None
    directory = Path(data.get("presets_dir") or presets_dir())

    presets: List[Preset] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        fname = str(item.get("file") or "")
        if not fname:
            continue
        path = directory / fname
        mtime = path.stat().st_mtime if path.is_file() else 0.0
        presets.append(
            Preset(
                name=str(item.get("name") or Path(fname).stem),
                file=fname,
                ext=str(item.get("ext") or Path(fname).suffix),
                size=int(item.get("size") or 0),
                mtime=mtime,
                path=path,
                source="builtin",
                via="cli",
            )
        )
    return presets


# --------------------------------------------------------------------------- #
# 路径 2：直接扫目录
# --------------------------------------------------------------------------- #


def discover_via_scan(directory: Optional[Path] = None) -> List[Preset]:
    """扫 presets/ 下的顶层文件（跳过 .cache/ 与隐藏文件）。"""
    base = Path(directory) if directory else presets_dir()
    presets: List[Preset] = []
    try:
        entries: Sequence[Path] = sorted(base.iterdir(), key=lambda p: p.name)
    except OSError:
        return presets

    for entry in entries:
        try:
            if not entry.is_file() or entry.name.startswith("."):
                continue
            if entry.suffix.lower() not in PRESET_SUFFIXES:
                continue
            stat = entry.stat()
        except OSError:
            continue
        presets.append(
            Preset(
                name=entry.stem,
                file=entry.name,
                ext=entry.suffix,
                size=int(stat.st_size),
                mtime=stat.st_mtime,
                path=entry,
                source="builtin",
                via="scan",
            )
        )
    return presets


# --------------------------------------------------------------------------- #
# 路径 3：用户预设
# --------------------------------------------------------------------------- #


def user_presets_dir() -> Path:
    """用户预设目录（不存在时也会尝试创建）。"""
    return up.get_user_preset_dir()


def discover_user(directory: Optional[Path] = None) -> List[Preset]:
    """读用户预设：先试 CLI ``--presets-dir <用户目录>``，失败回落扫目录。

    展示名由 :mod:`user_presets` 反解（``user_<时间戳>_<名字>.txt`` → ``<名字>``），
    CLI 标识（``cli_name``）仍是文件名去后缀 —— 插件只认文件名。
    """
    base = Path(directory) if directory else user_presets_dir()
    friendly = {item.file: item for item in up.list_user_presets(base)}

    via_cli = discover_via_cli_dir(base)
    if via_cli is not None:
        for item in via_cli:
            item.source = "user"
            meta = friendly.get(item.file)
            if meta is not None:
                item.name = meta.name
        return via_cli

    return [
        Preset(
            name=item.name, file=item.file, ext=item.ext, size=item.size,
            mtime=item.mtime, path=item.path, source="user", via="scan",
            cli_name=Path(item.file).stem,
        )
        for item in up.list_user_presets(base)
    ]


def discover_via_cli_dir(directory: Path, timeout: float = CLI_TIMEOUT) -> Optional[List[Preset]]:
    """对指定目录调 ``--list-presets-json --presets-dir``；失败返回 None。

    与 :func:`discover_via_cli` 的区别：这里显式带 ``--presets-dir``，
    所以用来读用户预设目录。目录里没有文件时返回空列表（不是 None）。
    """
    argv = _cli_argv_dir(directory)
    if argv is None:
        return None
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cfg.PROJECT_ROOT),
            env=cfg.cli_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    raw_items = data.get("presets")
    if not isinstance(raw_items, list):
        return None
    base = Path(data.get("presets_dir") or directory)
    presets: List[Preset] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        fname = str(item.get("file") or "")
        if not fname:
            continue
        path = base / fname
        presets.append(Preset(
            name=str(item.get("name") or Path(fname).stem),
            file=fname,
            ext=str(item.get("ext") or Path(fname).suffix),
            size=int(item.get("size") or 0),
            mtime=path.stat().st_mtime if path.is_file() else 0.0,
            path=path,
            source="user",
            via="cli",
        ))
    return presets


def _cli_argv_dir(directory: Path) -> Optional[List[str]]:
    python = cfg.venv_python()
    if python is None:
        return None
    return [
        str(python), "-m", "word_format_applier",
        "--list-presets-json", "--presets-dir", str(directory),
    ]


# --------------------------------------------------------------------------- #
# 合并
# --------------------------------------------------------------------------- #


def load_all_presets(use_cli: bool = True) -> List[Preset]:
    """合并「内置 + 用户」预设列表。

    返回 ``[Preset, ...]``，每项带 ``source``（builtin/user）与 ``via``（cli/scan）。
    同名冲突时：用户预设排在前（生效项），紧随其后保留同名的内置项（提示用）。
    永不抛异常，最多返回空列表。
    """
    builtin = load_presets(use_cli=use_cli)
    user = discover_user()

    user_names = {p.name for p in user}
    shadowed = [p for p in builtin if p.name in user_names]
    kept = [p for p in builtin if p.name not in user_names]
    return list(user) + shadowed + kept


def shadowed_names(presets: Sequence[Preset]) -> List[str]:
    """找出「被用户预设覆盖的同名内置预设」名字（提示用户用）。"""
    seen: Dict[str, int] = {}
    for preset in presets:
        seen[preset.name] = seen.get(preset.name, 0) + 1
    return sorted(name for name, count in seen.items() if count > 1)


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #


def load_presets(use_cli: bool = True, directory: Optional[Path] = None) -> List[Preset]:
    """列出**内置**预设：先 CLI，再回落扫目录。永不抛异常，最多返回空列表。"""
    if use_cli and directory is None:
        presets = discover_via_cli()
        if presets is not None:
            return presets
    return discover_via_scan(directory)


def preset_names(presets: Optional[Sequence[Preset]] = None) -> List[str]:
    """下拉框用的名字列表（保持顺序）。"""
    items = list(presets) if presets is not None else load_all_presets()
    return [p.name for p in items]


def find_preset(name: str, presets: Optional[Sequence[Preset]] = None) -> Optional[Preset]:
    items = list(presets) if presets is not None else load_all_presets()
    for item in items:
        if item.name == name:
            return item
    return None


def display_name(name: str, presets: Optional[Sequence[Preset]] = None) -> str:
    """``📦 格式要求1`` / ``👤 我的格式``。"""
    found = find_preset(name, presets)
    return found.display_name if found else name


def presets_dir_arg(preset: Optional[Preset]) -> Optional[str]:
    """该预设要用哪个 ``--presets-dir``：用户预设给用户目录，内置给 None。"""
    if preset is not None and preset.is_user:
        return str(user_presets_dir())
    return None


def read_preview(preset: Preset, limit: int = 4000) -> str:
    """预设文件前若干字符，供预览弹窗用（纯文本读，txt/md 才有内容）。"""
    if not preset.exists or preset.path is None:
        return "[文件不存在]"
    if preset.ext.lower() != ".txt" and preset.ext.lower() != ".md":
        return "[该格式为二进制模板，文本预览不可用]"
    try:
        text = preset.path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"[读取失败] {exc}"
    if len(text) > limit:
        return text[:limit] + f"\n\n…（已截断，全文 {len(text)} 字符）"
    return text
