# UI 视觉改版 · 交接笔记

> 本文件是跨会话交接用的。**接手前先读完这一页**，尤其是「四、踩过的坑」——
> 那几条都是花钱买来的教训，重犯一次就是白干。

---

## 一、当前状态

| 项 | 值 |
|---|---|
| 进度 | **UI 视觉改版全部完成（Step 1-5 + 切页优化），用户已验收通过（2026-10-08）**。切页由 unmap/map 的 ~190ms 改为 `tkraise`，并加**过渡遮罩**消除"两页混合"（方案 C，定稿）；`preset_manager.py` 行卡化 + 1px 行内分隔线；`upload_dialog.py` / `preview.py` / `home.py` 收口。**本轮明确不做**：启动 4 秒阻塞（方案 B，独立会话）。下方「未开始/残留」三项均为**用户确认推后**，不属于改版范围。 |
| 已完成 | ① `desktop/ui/theme.py` 全量重写（唯一色源 + 尺寸刻度 + 控件工厂）<br>② `app.py` 骨架（侧栏 210 / 选中态左竖条 / 状态条 26 / `apply_root_theme` / 待清色值 1-3 已清）<br>③ Step 3 阶段一：`home.py` 右主左辅**布局骨架**（左列标题+拖拽区+已选文件卡+日志，右列参数卡+按钮行；内框视口高度分配已修）<br>④ Step 3 阶段二：`home.py` 标题右侧**三节点步骤轨道**（`_build_steps` / `_refresh_steps`，状态绑定 8 个已有变化点）<br>⑤ Step 3 阶段三：`home.py` **拖拽区四态**（`_apply_drop_state` + `_DROP_STATES` / `_DROP_PULSE_SPECS`，120ms `after()` 插值 + 220ms 纯绿呼吸；矩阵见「六」末）<br>⑥ **Step 4 设置页**：`settings.py` 布局重排（输出+外观半宽并排 / 其余全宽）+ `_card_row` 行容器 + API 标题徽章 + 色值 8 已清（决策见「七」Step 4）<br>⑦ **Step 5 第一轮**：`dialogs.py` `ModalWindow` 统一头部（可选图标泡 + 标题 + ✕ + 1px 分隔线；**行次改为 0 头部 / 1 分隔线 / 2 内容**）+ `confirm` 走 `danger=True` 工厂 + 明细框 `th.textbox(mono=True)` + 三个弹窗按钮宽收敛到 88/110 + 死代码 `PLACEHOLDER_*`/`phase3_placeholder` 已删；`about.py` 版本行清色（细节见「五」末）<br>⑧ **Step 5 第二轮**：`preset_manager.py` 表格 → **行卡 + 1px 行内分隔线 + 胶囊徽章 + 文字型操作按钮**（表头整行删除；斑马纹方案用户实测太淡已弃用）；`upload_dialog.py` / `preview.py` 跟随新头部 + 文本框走工厂 + 按钮宽 88/110；`home.py` 剩两处 `grayXX` 清零、两处 `width=120 → BTN_W_XL`、日志框走 `th.textbox(mono=True)`（细节见「五」末）<br>⑨ **切页卡顿修复（方案 A）**：`app.py` `_build_pages` 4 页改为**同格常驻映射**、`show_page` 改 `tkraise()`（~190ms → ~30ms），并加焦点治理与 `home.on_shown` 补算（细节见「十」）<br>⑩ **切页过渡遮罩（方案 C，定稿）**：`app.py` `show_page` 用"`place` → `lift` → `update()` → `tkraise()` → **再 `lift()`** → … → `update()` → `place_forget()` → `update()`"消掉两页混合帧；保留环境开关 **`WFA_PAGE_MASK=0`**（退回老行为，每次少 ~26ms，用于 A/B 观感），调试用 `WFA_PAGE_TRACE=1`（每次切页打"遮罩在屏 / 方法总阻塞"两行）。**用户已肉验通过**（细节 + 两个坑见「十」方案 C） |
| 推后（不属本轮改版范围） | **启动 4 秒阻塞（方案 B，独立会话，见「十」末）**；Step 3 残留两项（按钮行提示文案 / 日志区重复标题待删）；Step 2 遗留的导航两列网格。三项均为用户确认推后，**改版本身（Step 1-5 + 切页优化）已全部完成并验收** |
| Step 3 残留 | 按钮行随状态变化的提示文案（阶段三未列入范围）· 日志区标题与侧栏品牌重复那一行待删 |
| Step 2 遗留 | 导航图标「26px 图标列 + 文字列」两列网格 —— 用户确认**本轮推后**，`app.py` 现仍用 `f"  {icon}  {label}"` |
| 死 token | `th.BG_STRIPE`（浅 `#FAFBFC` / 深 `#1B2027`）**全项目零引用**，斑马纹方案已弃用。预设页的行分隔线实际在 **`preset_manager.py:117`**（`th.divider`，1px，挂在外层 `holder` 上而不是卡内，避免被圆角截短）。**别再去找/调斑马纹**。 |
| 本机环境坑 | ① `--selftest` 的弹窗步骤靠"后台线程 0.6s 后发 `<Escape>`"关模态框，是**时序竞争**，偶发卡到 60s 兜底（遮罩开/关两轮都一样 → 与本轮改动无关）。② DSH 会话里 `user preset save` 报 `PermissionError`（python 子进程写 `%APPDATA%\WordFormatAssistant\presets` 被拒，同路径 PowerShell 可写）—— **用户在真机跑正常**，不是代码问题。详见「八」。 |
| 备份 | `desktop.bak_20261007/`（开工前全量副本，含 `ui/`） |
| 回滚 | `Copy-Item desktop.bak_20261007\ui\theme.py desktop\ui\theme.py -Force`，或整目录对调 |

**用户已确认的设计决策**（不要再问一遍）：

1. 首页改 **右主左辅**：左列 = 标题 + 拖拽区（大）+ 已选文件卡 + 日志；右列 = 处理参数卡，底部封「预览效果 / 开始处理」。动作入口在左、动作收口在右。
2. 配色 **靛蓝 `#4F46E5` + 橙 `#EA7317`**（先按此实现，看效果再微调）。
3. 侧栏 **180 → 210px**。
4. `app.py:362-364` 那 4 个硬编码色值本轮必须一起清掉。

**Step 3 阶段一已定的布局决策**（后续阶段按此继续，不要再改结构）：

- **左 flex + 右固定 320px**，不用纯比例。右列 `_right = CTkFrame(_scroll, width=320)` + `grid_propagate(False)`；
  `_scroll` 只给 col0 `weight=1`、col1 `weight=0`。宽度交给固定值而不是比例——
  参数卡宽度在任意窗口尺寸下都一样。实测 `1080` 窗口 左 477 / 右 320；
  `minsize 860`（`app.py:213`）下 左 257 / 右 320，按钮右沿不溢出。
- 两列的 padding **放外层**（`_left` 用 `padx=(PAD_L, 0)`，`_right` 用 `padx=(PAD, PAD_L)`），
  这样 `_right` 的 `width=320` 就是卡片真实宽度，不被内边距吃掉。
- 余高只挂 `_left` 的 **row3（日志）**：`grid_rowconfigure(3, weight=1, minsize=160)`，
  row0/1/2 `weight=0`。窗口加高 → 只有日志变长，拖拽区纹丝不动（实测 720→900 日志 132→312）。
- 按钮行贴参数卡下方（`_right` row1），**不加吸底空行**。
- `_build_file_card` 的 `wraplength`：330 → **420**（静态大值，不用 `<Configure>` 动态绑）。
  依据：默认窗口下左列可用宽约 438，420 留 18px 边界；只有缩到极小窗口才折行。

**Step 3 阶段二已定的决策**（步骤轨道，用户已确认）：

- 点亮规则用**累积式**：第 N 个亮 = 前 N 个条件都满足。独立式会在启动时出现
  「步骤 2 亮、步骤 1 灭」（`refresh_presets` 会自动选中第一个预设），所以不用。
- 三条件只读已有事实：① `self.selected_file is not None` ② `self.current_preset() is not None`
  ③ `self._processed_ok`（纯视觉标记，**不参与** `_require_ready` 的业务判定）。
- `load_file` / `_on_preset_change` / `start_process` 三处会把 `_processed_ok` 置 False
  （换了输入或预设，上一轮的「已完成」不再对应当前配置）；`_on_process_done` 回填真实 ok。
- 轨道**不加动画**（不动 `after`）：避开 220ms 常驻 `_flash_step`（见「六」第 5 条）。
- 轨道颜色**一律传 token 色对，禁止 `th.C()`**：`apply_theme` 不重建页面（`app.py:483-488`），
  单色会在切主题后停在旧色。无头自检实测浅色解出 `#4F46E5`、深色 `#8B87F5`。

**Step 3 阶段三已定的决策**（拖拽区四态，用户已确认）：

- 四态 = `idle` / `hover` / `pulse`（接收）/ `selected`（已选），由 `_apply_drop_state()`
  **单一入口**推导；渲染参数集中在 `_DROP_STATES` / `_DROP_PULSE_SPECS` 两张表。
- 优先级：悬停 > 已选。`pulse` 期间被悬停打断时，`_apply_drop_state` 会**清零
  `_flash_steps`**（否则残留脉冲会在松手后把态抢回去）。
- 状态判据只读已有事实：`_drop_hovering` / `_flash_steps` / `selected_file is None`。
  **没有动 `load_file`**，收尾时惰性落 `selected`。
- `selected` 样式（用户定稿）：**绿 1.5px 实线**（`create_rectangle`，非虚线）+ `✅` + 文件名。
- `pulse` 样式（用户定稿）：**纯绿呼吸，边框 1px ↔ 3px 交替，不切颜色**。
  橙色在本 UI 里是「警告」，用在接收反馈上会被误读成出错——**禁止**。
- 过渡动画：4 步 × 30ms `after()` 插值（`_drop_seq` 世代号 + 帧回调校验），
  只插值颜色，文字/图标立刻切。脉冲沿用原有 220ms 常驻 `_flash_step`，**不新增定时器**。

---

## 二、红线（违反即停）

1. **只改** `desktop/ui/*.py` 和 `desktop/app.py` 的界面表现。**不许改**：`core/bridge.py`、`core/user_presets.py`、`core/config.py`、`parser/*`、`src/`、`presets/`。
2. **不引新依赖**：图标只用 emoji，字体只用系统字体（微软雅黑 / Consolas），UI 库只用 customtkinter，动画只用 `after()`。
3. **刚修好的 bug 不许复发**：编码、拖拽（WM_DROPFILES）、Tkinter 命名冲突。
4. 颜色/字号/圆角/间距**只能**写在 `theme.py`，页面里不许出现十六进制或 `grayXX`。
5. 不要为改而改——本来就不错的地方保留。

---

## 三、theme.py 现状（Step 1 产物，520 行）

**对外接口稳定**：所有函数名与签名保持原样，所以 8 个页面 + 弹窗模块里的 51 处 `th.*` 调用点一个都没动。

### 可用 token（页面只引用这些名字）

```
背景   BG_PAGE BG_SURFACE BG_SURFACE_ALT BG_SIDEBAR BG_STATUSBAR BG_STRIPE
       HOVER_FILL HOVER_FILL_SUB
描边   BORDER BORDER_STRONG DIVIDER
文字   TEXT TEXT_SECOND TEXT_MUTED TEXT_ON_ACCENT
强调   ACCENT ACCENT_HOVER ACCENT_SOFT ACCENT_TEXT
副色   SECONDARY SECONDARY_SOFT SECONDARY_TEXT        # 上传/导入类动作
状态   SUCCESS SUCCESS_SOFT DANGER DANGER_HOVER DANGER_SOFT WARNING WARNING_SOFT
拖拽   DROP_BORDER_IDLE DROP_BORDER_ACTIVE DROP_FILL_ACTIVE
       DROP_FILL_OK DROP_BORDER_OK DROP_BORDER_WARN DROP_FILL_IDLE
日志   LOG_BG LOG_TEXT
滚动条 SCROLL_TRACK SCROLL_THUMB SCROLL_HOVER
```

### 可用刻度

```
SP.XXS=2 XS=4 S=8 M=12 L=16 XL=20 XXL=24 XXXL=28 HUGE=32
FS.CAPTION=11 SMALL=12 BODY=13 LEAD=14 H3=15 H2=22 H1=26 HERO=30 ICON=24
RADIUS_S=6 RADIUS=8 RADIUS_L=12 RADIUS_XL=16 RADIUS_PILL=999
CTRL_H_S=28 CTRL_H=34 CTRL_H_L=40
BTN_W_S=56 BTN_W_M=72 BTN_W_L=88 BTN_W_XL=110
PAGE_PAD_X=28 PAGE_PAD_Y=24 CARD_PAD=16
SIDEBAR_WIDTH=210 SIDEBAR_ITEM_H=40 SIDEBAR_ACCENT_W=4 STATUSBAR_HEIGHT=26
```

### 可用工厂

```
字体   font(size, weight)  mono_font(size, weight)
容器   card(纯白+描边)  plain(透明排版层)  divider(1px 线)  scroll(page_level=)
文本   page_title  section_title  hint  badge(text, tone)  icon_bubble(glyph, tone, size)
按钮   primary_button(..., danger=)  ghost_button(..., width=None)  text_button  small_button
输入   entry  textbox(mono=)  combo  segmented  progress
工具   C(token|色对) → 当前主题单色   is_light()   tone_colors(tone)   apply_root_theme(root)
保留   dashed_border  bind_drop_target  last_registered_count  parse_drop_event
```

`badge` 的 tone 取 `accent / secondary / success / danger / warning / muted`。

---

## 四、踩过的坑（重犯即白干）

1. **`CTkLabel` 没有 `padx` / `pady` 参数**。给 label 传这两个会直接 `TypeError`。徽章的留白是用 EN SPACE（`\u2002`）撑的。
2. **`CTkButton` / `CTkFrame` / `CTkProgressBar` 都有 `border_color`**，可以放心用（已在 6.0.0 源码确认）。
3. **`ghost_button` 不传 `width` 时不要设默认宽度**。页面里有 `ghost_button(...).grid(sticky="ew")` 依赖「不传宽 → 可拉伸」（如 `home.py:317` 的「上传格式要求…」）。显式传 `width` 才固定宽度。
4. **customtkinter 在这里是 6.0.0**，不是常见的 5.2.2。用任何新控件前先确认参数名：
   `.venv\Lib\site-packages\customtkinter\windows\widgets\ctk_*.py` 里看 `def __init__`。
5. **`fg_color="transparent"` 会被 CTk 解析成父级底色**，所以遍历控件树时会看到 `gray92`/`gray17` 这类值——那是正常产物，不是残留。
6. **CTk 控件无法在 `withdraw()` 的根窗口下构造**（初始化要 `update_idletasks` 读实际尺寸）。做无头自检时，另开一个 `+3000+3000` 的屏幕外窗口。
7. **`desktop/dnd.py` 是顶层模块，名字会遮蔽同名包**。页面里 `import dnd` 是这个模块，别写成别的。
8. **`desktop/dist/_internal/` 里有一份 customtkinter 与 docx 的拷贝**（PyInstaller 打包产物）。`glob`/`grep` 时记得排除，否则满屏噪音。`desktop.bak_20261007/` 也含 dist 副本，比较文件数量时别被吓到（3422 个文件）。
9. **`home.py` 用的是 `from ui import theme as th`（绝对导入优先）+ `except ImportError` 回退到相对导入**，两个分支都要能跑（frozen 下 `ui/core` 是顶层包）。改 import 时别只改一支。
10. **`CTkScrollableFrame` 不会把余高分给子控件**（Step 3 阶段一实测）。它的
    `_fit_frame_dimensions_to_canvas`（`ctk_scrollable_frame.py:250-254`）**只把内框宽度对齐视口，
    高度不设**，内框永远保持「内容自然高」。后果：窗口比内容高时，内框不拉伸 →
    放在里面的 frame 再怎么写 `grid_rowconfigure(..., weight=1)` **都没有余高可吸**。
    最小复现对照：同结构在普通 `CTkFrame` 里 600x300→700 时子控件 240→640（正常吸收）；
    套一层 `CTkScrollableFrame` 后恒为 60→60。
    `home.py` 的修法是新增 `_stretch_scroll_viewport`，给内框的 canvas window item 设 height：
    - `s._set_dimensions(height=...)` **无效**（它只改 canvas 自身的 wanted height，动不了 `_create_window_id` 这个 item）；
      有效的是 `canvas.itemconfigure(s._create_window_id, height=viewport)`（实测 712 → 874）。
    - 触发：`canvas.bind("<Configure>", fit, add="+")` + 启动一次 `after_idle(fit)`。
    - 只在 `viewport >= 内容自然高` 时抬升；内容超出视口时一律不碰，否则会毁掉滚动。
    - 改高度前存 `canvas.yview()[0]`、改完 `yview_moveto` 回位；窗口缩回时内框回落，否则留下「假滚动条」。
    - 版本差异防护：拿不到 `_parent_canvas` / `_create_window_id` 直接 return，退化为原行为。
    - **别再用 `_current_height`**——CTk 6.0.0 没这个属性（本步踩过：fit 每次都在 `except` 里静默返回，
      表现是「改了没反应」，白烧两轮定位）。
11. **`widget.cget("text_color")` 返回的是"配置进去的色对"**（如 `('#4F46E5', '#8B87F5')`），
    不是当前主题解出的单色。想核对「切换主题是否跟随」，先用 `th.C(cget(...))` 解一次再比；
    直接拿 `cget` 和 `PALETTE["accent"][0]` 比会永远不相等（阶段二自检踩过）。
12. **`tools/` 目录对子进程不可写**（`PermissionError: [Errno 13]`，ACL 问题，DSH 的写文件工具不受影响）。
    无头自检脚本要落临时文件（样例 docx 之类）时一律用 `%TEMP%`（AGENTS 已把它指向 `.venv\pip-tmp`）；
    脚本本身仍可放 `tools/`。
13. **`dnd` 不能整体 stub 成空模块**做无头自检：`_build_drop_zone` 会调 `dnd.set_hover_callback`
    （`home.py:378` 附近）等一堆属性，缺一个就是 `AttributeError`。正确做法是 import 真模块后
    只把 `hook` / `unhook` 替换成空实现。
14. **`_drop_from` 是 2 元组 `(边框色对, 底色对)`，不是状态表的行**。阶段三自检第一轮就栽在这里：
    `_paint_frame` 按状态表索引去读 `src[3]`（那是状态表的"底色位"），
    `_drop_from` 只有 2 个元素 → `IndexError: tuple index out of range`。
    想读"起点底色"只有一个正确写法：**`src[1]`**。别再按状态表的 1/2/3 去点。
15. **`pulse` 与 `selected` 不能共用「绿描边 + `DROP_FILL_OK` 绿底」**：两者只剩线宽 1↔3 的差别，
    呼吸时会看起来像"已经选好了"。`PALETTE` 里**没有 `drop_fill_warn`**（橙色只有描边），
    所以 pulse 的底色改用降一档的 `DROP_FILL_ACTIVE`（accent 淡底）+ 绿描边，
    与 selected 的绿淡底彻底分开。四态渲染矩阵必须两两可辨——自检里有这条断言。
16. **相邻面的明度差 <8/255 时人眼分不出来**（本轮实测）。`BG_STRIPE` `#FAFBFC` 落在
    `BG_SURFACE` `#FFFFFF` 上只差 5/255，落在页面底 `#F7F8FA` 上只差 3/255 ——
    无头自检"渲染成功、色值正确、深浅两轮都通过"，但**用户一眼就说"看不出来"**。
    教训：**靠明度差做层次/分隔的方案，写代码前先算两色的十进制差**（或直接换 1px 描边/分隔线）。
    自检能验证"配置对了"，验证不了"看得见"——这类判断必须留给用户手动验收，
    所以本轮返工成本 = 重写 `_render` 的 5 行。
17. **`CTkFrame` 的 `border_width` 只能四边同画**，没有 CSS 那种 `border-bottom`。
    想要"只画下边框"只能用**外层容器 + 1px `th.divider()` 兄弟节点**（见「五」末 ① 的分隔线做法）。
    另外 `CTkFrame` **没有** `pady`/`padx` 构造参数（和 `CTkLabel` 不同，见第 1 条）——
    留白必须靠 `grid()` 的 `padx`/`pady` 或外层容器。**`CTkFrame.place()` 同理不接受
    `width`/`height`**（必须写进构造函数，否则 `ValueError`）。
18. **CTk 控件的 `winfo_class()` 大多报 `Frame`，焦点参数也不在外层**（方案 A 实测）：
    `CTkEntry`/`CTkButton` 都报 `Frame`；`CTkButton` **没有内层按钮**（文字画在
    `_canvas` 上，真实类型 `CTkCanvas`）；对 CTk 外层控件 `configure(takefocus=…)`
    直接 `ValueError`。要找"按钮"必须走 `isinstance(w, ctk.CTkCanvas) and
    isinstance(w.master, ctk.CTkButton)` —— 按 `winfo_class()=="Canvas"` 找会**一个都找不到**
    （全页 186 个 Canvas 类控件里没有一个 `CTkButton`）。
19. **`tk_focusNext(root)` 返回 root 自身**（不是 `None`），而且返回的是 **`Tcl_Obj`**
    （不可哈希，要先 `str()`）。写 Tab 遍历时：① 不能从 root 起步后"没值就停"，
    会首跳即退出得到空链；② 起点本身也算链的一员（页面只有一个焦点控件时，
    不含起点的计数会得 0，误判"链空"）。

---

## 五、剩余待清色值（原 9 处 + 新发现 2 处 = 11 处；**已清 11 处，剩 0 处**）

| # | 位置 | 现值 | 归属步骤 |
|---|---|---|---|
| 1 | `app.py:362` | `fg_color=("#3b82f6", "#2563eb")` 选中态实心块 | Step 2 ✅ 已清 |
| 2 | `app.py:363` | `text_color=("#ffffff", "#ffffff")` | Step 2 ✅ 已清 |
| 3 | `app.py:364` | `hover_color=("#2563eb", "#1d4ed8")` | Step 2 ✅ 已清 |
| 4 | `dialogs.py:81` | `("#c0392b","#ff7b72")` 错误 / `("#1f6feb","#58a6ff")` 信息 | Step 5 ✅ 已清 |
| 5 | `dialogs.py:145` | danger 主按钮 `("#c0392b","#a93226")` + hover | Step 5 ✅ 已清 |
| 6 | `preset_manager.py:142` | 成功绿 `("#1a7f37","#3fb950")` | Step 5 第二轮 ✅ 已清（改 `th.badge(tone="success")`） |
| 7 | `preset_manager.py:155,160` | danger 小按钮 `("#c0392b","#a93226")` + hover | Step 5 第二轮 ✅ 已清（改 `th.text_button(text_color=DANGER, hover_color=DANGER_SOFT)`） |
| 8 | `settings.py:199,367` | 成功绿 / 缺失红（同一组语义色写了两遍） | Step 4 ✅ 已清 |
| 9 | `upload_dialog.py:178` | `("#c0392b","#ff7b72")` | Step 5 第二轮 ✅ 已清（改头部 `icon="✕", tone="danger"`） |
| 10 | `home.py:668` | `text_color=("gray40","gray65")` 文件卡「大小/段落数/修改时间」表头 | Step 5 第二轮 ✅ 已清 → `th.TEXT_SECOND` |
| 11 | `home.py:751` | `text_color=("gray20","gray90")` 日志区标题按钮文字 | Step 5 第二轮 ✅ 已清 → `th.TEXT` |

**Step 5 第一轮实际清掉的（含表外项）**：4、5（`dialogs.py`，其中错误/信息色改由头部 `th.icon_bubble(tone=)` 承担）、`dialogs.py` confirm 明细的 `("gray40","gray65")` → `th.TEXT_SECOND`、`about.py:57` 版本行 `("gray40","gray65")` → `th.TEXT_SECOND`。**另**：`dialogs.py` 3 处裸 `CTkTextbox` → `th.textbox()`（明细框用 `mono=True`），按钮宽 100/90/110 → `th.BTN_W_L`/`th.BTN_W_XL`。

改法：全部换成 `th.badge(..., tone=)` / `th.primary_button(..., danger=True)` / `th.tone_colors(tone)`。
第 10-11 项直接换 token：`("gray40","gray65")` → `th.TEXT_SECOND`（`#5B6572`/`#A5AEB9`），
`("gray20","gray90")` → `th.TEXT`（`#141A21`/`#E9EDF3`）。**11 处至此全部清完。**

**Step 5 第二轮实际清掉的**：6、7、9、10、11（见上表）。**全文复核**（`grep 'gray[0-9]+|#[0-9a-fA-F]{6}'`）：
`desktop/ui/*.py` 只剩 `theme.py`（色源本身）和两处注释里的字样（`home.py:566` 注释、`preset_manager.py` 分隔线方案的说明注释），
代码里 0 处硬编码色值。

> Step 2 实际改法（1-3）：选中态 = 左侧 `th.ACCENT` 竖条（4×24，`place(x=0, rely=0.5, anchor="w")` 贴侧栏最左沿）
> + `th.ACCENT_SOFT` 底 + `th.ACCENT_TEXT` 字；悬停 `th.HOVER_FILL`（选中项 `th.HOVER_FILL_SUB`）。
> `desktop/app.py` 全文现已 0 处 hex / `grayXX`（`grep '#[0-9a-fA-F]{6}|gray[0-9]+'` 无匹配）。
>
> **`home.py` 的拖拽区已全清**（阶段三）：模块级 4 个本地色常量 + `_flash_border` / `_flash_bg`
> 已删，边框与底色全部走 `th.DROP_*`；拖拽区源码段内 0 处 hex / `grayXX`。
> **注意**：第 10-11 项不在拖拽区（文件卡 / 日志区）。阶段三自检里那条源码扫描只覆盖了
> `_build_drop_zone` → `_on_drag_hover` 这一段，所以别把"拖拽区已清"读成"`home.py` 全文已清"——
> 全文仍剩这两处，验收时要单独 grep 全文件而不是只 grep 拖拽区。

### 顺带要处理的旧写法

- `app.py:352-368` `show_page`：选中态「实心蓝块 + 三个硬编码色」整体换成「左侧 4px 强调竖条（`place` 贴左边）+ `ACCENT_SOFT` 淡底 + `ACCENT_TEXT` 加粗文字」。竖条用 `place(x=0, y=.., width=SIDEBAR_ACCENT_W, sticky="ns")`，不参与 grid 布局。
- `home.py:335` 输出目录用 `trace_add` 即时落盘，**这个行为保留**，只换控件外观。
- `dialogs.py:229-234`：`PLACEHOLDER_PREVIEW` / `PLACEHOLDER_PROCESS` / `PLACEHOLDER_UPLOAD`
  三个常量和 `phase3_placeholder()` 函数是 Phase 2 遗留占位。**已核实全项目零引用**
  （`dialogs.py` 内部之外没有任何调用点），是死代码，可以直接删。
- `preset_manager.py:33` `WRITE_BLOCKED_HINT` 里写死了绝对路径 `E:\dsh_plugins\...`，
  且有 5 处调用（`196/209/234/249/277`）。属于文案不是视觉，**不在本次范围**，别顺手改。
- `settings.py:124` 原先直接用 `ctk.CTkSegmentedButton`（主题切换）。**Step 4 已换成 `th.segmented(...)`**，
  并去掉了 `height=32` 覆盖，走工厂默认 `CTRL_H=34`。**不是新引入控件**，只是补配色。
- 色值 6-7（`preset_manager.py`）**Step 5 第二轮已清**（见上表）。
- `settings.py:216` 「测试 API 连接」`width=120` → `th.BTN_W_XL`(110)，顺带 `219` 行的 `88` → `th.BTN_W_L`。
  这就是第一轮清单里点名的"三处 `width=120`"的第 3 处（另两处是 `home.py:373` / `home.py:727`）——
  **旧笔记只写了"三处"没写位置，第二轮差点漏掉，已补全**。全 `desktop/ui/` 再 grep `width=(90|100|120)\b` 只剩
  `about.py:110`「打开程序目录」的 `width=140`（属 Step 5 第一轮范围外，**未动**，待用户决定是否一并收口）。

### Step 4 设置页布局定稿（**用户已验收；改之前先看这一节**）

`settings.py`，层级 = **页 → scroll → 行容器（`_card_row`）→ 列 holder → 卡（`_card`）**：

| 行 | 卡 | 列 | 列数 |
|---|---|---|---|
| 1 | 默认输出目录（`col=0`） + 外观主题（`col=1`） | 半宽并排 | 2 |
| 2 | API 配置 | 全宽 | 1 |
| 3 | 用户预设目录 / Token 用量统计 | 全宽 | 1 |

- **两张半宽卡才用 `uniform="cards"`**：实测 1080 窗口下 holder 399 / 398（等宽成立）。
- **卡片间距**：行容器 `pady=(0, th.SP.L)` = **16px**（12→16 落在这一处）。`th.PAD` 本身**没动**——
  它同时被卡内 8 处内边距引用，改它会把卡内留白一起放大。
- **卡缝 8px、左右外沿 `PAD_L`**：左卡 holder `padx=(PAD_L, PAD_S)`、右卡 `(PAD_S, PAD_L)`，
  这样并排中间只有 8px 缝，不是 40px。
- `_card(master, row, title, col=…, badge=…, span=…)`：**卡在行容器里固定用 `sticky="ew"`**；
  `span` = 卡内字段占的列数，徽章落在其后一列（贴右沿），标题仍可独占前 `span` 列。无徽章时 `span` 忽略。
- **输出卡 / 外观卡是行内行号 0**（不是原来的 1 / 2）；`_build_output_card(master, col=0)` 多一个 `col` 参数。
- **API 卡**：标题徽章在 `col=3`（`span=3`），文案 `已配置`/`未配置齐` + tone `success`/`danger`，
  由 `cfg.env_field_rows()` 的 `present` 全真/有假推导；三字段行保留 `已设置`/`缺失` 徽章在 `col=2`。
  结果框 `th.textbox(mono=True, height=72)` = **恰好 3 行**，`columnspan=3`（卡内仍是 3 列）。
- **徽章运行时刷新**：`th.badge` 返回的是**裸 `CTkLabel`**（`theme.py:399`），可直接 `configure`；
  `_apply_env_state(state, present)` 用 `th.tone_colors(...)` 解出「底色/文字色对」再 configure，
  文案要自己补两侧 EN SPACE（`\u2002`），因为留白是构建时写进 `text` 的。
  实测：`已设置` → `缺失` 时 `fg` 从 `('#E8F7EE','#12301F')` 变 `('#FDECEC','#3A1D1D')`。
- **`settings.py` 全文已 0 处 hex / `grayXX`**（第 8 项已清）。

### Step 5 第一轮定稿（**用户手动验证前先看这一节**）

`dialogs.py` 的 `ModalWindow` 头部改为统一三段式，**行次变了**（子类只碰 `self.body`，不受影响）：

| 行 | 内容 |
|---|---|
| 0 | 头部：`[icon_bubble(36)]` + 标题（`FS.H3` bold）+ 右侧 `✕`（`th.text_button`，`CTRL_H_S` 见方，`TEXT_MUTED` / hover `HOVER_FILL`） |
| 1 | `th.divider()` 1px 分隔线（贴着头部下沿） |
| 2 | `self.body`（`weight=1`，`padx=PAD_L`，`pady=(PAD, PAD)`） |

- **`icon` 不传就不建图标泡**（用户定稿）：表单类弹窗（重命名 / 复制预设）保持素净。签名变为
  `ModalWindow(master, title, size, resizable=False, icon="", tone="accent")`——新参数全在末尾且有默认值，5 个调用点无需改。
- 已给的图标/色调：信息 `ℹ`/`accent`、错误 `✕`/`danger`、确认 `⚠`/`warning`、
  文本窗 `✎`（可编辑）/`👁`（只读）`accent`、表格窗 `📋`/`muted`。
- **坑：`danger` 只能走工厂关键字**。`th.primary_button(...)` 的 `opts.update(kwargs)` 会把
  显式传入的 `fg_color=None` 覆盖掉默认强调色 → 按钮落回 CTk 默认蓝 `#3B8ED0`（与调色板不符）。
  正确写法就是 `th.primary_button(..., danger=danger)`，**不要**再手配 `fg_color`/`hover_color`。
- **`th.text_button` / `small_button` 只有 4 个形参**（`master, text, command, **kwargs`），没有 `danger` 关键字；
  行内危险操作按调用点传 `text_color=th.DANGER, hover_color=th.DANGER_SOFT` 即可（kwargs 透传，已确认可行）。
  Step 5 第二轮清 `preset_manager.py` 的「删除」按钮走这条路。
- `_message` 的行号：说明文字 `row0`、明细框 `row1`(weight=1)、按钮 `row2`；没有明细时
  `after(80, grid_remove + geometry(widthx280))` 的老行为保留。
- 死代码已删：`PLACEHOLDER_PREVIEW/PROCESS/UPLOAD` + `phase3_placeholder()`（全项目零引用，已复核）。
- **验证状态**：无头自检 24/24 绿（含深浅色两轮 × 3 类弹窗的原生 tk `bg` 解析检查、`✕` 按钮存在、
  danger 按钮 `fg_color == PALETTE['danger']`、行次 `[0,1,2]`）；**用户手动四项验收尚未进行**。
- 自检踩的两个坑（下次写自检直接用）：① `CTkFrame` **没有** `grid_propagate_` 属性，判断图标泡要用
  `w.grid_propagate()`（带括号，tkinter 原生 query）；② `confirm` 里的 `wait_window()` 是 `tkwait`，
  **没有 timeout**，事件循环里 `after` 排的销毁回调不会被处理 → 自检必须 monkeypatch 成轮询版顶替，
  否则永久卡住（实测卡死，kill 了两轮）。

### Step 5 第二轮定稿（**用户手动验证前先看这一节**）

**① `preset_manager.py`：表格 → 行卡**（UX 改动，不只是视觉）

| 项 | 定稿 |
|---|---|
| 表头 | **整行删除**。信息改由卡内承担：名称（粗体）· 来源胶囊 · 修改时间（同行，右对齐）；第二行 = 文件信息 + 行内操作 |
| `COLUMNS` 常量 | **保留**（不再画表头），只用于空状态提示的 `columnspan`；`ROW_PAD` 常量已删（改用 `th.SP`） |
| 容器 | `th.scroll(self, page_level=False)` —— 它才把容器底设成 `BG_SURFACE`（纯白）+ `BORDER` 描边 + 调色板滚动条 |
| 分隔方式 | **1px 行内分隔线**（`th.divider()`），挂在**外层 `th.plain`** 上、卡的下方 |
| 行卡 | 外层 `holder = th.plain(self.table)`（`padx=th.SP.S`）→ 卡 `th.card(holder, corner_radius=th.RADIUS_S)`（`pady=(th.SP.XS, 0)`）→ 分隔线 `th.divider(holder).grid(row=1, sticky="ew", pady=(th.SP.S, 0))` |
| 来源徽章 | `th.badge(top, "👤 用户"/"📦 内置", tone="success"/"muted")`（原来是手写绿/gray 色对） |
| 操作按钮 | `th.text_button(..., width=th.BTN_W_S)`；**删除** = `text_color=th.DANGER, hover_color=th.DANGER_SOFT` |
| 页标题 | 裸 `CTkLabel(font(22,"bold"))` → `th.page_title()`（H1=26，与 settings 页同源） |

> ⚠️ **分隔线是第二轮返工后的方案，别再改回斑马纹**：`BG_STRIPE` 浅色 `#FAFBFC` 与卡底
> `BG_SURFACE` `#FFFFFF` 只差 **5/255**（与页面底 `#F7F8FA` 更是只差 3/255）——
> **用户实测"太淡，看不出来"，已确认弃用**。`th.BG_STRIPE` 这个 token 现在全项目零引用
> （定义还在 palette 里，留着不碍事）。改回斑马纹 = 返工。
>
> ⚠️ **为什么分隔线挂外层 plain 而不是卡内**：`CTkFrame` 的 `border_width` 只能四边同画，
> `th.card()` **没有"只画下边框"的能力**；用 `border_width` 画四边会把卡变成方框，与原设计冲突。
> 画在卡内则会被 `RADIUS_S` 圆角截短。外层 plain 的 `padx` 与卡一致，分隔线才与卡左右沿齐平
> （无头自检实测：浅深两轮 div_w == card_w == 993）。
>
> ⚠️ **分隔线在最末一行下面也会画**（每行一条，含最后一行）。这是有意的收尾线；
> 若嫌多余，判据是 `if i < len(self.presets)`。
>
> ⚠️ **表头删除是 UX 决策，用户验收时要重点看**：名称 / 来源 / 时间是否还能一眼区分。
> 若扫读变乱，补救成本很低 —— 在 `_render` 开头加回一行迷你表头（`th.hint` 小字、无背景）即可。

**② `upload_dialog.py` / `preview.py`：跟随新头部**

- `_prompt_open_settings`：`ModalWindow(..., icon="✕", tone="danger")`，**删掉**原来那个裸红 `✕` 标签；
  行次重排为 说明 `row0` / 明细框 `row1`（`th.textbox(mono=True)`，`weight=1`）/ 按钮 `row2`。
- 三个文本框全部走工厂：`_build_source_panel` 的粘贴框、`_prompt_open_settings` 的明细框、
  `UploadDialog` 的 DSL 框（`mono=True`）、日志框（见下）。**注意**：工厂默认带 1px 边框 + `BG_SURFACE_ALT` 底，
  原来这些裸 `CTkTextbox` 是无边框、`gray` 底 —— 这是**有意的外观变更**（与 `dialogs.py` 第一轮同口径）。
- 按钮宽：`90/100/120` → `th.BTN_W_L`(88) / `th.BTN_W_XL`(110)。`_ask_name` 的 88/88 已是 token 值。
- `preview.py`：`PreviewDialog` 传 `icon="👁"`（`tone` 走默认 accent）；三个分段滚动框补
  `border_color=th.BORDER, fg_color=th.BG_SURFACE`（原来只写了 `border_width=1`，描边是 CTk 出厂灰）。

**③ `home.py`：三处 token + 两处按钮宽 + 日志框**

- `668` 文件卡表头 → `th.TEXT_SECOND`；`751` 日志标题 → `th.TEXT`。
- `373` 拖拽区「选择文件」、`727` 「预览效果」：`width=120` → `th.BTN_W_XL`(110)。
  **`731` 主按钮「开始处理」的 `width=140` 保留**（用户拍板 A：主按钮比次级宽，视觉层级更清楚）。
- `759` 日志框：`ctk.CTkTextbox(font=CTkFont("Consolas", LOG_FONT_SIZE))` → `th.textbox(mono=True, height=150)`。
  **口径等价**（`mono_font()` = Consolas，`FS.SMALL == LOG_FONT_SIZE == 12`），字体/字号/高度全不变。

- **验证状态**：三组无头自检全绿 —— 预设页 25 项 ×（浅/深两轮）、弹窗 56 项（3 类 dialogs + prompt +
  SourceDialog + UploadDialog + PreviewDialog 的头部行次与按钮宽）、日志行为 22 项
  （追加 30 行 / `see(end)` 滚到底 / 折叠展开 / 清空后仍可追加 / 深浅两轮内容不丢）。
  **用户一次性手动验收尚未进行**。
- 自检新增的两个坑（下次直接用）：① `wait_window` 定义在 **`tkinter.Misc`**，不是 `CTk` ——
  打补丁要打 `tkinter.Misc.wait_window`，打在 `ctk.CTk` 上无效，`confirm()` 会进嵌套事件循环把自检永久卡死
  （本轮实测踩到，kill 了一次）；② `CTkTextbox` **没有** `_yview`，视口位置用 `yview()`
  （`box._yview()` 直接 `AttributeError`）；③ 断言日志/文本内容时别用
  `get("1.0","end-1c").split("\n")` 数行数 —— 末尾带 `\n` 的缓冲会多出一个空串元素，
  要按"非空行"口径过滤。

---

## 六、改拖拽区时的硬约束（Step 3 最容易踩）

`home.py` 的拖拽区不是普通控件，动它之前必须知道这些：

1. **必须保留 `self.drop_frame` 这个对象本身**，以及 `dnd.hook(self, self._on_drop_files)` 的绑定位置（阶段三后为 `home.py:378`）。`dnd.py` 是按 HWND 逐个接管窗口过程的（`desktop/dnd.py` 顶部有完整说明），换控件 = 重新挂钩 = 拖放可能失效。
2. `canvas = self.drop_frame._canvas`（阶段三后 `home.py:357`）是 customtkinter 的内部画布。边框靠它画：`<Configure>`（`home.py:359`）→ `_redraw_border`（`home.py:610`）→ `_paint_frame`。**边框必须继续用 `_canvas`**，CTk 没有别的绘制面。
3. `_paint_frame`/`_paint_drop_bg` 里刷 `canvas.configure(bg=...)` 走 `th.C(...)`（底层 canvas 不吃色对，只能取单色）。
4. **`_flash_step` 是常驻 `after(220)` 定时器**（`home.py:424`），`_flash_steps` 由 `_take_paths` 置位。收尾必须回到常态外观，不能停在亮帧；阶段三后收尾统一走 `_apply_drop_state()`。
5. **`_track_drop_hover` 是按住期间每 80ms 轮询光标**（`home.py:404`）。任何新增动画都要和它共处，别叠加高频重绘——阶段三的 120ms 过渡只有 4 帧且状态不变时直接 return，不会和它打架。
6. **悬停态靠 `_pointer_over_drop_zone()` 沿 `master` 链上溯判断**（`home.py:411`）。拖拽区内部控件结构变了要复核这个判断还成立。
7. 拖拽区高度：`DROP_ZONE_HEIGHT = 184` 常量与其本地色常量 **阶段三已删**；高度改由 `_left` 的 `grid_rowconfigure(1, minsize=200)` 控制，配色一律走 `th.DROP_*`。`home.py:668` / `home.py:751` 还有两处旧 `("gray40","gray65")` / `("gray20","gray90")`（文件卡与日志区，非拖拽区），留给 Step 3 收尾。
8. `home.py` 里 `import tkinter as tk` 是给 `tk.StringVar` 用的。**注意别再引入叫 `dnd` 的局部变量**，会遮蔽顶层 `dnd` 模块。

### 四态渲染矩阵（**阶段三定稿，用户已验收；改动前先看这张表**）

| 态 | 边框色（浅/深） | 解出单色（浅） | 线宽 | 虚线 gap | 底色（浅/深） | 图标 / 文案 |
|---|---|---|---|---|---|---|
| `idle` | `DROP_BORDER_IDLE` `#C4CBD6`/`#39414D` | `#C4CBD6` | 1 | 7 | `DROP_FILL_IDLE` `#FBFCFD`/`#171B21` | ⬇ 拖拽 .docx 文件到此处 |
| `hover` | `DROP_BORDER_ACTIVE` `#4F46E5`/`#8B87F5` | `#4F46E5` | 3 | 4 | `DROP_FILL_ACTIVE` `#EEF0FE`/`#1B2A45` | 📥 松开即可导入 |
| `pulse` | `DROP_BORDER_OK` `#2FB344`/`#4ADE80` | `#2FB344` | **1 ↔ 3 交替** | 8 | `DROP_FILL_ACTIVE`（同上，**不是**绿底） | 📥 松开即可导入 |
| `selected` | `DROP_BORDER_OK`（同上） | `#2FB344` | **1.5 实线**（`create_rectangle`） | — | `DROP_FILL_OK` `#E9F9EC`/`#14301C` | ✅ 已选择：<文件名> |

四条**别改坏**的约定：

- **`pulse` 与 `selected` 必须靠底色分开**（accent 淡底 vs 绿淡底），不能共用绿底——
  否则呼吸时只剩线宽 1↔3 之差，看起来像"已经选好了"。橙色在本 UI 里是「警告」，
  接收反馈**禁止**用橙色。（`PALETTE` 里也确实没有 `drop_fill_warn`。）
- 四态渲染矩阵必须**两两可辨**；阶段三自检里有一条硬断言，改表时它会红。
- 状态推导只有 `_apply_drop_state()` 一个入口（`home.py:467`），优先级 `pulse` > `hover` > `selected` > `idle`；
  悬停打断脉冲时会清零 `_flash_steps`，避免残留脉冲把态抢回去。
- **过渡只插值颜色**（`home.py:529` `_paint_frame`，4 步 × 30ms，`_drop_seq` 世代号防旧帧回写）；
  文字/图标立刻切。`_drop_from` 是 **2 元组** `(边框色对, 底色对)`，读起点底色用 `src[1]`——
  **不要**按状态表的 7 元组索引去点它（踩过，见「四」第 14 条）。

补充：光标轮询与按钮行提示文案**不在**状态表里——`_track_drop_hover` 每 80ms 喂
`_set_drop_hover()`（`home.py:455`），`_take_paths`（`home.py:627`）负责收尾。

---

## 七、Steps 2-5 待办

### Step 2 · `app.py` 骨架 —— ✅ 已完成（用户手动验证通过）
- [x] 侧栏 `SIDEBAR_WIDTH` 180 → 210（`app.py` 另加 `bar.grid_columnconfigure(0, weight=1)`，否则导航行撑不满 210）
- [x] 导航选中态：左侧强调竖条 + 淡靛蓝底 + 强调色文字（清掉 9 处色值中的 1-3）
- [x] 品牌区改 `▸ 格式助手` + 一行副标题；底部版本卡改小圆角浅底块（副标题文案保留「桌面版外壳」）
- [x] 状态条 30 → `STATUSBAR_HEIGHT=26`，进度条走 `th.progress()`
- [x] `ctk.set_appearance_mode(...)` 之后调 `th.apply_root_theme(self)`（启动 `__init__` + `apply_theme()` 切主题时各一次）
- [ ] **本轮推后（用户确认）**：导航图标改「固定 26px 图标列 + 文字列」的两列网格，解决 emoji 光学宽度参差

### Step 3 · `home.py` 首页 —— ✅ 已通过用户手动验收（阶段一/二/三）
- [x] **阶段一（骨架）**：重排为右主左辅（左：标题+拖拽区+文件卡+日志；右：参数卡封底「预览效果/开始处理」）——用户已跑通确认
- [x] **阶段一**：删掉 `_build_columns` 里旧的 `cols` 容器（它把两张卡一起抬到 `_scroll` 的 col0/row2，是骨架的第一号坑）
- [x] **阶段一**：`_stretch_scroll_viewport`（见「四、踩过的坑」第 10 条）
- [x] **阶段二**：标题区加三节点步骤轨道（`● 拖入文件 ── ○ 选择格式 ── ○ 开始处理`），由真实状态驱动点亮
      （`_build_steps` home.py:143 / `_refresh_steps` home.py:177；绑定点：`__init__` L80、
      `refresh_presets` 两个出口 L572/L587、`_on_preset_change` L618、`load_file` L633、
      `start_process` L758、`_on_process_done` L806、`_on_process_failed` L841）
- [x] **阶段三**：拖拽区四态一体（空闲/悬停/接收/已选），高度 `DROP_ZONE_HEIGHT` 184 → **200**
      （改由 `_left` row1 `minsize=200` 控制，实测 3 种窗口尺寸恒为 200），圆角 `RADIUS_L` → `RADIUS_XL`，
      边框色/底色 120ms `after()` 插值（`_apply_drop_state` → `_start_drop_anim` → `_animate_drop`）
- [x] **阶段三**：删掉本地色常量 + `DROP_ZONE_HEIGHT` + `_flash_border`/`_flash_bg`，全部改用 `th.DROP_*`；
      `_build_drop_zone`(fg_color/RADIUS_XL) / `_set_drop_hover` / `_flash_step`（收尾）三处逻辑已重写，
      `dnd.hook` 绑定位置未动。拖拽区源码段内 0 处 hex 色值
      （**全文仍有 2 处旧 `grayXX`**：`home.py:668` 文件卡表头、`home.py:751` 日志标题，见「五」第 10-11 项）
- [ ] **阶段三**：按钮行随状态变化的提示文案（依赖四态）——**用户本轮未列入范围**
- [ ] 日志区已搬进左列底部（阶段一完成）；标题与侧栏品牌重复的那一行待删
- [ ] Step 3 收尾：`home.py:668` / `home.py:751` 两处旧 `grayXX` 色值（文件卡 / 日志区）

### Step 4 · `settings.py` + `preset_manager.py`
- [x] **设置页布局定稿**：输出 + 外观**两张半宽卡并排**；用户预设 / Token / API 各自**独占全宽**
      （`_card_row` 行容器 + `uniform="cards"`，实测 holder 399/398；卡片间距 16px；卡缝 8px）
- [x] API 那列绿字「已设置」改标题行右侧状态徽章（`th.badge`，`col=3`），三字段状态也改徽章
- [x] 连接结果文本框压到 3 行等宽（`th.textbox(mono=True, height=72)`）
- [x] 清掉色值 8（`settings.py` 全文 0 处 hex / `grayXX`）
- [x] 主题切换改用 `th.segmented(...)`，去掉 `height=32` 覆盖
- [x] **偏差说明**：行内短卡仍**纵向堆叠**在左列（阶段一定稿），不是横向并排；卡内字段顺序未动
- [ ] 预设页：表头+网格 → 斑马纹行卡（`BG_STRIPE`），`[内置]/[用户]` 改胶囊徽章，行内按钮改 `th.text_button`
- [ ] 清掉剩余色值 6-7（`preset_manager.py:142/155/160`）

### Step 5 · `dialogs.py` + `upload_dialog.py` + `preview.py` + `about.py`
**第一轮（本会话已完成，待用户手动验收）**
- [x] `ModalWindow` 头部：`th.icon_bubble`（可选）+ 标题 + 右上 `✕` 图标按钮 + 1px 分隔线；行次改 0/1/2
- [x] 信息 `ℹ`/accent、错误 `✕`/danger、确认 `⚠`/warning 三色图标泡；危险确认主按钮走 `danger=True`
- [x] 明细框统一 `th.textbox(mono=True)`；`text_editor` 文本框也改走工厂
- [x] `dialogs.py` 按钮宽 100/90/110 → `BTN_W_L`(88) / `BTN_W_XL`(110)
- [x] 清掉色值 4、5 + `dialogs.py` 的 `gray40/gray65` + `about.py:57` 版本行
- [x] 死代码 `PLACEHOLDER_*` / `phase3_placeholder()` 已删
- [ ] **用户手动验收**：预览弹窗 / 上传弹窗 / 重命名弹窗（三个都继承 `ModalWindow`）+ 关于页版本行

**第二轮（本会话已完成，待用户一次性手动验收）**
- [x] 预设页：表头+网格 → **行卡 + 1px 行内分隔线**，`[内置]/[用户]` 改胶囊徽章，行内按钮改 `th.text_button`（删除传 `text_color=th.DANGER, hover_color=th.DANGER_SOFT`）
- [x] 预设页：表头整行删除（信息由卡内承担）；容器改走 `th.scroll(page_level=False)` 让条纹落在纯白底上
- [x] 清掉色值 6-7（`preset_manager.py:142/155/160`）
- [x] `upload_dialog.py:178` 红 `✕` → `ModalWindow(icon="✕", tone="danger")`；`_prompt_open_settings` 明细框 `mono=True`；按钮 90/100 → 88/110
- [x] `upload_dialog.py`：粘贴框 / DSL 框改走 `th.textbox`（DSL 框 `mono=True`）
- [x] `preview.py`：`PreviewDialog` 传 `icon="👁"`；footer 100/120 → 88/110；三段滚动框补 `border_color=BORDER`
- [x] `home.py:668` → `th.TEXT_SECOND`、`home.py:751` → `th.TEXT`；`373`/`727` 两处 `width=120` → `BTN_W_XL`（`731` 主按钮 140 保留）；日志框走 `th.textbox(mono=True)`
- [x] 业务回调（`master.after(80, callback)`、`wait_window`、临时目录清理）**一处未动**
- [ ] **用户一次性手动验收**：预设管理页（重点看表头删掉后能否一眼区分名称/来源/时间）+ 上传弹窗 + 预览弹窗 + 处理一次日志（重点看追加 / 滚动 / 折叠 / 清空）

---

## 八、验证方式

**用户手动跑（每完成一页跑一次，不要跳步）**

```powershell
cd E:\dsh_plugins\word-format-applier
.venv\Scripts\python.exe desktop\app.py
```

检查项：拖拽 / 选文件 / 处理 / 预览 / 上传 / 设置 / 切换深浅色 / 关闭窗口（`on_close` 走 `dnd.unhook()`，别留幽灵回调）。

**本会话不许起 GUI 自动化**（用户明确要求）。

**低成本无头自检**（Step 1 用过，可复用）：把临时脚本置 `sys.path` 到 `desktop/`，stub 掉 `dnd` 模块（`hook` 返回 True、`unhook` 空实现），构造 `FormatApp` 后 `withdraw()`，遍历控件树核对色值是否都在 `th.PALETTE` 里。注意坑 6（CTk 控件不能在 withdraw 的根窗口下构造，采集基线要另开屏幕外窗口）。**验证完删掉临时脚本**，别留在 `tools/`。

> **Step 5 第二轮的实际做法（比上面更省事，建议沿用）**：
> ① 脚本落到 `.venv\pip-tmp\`（`tools/` 对子进程不可写，见「四」12 条），跑完即删；
> ② **不构造完整 `FormatApp`** —— 用一个 30 行的 `FakeApp(ctk.CTk)`（只给 `settings.log_expanded` / `log` /
> `status` / `set_presets` / `show_page`）+ 屏幕外 `geometry("+3000+3000")`，就能直接实例化
> `PresetManagerPage` / `SourceDialog` / `UploadDialog` / `PreviewDialog`，也能用
> `HomePage.__new__(HomePage)` 绕开 `__init__` 单测 `_build_log` / `append_log` 这类方法；
> ③ 弹窗自检必须 `tkinter.Misc.wait_window = lambda *a, **k: None`（**不是** `ctk.CTk`，见「五」末 ①）；
> ④ 断言前先 `root.update_idletasks()`；深浅色两轮用 `ctk.set_appearance_mode` + `th.apply_root_theme`。
> 本轮三组脚本共 103 项断言（预设页 25 / 弹窗 56 / 日志 22），全绿。

**已知可接受的偏差**：`fg_color="transparent"` 会被解析成父级底色（`gray92`/`gray17` 等），遍历时看到这些值是正常的，不是残留。

**`--selftest` 的三个环境坑（2026-10-08 第三轮实测，都不是回归、不是代码问题）**

1. **弹窗步骤偶发卡住**：`step_dialogs` 靠"后台线程睡 0.6s 后 `event_generate("<Escape>")`"
   关模态框，是**时序竞争** —— 弹窗构造慢于 0.6s 时 ESC 在 `wait_window` 之前就被吃掉，
   之后只能等 60s 兜底（`finish(1)` → `SELFTEST_FAIL`，结果里停在 `file:` 那行）。
   实测 **`WFA_PAGE_MASK=1` 与 `=0` 两轮都失败**，故与遮罩改动无关。
   要稳定跑通就先给足构造时间（把 `schedule_escape` 的 delay 调大），或只信 `nav *: OK` 那几行。
2. `finish()` 用 `print` 打含 emoji 的结果行 → 在 GBK 控制台 / 重定向下
   `UnicodeEncodeError: 'gbk' codec can't encode '\U0001f464'`，异常抛出在 Tk 回调里，
   mainloop 继续跑 → 看起来像"卡死"。跑时加 `$env:PYTHONIOENCODING="utf-8"` 并重定向到文件。
3. `user preset save: FAIL PermissionError [Errno 13]` 是 **DSH 会话特有的环境限制**：
   python 子进程写 `%APPDATA%\WordFormatAssistant\presets` 被拒（同一路径 PowerShell 可写，
   已对照测过）—— **用户在真机跑 `desktop\app.py` 时正常**，与界面改动无关。
   同一条限制还让 `destroy()` 后多印一行 `can't open file for write !`。

---

## 九、上下文预算

Step 1 用掉约 70k（其中方案阶段占近半）。Steps 2-5 各自独立，**建议一步一会话**：新会话只读本文件的相关小节 + 目标文件的相关段落，不要整文件重读。

`desktop/ui/` 各文件实际行数（别信旧文档里的数字；下表 2026-10-07 用 Python 逐文件复核，
口径 = `bytes.count(b"\n")`，含空行）：

```
theme.py 697   home.py 1117  settings.py 534   preview.py 432
upload_dialog.py 373   preset_manager.py 334   dialogs.py 229   about.py 141
app.py 738
```

> **Step 5 第二轮后复核**（2026-10-08，同口径）：`home.py` 1118 → **1117**（净 -1：日志框 3 行并 1 行）、
> `preview.py` 428 → **432**（+4：三段滚动框各拆一行 + 头部多一行参数）、`upload_dialog.py` 377 → **373**（-4）、
> `preset_manager.py` 336 → **334**（表头循环删掉、行卡结构重写）、`dialogs.py` 240 → **229**（第一轮删死代码）。
> `settings.py` 534 未变（本轮只改一行按钮宽）。

> 更正：`theme.py` 旧记 520 行是抄了它自己文件头的注释、没复核（实际 697）；
> `settings.py` 旧记 479，Step 4 后为 534。其余各项复核后无误。
> **别用 `Get-Content | Measure-Object -Line` 数行数**——它按非空行口径给值（`theme.py` 会得到 520、
> `settings.py` 450），和上表对不上。
>
> ⚠️ **`home.py` 的行号引用有漂移**（2026-10-07 抽查）：Stage 3/「六」里写的 `home.py:143`
> （`_build_steps`）实际在 **228**，`_build_drop_zone` 实际在 **345**；`dnd.hook` 那条 `home.py:378`
> 是对的。**按旧行号定点读之前先 grep 复核**，别直接 `read(offset=143)`。
> `app.py` 的行号（`__init__` 191 / `show_page` 380）抽查无误。
>
> **方案 A 之后的行数**（2026-10-08）：`app.py` 738 → **858**（+120：焦点治理 + `on_shown` 钩子 +
> 注释），`home.py` 1117 → **1145**（+28：`_fit_scroll_viewport` 抽方法 + `on_shown`）。
> `show_page` 现在在 **app.py:429** 附近（旧记 380 已漂移），`_build_pages` 在 **334**。

---

## 十、切页卡顿（方案 A：4 页常驻 + tkraise）

**症状**：切页时新页面像"没加载完"，widget 一块一块冒出来。

**根因（实测，2026-10-08）**：`show_page` 原本对 4 页做 `grid_remove()`/`grid()`。
Tk 每做一次 unmap→map，子树里**每个 widget 都要重跑一遍默认值配置**（约 20 个选项），
CTk 的 canvas 还要全量重绘。代价 **~190ms/次**，且**与切到哪一页无关** ——
同一页反复 `grid_remove()`/`grid()` 也是 209/183/180/196ms。

分解（presets，176 个控件）：`grid()` 调用 0.0ms → `update_idletasks()` 几何传播 137ms →
`update()` 画像素 47~151ms。对照：同样 176 控件的纯 `tk.Label` 96ms vs `CTkLabel` **360ms**。

`show_page` 自身只有 6~30ms（改导航样式 8.5ms + grid 0.0ms），**它不是瓶颈**。

**改法**：
1. `_build_pages`：4 页 `grid(row=0, column=0, sticky="nsew")` 到**同一格**，不再 `grid_remove()`。
2. `show_page`：`self.pages[key].tkraise()` + 原导航样式 + `status` + `current_key`（全部保留）。
3. 新增 `on_shown()` **可选钩子**：`show_page` 用 `getattr(page, "on_shown", None)` 探测，
   页面没实现就跳过。home 用它补算滚动视口拉伸。

效果：**~190ms → ~30ms**（8 次连测 46~69ms，含 `update()`）。

### 四条必须记住的实证结论（改这块之前先读）

1. **`tkraise()` 不动几何** → 不触发 unmap/map，所以快。这是整个方案的全部依据。
   前提也验证过：`tkraise` 确实改变 Z 序（`winfo_containing` 取点实测命中新顶层）。
2. **未映射的控件 Tk 会自动跳过** —— 所以旧方案（`grid_remove`）本来**没有** Tab 穿透问题。
   这是常驻映射方案必须付的税。
3. **常驻映射后，被压在下层的页面里的 `Entry` 会被 Tab 到**（实测：两页都 mapped 时，
   `tk_focusNext` 两个 Entry 都会走到）。必须治理。
4. **`CTkButton` 默认不在 Tab 链里**（它没有内层按钮，文字画在 canvas 上）。
   要 `takefocus=1` 设到 **`CTkButton._canvas`（真实类型 `CTkCanvas`）** 上才会进链。

### 焦点治理实现要点（`app.py`）

- `_collect_focus_targets(key, page)`：构建期扫一次，缓存两类目标 ——
  `_page_inputs`（`Entry`/`Text`/`TCombobox`）与 `_page_buttons`（CTk 按钮的 `CTkCanvas`）。
  **不能按 `winfo_class()` 找按钮**：全页 186 个 Canvas 类控件里 182 个是 `CTkCanvas`、
  4 个是普通 `Canvas`，且**没有一个 `Canvas` 是 `CTkButton`**（按钮本体是 `Frame`）——
  照 `winfo_class()=="Canvas"` 找按钮会一个都找不到（踩过）。判据必须是
  `isinstance(w, ctk.CTkCanvas) and isinstance(w.master, ctk.CTkButton)`。
- `_sync_page_focus(key)`：非当前页的输入控件与按钮 canvas 一律 `takefocus=0`；
  当前页的**按钮 canvas** 设 `takefocus=1`（输入控件保持默认 `''`，Tk 本来就会遍历到）。
  实测每页 Tab 链只含当前页（home 81 个 / presets 22 / settings 81 / about 1）。
- 焦点回收：切页后若焦点不在目标页，`focus_first_on_page()` 依次尝试
  输入控件 → 按钮 canvas → 主窗口。
- **`_focus_dirty` 置脏重扫**：预设页的行按钮是 `reload()` 里运行时重建的，
  构建期缓存会漏掉新按钮（实测 22 个只进 21 个）。`reload_presets()` 里
  `self._focus_dirty.add("presets")`，下次 `show_page` 重扫。

### `home.on_shown` 与视口拉伸

- `_stretch_scroll_viewport` 的重算逻辑抽成 `_fit_scroll_viewport()`（**唯一实现**），
  `<Configure>` 与 `on_shown` 共用，不要再写成两份。
- guard 用 `winfo_ismapped()` 而非更严的"可见性"判断：实测**叠在下层的 home 照样收到
  `<Configure>`**（Tk 几何传播跟的是 map 状态），所以窗口在别的页面上被改高时日志区照样跟随；
  用 `winfo_viewable()` 之类反而会误伤。
- `on_shown()` 必须把 `_stretched_h` **清零**：它不是"已拉伸高度"而是"上次写进 item 的值"，
  不清零的话视口没变时 `_fit_scroll_viewport` 会直接 return，补算落空。
- 实测：启动 874/日志 312 → 直接加高到 412 → 切走改矮后切回 **232**（补算生效），
  且 item 高始终 == 视口高（不留假滚动条）。

### 副作用核查（本轮已测）

- **内存**：反复切页 6 轮，Python 侧增长 31KB（`tracemalloc`），**无明显上升**。
- **其他 `<Configure>` 依赖**：全项目只有 home 两处（`_stretch_scroll_viewport`、
  `_redraw_border`），没有第三处受影响的页面。
- **未验证**：真实拖拽 .docx、真实处理流程（留用户手动验收）。

### 「两页混合几帧」的修复（2026-10-08 第二轮，方案 A 的补丁）

用户复验后报「切页仍有两页混合几帧」。两个独立原因，都已修：

1. **页面外框是 `fg_color="transparent"`**（`home/preset_manager/settings/about` 四处
   `super().__init__`）。4 页同格叠放后彼此之间**没有不透明层** → 上层页面没绘制到的
   地方，下层页面的像素直接透出来 = 观感上"两页混合"。**这是主因，与重绘时序无关。**
   改法：四处一律 `fg_color=th.BG_PAGE`（父容器同色，视觉不变，但每页自遮）。
   ⚠️ 将来新增页面必须照做，透明页底在 tkraise 叠放下必然串页。
2. **`show_page` 里没有任何 update**（原本 427-456 行只有 tkraise + configure + status）。
   `tkraise` 只改 Z 序，像素重绘延后 → 实测 `show_page` 返回后还挂 44~53ms 绘制。
   改法：`tkraise()` 之后、导航样式之前加 `self.update()`（同步刷一次）。

**可选的整页重绘开关**：`app.py` 顶部 `_FULL_REPAINT_ON_SWITCH`（读环境变量
`WFA_PAGE_FULL_REPAINT=1`，**默认关**）。开了会对被提起的页面
`event_generate("<Expose>")` 强制整页重绘，消除"新页只画一角"的中间态，
**但 `show_page` 从 ~17ms 变 ~86ms**（那 86ms 就是整页重绘本身，原来以 ~50ms/帧
散在返回之后）。默认关是为了不引入新的同步阻塞；需要终极原子性时再开。

**实测（屏幕外窗口，取点校验 `winfo_containing` 命中页 == 当前页，4/4 正确）**：
`show_page` 均 ~68ms（不透明页底 + 同步 update 的代价，原来 ~30ms）。
⚠️ **屏幕外测量无法判定"是否还混合"** —— expose 消息不投递，`update()` 处理的是
Tk 侧积压（连续两次 update：第一次 48ms、第二次 0.01ms，可用来量残留）。
最终观感必须由用户肉眼判定，别再拿离屏数字下结论。

### 方案 C · 切页过渡遮罩（2026-10-08 第三轮；**第一版按"官方顺序"写=完全无效，已修正，用户肉验通过 → 定稿**）

方案 A + 不透明页底 + 同步 `update()` 之后**仍有混合帧**。已排除的：4 页常驻、
`self.update()`、页底 `transparent → BG_PAGE`、`WFA_PAGE_FULL_REPAINT=1`（默认关）。
结论：Windows 上 Tk 的重绘分帧提交，`update()` 保证不了"旧页像素/新页像素"同帧上屏。
剩下的路只有遮罩。

实现（`app.py`，**第一版照"place → lift → update_idletasks → tkraise"写，实测无效**，
下面是修正后的顺序）：
1. `__init__` 里 `_build_pages()` **之后**建 `self._mask = ctk.CTkFrame(self.content,
   corner_radius=0, fg_color=th.BG_PAGE)`，初始不 place。
2. `show_page` 顺序：`mask.place(...)` → `mask.lift()` → **`self.update()`** → `pages[key].tkraise()`
   → **`self._mask.lift()` 再来一次** → 原导航样式 / `current_key` / `on_shown` /
   `_sync_page_focus` / `status` → `self.update()`（新页在遮罩底下画完）→ `mask.place_forget()`
   → `self.update()`（把"撤遮罩后暴露整块内容区"的那次补绘收进本次调用）。**不加 `after` 延迟**。
3. `self.mask_hold_ms`（在屏时长）/ `self.mask_ms`（方法总阻塞）；`WFA_PAGE_TRACE=1`
   每次切页往 stdout 打一行。
4. 开关：`WFA_PAGE_MASK=0` 退回"直接换页"的老行为（无遮罩、无纯色闪、每次少 ~26ms），
   用于 A/B 对比观感。

### ⚠️ 两个坑（第一版就是这么废掉的，别再犯）

1. **`update_idletasks()` 画不出遮罩**。CTkFrame 的底色是它内层 canvas 在**自己的 WM_PAINT**
   里画的，WM_PAINT 是 **window 事件**；`update_idletasks()` 只抽 idle 队列。实测此时
   遮罩 `winfo_ismapped()==1`、`winfo_viewable()==1`、尺寸 870x694 全对，但**屏幕上一个像素都没有**
   （抓帧与旧页逐像素 diff = 0.000）。必须是 `update()`。
2. **`tkraise()` 会把新页提到遮罩之上**（两者都是 `content` 的兄弟）。只在 tkraise **之前**
   `lift()` 一次 = 遮罩被压回去，屏幕上完全看不到。tkraise 之后必须**再 `lift()` 一次**。

### 抓真实屏幕帧的验证（B 轮 8 次切页，钩在 `show_page` 内每次 `update()` 之后抓帧）

```
切到 settings  帧序: 遮罩 → 遮罩 → 设置页 → 设置页
切到 presets   帧序: 遮罩 → 遮罩 → 预设页 → 预设页
切到 about     帧序: 遮罩 → 遮罩 → 关于页 → 关于页   （整块到位，无鬼影）
切到 home      帧序: 遮罩 → 遮罩 → 首页   → 首页
```

修好之后**没有混合帧**：遮罩在屏期间内容区 std=0.00（纯色），撤掉后新页一次到位。

### 成本（1080x720、窗口在屏幕上、A/B 各 8 次；`update` 钩子量每次 update 的耗时）

| 轮 | 遮罩在屏 | 方法总阻塞 | 内部三次 update（遮罩 / 新页 / 撤遮罩后） |
|---|---|---|---|
| A 无遮罩（占位对象吃掉 place/lift） | — | avg **159.5** ms | 1 / 188 / 0 → 收尾那次 ≈0 |
| B 有遮罩 | avg **128.3** ms | avg **185.2** ms | 3~23 / 75~116 / 16~98 |

→ 遮罩比不遮**贵 ~26ms/次**（185 vs 160）：内容区被画了两遍（新页在遮罩底下画一次、
撤遮罩后再补一次，B 的第三次 update 就是那 ~16~98ms）。观感上混合帧换成 **~130ms 纯色**
（旧页 → 一块 BG_PAGE → 新页）。要压掉这 26ms 只剩"遮罩改成独立 CTkToplevel"一条路
（不同顶层不互相裁剪 → 新页只画一遍），代价是多一个置顶窗口、有焦点/层级风险，**未做**。

> A 轮基线 160ms（在屏测量）比「十」开头记的 ~30ms 大得多 —— 那个 30ms 是**离屏**测的，
> 离屏不投递 expose，`update()` 几乎不干活，两个数字不可比。

### 未做（方案 B，独立会话）

启动期 `app.__init__` **~3.7~4.0s 阻塞主线程**（窗口这期间没上屏）：
页面构造合计 2.48s，其中 `presets.reload` **971ms**（内部 3 次 `subprocess.run`，
每次 ~375ms）、`settings._build_api_card` 183ms、`home._build_log` 168ms、
`presets._render` 130ms。修法是页面懒构建 / 把子进程挪出主线程。
