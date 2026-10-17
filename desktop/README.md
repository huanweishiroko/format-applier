# desktop/ —— 桌面外壳（开发者说明）

用户请直接看仓库根目录的 [README](../README.md)。这里只记开发者需要知道的几件事。

## 目录职责

| 目录 / 文件 | 职责 |
| --- | --- |
| `app.py` | 主窗口、页面切换、`--wfa-cli` 打包入口 |
| `core/config.py` | 全部路径的唯一来源（程序目录 / `%APPDATA%\Taofu` / presets） |
| `core/bridge.py` | 调插件 CLI 的桥（开发期 `-m`，打包后 `--wfa-cli`） |
| `core/preset_loader.py`、`core/user_presets.py` | 内置预设与用户预设 |
| `parser/` | docx 文本提取、文本规则解析、LLM 解析 |
| `ui/` | 各页面与弹窗（home / preview / preset_manager / settings / upload_dialog / about / theme） |
| `Taofu.spec`、`build.bat`、`build_finish.py` | PyInstaller 打包 |
| `assets/` | 图标等只读资源 |

核心引擎在仓库根的 `src/word_format_applier/`，GUI 与 CLI 共用。

## 关键约定

- **用户可见路径一律由 `core/config.py` 推出**：打包后基于 `sys.executable`，
  开发期基于 `__file__`。不要自己拼绝对路径。
- **界面和日志里不要出现本机绝对路径**：显示用 `cfg.display_path()`，
  会显示成 `%APPDATA%\Taofu\…` 这类短写法。
- **API 配置的优先级**（`parser/llm_parser.py::load_config`）：
  `%APPDATA%\Taofu\config.json`（设置页保存）→ exe 同级 `.env` / 环境变量 →
  抛 `LlmConfigError` 提示去设置页填。
- **不要提交** `desktop/.env`（真实密钥）和 `desktop/config.json`（本机配置）。

## 打包

```bat
cd desktop
build.bat
```

产物是 `desktop\dist\桃符\`（onedir）。`build_finish.py` 会搬预设、
只复制 `.env.example` 模板、并清掉误入的开发文件（笔记 / `__pycache__` /
`tools` 等）。`dist\` 不会被清空。

## 本地跑 GUI

```bat
.venv\Scripts\python.exe desktop\app.py
```

Windows 上打包版本的 `.exe` 是窗口程序，不带控制台；开发期直接跑有控制台，
方便看异常堆栈。
