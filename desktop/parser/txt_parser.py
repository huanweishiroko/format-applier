"""txt_parser —— 判定一份 .txt「格式要求」到底是 DSL 还是自然语言。

DSL 判据（与 presets/ 下的预设完全一致）：某一行以「已知 DSL 键 + 冒号」开头，例如::

    标题：黑体 三号 居中 加粗
    正文：宋体 小四 1.5倍行距 首行缩进2字符 两端对齐
    清理：markdown 空白 删除空段落

判定为 DSL → 原样返回 DSL 原文（插件自带的规则解析器能直接吃它，不需要 LLM）。
判定为自然语言 → 原样返回自然语言原文（交给 llm_parser 转 DSL）。

本模块零依赖、零网络、零 LLM。

命令行::

    python txt_parser.py presets/格式要求1.txt
    python txt_parser.py presets/格式要求1.txt --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Tuple

# --------------------------------------------------------------------------- #
# DSL 键表
# --------------------------------------------------------------------------- #

#: 角色键 —— 决定「哪一类段落」用这套格式
ROLE_KEYS: Tuple[str, ...] = (
    "标题", "题目", "文章标题",
    "标题1", "标题2", "标题3", "标题4", "标题5", "标题6",
    "标题一", "标题二", "标题三", "标题四", "标题五", "标题六",
    "一级标题", "二级标题", "三级标题", "四级标题", "五级标题", "六级标题",
    "正文", "普通", "基本正文",
    "引用", "引文", "名言",
    "题注", "图注", "表注", "图题", "表题",
    "表格文字", "表格文本", "表内文字",
    "列表", "列表文字", "项目符号", "编号",
    "目录", "目录1", "目录2", "目录3",
)

#: 选项键 —— 不是排版角色，而是插件的行为开关
OPTION_KEYS: Tuple[str, ...] = (
    "清理", "保留符号", "删除符号",
    "结构预处理",
    "页面", "页边距", "纸张", "页面设置",
    "样式", "字体替换",
)

KNOWN_KEYS: Tuple[str, ...] = ROLE_KEYS + OPTION_KEYS

#: 一行里「键 + 冒号 + 至少一个非空字符」。全角「：」是预设里的标准写法，
#: 半角「:」也接受；键名允许被 markdown 标题前缀（#）污染。
TAG_LINE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?P<key>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9]{0,15})"
    r"\s*[:：]\s*(?P<value>\S.*)?$"
)


def _iter_tags(lines: Iterable[str]) -> Iterable[Tuple[str, str]]:
    """逐行吐出 (键, 原始行)，只认 KNOWN_KEYS 里的键。"""
    known = set(KNOWN_KEYS)
    for line in lines:
        m = TAG_LINE_RE.match(line)
        if m and m.group("key") in known:
            yield m.group("key"), line.rstrip("\n")


# --------------------------------------------------------------------------- #
# 结果对象
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TxtParseResult:
    """一份 .txt 的解析结论。"""

    path: str
    kind: str                       # "dsl" | "natural"
    text: str                       # 原文（解码后，一字未改）
    encoding: str = "utf-8"
    matched_tags: Tuple[str, ...] = field(default_factory=tuple)
    comment_only: bool = False      # 只在 # 注释里出现标签（弱判据）

    @property
    def is_dsl(self) -> bool:
        return self.kind == "dsl"

    @property
    def needs_llm(self) -> bool:
        return self.kind == "natural"

    def dsl_body(self) -> str:
        """去掉注释行与空行的 DSL 主体（喂给插件或做 diff 时用）。"""
        kept = []
        for line in self.text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            kept.append(stripped)
        return "\n".join(kept)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "kind": self.kind,
            "encoding": self.encoding,
            "is_dsl": self.is_dsl,
            "needs_llm": self.needs_llm,
            "comment_only": self.comment_only,
            "matched_tags": list(self.matched_tags),
            "chars": len(self.text),
            "lines": len(self.text.splitlines()),
        }


# --------------------------------------------------------------------------- #
# 核心
# --------------------------------------------------------------------------- #


def read_text(path: str | Path) -> Tuple[str, str]:
    """按 utf-8-sig → gbk → utf-8(replace) 依次尝试解码，返回 (文本, 编码名)。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def detect_dsl(text: str) -> Tuple[bool, Tuple[str, ...], bool]:
    """返回 (是否 DSL, 命中的标签, 是否只在注释里命中)。"""
    lines = text.splitlines()

    # 1) 强判据：非注释行上的标签
    body_lines = [ln for ln in lines if not ln.lstrip().startswith("#")]
    body_tags = tuple(dict.fromkeys(k for k, _ in _iter_tags(body_lines)))
    if body_tags:
        return True, body_tags, False

    # 2) 弱判据：整个文件没有可解析行，但注释里写了标签体系
    all_tags = tuple(dict.fromkeys(k for k, _ in _iter_tags(lines)))
    if all_tags:
        return True, all_tags, True

    return False, (), False


def parse_text(text: str, path: str = "<text>", encoding: str = "utf-8") -> TxtParseResult:
    """对一段文本做判定，不做 IO。"""
    is_dsl, tags, comment_only = detect_dsl(text)
    return TxtParseResult(
        path=path,
        kind="dsl" if is_dsl else "natural",
        text=text,
        encoding=encoding,
        matched_tags=tags,
        comment_only=comment_only,
    )


def parse_txt(path: str | Path) -> TxtParseResult:
    """读一个 .txt 文件并判定。"""
    text, enc = read_text(path)
    return parse_text(text, path=str(path), encoding=enc)


def looks_like_dsl(text: str) -> bool:
    """便捷函数：这段文本是否已经是 DSL。"""
    return detect_dsl(text)[0]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="判定 .txt 是 DSL 还是自然语言")
    ap.add_argument("path", help=".txt 文件路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON 摘要")
    ap.add_argument("--show", action="store_true", help="附带打印全文")
    args = ap.parse_args(argv)

    res = parse_txt(args.path)
    if args.json:
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"文件    : {res.path}")
        print(f"编码    : {res.encoding}")
        print(f"判定    : {'DSL（跳过 AI）' if res.is_dsl else '自然语言（需要 AI 转 DSL）'}")
        print(f"命中标签: {', '.join(res.matched_tags) if res.matched_tags else '（无）'}")
        if res.is_dsl:
            print("--- DSL 原文 ---")
            print(res.text if args.show else res.dsl_body())
    return 0


if __name__ == "__main__":
    sys.exit(_main())
