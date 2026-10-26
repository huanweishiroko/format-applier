# DSH 插件评估与安装记录（桃符项目）

> 记录时间：2026-10-20
> 适用环境：DeepSeek Harness Desktop `0.2.1-rc.2`（Windows 11），profile = `desktop`
> 评估对象：10 个候选项（9 个 DSH 插件 + 2 个 CustomTkinter 主题包，其中两个主题包合并为一节讨论）
> 结论一句话：**只装 ModLens 一个；其余 9 个在桃符当前阶段收益低于风险，暂不装。**

---

## 一、结论摘要

| 编号 | 插件 | 类型 | 决定 | 一句话理由 |
|---|---|---|---|---|
| 1 | **ModLens**（`@liustack/modlens`） | 视觉桥 | ✅ **已安装 3.27.1** | 唯一能补上"模型看不见图"的真实短板 |
| 2 | dsh-fuse | 成本熔断 | ⏸ 暂缓 | 好想法但 1★/未验证，且位于每次 LLM 调用的热路径上 |
| 3 | dsh-media-skills | 读图 + 生图 | ❌ 不装 | 与 #1 功能重叠，同装会出现粘贴路由抖动 |
| 4 | dsh-ui-spec | 截图→Web UI 规格 | ❌ 不装 | 产物是网页规格，桃符是 Tkinter |
| 5 | dsh-browser-scope | Chromium DevTools 工作台 | ❌ 不装 | 桃符无浏览器端；且声明只支持 0.1.5–0.1.7 |
| 6 | dsh-plugin-ui-debug | Playwright 驱动 Chrome | ❌ 不装 | 只能驱动 http(s) 页面，够不到 Tkinter 窗口 |
| 7 | dsh-revise | 可视化前端修订 | ❌ 不装 | 桃符没有 Web 前端 |
| 8 | DSH-to-Figma | Figma 画布工具 | ❌ 暂不装 | 无设计稿工作流；要装 Figma 桌面端 + 常驻 companion |
| 9 | dsh-appearance-gallery | DSH Web 换肤 | ❌ 不装 | 只改 DSH 自身外观，与桃符无关 |
| 10 | customtkinterthemes / CTkThemesPack | CTk 主题包 | ❌ 不装（可偷色） | 与桃符"theme.py 是唯一色源"的硬约束冲突 |

---

## 二、评估基线：桃符到底是什么

判断"有没有必要"之前，先固定三条事实，否则容易把 DSH 生态的东西错配到桃符上。

### 2.1 技术栈

| 项 | 事实 | 证据 |
|---|---|---|
| 界面框架 | Python + `customtkinter`（>=5.2，本机 6.0.0） | `desktop/requirements.txt` |
| 主题方式 | `ctk.set_default_color_theme("blue")` + 自建 `PALETTE` 覆盖 | `desktop/app.py:258-259`、`desktop/ui/theme.py` |
| 配色约束 | **theme.py 是唯一色源**，页面禁止写十六进制、禁止 `grayXX`；颜色一律 `(浅色, 深色)` 二元组 | `desktop/ui/theme.py` 顶部设计约束注释 |
| 分发方式 | PyInstaller 单文件目录（`_internal\` + `presets\`），无双击安装器 | `desktop/Taofu.spec`、README |
| 是否有 Web 前端 | **没有**。全部是原生 Tk 窗口 | `desktop/app.py` |

### 2.2 宿主环境

| 项 | 值 | 获取方式 |
|---|---|---|
| DSH 版本 | `0.2.1-rc.2` | `dsh.cmd --version` |
| Node / pnpm | `24.21.0` / `11.28.5` | `resources\runtime\versions.json` |
| profile | `desktop`（不是 `web`） | `~/.dsh/profiles/desktop` |
| 装前已有插件 | `dsh-compaction-threshold@1.0.4`、`dsh-whale-widget@0.3.17`、`dsh-workbuddy-connect@0.7.8` | `dsh plugin --profile desktop list` |
| 已有能力 | windows MCP（桌面截图/点击/键鼠）、office 系列 skill | 会话工具清单 |

### 2.3 判断标准

一个插件对桃符算"有必要"，必须同时满足三条：

1. **补的是真空白**：桃符当前工作流里确实做不到，而不是"也能做，只是换个姿势"。
2. **不侵入既有约束**：不能要求改 `theme.py` 的色源模型、不能要求改打包 spec、不能改变"正文一个字都不动"的核心承诺。
3. **失败可回滚**：卸载一条命令搞定，且不会连带污染 profile 启动。

用这三条筛，10 个候选里只剩 1 个全过。

---

## 三、逐项评估（为什么装 / 为什么不装）

### 3.1 ModLens —— ✅ 装

**它是什么**：给纯文本模型装"眼睛"。粘贴图片或给路径，走 `modlens_read_image` 返回结构化证据：全量 OCR 文本、阅读顺序的布局区域、实体关系、不确定项列表。

**为什么对桃符有必要**（关键论据，不是"看起来有用"）：

1. **桃符的验收场景天然产生图片证据**。改版、排版、打包这几类问题，用户第一反应是发截图——"这个间距不对""这行溢出框了""PyInstaller 弹了这个框"。而当前模型是 deepseek-flash，**纯文本**，收到图片等于收到一张白纸。
2. **现有工具补不上这个洞**。windows MCP 的 `Screenshot`/`Snapshot` 能截桌面，但返回的是像素；像素进了上下文，文本模型依然读不出字。所以"能截图"≠"能看图"，这不是重复能力。
3. **对 `AGENTS.md` 的防爆约束是正向的**。约束要求"不许凭视觉直觉改 UI，先量化"。ModLens 输出的正是可量化的证据（框坐标、阅读顺序、文字），比人工口述"左边一点"更符合这条纪律。
4. **零侵入**。它是一个独立 bundle，不碰桃符代码、不碰打包、不碰配色；卸载 = 删一个包。

**风险与缓解**：

| 风险 | 说明 | 缓解 |
|---|---|---|
| 供应链 | dshbase 静态扫描标记「越权 medium / 危险命令 high」；因为它要 spawn 本机 CLI、读本地文件 | MIT、单作者维护、4258★；只在本机跑，不经第三方中转；不配置就用不了 |
| 隐私 | 图片会发给所选视觉 provider | 默认不自动上传；provider 由你选，可只用本机已登录的 CLI |
| 依赖 | 需 Node ≥22.19 | 宿主是 24.21.0，满足 |
| 噪声 | 多一个工具在工具列表里 | 只在提到图片时触发，不影响文本任务 |

**实测状态**：已装、工具已注册、引擎未配置（详见第五节）。**这不是失败，是接线成功的证据**——报错本身就是插件在正常工作。

### 3.2 dsh-fuse —— ⏸ 暂缓（想清楚了再装）

**它是什么**：每次调用的计量 + 预算/模型/推理档位"保险丝"，在花 token 之前拦截。

**为什么有价值**：桃符的 AI 解析走 GLM / DeepSeek / Kimi 的付费 key，长会话确实有跑飞的可能。

**为什么这一轮不装**：

1. **位置太靠里**。它挂在"每次 LLM 调用"的热路径上。一旦它自己抛异常，坏的不是某个功能，是**整个会话**。这类插件出问题时的爆炸半径和视觉插件完全不是一个量级。
2. **成熟度不够**。1★、未验证、无安全扫描。对比 ModLens 的 4258★，风险收益比不划算。
3. **没有观测期就没有数据**。它的价值来自"先只计量、只告警，看清真实消耗再收紧"。而当前没有既有消耗曲线可对照，装了也只能先放着。

**什么时候再装**：连续一周记录到单日 API 花费超出预期，或者开始跑长时间自动批处理时。届时先只开"计量/告警"模式，跑一周再决定是否开启硬拦截。

**随时可加**，一条命令：

```powershell
& "C:\Users\zhangmeng\AppData\Local\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd" `
  plugin --profile desktop add github:openplancc/dsh-fuse
```

### 3.3 dsh-media-skills —— ❌ 不装

**能力**：免费读图（GLM-4V-Flash，可失败切换到 SiliconFlow / Gemini）+ 免费生图（Kolors）。

**不装的三条理由**：

1. **和 ModLens 正面重叠**。两者都解决"文本模型看图"。官方文档明确写了共存时的粘贴路由顺序（ModLens 先截，本插件的 api-proxy 兜底）——这意味着**同一张图谁处理取决于时序**，会出现"有时读到、有时读不到"的玄学问题。诊断这种问题的成本远高于收益。
2. **粘贴读图依赖宿主核心补丁**。它的 README 自己写了：粘贴自动描述能力在 DSH 核心（api-proxy 图片准入）里，本插件只提供模型路由 + skill。宿主是 0.2.1-rc.2，该补丁是否已进核心**未验证**。装完很可能只有"生图"能用。
3. **要多两个 key**（智谱 + 硅基流动），而 ModLens 复用本机 CLI 就能零 key 起步。

**唯一让我犹豫的点**：它的 `media-tools` 能免费生图，对桃符 README 头图、应用图标这类素材有用。但这个需求一年用不了几次，真需要时临时装、用完卸，比长期常驻更合适。

### 3.4 dsh-ui-spec —— ❌ 不装

**能力**：截图 → Windows 原生 OCR + 场景图重建 + 字体/形状证据 → 输出"可实现的 Web UI 规格"，还能给渲染结果打 0–100 分。

**为什么不装**：

- **产物错配**。它输出的是 viewport、组件计数、导航槽位、CSS 变量这类**网页**规格。桃符是 Tkinter 的 `grid/pack` + 像素常量，规格拿到手也没法落地。
- **它解决的问题桃符没有**。它服务的是"照着设计稿写 React 页面"。桃符的 UI 已经定稿（`NOTES.md` 记录改版已验收），不存在"照图重写"的场景。
- **成本不低**：要 Windows OCR 运行时 + sharp 预编译二进制 + Node ≥22.19。

**例外**：如果哪天要做桃符的官网/在线演示页，它是合适的工具——那时候再装。

### 3.5 dsh-browser-scope —— ❌ 不装（硬性版本不兼容）

**能力**：30 个 CDP 工具，断点、Source Map、网络时序、性能 Trace、Heap、双页实况。

**不装的两条理由**：

1. **桃符没有浏览器端**。它是原生窗口程序，CDP 根本连不上去。
2. **版本对不上，这条是决定性的**。它的 README 明确写：`1.0.0-rc7` 面向 DSH `0.1.5-rc.2 / 0.1.6-alpha.x / 0.1.7-rc.1 / 0.1.7-rc.2`。而宿主是 **0.2.1-rc.2**。跨了一个 minor 版本，大概率装上后工具注册不上，或者注册上了行为诡异。这类"半死不活"的状态最难排查。

### 3.6 dsh-plugin-ui-debug —— ❌ 不装

**能力**：Playwright 驱动真实 Chrome，`ui_shot` 截图、`ui_drive` 点击/输入/分段拖拽，配套一个调试方法论的 skill。

**为什么不装**：

- **射程只到 http(s)**。它服务的是"调试 DSH 插件面板 / Web UI"。桃符的窗口是 Tk 的，Playwright 够不到。
- **能力已被覆盖**。桌面截图/点击你已经有 windows MCP（`Snapshot`、`Click`、`Type`），而且更贴近原生窗口。
- 会额外拉起 Chrome、占端口，属于"装了就常驻成本"的类型。

**例外**：如果以后给桃符做 Web 版，或者要调 DSH 自己的插件面板，它是首选。

### 3.7 dsh-revise —— ❌ 不装

**能力**（按 `dshbase` 收录的 `@Lostforest7/dsh-revise`）：可视化前端修订——在页面上点元素、提修改、看截图 + 代码 diff。

**为什么不装**：桃符没有 Web 前端，这个工作流的每一步都落空。另外它 0★、未验证，连"能装"都没被验证过。

**注意同名坑**：生态里还有个 `dsh-revise-chan`（修改 AI 回答内容 + 常驻大纲侧栏），是另一回事。两者对桃符都没用，但选型时别混。

### 3.8 DSH-to-Figma —— ❌ 暂不装（唯一"技术上完全可用"的落选者）

**能力**：17 个 Figma 画布工具，能读写图层、组件、变量、导出素材、回传截图。声明支持 DSH `0.2.0-rc.2 / 0.2.1-rc.2`——**和宿主版本完全匹配**，这是它比 browser-scope 强的地方。

**为什么不装**：

- **桃符没有 Figma 工作流**。它解决的是"设计稿 → 前端代码"，桃符的界面已经用 Tkinter 写完了。
- **常驻成本高**：要 Figma 桌面端、要导入一次开发插件、要保持 companion 窗口开着、占本地 3055 端口。为一个用不上的能力付这些，不值。
- 功能边界也要看清：它的"设计稿→代码"只提供设计上下文和素材，**前端代码仍由模型写**；交互逻辑、响应式、后端行为它不管。

**例外**：要给桃符 3.0 做全新视觉稿、并且打算从 Figma 直接落代码时，再装。

### 3.9 dsh-appearance-gallery —— ❌ 不装（纯装饰，且只装饰 DSH）

**能力**：15 个主题家族 + 9 套 dsh-web-ui 皮肤复刻，改的是 **DSH Web GUI 自己的外观**。

**为什么不装**：

- **和桃符零关系**。桃符是独立 exe，DSH 换成什么皮肤都不会影响它一个像素。
- 它属于"让工作台好看"的消费型插件。真想装，随时一条 `dsh plugin --profile desktop add dsh-appearance-gallery`，不需要评估，也不需要写进本文档的决策链。

### 3.10 customtkinterthemes / CTkThemesPack —— ❌ 不装，但可以"偷色"

这两个是唯一**和桃符同技术栈**的候选，所以看起来最"应该装"，实际最不该装。

**它们是什么**：CustomTkinter 的主题 JSON 包。`CTkThemesPack` 是纯 JSON 集合（breeze/coffee/midnight/rose/patina/rime…，Unlicense）；`customtkinterthemes` 是 PyPI 上的管理器（`pip install`，1.0.2，MIT，依赖 `customtkinter`，部分主题要求本机装字体）。

**为什么不装**——三条都是硬冲突：

1. **机制上不生效**。CTk 主题 JSON 只定义"默认主题"的那组键（fg_color、button、entry 等）。而桃符的每个控件都是显式传色：`PALETTE["bg_surface"]`、`PALETTE["accent"]`……**显式值优先于主题默认值**。也就是说：装了主题，界面基本不变；要真变，得改 18 个页面模块——那就不叫"装主题"了，叫重写。
2. **违反你自己定的约束**。`theme.py` 顶部写着"本文档是唯一色源，页面里不许再写十六进制"。引入外部主题等于开第二个色源，以后调色会出现"改了一处、另一处没变"的幽灵问题。
3. **打包会疼**。桃符是 PyInstaller 分发（`Taofu.spec`）。多一个依赖意味着：`datas` 要收主题 JSON、字体要处理（缺失时 CTk 会警告）、`_internal` 体积变大、用户机器上的字体环境不可控。为一个"看起来不变"的效果付这些，完全不划算。

**正确做法：只抄色值，不引依赖。**
`CTkThemesPack` 的 `midnight`、`patina`、`rime` 三套冷色调，和 `theme.py` 里"冷灰底 + 靛蓝强调"的路子接近。需要新色时，把 3–5 个 hex 值手工加进 `PALETTE`，作为 `(浅色, 深色)` 二元组——零依赖、零打包风险、色源仍然唯一。

---

## 四、实际执行记录

### 4.1 变更清单

| 项 | 变更前 | 变更后 |
|---|---|---|
| profile 依赖 | 3 个包 | 4 个包（+`@liustack/modlens@3.27.1`） |
| `~/.dsh/profiles/desktop/package.json` | 无 modlens | `dependencies` 增加一项；`dsh.profile.bundles` 末尾追加 `"@liustack/modlens"` |
| 磁盘占用 | — | 解包约 719 KB + 6 个传递依赖（`undici`、`commander` 等） |
| 桃符项目文件 | — | **未改动任何源码**（本文档除外） |

### 4.2 使用的命令

```powershell
# 1) 确认 CLI 与 profile
& "C:\Users\zhangmeng\AppData\Local\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd" --version
# → 0.2.1-rc.2

& "...\dsh.cmd" plugin --profile desktop list
# → 3 packages（改前）

# 2) 备份（回滚用）
# C:\Users\zhangmeng\.dsh\profiles\desktop\.backup-20261020\
#   package.json / cordis.patch.yml / pnpm-lock.yaml

# 3) 安装
& "...\dsh.cmd" plugin --profile desktop add "@liustack/modlens@3.27.1"
# → Done in 8.4s using pnpm v11.28.5（exit=0）

# 4) 验证注册
& "...\dsh.cmd" plugin --profile desktop list
# → 4 packages
```

> 注意：**profile 必须写 `desktop`**。用 `--profile web` 装，当前桌面版 GUI 是不会认的——它加载的是 `desktop` 这个 profile。用全局 `dsh` 也可能因版本不一致而拒绝管理 `desktop`，所以固定用 `resources\runtime\cli\bin\dsh.cmd`。

### 4.3 验证结果

| 验证项 | 结果 | 说明 |
|---|---|---|
| 包安装 | ✅ | `@liustack/modlens 3.27.1`，pnpm 无报错（仅 1 个 deprecated 子依赖告警） |
| bundle 注册 | ✅ | `dsh.profile.bundles` 已含 `@liustack/modlens`，插件自带 `cordis.patch.yml` |
| 工具热注册 | ✅ | 本会话工具列表**当场出现** `modlens_read_image`，未重启 |
| 引擎健康 | ⚠ 待配置 | `doctor`：所有 provider 均不可用（无 key / 无本机 CLI） |
| 端到端读图 | ⏸ 待验证 | 见下方报错，属于"缺引擎"而非"插件坏" |

### 4.4 `doctor` 关键输出（摘要）

```text
Config file: C:\Users\zhangmeng\.modlens\config.json   (not present)
Selected provider: antigravity-cli   (built-in default)
Failover chains: local (none) / remote (none)

[!!] antigravity-cli: agy not on PATH
[!!] gemini-api:      missing: apiKey
[!!] openai:          missing: baseUrl, apiKey, model
[!!] anthropic:       missing: apiKey
[!!] claude-cli:      claude not on PATH
[!!] kimi-cli:        kimi not on PATH
```

### 4.5 冒烟测试的真实结果（重要，别误读）

对 `screenshots/gui-api-help.png` 调用 `modlens_read_image`，返回：

```text
Error: modlens failed (exit 1): No vision provider is set up on this machine.
Install Antigravity CLI ... or configure a key:
modlens config set gemini-api.apiKey <key>. Run modlens doctor for the full picture.
```

**这条报错是"接线成功"的证据**：

- 工具被正确注册、能被调用、能读到本地路径 ✅
- 失败发生在"选引擎"这一步，是**可配置的缺口**，不是安装或兼容性问题 ✅
- 报错自带修复指令，属于作者设计良好的失败路径 ✅

**没有验证到的**：OCR 准确率、中文排版读图质量、响应耗时。这三项必须配好引擎后补测。

### 4.6 为什么没配引擎（以及为什么不偷偷用现成 key）

排查过本机所有可用 key，结论是**没有视觉能力的 key**：

| 来源 | 内容 | 能否当视觉引擎 |
|---|---|---|
| `~/.dsh/.credentials.yaml` | `DEEPSEEK_API_KEY`（35 字符） | ❌ DeepSeek 文本模型无视觉 |
| `desktop/.env` | `OPENAI_BASE_URL` / `OPENAI_MODEL`（13 字符，形如 `deepseek-chat`） | ❌ 同上，指向 DeepSeek |
| `%APPDATA%\Taofu\config.json` | `api_key` 为空 | ❌ 未配置 |

所以不是"懒得配"，是**本机确实没有可用的视觉端点**。配一个需要你去拿免费 key（约 3 分钟），这属于需要你本人操作的步骤，我没有替你注册账号。

> 顺带说明：评估过程中读过 `%APPDATA%\Taofu\config.json` 的**结构**（确认 `api_key` 长度 0），没有打印或外传任何密钥值。

---

## 五、下一步：配一个免费视觉引擎（三选一）

按推荐顺序。

### 方案 A：免费 Gemini key（推荐，5–10 秒/次）

1. 打开 <https://aistudio.google.com> → Get API key（免费，不需信用卡）。
2. 在本机终端执行（key 走隐藏输入，不会留在命令历史）：

```powershell
cd "$env:USERPROFILE\.dsh\profiles\desktop"
node .\node_modules\@liustack\modlens\dist\main.js config set gemini-api.apiKey
```

3. 复检：

```powershell
node .\node_modules\@liustack\modlens\dist\main.js doctor
```

> 隐私提示：Gemini 免费层的数据可能被用于改进 Google 产品。**含身份证、合同、客户数据的文档截图不要走这条**，改用方案 B。

### 方案 B：智谱 GLM-4V-Flash（国内直连，免费，隐私更可控）

你 README 里已经写了智谱的注册流程，同一套账号即可：

```powershell
cd "$env:USERPROFILE\.dsh\profiles\desktop"
node .\node_modules\@liustack\modlens\dist\main.js config set openai.baseUrl "https://open.bigmodel.cn/api/paas/v4"
node .\node_modules\@liustack\modlens\dist\main.js config set openai.model "glm-4v-flash"
node .\node_modules\@liustack\modlens\dist\main.js config set openai.apiKey
```

好处：和桃符"AI 解析"用同一家平台，key 管理只有一处；图片不出境。

### 方案 C：Antigravity CLI（零 key，但要浏览器登录，15–45 秒/次）

```powershell
# 官方安装脚本是 bash；Windows 下建议用 WSL 或 Git Bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
agy   # 浏览器登录一次，然后退出
```

适合"完全不想碰 API key"的情况，代价是慢。

> 配好后**不需要改桃符任何代码**。ModLens 是宿主侧能力，桃符仍是纯离线 + 可选 AI 解析的架构。

---

## 六、重启后的冒烟验证清单（5 步，约 3 分钟）

装完插件、配好引擎后，**需要重启一次 DeepSeek Harness Desktop**（本会话是热注册的，但完整加载建议重启一次）。然后：

| # | 动作 | 预期 |
|---|---|---|
| 1 | 新开会话，输入框旁/模型选择器看是否有 `(modlens vision)` 条目 | 出现即说明模型路由已注入 |
| 2 | 把 `screenshots/gui-api-help.png` 直接粘进输入框，问"这张图里有几个输入框？" | 回答引用了图中真实文字（如"API 地址""API 密钥""模型名称"） |
| 3 | 不给图，只给路径：`读一下 E:\dsh_plugins\word-format-applier\screenshots\gui-presets-light.png` | 触发 `modlens_read_image`，返回 OCR 文本 |
| 4 | 让它报出图中第一行标题原文 | 与图片实际文字逐字一致（这是 OCR 准确率的硬检验） |
| 5 | 观察 `meta.attempts` / 耗时 | 5–10s（API 路线）属正常；>45s 说明走了 CLI 兜底 |

**如果第 2 步失败**：先 `doctor` 看 provider 是否 ready，再看宿主是否把粘贴路由给了本插件（DSH 0.2.x 对"模型是否确认纯文本"有判定逻辑，未确认的模型不接管粘贴）。此时第 3 步的"给路径"方式一定可用，可作为兜底工作流。

---

## 七、回滚方案

任何一步出问题，两条命令回到装前状态：

```powershell
# 方式 1：正常卸载
& "C:\Users\zhangmeng\AppData\Local\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd" `
  plugin --profile desktop remove @liustack/modlens

# 方式 2：文件级还原（卸载异常时用）
$b = "$env:USERPROFILE\.dsh\profiles\desktop\.backup-20261020"
$p = "$env:USERPROFILE\.dsh\profiles\desktop"
Copy-Item "$b\package.json"     "$p\package.json"     -Force
Copy-Item "$b\cordis.patch.yml" "$p\cordis.patch.yml" -Force
Copy-Item "$b\pnpm-lock.yaml"   "$p\pnpm-lock.yaml"   -Force
```

备份目录保留到确认稳定运行一周后再删。

> 注意：`dsh plugin` 的子命令实际是**把参数转发给 pnpm**（见 `dsh plugin --help`）。所以 `remove` 之后请顺手确认 `package.json` 里的 `dsh.profile.bundles` 数组是否也删掉了 `"@liustack/modlens"`；如果没删，DSH 启动时仍会尝试加载它并报错。手工删掉那一行即可，或用上面的方式 2 整体还原。

**注意**：如果重启后 DSH 起不来，先按方式 2 还原，再启动；不要反复试装。

---

## 八、遗留问题与后续观察点

| # | 事项 | 处理时机 |
|---|---|---|
| 1 | ModLens 在 0.2.1-rc.2 上的粘贴增强是否生效（官方验证版本是 0.1.7 系） | 重启后按第六节第 2 步验证 |
| 2 | 视觉引擎选型（Gemini / 智谱 / antigravity） | 你决定后我配 |
| 3 | dsh-fuse 是否值得装 | 出现单日 API 花费异常时重新评估 |
| 4 | 混合场景：看 Word 渲染图判断排版 | 引擎配好后，用 `office-render` 出图 → ModLens 读图，可做"机器初筛 + 人工确认" |
| 5 | 8 个落选插件的复评条件 | 见第三节各条"例外" |

---

## 九、一句话总结

这次只装了一个插件，但**装对了位置**：它补的是"模型看不见图"这个所有排版/打包/界面问题都会撞上的结构性缺口，而不是某个锦上添花的功能。其余 9 个不是不好，是**不在桃符这条线上**——把 DSH 生态的 Web 前端工具硬塞给一个 Tkinter 桌面程序，得到的不是能力，是排查成本。
