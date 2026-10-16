# Word 格式助手 · 使用说明

一个把 `.docx` 按格式要求（字体、字号、标题级别、段落缩进、页面设置…）批量重排的
桌面小工具。**绿色免安装：整个文件夹拷到哪都能跑，目标机器不需要装 Python。**

---

## 一、启动

双击文件夹里的 **`Word格式助手.exe`**。

* 首次启动会慢 3～5 秒（onedir 模式要先解包 bootloader），之后正常。
* 不会弹黑窗（无控制台窗口）；启动后是一个窗口界面。
* 如果 Windows 弹出「已保护你的电脑」（SmartScreen），见第五节。

> 不要单独把 exe 拷出去——它依赖同目录的数据。**移动就整个
> `Word格式助手` 文件夹一起移**。

---

## 二、首次使用：配置 API（可选）

程序有两条解析路线：

| 路线 | 需要 API 吗 | 说明 |
| --- | --- | --- |
| **本地规则解析** | 不需要 | 选内置预设（格式要求1/2/3）或自己贴 DSL，全程离线 |
| **上传格式要求让 AI 转成规则** | 需要 | 粘贴/上传一段中文格式要求，AI 把它翻译成 DSL |

**只做前者的话，本节可以跳过。**

需要 AI 时：

1. 在 **exe 同级的文件夹**里找到 `.env.example`（就在 `Word格式助手.exe` 旁边）；
2. 把它**改名成 `.env`**（去掉 `.example`，保留前面的点），留在原地；
3. 用记事本打开，把 `sk-你的key` 换成真实密钥，按需改地址和模型名：

   ```
   OPENAI_BASE_URL=https://api.deepseek.com/v1
   OPENAI_API_KEY=sk-你的key
   OPENAI_MODEL=deepseek-chat
   ```

4. 保存后重启程序，进 **设置 → 测试 API 连接**，显示往返延迟即成功。
   设置页的「配置文件」一行显示的就是程序实际读取的 `.env` 路径，对不上看那一行。

> 不想建文件也可以：直接设 `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL`
> 三个环境变量，**环境变量优先级最高**，设了就不读 `.env`。
> 老版本把 `.env` 放在 `_internal\` 里的，新版仍能读到（兼容），但建议搬到 exe 同级。

> `.env` 里是明文密钥，别把它连同文件夹一起发给别人。
> 不想配也没关系：填错/不填只影响 AI 解析，其他功能照用。

---

## 三、日常使用（四步）

1. **拖 .docx 进窗口** —— 拖不动就点一下拖拽区选文件（拖放不可用时自动降级）。
   界面会显示文件名、大小、段落数、修改时间。
2. **选预设** —— 下拉框里 `📦` 是内置预设，`👤` 是你自己保存的用户预设。
3. **预览效果**（建议先看）—— 弹窗三段：① 识别出的标题结构 ② 预设的角色映射
   ③ 前 3 段的实际格式。预览在临时目录里真跑一遍，**不会**动你的输出目录。
4. **开始处理** —— 生成 `<原名>_formatted.docx` 到「输出目录」（首页可改，
   默认在**我的文档**下的 `WordFormatAssistant\`），同时生成一份 `.report.json` 报告。
   **原始文件永远不被改写。**

想自己写格式要求：**上传格式要求** → 粘贴文字 / 选 `.txt` / 选 `.docx`
→ 出 DSL → 确认使用 → 存成用户预设，下次直接在下拉框里选。

---

## 四、东西都存哪

| 内容 | 位置 | 卸载时 |
| --- | --- | --- |
| 内置预设（格式要求1/2/3 + 1 个 docx 模板） | **优先** exe 同目录 `presets\`，没有就用 `_internal\presets\` | 随文件夹一起删 |
| 解析缓存 | 随上面那个被选中的 `presets\.cache\` | 随文件夹一起删，删了会自动重建 |
| **API 配置 `.env`** | **exe 同级** `.env`（模板 `.env.example` 也在那儿） | 随文件夹一起删 |
| **用户配置 `config.json`** | `%APPDATA%\WordFormatAssistant\config.json` | **要手动删**（见第六节） |
| **用户预设** | `%APPDATA%\WordFormatAssistant\presets\` | **要手动删**（见第六节） |
| Token 统计 | `%APPDATA%\WordFormatAssistant\usage.json` | **要手动删** |
| 处理输出 | 首页「输出目录」（默认 `我的文档\WordFormatAssistant\`） | 自己决定留不留 |

程序本体与依赖都在 `_internal\` 里，**别只搬 exe**：`presets\`（如果有）、
`.env` 和 `_internal\` 都要跟着走。

> **一句话记住**：`_internal\` 是程序的肚子（只读、不用管）；
> exe 同级放"你要改的东西"（`.env`）；`%APPDATA%\WordFormatAssistant\` 放
> "程序替你记的东西"（config.json / 预设 / 统计），换版本也不会丢。

> **想换内置预设？** 在 exe 同级新建一个 `presets\` 目录，放你的 `.txt` /
> `.docx`，程序会自动优先用它（`_internal\presets\` 里那份就当备份）。
> 想恢复默认，把 exe 同级那个目录删掉即可。

> **从旧版本升上来？** 旧版的 `.env` / `config.json` / `output\` 埋在 `_internal\` 里。
> 首次启动时：旧的 `config.json` 会被自动沿用（启动后写进上面的新位置）；
> `.env` 和 `output\` 里的文件会问一次"要不要复制到新位置"，点确认即可
> （旧文件一律保留，不会删）。

`%APPDATA%` 的快捷打开方式：按 `Win+R`，输入 `%APPDATA%\WordFormatAssistant`，回车。

> 用户数据放在系统用户目录，所以**换新版本、换文件夹位置都不会丢**。

---

## 五、常见问题

**1. 杀毒软件报毒 / 直接删掉 exe**
PyInstaller 打出来的 exe 被误报是行业常态（它带自解包引导器）。处理办法：
把 `Word格式助手.exe` 和整个 `Word格式助手` 文件夹加进杀毒软件的**信任区/白名单**，
然后重新解压或重新打包一份。本程序不联网上传任何文档，只有你主动点 AI 解析时
才把「格式要求文字」发给 `.env` 里配置的那家 API。

**2. 双击没反应 / 弹出「Windows 已保护你的电脑」**
SmartScreen 提示 → 点「更多信息」→「仍要运行」。
如果完全没反应：右键 → 以管理员身份运行试一次；仍不行说明被安全软件拦了（见上条）。

**3. 首次启动很慢**
onedir 模式正常现象，3～5 秒。第二次起会快很多。

**4. 拖拽没反应**
窗口顶部日志区会写「拖放能力：不可用（降级为点击选择）」——直接用点击选择文件，
功能一样。

**5. 提示「找不到预设」/ 内置预设空了**
正常情况用 `_internal\presets\` 里那份，`_internal\presets\` 没被动过就一定能列出来。
如果你在 exe 同级放过自定义 `presets\` 又想改回默认，把那个目录删了即可。
只拷了 exe 出来，`presets\` + `_internal\` 都要拷。

**6. 设置页 API 显示「(未设置)」**
`.env` 放错地方了：新版读 **exe 同级**（和 `Word格式助手.exe` 同一个文件夹），
不是 `_internal\` 里（旧版才在那儿，程序仍兼容）。看设置页「配置文件」那一行显示的路径。
实在懒得建文件，就设三个环境变量，它们优先级最高。

**7. 处理完没看到输出文件**
看首页日志最后几行给出的输出路径，以及同目录的 `*.report.json`。
默认输出目录是 `我的文档\WordFormatAssistant\`（首页/设置页都能改）。

---

## 六、卸载

1. 直接删掉整个 `Word格式助手` 文件夹（程序本体、内置预设、`.env` 一起没了）；
2. 手动清用户数据（不删会残留你的设置、预设和统计）：

   ```
   %APPDATA%\WordFormatAssistant\      ← config.json / presets\ / usage.json
   ```

3. 自己看看 `我的文档\WordFormatAssistant\` 里有没有想留的处理结果。

没有注册表项、没有服务、没有开机自启，删完即净。

---

## 七、给维护者：重新打包

```bat
cd E:\dsh_plugins\word-format-applier\desktop
build.bat
```

`build.bat` 会用 `.venv` 里的 Python 检查/安装 PyInstaller，按
`WordFormatAssistant.spec`（onedir + windowed）打包到 `desktop\dist\Word格式助手\`，
再把 `.env.example` 复制到 **exe 同级**（`_internal\` 里那份是 spec 铺的兼容副本）、
清掉 `build\` 中间产物。

**路径归属（改代码前先看这张表）**：用户可见 / 可改的路径一律由
`sys.executable`（frozen）或 `__file__`（开发期）推出来，见 `core/config.py`：

| 常量 | 含义 | 打包后 |
| --- | --- | --- |
| `APP_DIR` | 程序目录 | exe 所在目录 |
| `ENV_PATH` | 实际读到的 .env | `<exe>\\.env`（没有则 `_internal\\.env`，再没有 = None） |
| `ENV_TARGET_PATH` | 建议新建 .env 的位置 | `<exe>\\.env` |
| `CONFIG_PATH` | config.json | `%APPDATA%\WordFormatAssistant\config.json` |
| `PRESETS_DIR` | 内置预设 | `<exe>\presets` → `_internal\presets` |

**绝不要用 `__file__` 推用户可见路径**——frozen 下它指向 `_internal\`，
推出来的东西用户既找不到也不好改（Phase 4 的老 bug 就是这个）。

**预设目录不靠 bat 搬**（bat 处理中文路径脆弱）：`spec` 把内置预设打进
`_internal\presets\`，程序启动时由 `core/config.py` 的 `resolve_presets_dir()`
按 `<exe 同级>\presets\` → `_internal\presets\` → `<程序目录>\presets\` 的顺序探测，
所以打包后**首次启动就能直接读到内置预设**。build.bat 里那段 `shutil.move`
只是"万一 spec 改了落点"的兜底。

* 改了 `src/` 或 `presets/` **不需要**改 spec，重新打包即可带上新内容。
* 打包后自测插件 CLI 通道（不开 GUI）：

  ```bat
  dist\Word格式助手\Word格式助手.exe --wfa-cli --list-presets-json
  ```

  应输出 `{"presets": [...]}` 且 `count` 为 4（3 个内置 + 1 个 docx 模板副本）。
  注意这条走的是**插件自己的**默认目录（exe 同级），所以别在 exe 同级放空 `presets\`。
* 回滚：删掉 `desktop\dist\` 和 `desktop\build\`，源码未被改动，重跑 `build.bat` 即可；
  旧版本备份就是上一次打包出来的整个文件夹。
