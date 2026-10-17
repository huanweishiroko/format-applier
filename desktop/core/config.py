# -*- coding: utf-8 -*-
"""用户配置与 .env 读取（路径解析的唯一出口）。

本模块只做"文件与字符串"级别的事，不 import tkinter，方便单测与复用。

职责：
  * 定位程序本体目录、项目根（desktop/ 的上一级）与关键目录（presets/、src/、.venv/）
  * 定位 config.json（**%APPDATA%\\Taofu**）与 .env（**exe 同级**，老用户兼容）
  * 读写 config.json（默认输出目录、主题、窗口尺寸、API 地址/密钥/模型等用户偏好）
  * 提供 API 配置的读取与来源说明；密钥展示一律脱敏

路径布局（Phase 5 起）
--------------------
============================  ==================================================
``config.json``               ``%APPDATA%\\Taofu\\config.json``（含 API 配置三项）
``.env``                      **exe 同级**（开发期 = ``desktop\\.env``）；
                              老用户兼容，新用户不需要；旧版 ``_internal\\.env``
                              仍可被读到（兼容，不报错）
``.env.example``              exe 同级（打包时由 build_finish.py 放一份模板）
默认输出目录                  ``%USERPROFILE%\\Documents\\Taofu\\``
内置预设                      ``<exe 同级>\\presets\\`` → ``_internal\\presets\\`` → ``<项目根>\\presets\\``
============================  ==================================================

要点：**不要**用 ``__file__`` 推用户可见路径。frozen 后模块的 ``__file__`` 指向
``_internal\\``，用它推出来的路径用户既找不到也不好改（这正是本次要修的问题）。
用户可见的路径一律用 ``sys.executable``（frozen）/ ``__file__``（开发期）来推。
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import stat
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# 路径常量
# --------------------------------------------------------------------------- #

def frozen() -> bool:
    """当前进程是否跑在 PyInstaller 打包产物里。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """用户眼中的"程序目录"：frozen = exe 所在目录，开发期 = ``desktop\\``。

    ***用户可见文件（.env 等）一律以这里为基准***，因为 frozen 后
    ``__file__`` 指向 ``_internal\\``（用户不会去翻的地方）。
    """
    if frozen():
        try:
            return Path(sys.executable).resolve().parent
        except (OSError, ValueError, TypeError):  # pragma: no cover - exe 路径异常
            pass
    return Path(__file__).resolve().parent.parent


#: 程序目录（exe 同级 / desktop/）
APP_DIR: Path = app_dir()

#: 兼容别名：老代码（与文档）里的 DESKTOP_DIR 就是"程序目录"
DESKTOP_DIR: Path = APP_DIR

#: 项目根：开发期 = 仓库根；frozen 下 = exe 同级（.venv/src/samples 都在开发期那边，
#: 打包后用不到，但 PYTHONPATH / cwd 仍要有个稳定的绝对路径）
PROJECT_ROOT: Path = APP_DIR.parent
SRC_DIR: Path = PROJECT_ROOT / "src"

#: 预设文件后缀（与插件 presets.py 的 PRESET_EXTENSIONS 对齐）
PRESET_SUFFIXES = (".txt", ".md", ".docx")


def _internal_dir() -> Optional[Path]:
    """PyInstaller 的 _MEIPASS（onedir 下 = exe 同级的 _internal\\）。"""
    raw = getattr(sys, "_MEIPASS", None)
    return Path(str(raw)) if raw else None


def asset_path(name: str) -> Path:
    """只读资源（图标等）的定位：开发期在 desktop/assets/，frozen 后在 _MEIPASS/assets/。

    spec 会把整个 desktop/assets 铺进 _internal/assets（见 Taofu.spec），所以这里
    frozen 走 `_internal_dir()`，**不要**用 APP_DIR —— exe 同级没有 assets。
    返回的路径不保证存在，调用方自己 try/except 兜底。
    """
    internal = _internal_dir()
    if frozen() and internal is not None:
        return internal / "assets" / name
    return APP_DIR / "assets" / name


# --------------------------------------------------------------------------- #
# .env 定位（顺序即优先级）
# --------------------------------------------------------------------------- #


def _legacy_env_candidates() -> Tuple[Path, ...]:
    """旧版 .env 落点（只读兼容，找不到就忽略，绝不报错）。

    * ``_internal\\.env`` —— Phase 4 打包时 ``config.ENV_PATH = _MEIPASS/.env``
      写出来的位置；开发期不存在，忽略即可。
    * 开发期 ``desktop\\.env`` —— 只有非 frozen 时才可能是"旧落点"；frozen 下
      这个路径指向仓库，绝不能拿来当候选（否则打包版会读到开发机的密钥）。
    """
    candidates: List[Path] = []
    internal = _internal_dir()
    if internal is not None:
        candidates.append(internal / ".env")
    if not frozen():
        candidates.append(APP_DIR / ".env")
    return tuple(candidates)


def resolve_env_path() -> Optional[Path]:
    """按优先级选一个 .env 文件；一个都没有就返回 ``None``（不是错误）。

    1. exe 同级 ``.env``（开发期 = ``desktop\\.env``）
    2. 旧版 ``_internal\\.env``
    3. 旧版开发期 ``desktop\\.env``

    注意：**环境变量本身优先于任何 .env 文件**（见 ``env_values()``），
    所以用户完全不建 .env、只设 OPENAI_* 环境变量也能跑。
    """
    primary = APP_DIR / ".env"
    if primary.is_file():
        return primary
    for candidate in _legacy_env_candidates():
        try:
            if candidate.is_file():
                return candidate
        except OSError:  # pragma: no cover - 极端路径
            continue
    return None


#: 当前实际生效的 .env 路径（可能是 None；导入后不再变化）
ENV_PATH: Optional[Path] = resolve_env_path()

#: 新建 .env 时建议的位置：**永远**是 exe 同级（不给用户往 _internal 里放）
ENV_TARGET_PATH: Path = APP_DIR / ".env"

#: 找不到 .env 时提示用户照抄的模板（同在 exe 同级）
ENV_EXAMPLE_PATH: Path = APP_DIR / ".env.example"


# --------------------------------------------------------------------------- #
# 用户数据目录 %APPDATA%\Taofu\（config.json / presets / usage.json）
# --------------------------------------------------------------------------- #


def user_data_dir(create: bool = False) -> Path:
    """用户数据根目录；``%APPDATA%`` 缺失（罕见）时降级到 ``~/.taofu``。

    config.json、presets\\、usage.json 三者都挂在这个根下面，保持一致。
    """
    appdata = (os.environ.get("APPDATA") or "").strip()
    base = Path(appdata) / "Taofu" if appdata else Path.home() / ".taofu"
    if create:
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return base


def display_path(path: "str | Path") -> str:
    """把本机绝对路径换成用户看得懂的短写法。

    界面/日志里不该出现一长串夹带用户名的 AppData 绝对路径，
    统一显示成 ``%APPDATA%\\Taofu\\config.json``；
    家目录下的路径显示成 ``%USERPROFILE%\\...``；其它路径原样返回。
    """
    raw = str(path or "")
    if not raw:
        return ""
    try:
        target = Path(raw)
        for base, token in ((user_data_dir(), "%APPDATA%\\Taofu"),
                            (Path.home(), "%USERPROFILE%")):
            try:
                rel = target.relative_to(base)
            except ValueError:
                continue
            return token + ("\\" + str(rel) if str(rel) not in ("", ".") else "")
    except (OSError, ValueError):
        pass
    return raw


def config_path() -> Path:
    """config.json 路径（``%APPDATA%\\Taofu\\config.json``）。"""
    return user_data_dir() / "config.json"


#: 用户配置落点（导入时求值一次；与 user_presets 的用户预设目录同根）
CONFIG_PATH: Path = config_path()


def config_candidates() -> Tuple[Path, ...]:
    """config.json 的候选落点，按优先级排列。

    1. ``%APPDATA%\\Taofu\\config.json`` —— 正常情况只用这一个；
    2. ``%LOCALAPPDATA%\\Taofu\\config.json`` —— 主落点被锁死（杀软拦截、权限、
       文件被占用）时的退路，仍在用户目录里，不进程序目录；
    3. ``<exe 同级>\\data\\config.json`` —— 绿色便携场景（仅 frozen，且前两处都写不进）。

    写入按顺序退让；读取由 ``active_config_path()`` 挑最新的一份。
    """
    out: List[Path] = [CONFIG_PATH]
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        candidate = Path(local) / "Taofu" / "config.json"
        if candidate != CONFIG_PATH:
            out.append(candidate)
    if frozen():
        candidate = APP_DIR / "data" / "config.json"
        if candidate not in out:
            out.append(candidate)
    return tuple(out)


def active_config_path() -> Path:
    """当前**实际生效**的 config.json。

    规则：候选里“存在”的那几份，取**修改时间最新**的一份；都不存在则返回主落点。
    这样主落点写不进、配置自动改存到第二落点时，下次启动读的仍是最新那份，
    而不会被旧的半截文件顶掉。
    """
    best: Optional[Path] = None
    best_mtime = -1.0
    for candidate in config_candidates():
        try:
            if not candidate.is_file():
                continue
            mtime = candidate.stat().st_mtime
        except OSError:
            continue
        if mtime > best_mtime:
            best, best_mtime = candidate, mtime
    return best if best is not None else CONFIG_PATH

#: 旧版 config.json 落点（Phase 4 打包后在 _internal\\，仅在内存里读旧值用）
LEGACY_CONFIG_CANDIDATES: Tuple[Path, ...] = (
    (_internal_dir() / "config.json",) if _internal_dir() is not None else ()
)


#: 旧版用户数据目录名（v1.x 用的）；只在 migrate_legacy_data() 里出现
LEGACY_DATA_DIRNAME = "WordFormatAssistant"


def legacy_user_data_dir() -> Path:
    """旧版用户数据根目录（%APPDATA%/WordFormatAssistant，APPDATA 缺失时 ~/.word_format_assistant）。"""
    appdata = (os.environ.get("APPDATA") or "").strip()
    if appdata:
        return Path(appdata) / LEGACY_DATA_DIRNAME
    return Path.home() / ".word_format_assistant"


def migrate_legacy_data() -> Optional[str]:
    """把旧版用户数据从 WordFormatAssistant 目录搬到 Taofu 目录（v2.0.0 一次性迁移）。

    触发条件（两条都满足才动手）：新目录**不存在** + 旧目录存在。
    迁移内容：config.json、usage.json、presets/。
    **只复制不删除** —— 旧目录原样保留作备份，用户反悔了还能自己翻回来。

    返回一行摘要（给启动日志用）；没触发 / 没内容可搬 / 出错都返回 None，
    绝不抛异常阻断启动。必须在 ``load_settings()`` 之前调用一次。
    """
    new_dir = user_data_dir()
    old_dir = legacy_user_data_dir()
    if new_dir.exists() or not old_dir.is_dir():
        return None

    copied: List[str] = []
    try:
        new_dir.mkdir(parents=True, exist_ok=True)
        for name in ("config.json", "usage.json"):
            src = old_dir / name
            if src.is_file():
                shutil.copy2(src, new_dir / name)
                copied.append(name)
        src_presets = old_dir / "presets"
        if src_presets.is_dir():
            shutil.copytree(src_presets, new_dir / "presets", dirs_exist_ok=True)
            copied.append("presets/")
        # copy2/copytree 会把老目录的只读属性原样搬过来——新目录一开局就“不可写”，
        # 表现就是设置页怎么点保存都失败。这里统一清成可写。
        _make_tree_writable(new_dir)
    except OSError as exc:              # 权限不足 / 磁盘满：只报告，不阻断启动
        return f"旧用户数据迁移失败：{_error_detail(exc)}"
    if not copied:
        return None
    return f"已迁移旧用户数据 -> {new_dir}（{'、'.join(copied)}；旧目录保留作备份）"


def _has_preset_files(folder: Path) -> bool:
    """目录里是否真有预设文件（.cache\\ 之类不算）。"""
    try:
        for entry in folder.iterdir():
            if entry.is_file() and not entry.name.startswith(".") \
                    and entry.suffix.lower() in PRESET_SUFFIXES:
                return True
    except OSError:
        return False
    return False


def resolve_presets_dir() -> Path:
    """内置预设目录，按优先级探测（打包后不再依赖"打完搬文件"）。

    1. ``<exe 同级>\\presets\\`` —— 用户可直接覆盖/自定义：只要放了这个目录
       且里面有预设文件，就用它；
    2. ``_internal\\presets\\`` —— spec 打进去的内置预设（`_MEIPASS/presets`）；
    3. ``<项目根>\\presets\\`` —— 开发期（非冻结）路径。

    冻结后 ``PROJECT_ROOT`` = exe 所在目录的上一级，而第 1 条用的
    ``internal.parent`` 才是 exe 同级；两条分开写就是为了让开发态语义保持
    "仓库里的 presets/"。都探测不到时返回的项目根路径允许不存在（调用方会兜）。
    """
    internal = _internal_dir()
    if frozen() and internal is not None:
        beside_exe = internal.parent / "presets"
        if _has_preset_files(beside_exe):
            return beside_exe
        if _has_preset_files(internal / "presets"):
            return internal / "presets"
    return PROJECT_ROOT / "presets"


#: 内置预设目录（探测结果；`presets_dir()` 是同一件事的函数形式）
PRESETS_DIR: Path = resolve_presets_dir()

APP_NAME = "桃符"
APP_VERSION = "2.0.0"
PHASE_LABEL = "正式版"

#: 老版 .env 的三项（兼容保留）：新用户请在设置页填写，不需要碰 .env。
#: 只有 config.json 里没有 API 配置时，才会回落到它们。
ENV_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("OPENAI_BASE_URL", "API 地址"),
    ("OPENAI_API_KEY", "API 密钥"),
    ("OPENAI_MODEL", "模型名"),
)

#: 视为密钥的字段，展示时脱敏
SECRET_FIELDS = frozenset({"OPENAI_API_KEY"})

THEME_CHOICES = ("浅色", "深色", "跟随系统")
_THEME_TO_CTK = {"浅色": "light", "深色": "dark", "跟随系统": "system"}


# --------------------------------------------------------------------------- #
# 用户设置
# --------------------------------------------------------------------------- #


@dataclass
class Settings:
    """config.json 的结构。字段缺失时用这里的默认值。

    ``output_dir`` 的空串是**哨兵值**，表示"用户还没配过"：由
    ``ensure_output_dir()`` 在启动时解析成默认目录并立刻落盘。
    """

    output_dir: str = ""
    theme: str = "浅色"
    window_size: str = "1080x720"
    last_preset: str = ""
    log_expanded: bool = False
    #: AI 解析配置：设置页填三项并点「保存配置」后写进 config.json。
    #: 只有 config.json 里**缺**这些字段时才回落到 exe 同级的 .env（兼容老用户）。
    api_base_url: str = ""
    api_key: str = ""
    api_model: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    #: 运行时标记（不落盘）：本次是首次启动，输出目录还是默认值
    first_run: bool = False

    # -- 主题 -------------------------------------------------------------- #
    @property
    def ctk_appearance(self) -> str:
        """转成 customtkinter 的 appearance mode。"""
        return _THEME_TO_CTK.get(self.theme, "light")


def _documents_dir() -> Path:
    """用户的「文档」目录。

    优先读注册表 ``User Shell Folders\\Personal``（被 OneDrive 重定向过的机器上
    才准），读不到就回落 ``~/Documents``（不存在则再退到用户主目录）。
    """
    try:
        import winreg  # type: ignore[import-not-found]

        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            raw, _kind = winreg.QueryValueEx(handle, "Personal")
        expanded = os.path.expandvars(str(raw))
        if expanded:
            return Path(expanded)
    except Exception:  # noqa: BLE001 - 非 Windows / 注册表不可读都不该影响启动
        pass
    home = Path.home()
    for candidate in (home / "Documents", home):
        if candidate.is_dir():
            return candidate
    return home


def default_output_dir() -> Path:
    """默认输出目录（用户可见、不埋在 _internal）。

    首选 ``%USERPROFILE%\\Documents\\Taofu\\``；建不出来时退回
    用户的「文档」目录本身（不抛异常）。
    """
    preferred = _documents_dir() / "Taofu"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        return _documents_dir()


def ensure_output_dir(base: Optional[Path] = None) -> str:
    """把输出目录**落实成一个真的存在的路径**并返回。

    空 / 缺失 → 默认目录；用户填的路径建不出来 → 不擅自改，原样返回（由界面提示）。

    首次解析出的默认值请由 ``app.save_settings()`` 落盘（本函数不写文件）。
    """
    raw = str(base if base is not None else "").strip()
    if not raw:
        return str(default_output_dir())
    try:
        Path(raw).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return raw


def _read_json_dict(target: Path) -> Dict[str, Any]:
    """读一个 JSON 对象；不存在 / 损坏 / 不是对象都返回空 dict，绝不抛异常。"""
    try:
        if target.is_file():
            raw = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
    except (OSError, ValueError):
        pass
    return {}


def load_settings(path: Optional[Path] = None) -> Settings:
    """读 ``%APPDATA%\\Taofu\\config.json``，缺字段用默认值。

    ``path`` 显式给定时只读那个文件（单测用）。未显式给定时：
      1. 新位置有 → 读新的；
      2. 新位置没有、旧版 ``_internal\\config.json`` 有 → **只在内存里**沿用旧值
         （不自动写新文件，是否迁移由用户在启动提示里决定）；
      3. 都没有 → 默认值，并把 ``first_run`` 标为 True。

    ``first_run`` 不进 JSON，只是提示调用方"输出目录需要落实并落盘"。
    """
    if path is not None:
        data = _read_json_dict(Path(path))
    else:
        data = _read_json_dict(active_config_path())
        if not data:
            for legacy in LEGACY_CONFIG_CANDIDATES:
                data = _read_json_dict(legacy)
                if data:
                    break
    first_run = not str(data.get("output_dir") or "").strip()

    known = {f for f in Settings.__dataclass_fields__ if f not in ("extra", "first_run")}
    kwargs = {k: v for k, v in data.items() if k in known}
    extra = {k: v for k, v in data.items() if k not in known}

    settings = Settings(**kwargs)
    settings.extra = extra
    settings.first_run = first_run
    if settings.theme not in THEME_CHOICES:
        settings.theme = "浅色"
    if not isinstance(settings.output_dir, str):
        settings.output_dir = ""
    return settings


def _clear_readonly(target: Path) -> None:
    """清掉目标文件/目录的只读属性。

    Windows 上只读属性会让 ``write_text`` 直接抛 ``PermissionError``
    (WinError 5)，而这恰恰是 ``copy2``/``copytree`` 从老目录带过来的东西。
    """
    for item in (target, target.parent):
        try:
            mode = item.stat().st_mode
            if not mode & stat.S_IWRITE:
                os.chmod(item, mode | stat.S_IWRITE)
        except OSError:                 # 不存在 / 无权限：交给后面的写入报错
            continue


def _error_detail(exc: OSError) -> str:
    """把 OSError 整理成一行可读、可贴给用户的说明（含 WinError / errno / 路径）。"""
    parts = [f"{type(exc).__name__}: {exc}"]
    winerror = getattr(exc, "winerror", None)
    if winerror:
        parts.append(f"WinError={winerror}")
    if exc.errno is not None:
        parts.append(f"errno={exc.errno}")
    if getattr(exc, "filename", None):
        parts.append(f"path={exc.filename}")
    return " · ".join(parts)


def _write_config_file(target: Path, text: str) -> None:
    """把 text 写进 target；写不进去就抛 OSError（带上最后一次的真实原因）。

    依次尝试四种写法，专治 Windows 上最常见的几种失败：
      1. 建目录 + 清只读 + 直接覆盖；
      2. 写 ``<name>.tmp`` 再 ``os.replace`` 原子替换（绕过“文件被占用”）；
      3. 删掉目标文件再重建（绕过“文件被锁但目录可写”）；
      4. 只读属性顽固时再强制 chmod 后重试一次。
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    _clear_readonly(target)
    tmp = target.with_name(target.name + ".tmp")
    strategies = (
        lambda: target.write_text(text, encoding="utf-8"),
        lambda: (tmp.write_text(text, encoding="utf-8"), os.replace(tmp, target)),
        lambda: (target.unlink(missing_ok=True), target.write_text(text, encoding="utf-8")),
        lambda: (_force_writable(target), target.write_text(text, encoding="utf-8")),
    )
    last: Optional[OSError] = None
    for strategy in strategies:
        try:
            strategy()
            return
        except OSError as exc:
            last = exc
            try:                        # 失败时别把 .tmp 留在用户目录里
                tmp.unlink()
            except OSError:
                pass
    raise last if last is not None else OSError("未知写入错误")


def _force_writable(target: Path) -> None:
    """强制给目标（存在时）加写权限；不存在则跳过。"""
    try:
        if target.exists():
            os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _make_tree_writable(root: Path) -> None:
    """把整棵目录树（含自身）的文件/目录只读属性清掉。

    用于老数据迁移之后：``copy2`` / ``copytree`` 会把源文件的只读属性一并复制，
    或者源目录本身带拒绝权限，结果新目录里的 ``config.json`` 天生不可写。
    """
    targets: List[Path] = [root]
    try:
        targets.extend(root.rglob("*"))
    except OSError:
        pass
    for item in targets:
        try:
            mode = item.stat().st_mode
            if not mode & stat.S_IWRITE:
                os.chmod(item, mode | stat.S_IWRITE)
        except OSError:
            continue


def save_settings_ex(settings: Settings,
                     path: Optional[Path] = None) -> Tuple[bool, Path, str]:
    """写 config.json；主落点失败时按 ``config_candidates()`` 依次退让。

    返回 ``(是否成功, 实际落点, 失败原因)``。失败原因把每个落点的**具体**
    OSError（WinError / errno / 路径）串起来，界面可以直接展示。
    ``path`` 显式给定时只试那一个，不退让（单测用）。
    """
    targets = (Path(path),) if path is not None else config_candidates()
    payload = asdict(settings)
    extra = payload.pop("extra", {}) or {}
    payload.pop("first_run", None)      # 运行时标记，不落盘
    payload.update(extra)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    errors: List[str] = []
    for target in targets:
        try:
            _write_config_file(Path(target), text)
            return True, Path(target), ""
        except OSError as exc:
            errors.append(f"{display_path(target)} → {_error_detail(exc)}")
    if path is not None and targets:    # 显式路径：错误文案里给出真实路径
        errors = [f"{targets[0]} → {err.split(' → ', 1)[-1]}" for err in errors]
    return False, Path(targets[0]) if targets else CONFIG_PATH, "；".join(errors)


def save_settings(settings: Settings, path: Optional[Path] = None) -> bool:
    """写 config.json，成功返回 True（失败原因见 ``save_settings_ex``）。"""
    return save_settings_ex(settings, path)[0]


# --------------------------------------------------------------------------- #
# .env（只读展示）
# --------------------------------------------------------------------------- #


def read_env_file(path: Optional[Path] = None) -> Dict[str, str]:
    """朴素解析 .env（KEY=VALUE），不展开变量、不写回。"""
    target = Path(path) if path else ENV_PATH
    result: Dict[str, str] = {}
    if target is None:
        return result
    try:
        if not target.is_file():
            return result
        for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return {}
    return result


def _clean_env_value(raw: Optional[str]) -> str:
    value = (raw or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def env_values(path: Optional[Path] = None) -> Tuple[Dict[str, str], Optional[Path]]:
    """本次实际生效的 API 配置，返回 ``(值, 来源文件)``。

    合并顺序（后者不覆盖前者）：
      1. **进程环境变量** —— 最高优先级；设了就不必建 .env；
      2. .env 文件 —— ``path`` 显式给定时只读它，否则用 ``ENV_PATH``
         （exe 同级 → 旧版 ``_internal\\.env``）。

    ``来源文件`` 可能是 ``None``（纯环境变量或什么都没有）。
    """
    values: Dict[str, str] = {}
    for key, _label in ENV_FIELDS:
        value = _clean_env_value(os.environ.get(key))
        if value:
            values[key] = value

    source = Path(path) if path is not None else ENV_PATH
    file_values = read_env_file(source) if source is not None else {}
    for key in file_values:
        if key not in values:
            values[key] = _clean_env_value(file_values.get(key))

    return values, (source if file_values else None)


def env_source_label(path: Optional[Path] = None) -> str:
    """设置页/关于页显示用的"配置来源"一行文字。"""
    values, source = env_values(path)
    if source is not None:
        return str(source)
    from_env = [k for k, _l in ENV_FIELDS if _clean_env_value(os.environ.get(k))]
    if from_env:
        return "环境变量（未使用 .env）"
    if path is not None:
        return f"{path}（不存在）"
    return f"{ENV_TARGET_PATH}（不存在）"


def mask_secret(value: str, keep_head: int = 6, keep_tail: int = 4) -> str:
    """sk-2df0b0…4d64b 风格的脱敏；过短则整体打码。"""
    if not value:
        return "(空)"
    if len(value) <= keep_head + keep_tail:
        return "*" * len(value)
    return f"{value[:keep_head]}{'*' * 8}{value[-keep_tail:]}"


def env_field_rows(path: Optional[Path] = None) -> List[Tuple[str, str, str, bool]]:
    """返回 [(变量名, 中文标签, 展示值, 是否存在)]，供设置页渲染。

    值来自「环境变量 + .env」的合并结果（环境变量优先），所以只设环境变量、
    不建 .env 的机器也能看到"已设置"。
    """
    env, _source = env_values(path)
    rows: List[Tuple[str, str, str, bool]] = []
    for key, label in ENV_FIELDS:
        raw = env.get(key, "")
        present = bool(raw)
        value = mask_secret(raw) if key in SECRET_FIELDS else (raw or "(未设置)")
        if not present:
            value = "(未设置)"
        rows.append((key, label, value, present))
    return rows


# --------------------------------------------------------------------------- #
# API 配置（设置页填写 → %APPDATA%\Taofu\config.json）
# --------------------------------------------------------------------------- #

#: 设置页三行输入框：(Settings 字段名, 中文标签)，顺序即展示顺序
API_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("api_base_url", "API 地址（Base URL）"),
    ("api_key", "API 密钥（API Key）"),
    ("api_model", "模型名称（Model）"),
)

#: Settings 字段 ←→ 老版 .env 变量名（只读兼容，新用户不需要碰 .env）
API_ENV_ALIAS: Dict[str, str] = {
    "api_base_url": "OPENAI_BASE_URL",
    "api_key": "OPENAI_API_KEY",
    "api_model": "OPENAI_MODEL",
}


def api_config_values(path: Optional[Path] = None) -> Dict[str, str]:
    """只读 ``config.json`` 里的三项 API 配置（设置页保存的那份）。

    ``path`` 显式给定时只读那个文件（单测/迁移用）。缺失的字段返回空串，
    不抛异常——配置文件损坏也不该拦住启动。
    """
    data = _read_json_dict(Path(path) if path is not None else active_config_path())
    values: Dict[str, str] = {}
    for key, _label in API_FIELDS:
        raw = data.get(key)
        values[key] = _clean_env_value(str(raw)) if raw is not None else ""
    return values


def api_configured(values: Optional[Dict[str, str]] = None) -> bool:
    """三项是否都已填（不校验连通性）。"""
    data = api_config_values() if values is None else values
    return all(str(data.get(key) or "").strip() for key, _label in API_FIELDS)


def api_field_rows(path: Optional[Path] = None) -> List[Tuple[str, str, str, bool]]:
    """设置页输入框的初始值，返回 ``[(字段名, 中文标签, 值, 是否已有值)]``。

    取值顺序：**config.json**（设置页保存的）→ 老版 ``.env`` / 环境变量。
    老用户只配过 ``.env`` 时也能被带进输入框，点一次「保存配置」就迁移过来。
    返回值是**原值**（是否遮蔽密钥由界面决定）。
    """
    saved = api_config_values(path)
    legacy, _source = env_values()
    rows: List[Tuple[str, str, str, bool]] = []
    for key, label in API_FIELDS:
        value = _clean_env_value(saved.get(key) or legacy.get(API_ENV_ALIAS[key], ""))
        rows.append((key, label, value, bool(value)))
    return rows


def api_source_label(path: Optional[Path] = None) -> str:
    """本次 API 配置实际来自哪儿——一句人话，供设置页/关于页显示。"""
    saved = api_config_values(path)
    legacy, source = env_values()
    if all(saved.get(key) for key, _label in API_FIELDS):
        return "设置页保存的配置"
    if all(legacy.get(API_ENV_ALIAS[key]) for key, _label in API_FIELDS):
        name = ".env 文件" if source is not None else "环境变量"
        return f"{name}（老版本配置，建议点「保存配置」迁移到设置页）"
    if any(saved.get(key) or legacy.get(API_ENV_ALIAS[key]) for key, _label in API_FIELDS):
        return "只填了一部分，尚未可用"
    return "尚未配置"


# --------------------------------------------------------------------------- #
# Token 用量统计（%APPDATA%\Taofu\usage.json）
# --------------------------------------------------------------------------- #


def usage_path() -> Path:
    """usage.json 路径；APPDATA 缺失时降级到 ~/.taofu/。"""
    return user_data_dir() / "usage.json"


def empty_usage() -> Dict[str, Any]:
    """usage.json 的初始结构。"""
    return {
        "total_calls": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_tokens": 0,
        "last_call_at": None,
        "by_model": {},
    }


def load_usage(path: Optional[Path] = None) -> Dict[str, Any]:
    """读 usage.json；缺失/损坏时返回全 0 结构，绝不抛异常。"""
    target = Path(path) if path else usage_path()
    data = empty_usage()
    try:
        if target.is_file():
            raw = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in ("total_calls", "total_prompt_tokens",
                            "total_completion_tokens", "total_tokens"):
                    try:
                        data[key] = int(raw.get(key) or 0)
                    except (TypeError, ValueError):
                        data[key] = 0
                data["last_call_at"] = raw.get("last_call_at")
                by_model = raw.get("by_model")
                data["by_model"] = by_model if isinstance(by_model, dict) else {}
    except (OSError, ValueError):
        return empty_usage()
    return data


def record_usage(prompt_tokens: int = 0, completion_tokens: int = 0,
                 total_tokens: Optional[int] = None, model: str = "",
                 kind: str = "", path: Optional[Path] = None,
                 when: Optional[str] = None) -> Dict[str, Any]:
    """累加一次 LLM 调用的用量并落盘，返回累加后的结构。

    写盘失败（目录不可写等）只影响统计，不影响调用方，返回的还是内存里的新值。
    """
    target = Path(path) if path else usage_path()
    data = load_usage(target)
    prompt = max(int(prompt_tokens or 0), 0)
    completion = max(int(completion_tokens or 0), 0)
    total = int(total_tokens) if total_tokens is not None else prompt + completion

    stamp = when or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["total_calls"] = int(data.get("total_calls") or 0) + 1
    data["total_prompt_tokens"] = int(data.get("total_prompt_tokens") or 0) + prompt
    data["total_completion_tokens"] = int(data.get("total_completion_tokens") or 0) + completion
    data["total_tokens"] = int(data.get("total_tokens") or 0) + max(total, 0)
    data["last_call_at"] = stamp

    key = (model or "未知模型").strip() or "未知模型"
    by_model = data.setdefault("by_model", {})
    bucket = by_model.get(key)
    if not isinstance(bucket, dict):
        bucket = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        by_model[key] = bucket
    bucket["calls"] = int(bucket.get("calls") or 0) + 1
    bucket["prompt_tokens"] = int(bucket.get("prompt_tokens") or 0) + prompt
    bucket["completion_tokens"] = int(bucket.get("completion_tokens") or 0) + completion
    bucket["total_tokens"] = int(bucket.get("total_tokens") or 0) + max(total, 0)
    if kind:
        bucket["last_kind"] = kind
    bucket["last_at"] = stamp

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        pass
    return data


def reset_usage(path: Optional[Path] = None) -> Dict[str, Any]:
    """清零统计（设置页「清零」按钮用）。"""
    target = Path(path) if path else usage_path()
    data = empty_usage()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        pass
    return data


# --------------------------------------------------------------------------- #
# 其它小工具
# --------------------------------------------------------------------------- #


def venv_python() -> Optional[Path]:
    """插件 CLI 用的解释器：优先 .venv\\Scripts\\python.exe。"""
    candidate = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    return candidate if candidate.is_file() else None


def human_size(num: int) -> str:
    """字节数转可读字符串。"""
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def fmt_mtime(path: Path) -> str:
    """本地时间 yyyy-MM-dd HH:mm。"""
    import datetime

    try:
        ts = path.stat().st_mtime
    except OSError:
        return "-"
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def ensure_dir(path: str | Path) -> bool:
    """确保目录存在（用于输出目录）。"""
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def env_flag(name: str, default: bool = False) -> bool:
    """读布尔环境变量（Phase 3 会用来探测 --wfa-cli）。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def cli_env() -> Dict[str, str]:
    """给插件 CLI 子进程用的环境：UTF-8 输出 + src 上 PYTHONPATH。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


# --------------------------------------------------------------------------- #
# 一次性迁移：旧版 _internal\ 里的 .env / config.json / output\
# --------------------------------------------------------------------------- #
# 只做"检测 + 提示 + 复制"，**不删除**旧文件（留作备份），也不引入版本框架。


def _is_file(path: Optional[Path]) -> bool:
    try:
        return path is not None and Path(path).is_file()
    except OSError:  # pragma: no cover - 极端路径
        return False


def _all_present_in(files: List[Path], source_root: Path, target: Path) -> bool:
    """``files`` 是否都已经按相对路径存在于 ``target``（避免重复提示迁移）。"""
    for src in files:
        try:
            if not (target / Path(src).relative_to(source_root)).exists():
                return False
        except (OSError, ValueError):  # pragma: no cover
            return False
    return True


def legacy_internal_dir() -> Optional[Path]:
    """旧版用户文件所在目录（frozen 下 = ``_internal\\``）；开发期为 None。"""
    return _internal_dir() if frozen() else None


def legacy_items(output_dir: str = "") -> List[Dict[str, Any]]:
    """需要一次性迁移的旧版文件清单（只读检测，不复制任何东西）。

    每项：``{"kind", "source", "target", "files"}``；``kind`` 为
    ``"env" | "config" | "output"``。目标已存在的项不返回。
    """
    internal = legacy_internal_dir()
    if internal is None:
        return []

    items: List[Dict[str, Any]] = []

    legacy_env = internal / ".env"
    if _is_file(legacy_env) and not _is_file(ENV_TARGET_PATH):
        items.append({"kind": "env", "source": legacy_env, "target": ENV_TARGET_PATH})

    legacy_config = internal / "config.json"
    if _is_file(legacy_config) and not _is_file(CONFIG_PATH):
        items.append({"kind": "config", "source": legacy_config, "target": CONFIG_PATH})

    legacy_output = internal / "output"
    try:
        if legacy_output.is_dir():
            files = [p for p in legacy_output.rglob("*") if p.is_file()]
            target = Path(output_dir).expanduser() if str(output_dir).strip() else None
            # 已经搬过一次（目标里同名文件都在）就不再打扰用户
            if files and not (target is not None and _all_present_in(files, legacy_output, target)):
                items.append({"kind": "output", "source": legacy_output,
                              "target": target, "files": files})
    except OSError:  # pragma: no cover
        pass

    return items


def apply_migration(items: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    """按 ``legacy_items()`` 的结果复制文件，返回 ``(成功文件数, 错误信息)``。

    同目录已存在的目标文件**不覆盖**；失败只记错误，不抛异常。
    """
    import shutil

    done = 0
    errors: List[str] = []
    for item in items:
        target = item.get("target")
        if target is None:
            errors.append(f"{item.get('kind')}：没有可用的目标目录，已跳过")
            continue
        if item.get("kind") == "output":
            root = Path(target)
            for src in item.get("files") or []:
                try:
                    rel = Path(src).relative_to(Path(item["source"]))
                    dst = root / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        continue
                    shutil.copy2(src, dst)
                    done += 1
                except (OSError, ValueError) as exc:
                    errors.append(f"{src} → {target}：{exc}")
            continue
        try:
            dst = Path(target)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                continue
            shutil.copy2(Path(item["source"]), dst)
            done += 1
        except OSError as exc:
            errors.append(f"{item.get('source')} → {target}：{exc}")
    return done, errors
