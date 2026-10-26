# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配方 · 桃符（v2.0.0）。

用法（开发者在本机终端手动执行）::

    cd <仓库>/desktop
    .\\build.bat

关键设计与理由
--------------
* **onedir**（不是 onefile）：启动快，customtkinter 的 theme/font 资产不用每次
  解压；代价是 dist 里是一整个文件夹——这符合验收清单第 6 条（整目录可移动）。
* **console=False**：双击不弹黑窗。
* **入口用 `desktop/app.py`**：它开头就是 `--wfa-cli` 分支（Phase 4 新增），
  bridge.py 正是靠 `sys.executable --wfa-cli` 让 exe 自调插件 CLI 的。
  所以 exe 必须能 import 到 `word_format_applier` 这个包：
  `datas` 里把 `../src/word_format_applier` 原样铺进包根，再配
  `hidden-import word_format_applier` 双保险。
* **datas 的落点**：onedir 下 `sys._MEIPASS` 指向 `dist/桃符/_internal`。
  `core/config.py` 里凡"用户可见/可改"的路径都以 `sys.executable`（= exe 同级）
  为基准，只有**只读资源**才走 `_MEIPASS`：`presets/` 落在这里
  （`_MEIPASS/presets`），插件 `presets.py` 的 `PLUGIN_ROOT` 同样推算成 `_MEIPASS`。
* **`.env` 的落点**：`config.ENV_PATH` = **exe 同级 `.env`**（老用户兼容用）。
  新用户直接在软件「设置 → API 配置」里填，写 `%APPDATA%\\Taofu\\config.json`。
  `.env.example` 的主副本由 build_finish.py 放到 **exe 同级**；spec 这里再往
  `_MEIPASS/.env.example` 铺一份，只是为了旧版路径下也能看到模板（向后兼容）。
  **绝不打包 desktop/.env 本体**——那会把开发机的真实 API key 一起发出去；
  build_finish.py 还会删掉误入 dist 的 `.env`。
* **不要加入 `samples/`、`tests/`、`tools/`、`NOTES.md`、`_acl-recovery/`、
  `docs/`、`__pycache__`**：dist 体积和杀毒误报都靠它。datas 只列白名单，
  build_finish.py 再兜底删一遍开发残留。
"""

import os
from PyInstaller.utils.hooks import collect_all

#: 本 spec 所在目录（desktop/），build.bat 会先 cd 到这里；不依赖 cwd。
_SPEC_DIR = os.path.abspath(os.path.dirname(SPEC))  # noqa: F821 - SPEC 由 PyInstaller 注入
_ROOT = os.path.dirname(_SPEC_DIR)

# --- 依赖包的资产（theme json / tkdnd 扩展 / docx 模板等）--------------------- #
_datas = []
_binaries = []
_hiddenimports = []

for _pkg in ("customtkinter", "tkinterdnd2", "docx", "openai"):
    _pkg_datas, _pkg_binaries, _pkg_hidden = collect_all(_pkg)
    _datas += _pkg_datas
    _binaries += _pkg_binaries
    _hiddenimports += _pkg_hidden

# --- 插件源码（关键）--------------------------------------------------------- #
# src/word_format_applier → <包根>/word_format_applier
_datas.append((os.path.join(_ROOT, "src", "word_format_applier"), "word_format_applier"))

# --- 内置预设（只读资源，含 1 个 .docx 模板）-------------------------------- #
# 这里按默认铺进 _internal\presets\，再由 build.bat 用 Python（shutil）搬到
# **exe 同级**的 presets\。为什么不直接在 datas 里写 exe 同级：PyInstaller
# 6.22 会直接拒绝 —— "Invalid (SRC, DEST_DIR) tuple: DEST_DIR must not point
# outside of application's top-level directory!"（本机实测）。
# 搬到 exe 同级是为了对齐两条读取路径：
#   * 插件侧：frozen 下 `presets.py` 的 PLUGIN_ROOT = Path(_MEIPASS).parent =
#     exe 所在目录，CLI 默认就在这儿找预设；
#   * 外壳侧：`core/config.py::resolve_presets_dir()` 第一优先级也是这里。
_datas.append((os.path.join(_ROOT, "presets"), "presets"))

# --- 图标资源（只读，v2.0.0 新增）-------------------------------------------- #
# 窗口/任务栏图标走 `core/config.py::asset_path()`：frozen 时 = _MEIPASS/assets/。
# 注意区分：**exe 本体**的图标不靠这里，靠下面 EXE(icon=...) —— 那里必须是磁盘上的
# 真实路径，不能是 _MEIPASS（打包期 _MEIPASS 还不存在）。
_datas.append((os.path.join(_SPEC_DIR, "assets"), "assets"))

# --- 用户参考文件 ------------------------------------------------------------- #
# 1) .env 模板 → 落在 _MEIPASS（build.bat 另在 exe 同级放一份，那份才是主副本，
#    因为 Phase 5 起 config.ENV_PATH 指的是 exe 同级；这里留一份只为兼容旧路径）
_env_example = os.path.join(_SPEC_DIR, ".env.example")
if os.path.isfile(_env_example):
    _datas.append((_env_example, "."))
# 2) 依赖清单 → 落到 _MEIPASS，供用户/排障参考
_datas.append((os.path.join(_SPEC_DIR, "requirements.txt"), "."))

# --- 插件包的模块级 hidden import（datas 是双保险的第一道）------------------- #
_hiddenimports += [
    "word_format_applier",
    "word_format_applier.cli",
    "word_format_applier.__main__",
    "word_format_applier.applier",
    "word_format_applier.cleanup",
    "word_format_applier.docxio",
    "word_format_applier.llm_fallback",
    "word_format_applier.parser",
    "word_format_applier.presets",
    "word_format_applier.report",
    "word_format_applier.schema",
    "word_format_applier.structure",
    "word_format_applier.textparse",
    "dotenv",
    "darkdetect",
]

# --- 桌面外壳自己的子模块 ----------------------------------------------------- #
# 入口是 `desktop/app.py`（直跑脚本，模块名是 __main__），它的兄弟模块靠
# PYTHONPATH 上的 desktop/ 以顶层名 `core.*` / `ui.*` / `parser.*` 导入。
# 静态分析基本都能跟上，这里显式列一遍是防止"某个模块只在回调里才 import，
# 打包后一点按钮就 ModuleNotFoundError"。多列不存在的模块只会 warning，不报错。
_hiddenimports += [
    "core", "core.bridge", "core.config", "core.preset_loader", "core.user_presets",
    "ui", "ui.theme", "ui.dialogs", "ui.home", "ui.preview", "ui.upload_dialog",
    "ui.preset_manager", "ui.settings", "ui.about",
    "parser", "parser.txt_parser", "parser.docx_extractor", "parser.llm_parser",
    "parser.diag_env",
]

a = Analysis(  # noqa: F821 - Analysis 由 PyInstaller 注入
    [os.path.join(_SPEC_DIR, "app.py")],
    pathex=[os.path.join(_ROOT, "src"), _SPEC_DIR],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 明确排除：省体积、少误报；tkinter 的 ttk 等仍会被自动带上
    excludes=[
        "matplotlib", "numpy", "pandas", "scipy", "pytest",
        "PIL.ImageQt", "PyQt5", "PySide2", "PySide6",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821 - PYZ 由 PyInstaller 注入

exe = EXE(  # noqa: F821 - EXE 由 PyInstaller 注入
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="桃符",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX 压缩极易触发杀毒误报，明确关闭
    console=False,      # 无控制台窗口；CLI 分支靠管道 + 标准流重定向工作
    # 普通权限（asInvoker）。绝不能设成 True：管理员运行时 Windows 的 UIPI
    # 会让资源管理器拖入的文件失效，普通用户无法接受。配置写入已改为
    # %APPDATA% → %LOCALAPPDATA% → ~/.taofu → %TEMP% 逐级降级，不需要提权。
    uac_admin=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(_SPEC_DIR, "assets", "taofu.ico"),   # exe 本体图标（资源管理器/任务栏）
)

coll = COLLECT(  # noqa: F821 - COLLECT 由 PyInstaller 注入
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="桃符",
)
