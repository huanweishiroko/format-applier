# -*- coding: utf-8 -*-
"""user_presets —— 用户预设的存放、命名与增删查（与内置 presets/ 完全分离）。

存放位置::

    %APPDATA%\\Taofu\\presets\\user_<YYYYMMDD_HHMMSS>_<名字>.txt

根目录由 ``core/config.py`` 统一解析（APPDATA 缺失时降级到
``~/.taofu/presets/``），与 config.json、usage.json 同根。

命名规则把"时间戳"写进文件名，好处是：
  * 同一秒之外的任何两次保存都不会互相覆盖；
  * 用户预设目录永远是扁平的一层，交给插件 ``--presets-dir`` 直接扫；
  * 展示名从文件名里反解（``user_20250101_120000_我的格式`` → ``我的格式``）。

本模块只碰上面那个目录，**绝不写**项目里的 presets/。
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 文件名模板里的用户名字段允许的最大长度
MAX_NAME_LEN = 60

#: Windows 文件名非法字符
_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

#: 用户预设文件名：user_<YYYYMMDD>_<HHMMSS>_<名字>.txt
_NAME_RE = re.compile(r"^user_(?P<date>\d{8})_(?P<time>\d{6})_(?P<label>.+)$")

#: 允许作为预设的扩展名（与插件 presets 一致）
ALLOWED_SUFFIXES = (".txt", ".md", ".docx")


def _config_module():
    """延迟拿到 ``core.config``（两种导入形态都能用，且避开导入顺序问题）。"""
    try:
        from core import config as cfg  # 绝对优先，见 preview.py 顶部注释
    except ImportError:  # pragma: no cover - 包内运行时
        from ..core import config as cfg  # type: ignore
    return cfg


def _fallback_dir() -> Path:
    return Path.home() / ".taofu" / "presets"


def user_data_dir(create: bool = True) -> Path:
    """``%APPDATA%\\Taofu``（config.json / usage.json 也在这里）。

    真正的解析在 ``core/config.py::user_data_dir()``，这里只是它的界面版
    （默认 ``create=True``，失败不抛）。
    """
    base = _config_module().user_data_dir(create=create)
    if not create:
        return base
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return base


def get_user_preset_dir(create: bool = True) -> Path:
    """用户预设目录；``create=True`` 时确保它存在（失败也不抛，交给调用方判断）。"""
    base = user_data_dir(create=False) / "presets"
    if create:
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return base


# --------------------------------------------------------------------------- #
# 命名
# --------------------------------------------------------------------------- #


def sanitize_name(name: str) -> str:
    """清洗用户输入的名字：去非法字符、压空白、限长。空则回落到「我的格式」。"""
    cleaned = _ILLEGAL_RE.sub("_", (name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if len(cleaned) > MAX_NAME_LEN:
        cleaned = cleaned[:MAX_NAME_LEN].rstrip(" .")
    return cleaned or "我的格式"


def build_filename(name: str, when: Optional[_dt.datetime] = None) -> str:
    """按 ``user_<YYYYMMDD_HHMMSS>_<名字>.txt`` 生成文件名。"""
    stamp = (when or _dt.datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"user_{stamp}_{sanitize_name(name)}.txt"


def parse_filename(filename: str) -> Dict[str, Any]:
    """从文件名反解展示信息；非本模块命名规则的文件也能给出合理回落。"""
    stem = Path(filename).stem
    m = _NAME_RE.match(stem)
    label = sanitize_name(m.group("label")) if m else stem
    created = ""
    if m:
        try:
            created = _dt.datetime.strptime(
                m.group("date") + m.group("time"), "%Y%m%d%H%M%S"
            ).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            created = ""
    return {"name": label, "raw": stem, "created": created}


# --------------------------------------------------------------------------- #
# 列表项
# --------------------------------------------------------------------------- #


@dataclass
class UserPreset:
    """用户预设目录里的一条记录。"""

    name: str                 # 展示名（用户输入的名字）
    file: str                 # 实际文件名
    path: Path
    size: int = 0
    mtime: float = 0.0
    created: str = ""         # 从文件名时间戳反解

    @property
    def ext(self) -> str:
        return self.path.suffix.lower()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "file": self.file,
            "path": str(self.path),
            "ext": self.ext,
            "size": self.size,
            "mtime": self.mtime,
            "created": self.created,
            "source": "user",
        }


def list_user_presets(directory: Optional[Path] = None) -> List[UserPreset]:
    """扫用户预设目录（找不到目录返回空列表，不抛异常）。"""
    base = Path(directory) if directory else get_user_preset_dir()
    items: List[UserPreset] = []
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name)
    except OSError:
        return items
    for entry in entries:
        try:
            if not entry.is_file() or entry.name.startswith("."):
                continue
            if entry.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            stat = entry.stat()
        except OSError:
            continue
        meta = parse_filename(entry.name)
        items.append(UserPreset(
            name=meta["name"], file=entry.name, path=entry,
            size=int(stat.st_size), mtime=stat.st_mtime, created=meta["created"],
        ))
    return items


def find_user_preset(name: str, directory: Optional[Path] = None) -> Optional[UserPreset]:
    for item in list_user_presets(directory):
        if item.name == name:
            return item
    return None


# --------------------------------------------------------------------------- #
# 写入 / 删除
# --------------------------------------------------------------------------- #


def save_user_preset(name: str, dsl_text: str,
                     directory: Optional[Path] = None) -> Path:
    """保存一份 DSL 为用户预设，返回落盘路径。

    同名文件已存在时自动加 ``-2``、``-3`` 后缀，绝不静默覆盖。
    写入失败（权限/路径）抛 ``OSError``，由界面转成可读提示。
    """
    base = Path(directory) if directory else get_user_preset_dir()
    base.mkdir(parents=True, exist_ok=True)
    text = (dsl_text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ValueError("DSL 内容为空，未保存")
    if not text.endswith("\n"):
        text += "\n"

    target = base / build_filename(name)
    if target.exists():
        stem = target.stem
        for i in range(2, 1000):
            candidate = base / f"{stem}-{i}{target.suffix}"
            if not candidate.exists():
                target = candidate
                break
        else:  # pragma: no cover - 极端情况
            raise OSError(f"同名预设过多，无法在 {base} 下新建")
    target.write_text(text, encoding="utf-8")
    return target


def delete_user_preset(name: str, directory: Optional[Path] = None) -> None:
    """按展示名删除用户预设；不存在则抛 ``FileNotFoundError``。"""
    item = find_user_preset(name, directory)
    if item is None:
        raise FileNotFoundError(f"找不到用户预设「{name}」")
    item.path.unlink()


def rename_note(path: Path) -> str:
    """把落盘文件名翻译成一句人话（日志用）。"""
    meta = parse_filename(path.name)
    when = f"（保存于 {meta['created']}）" if meta["created"] else ""
    return f"{path.name}{when}"
