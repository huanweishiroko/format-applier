"""llm_parser —— 用 OpenAI 兼容接口把「自然语言要求 / docx 样式指纹」转成插件 DSL。

依赖：
    openai          调用 OpenAI 兼容的 /chat/completions
    python-dotenv   读老用户的 .env（OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL）

配置来源（优先级从高到低，见 load_config）：
    1. %APPDATA%\\Taofu\\config.json —— 软件「设置 → API 配置」保存的三项
    2. exe 同级 .env / 环境变量 —— 老用户兼容
    3. 都没有 → LlmConfigError，提示去设置页填写

行为：
    * system prompt 内置 DSL 语法说明（对齐 presets/格式要求1.txt 的标签体系）。
    * 输出清洗：剥掉 ``` 代码块、前后解释文字，只留 DSL 主体。
    * 校验：结果必须含「标题：」或「正文：」之一，否则视为失败。
    * 失败重试 1 次（共 2 次尝试），仍失败抛 LlmParseError，**不吞错**。

命令行::

    python llm_parser.py --text "标题黑体二号居中；正文宋体小四 1.5倍行距"
    python llm_parser.py --txt-file presets/格式要求1.txt
    python llm_parser.py --docx samples/target.docx --out out.dsl.txt
    python llm_parser.py --text "..." --print-prompt      # 不联网，只看 prompt
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

#: .env 默认位置由 core/config.py 统一解析：打包后 = exe 同级 .env，
#: 开发期 = desktop/.env（旧版 _internal\.env 仍兼容）。这里保留旧名字不破外部引用。
DESKTOP_DIR = Path(__file__).resolve().parent.parent


def _default_env_path() -> Path:
    """本次实际该读的 .env：core/config.py 探测结果，找不到就给"建议路径"。"""
    try:
        try:
            from core import config as cfg  # 绝对优先（frozen 下 core 是顶层包）
        except ImportError:  # pragma: no cover - 包内运行时
            from ..core import config as cfg  # type: ignore
        found = cfg.ENV_PATH
        return Path(found) if found is not None else Path(cfg.ENV_TARGET_PATH)
    except Exception:  # noqa: BLE001 - 解析失败也不该拦住 AI 解析
        return DESKTOP_DIR / ".env"

#: 首次 + 重试 1 次
DEFAULT_MAX_ATTEMPTS = 2

#: 校验用：DSL 主体必须至少出现下列角色之一
REQUIRED_ROLE_RE = re.compile(r"^\s*(?:\*\*)?\s*(标题|正文)\s*[:：]", re.M)

#: 清洗用：一行「中文键 + 冒号 + 取值」，允许被 markdown 前缀污染
_CN_TAG_LINE_RE = re.compile(
    r"^\s*(?:[-*+>]\s*)?(?:#{1,6}\s*)?(?:\*\*)?[\u4e00-\u9fff]{2,8}\s*[:：]\s*\S"
)

_INVISIBLE_RE = re.compile("[\u200b\u200c\u200d\ufeff\u2060]")

SYSTEM_PROMPT = """\
你是「Word 排版要求 → DSL」转换器。把输入的自然语言要求或文档样式指纹，转成排版插件可直接解析的 DSL。

# DSL 语法
1. 一行一个标签，标签与取值之间用**全角冒号「：」**分隔。
2. 以 `#` 开头的行是注释，插件会忽略。
3. 角色行（决定哪一类段落用这套格式）：
   标题 / 正文 / 标题1 / 标题2 / 标题3（也接受 一级标题、二级标题）/ 引用 / 题注 /
   图题 / 表题 / 表格文字 / 列表 / 目录1
4. 取值词表（空格分隔，顺序不限）：
   - 字体：中文字体 宋体|黑体|楷体|仿宋|微软雅黑｜西文字体 Times New Roman|Arial
     也可简写为「宋体」「黑体」；中英文都要给时写「中文字体 宋体 西文字体 Times New Roman」
   - 字号：初号 小初 一号 小一 二号 小二 三号 小三 四号 小四 五号 小五 六号 小六（或 12pt / 12磅）
   - 字形：加粗 / 斜体 / 下划线 / 删除线
   - 对齐：居中 / 左对齐 / 右对齐 / 两端对齐 / 分散对齐
   - 缩进：首行缩进2字符 / 悬挂缩进2字符 / 左缩进2字符 / 右缩进2字符
   - 行距：1.5倍行距 / 单倍行距 / 固定值20磅 / 最小值12磅
   - 段距：段前0.5行 / 段后6磅
5. 文本清理（可选，只删标记符号、不改文字内容）：
   清理：markdown 不可见字符 重复标点 空白 装饰符号 空段落 删除空段落
   也可以写「清理：全部」或「清理：无」；两行可选：
   保留符号：% ‰ ° ± ℃ ℉ ※
   删除符号：~^
6. 结构预处理（可选，把整段加粗/带编号的段落识别成 Word 内置标题样式）：
   结构预处理：整段加粗 编号正则 首段标题 居中短行
7. 角色行至少要有「标题：」或「正文：」其中之一，否则结果无效。

# 输出要求
- 只输出 DSL 正文本身。
- 不要解释、不要前言后语、不要 markdown 代码块、不要英文说明。
- 用户没提到的属性不要编造；用户明确提到的属性必须落到对应行。

# 示例
输入：标题黑体二号居中加粗；一级标题黑体四号左对齐；正文宋体小四，1.5倍行距，首行缩进2字符，两端对齐；要做文本清理，删 markdown 和空段落
输出：
标题：黑体 二号 居中 加粗
标题1：黑体 四号 左对齐
正文：宋体 小四 1.5倍行距 首行缩进2字符 两端对齐
清理：markdown 删除空段落
"""

# --------------------------------------------------------------------------- #
# 异常与结果
# --------------------------------------------------------------------------- #


class LlmParseError(RuntimeError):
    """.env 配置或 LLM 输出最终无法得到合法 DSL。"""


class LlmConfigError(LlmParseError):
    """缺少必需的 .env 配置。"""


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.0
    timeout: float = 120.0
    env_path: str = ""
    #: 本次配置的来源："config.json"（设置页保存）/ ".env"（老用户）/ "环境变量"
    source: str = ""
    missing: tuple = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "env_path": self.env_path,
            "source": self.source,
            "api_key": f"***{self.api_key[-4:]}" if self.api_key else "",
        }


@dataclass(frozen=True)
class DslResult:
    dsl: str
    source_kind: str          # "natural" | "fingerprint"
    attempts: int
    model: str
    raw_outputs: tuple = field(default_factory=tuple)
    #: 本次转换累计的 token 用量 {prompt_tokens, completion_tokens, total_tokens}
    usage: Dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.dsl)

    @property
    def total_tokens(self) -> int:
        return int((self.usage or {}).get("total_tokens") or 0)


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #


def _app_config():
    """``core/config.py`` 模块（拿 %APPDATA%\\Taofu\\config.json 的读取器）。

    导入失败返回 ``None``：AI 解析不能因为配置模块缺失就崩掉。
    """
    try:
        try:
            from core import config as appcfg  # 绝对优先（frozen 下 core 是顶层包）
        except ImportError:  # pragma: no cover - 包内运行时
            from ..core import config as appcfg  # type: ignore
        return appcfg
    except Exception:  # noqa: BLE001
        return None


def load_config(env_path: str | Path | None = None, *, required: bool = True) -> LlmConfig:
    """读 AI 配置，三级优先级：

    1. **config.json** —— ``%APPDATA%\\Taofu\\config.json``，设置页「保存配置」写入。
       这是新用户唯一需要碰的地方；
    2. **exe 同级 .env**（开发期 = ``desktop\\.env``）—— 兼容老用户；进程环境变量
       ``OPENAI_*`` 也算这一级（设了就不用建文件）；
    3. 都没有 → 抛 ``LlmConfigError``，提示去「设置 → API 配置」填密钥。

    ``env_path`` 显式给定时只读那个 .env（命令行 ``--env``），跳过第 1 级。
    """
    appcfg = _app_config()
    saved: Dict[str, str] = {}
    if env_path is None and appcfg is not None:
        try:
            saved = appcfg.api_config_values()
        except Exception:  # noqa: BLE001 - 配置文件损坏也不能拦住流程
            saved = {}

    base_url = (saved.get("api_base_url") or "").strip()
    api_key = (saved.get("api_key") or "").strip()
    model = (saved.get("api_model") or "").strip()
    source = "config.json" if (base_url and api_key and model) else ""

    path = Path(env_path) if env_path else _default_env_path()
    if not source:
        # 第 2 级：.env（老用户）+ 环境变量。文件不存在时**不再**从 cwd 往上瞎找：
        # 打包后 cwd 可能是任意目录，从那儿捡到别人的 .env 会让人查半天。
        # 用 dotenv_values 而不是 load_dotenv：只读文件、不污染 os.environ，
        # 这样每次调用都严格按优先级取值。
        from dotenv import dotenv_values

        file_values: Dict[str, str] = {}
        if path.is_file():
            try:
                file_values = {
                    key: (value or "").strip()
                    for key, value in dotenv_values(path).items()
                }
            except Exception:  # noqa: BLE001 - 坏 .env 当没有
                file_values = {}

        def _env(name: str) -> str:
            return (os.getenv(name) or "").strip() or file_values.get(name, "")

        if not base_url:
            base_url = _env("OPENAI_BASE_URL")
        if not api_key:
            api_key = _env("OPENAI_API_KEY")
        if not model:
            model = _env("OPENAI_MODEL")
        if base_url and api_key and model:
            source = ".env" if path.is_file() else "环境变量"

    missing = tuple(
        name for name, value in
        (("API 地址", base_url), ("API 密钥", api_key), ("模型名称", model))
        if not value
    )
    if missing and required:
        raise LlmConfigError(
            "缺少 LLM 配置：" + "、".join(missing) +
            "。请前往「设置 → API 配置」填入 API 地址、API 密钥和模型名称，"
            "点「保存配置」后重试。"
        )

    def _num(name: str, default: float) -> float:
        raw = (os.getenv(name) or "").strip()
        try:
            return float(raw) if raw else default
        except ValueError:
            return default

    return LlmConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=_num("OPENAI_TEMPERATURE", 0.0),
        timeout=_num("OPENAI_TIMEOUT", 120.0),
        env_path=str(path),
        source=source,
        missing=missing,
    )


def get_client(cfg: LlmConfig):
    """按配置建 OpenAI 客户端（OpenAI 兼容接口）。"""
    from openai import OpenAI

    return OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=cfg.timeout)


# --------------------------------------------------------------------------- #
# 输出清洗与校验
# --------------------------------------------------------------------------- #


def _strip_fences(text: str) -> str:
    """剥掉 ``` / ```text 代码围栏，只留围栏内的内容。"""
    lines = text.split("\n")
    fence_idx = [i for i, ln in enumerate(lines) if ln.strip().startswith("```")]
    if not fence_idx:
        return text
    if len(fence_idx) >= 2:
        start, end = fence_idx[0], fence_idx[-1]
        return "\n".join(lines[start + 1:end])
    return "\n".join(ln for i, ln in enumerate(lines) if i != fence_idx[0])


def _strip_line_prefix(line: str) -> str:
    """去掉每行的 markdown 前缀：>、-、*、+、#，以及键名上的 ** 强调。"""
    out = re.sub(r"^\s*(?:[-*+>]\s+|#{1,6}\s+)+", "", line)
    if _CN_TAG_LINE_RE.match(out) or _CN_TAG_LINE_RE.match(out.replace("**", "")):
        out = out.replace("**", "")
    return out


def clean_dsl(raw: str) -> str:
    """把 LLM 原始输出洗成纯 DSL 主体。

    步骤：去不可见字符 → 剥代码围栏 → 去行首 markdown 前缀 →
    截取「第一个标签行 ~ 最后一个标签行」之间的内容。
    """
    if not raw:
        return ""
    text = _INVISIBLE_RE.sub("", raw.replace("\r\n", "\n").replace("\r", "\n"))
    text = _strip_fences(text)

    lines = [_strip_line_prefix(ln).rstrip() for ln in text.split("\n")]
    tag_idx = [i for i, ln in enumerate(lines) if _CN_TAG_LINE_RE.match(ln)]
    if not tag_idx:
        return "\n".join(lines).strip()

    body = lines[tag_idx[0]:tag_idx[-1] + 1]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body).strip()


def validate_dsl(dsl: str) -> bool:
    """DSL 必须含「标题：」或「正文：」。"""
    return bool(dsl) and bool(REQUIRED_ROLE_RE.search(dsl))


# --------------------------------------------------------------------------- #
# prompt 组装
# --------------------------------------------------------------------------- #


def build_messages(source: str, kind: str = "natural",
                   previous_error: Optional[str] = None) -> List[Dict[str, str]]:
    """组装 messages。kind: natural | fingerprint。"""
    if kind == "fingerprint":
        user = (
            "下面是一份 Word 文档每段的样式指纹（含字体/字号/加粗/对齐/缩进/行距/样式名）。"
            "请归纳出这份文档的排版规则，并转成 DSL。\n"
            "要求：用样式名和属性的分布判断角色——样式名为「标题」「Heading 1」「标题 1」的段落"
            "分别对应 DSL 的「标题」「标题1」；多数段落（Normal/正文）对应「正文」。"
            "整篇一致的属性写进对应角色行；明显是残留标记的（如文本里还有 # ** 等）可在「清理：」行加上 markdown。\n\n"
            "=== 样式指纹 ===\n" + source.strip() + "\n=== 指纹结束 ==="
        )
    else:
        user = "把下面的自然语言排版要求转成 DSL：\n\n" + source.strip()

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    if previous_error:
        messages.append({
            "role": "user",
            "content": (
                "上一次的输出不合法：" + previous_error +
                "。请只输出 DSL 正文，必须至少包含「标题：」或「正文：」两行之一，"
                "不要任何解释文字和代码块。"
            ),
        })
    return messages


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def _extract_content(response: Any) -> str:
    """从 chat.completions 返回里取正文字符串。"""
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise LlmParseError(f"无法从接口返回里取到正文：{response!r}") from exc
    if content is None:
        raise LlmParseError("接口返回的正文为空（content=None）")
    return content


def extract_usage(response: Any) -> Dict[str, int]:
    """从响应里取 token 用量；取不到就返回全 0（不抛异常）。"""
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    def _int(name: str) -> int:
        try:
            return int(getattr(usage, name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    prompt = _int("prompt_tokens")
    completion = _int("completion_tokens")
    total = _int("total_tokens") or (prompt + completion)
    if not (prompt or completion or total):
        return {}
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def record_usage_to_config(model: str, usage: Dict[str, int], kind: str = "") -> None:
    """把一次调用的用量累加进 ``%APPDATA%\\Taofu\\usage.json``。

    统计失败绝不影响转换结果（静默忽略）。本函数由桌面层使用；
    插件 CLI 自带 LLM 回退时不走这里。
    """
    if not usage:
        return
    try:
        sys.path.insert(0, str(DESKTOP_DIR))
        from core import config as _cfg  # type: ignore
    except Exception:  # noqa: BLE001 - 桌面层不可用时只管跳过
        return
    try:
        _cfg.record_usage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens"),
            model=model,
            kind=kind,
        )
    except Exception:  # noqa: BLE001
        pass


def to_dsl(source: str, kind: str = "natural", *,
           cfg: Optional[LlmConfig] = None,
           client: Any = None,
           max_attempts: int = DEFAULT_MAX_ATTEMPTS,
           verbose: bool = False) -> DslResult:
    """把 source 转成 DSL。失败重试 max_attempts-1 次，仍失败抛 LlmParseError。"""
    if not source or not source.strip():
        raise LlmParseError("输入为空，无法转换")
    if max_attempts < 1:
        raise ValueError("max_attempts 必须 >= 1")

    cfg = cfg or load_config()
    own_client = client is None
    client = client or get_client(cfg)
    try:
        return _attempt_loop(client, cfg, source, kind, max_attempts, verbose)
    finally:
        if own_client:                     # 自己建的 client 自己关，避免连接泄漏
            try:
                client.close()
            except Exception:              # noqa: BLE001 - 关闭失败不影响结果
                pass


def _attempt_loop(client, cfg: LlmConfig, source: str, kind: str,
                  max_attempts: int, verbose: bool) -> DslResult:
    """真正发请求的循环：失败带上一次的错误重试，最终仍失败则抛 LlmParseError。"""
    raw_outputs: List[str] = []
    usage_total: Dict[str, int] = {}
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        messages = build_messages(source, kind, previous_error=last_error or None)
        try:
            response = client.chat.completions.create(
                model=cfg.model,
                messages=messages,
                temperature=cfg.temperature,
            )
            raw = _extract_content(response)
            for key, value in extract_usage(response).items():
                usage_total[key] = usage_total.get(key, 0) + int(value)
        except LlmParseError:
            record_usage_to_config(cfg.model, usage_total, kind)
            raise
        except Exception as exc:                       # 网络/鉴权/限流等
            last_error = f"{type(exc).__name__}: {exc}"
            if verbose:
                print(f"[llm_parser] 第 {attempt} 次调用失败：{last_error}", file=sys.stderr)
            if attempt >= max_attempts:
                record_usage_to_config(cfg.model, usage_total, kind)
                raise LlmParseError(
                    f"调用 LLM 连续 {max_attempts} 次失败：{last_error}"
                ) from exc
            continue

        raw_outputs.append(raw)
        dsl = clean_dsl(raw)
        if validate_dsl(dsl):
            record_usage_to_config(cfg.model, usage_total, kind)
            return DslResult(
                dsl=dsl,
                source_kind=kind,
                attempts=attempt,
                model=cfg.model,
                raw_outputs=tuple(raw_outputs),
                usage=dict(usage_total),
            )

        last_error = f"结果里没有「标题：」或「正文：」（原始输出前 200 字：{raw.strip()[:200]!r}）"
        if verbose:
            print(f"[llm_parser] 第 {attempt} 次输出不合法：{last_error}", file=sys.stderr)

    record_usage_to_config(cfg.model, usage_total, kind)
    raise LlmParseError(
        f"LLM 连续 {max_attempts} 次都没给出合法 DSL；最后一次：{last_error}"
    )


def natural_language_to_dsl(text: str, **kwargs) -> DslResult:
    """自然语言要求 → DSL。"""
    return to_dsl(text, kind="natural", **kwargs)


def fingerprint_to_dsl(fingerprint_text: str, **kwargs) -> DslResult:
    """docx 样式指纹 → DSL。"""
    return to_dsl(fingerprint_text, kind="fingerprint", **kwargs)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _read_source(args) -> tuple[str, str, bool]:
    """返回 (source, kind, already_dsl)。"""
    if args.docx:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from docx_extractor import extract_fingerprint

        fp = extract_fingerprint(args.docx, limit=args.limit)
        return fp.to_text(), "fingerprint", False
    if args.txt_file:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from txt_parser import parse_txt

        res = parse_txt(args.txt_file)
        return res.text, "natural", res.is_dsl
    if args.text:
        return args.text, "natural", False
    raise SystemExit("必须提供 --text / --txt-file / --docx 之一")


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="自然语言 / docx 指纹 → DSL")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="自然语言要求原文")
    src.add_argument("--txt-file", help="自然语言 .txt 文件")
    src.add_argument("--docx", help=".docx 文件（先取样式指纹）")
    ap.add_argument("--limit", type=int, default=200, help="docx 指纹段数上限")
    ap.add_argument("--env", help=".env 路径（默认 exe 同级 .env；开发期 desktop/.env）")
    ap.add_argument("--out", help="把 DSL 写入该文件")
    ap.add_argument("--print-prompt", action="store_true", help="只打印 prompt，不调用 LLM")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    source, kind, already_dsl = _read_source(args)

    if already_dsl:
        print("[llm_parser] 输入已是 DSL，跳过 AI 调用", file=sys.stderr)
        print(source)
        if args.out:
            Path(args.out).write_text(source + "\n", encoding="utf-8")
        return 0

    if args.print_prompt:
        print(json.dumps(build_messages(source, kind), ensure_ascii=False, indent=2))
        return 0

    cfg = load_config(args.env)
    print(f"[llm_parser] base_url={cfg.base_url} model={cfg.model}", file=sys.stderr)
    result = to_dsl(source, kind, cfg=cfg, verbose=args.verbose)
    print(result.dsl)
    if args.out:
        Path(args.out).write_text(result.dsl + "\n", encoding="utf-8")
        print(f"[llm_parser] 已写入 {args.out}（尝试 {result.attempts} 次）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
