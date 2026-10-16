# 推 GitHub 前的检查清单

> 面向本仓库（`word-format-applier`）的一次性收尾流程。
> 核心原则：**先确认没有敏感文件，再 commit；宁可多看一眼 `git status`。**

---

## 一、推送前必须确认的三件事

### 1. `.gitignore` 已覆盖敏感文件

仓库根 `.gitignore` 里应当包含下列条目（缺一不可）：

| 必须忽略 | 内容 | 为什么 |
| --- | --- | --- |
| `.env` / `desktop/.env` | **明文 API 密钥** | 泄露即被盗刷 |
| `desktop/config.json` | 本机绝对路径、上次用的预设 | 隐私 + 噪音 |
| `.venv/` | 85 MB 的虚拟环境 | 不该进仓库 |
| `dist/`、`desktop/dist/` | 75 MB 打包产物 | 体积；exe 走 Release |
| `build/`、`desktop/build/` | PyInstaller 中间产物 | 体积 |
| `__pycache__/` | 字节码缓存 | 噪音 |
| `presets/.cache/` | 解析缓存，可重建 | 噪音 |
| `desktop.bak_*/`、`*.fullbak_*/`、`wfa-gui-*/` | 本地备份/临时目录 | 体积 |
| `samples/*.report.json`、`samples/测试输出*` | 跑批残渣 | 噪音 |
| `_acl-recovery/*.json`、`*.jsonl`、`*.acl.txt` | 扫描快照（MB 级） | 体积 |
| `sessions/` | 会话记录 | 隐私 |

自查命令：

```powershell
Get-Content .gitignore
```

### 2. `git init` 之后，**先 `git status` 逐项检查**

```powershell
git init
git status --short
```

**看到下列任何一项就停下，不要 add：**

* `.env`、`desktop/.env`（密钥）
* `.venv/`、`venv/`
* `dist/`、`desktop/dist/`、`build/`、`desktop/build/`
* `desktop/config.json`
* 任何 `*.fullbak_*` / `desktop.bak_*`

若确实被列出来了，说明 `.gitignore` 没生效或路径写错：先修 `.gitignore`，
再 `git status` 复检；已经 `git add` 过的话用 `git rm --cached <path>` 撤出暂存区
（**不是** `git rm`）。

### 3. 再看一眼「将要提交的总字节数」

```powershell
git add -A
git status --short
git count-objects -vH     # 或看 git status 的文件数是否离谱
```

预期规模：**几百个文件、几 MB 级别**（`src/` 0.4 MB + `desktop/*.py` + `presets/` 0.1 MB
+ `samples/` 0.1 MB + `screenshots/` 0.4 MB）。
如果动辄上万文件 / 上百 MB，几乎肯定是 `.venv` 或 `dist` 混进来了。

---

## 二、首次提交建议命令序列

```powershell
# 0. 进仓库根
cd E:\dsh_plugins\word-format-applier

# 1. 初始化（默认分支名用 main，与 GitHub 一致）
git init -b main

# 2. 检查：这一步是安全闸，看到 .env / .venv / dist 就停
git status --short

# 3. 配置身份（首次用 git 才需要）
git config user.name  "zhangmeng"
git config user.email "你的邮箱@example.com"

# 4. 暂存全部
git add -A

# 5. 再检查一次暂存区：确认没有敏感文件
git status --short
git diff --cached --stat | Select-Object -Last 5

# 6. 提交
git commit -m "chore: 整理为桌面版仓库（移除 DSH 插件形态）

- 删除 plugin/、cordis.patch.yml、package.json、docs/harness-plugin-api.md
- 清理 build/、desktop.bak_20261007/、sessions/、ACL 快照等本地产物
- 补 LICENSE (MIT) 与桌面版 README"

# 7. 关联远程（先在 GitHub 上建好空仓库，见第三节）
git remote add origin https://github.com/<你的账号>/word-format-applier.git

# 8. 首次推送并建立上游跟踪
git push -u origin main
```

> 推送前如果提示要登录：用 Personal Access Token 或 `gh auth login`，
> 不要把 token 写进 remote URL 后提交任何配置。

---

## 三、建远程仓库：从 Private 起步

在 GitHub 网页端 **New repository**：

| 选项 | 选择 | 理由 |
| --- | --- | --- |
| Repository name | `word-format-applier` | 与本地一致 |
| Visibility | **Private**（起步） | 给自己留一个「历史里混进密钥」的悔棋机会 |
| Initialize with README | **不勾** | 本地已有内容，勾了会冲突 |
| Add .gitignore / license | **不勾** | 本地已有 |

Private 期间可以放心反复 `push --force` 修历史；等确认干净了再切 Public。

---

## 四、之后若要转 Public：先确认历史里没有敏感文件

`git status` 只看**当前**工作区，看不到历史。以前提交过的 `.env`
会永远留在 commit 里，之后即使删掉文件也照样能被翻出来。

排查：

```powershell
# 历史里是否出现过敏感路径
git log --all --name-only --pretty=format: | Sort-Object -Unique | Select-String -Pattern '\.env$|config\.json$|\.venv/|/dist/|fullbak'

# 历史里是否有疑似密钥的字符串
git grep -n -I -E 'sk-[A-Za-z0-9]{16,}|OPENAI_API_KEY\s*=\s*sk-' $(git rev-list --all) -- 2>$null
```

* **从未提交过** → 直接切 Public 即可。
* **提交过** → 不要只在新 commit 里删文件。要么用 `git filter-repo` 重写历史
  （或干脆删库重建，把这个仓库当新仓库推），要么**直接注销并更换那批 API 密钥**
  ——已被推上云端的密钥一律视为已泄露。

确认干净后再：GitHub → Settings → General → Danger Zone → Change visibility → Public。

---

## 五、发布 exe：走 Release 附件，不进 commit

`desktop/dist/Word格式助手/` 有 75 MB，提交进仓库会让 clone 变得极慢，
而且 Git 对二进制不做增量存储（每次重打包都再存一份完整副本）。

正确做法：

1. 本地打包：`cd desktop` → `build.bat`，产物在 `desktop\dist\Word格式助手\`；
2. 把**整个文件夹压成 zip**，例如 `Word格式助手-v0.1.0-win64.zip`；
3. GitHub 仓库页 → **Releases** → *Draft a new release*；
4. Tag 填 `v0.1.0`，标题写版本号，把 zip **拖进附件区**（Assets）；
5. 发布。仓库本身只存源码，`.gitignore` 里的 `desktop/dist/` 保证它永远不会被误提交。

> 发布前建议顺手在 Release 说明里写一句：本程序不联网上传文档，
> 杀软误报属 PyInstaller 常态，请把整个文件夹加入信任区。
> 并附上 `SHA256`，方便用户校验。

---

## 六、一页速查

```powershell
git init -b main
git status --short          # ← 看到 .env / .venv / dist 就停
git add -A
git status --short          # ← 再确认一次
git commit -m "..."
git remote add origin <私有仓库地址>
git push -u origin main
```

**三条铁律**

1. `.env`、`config.json`、`dist/`、`build/`、`.venv/` 一个都不能进 commit。
2. 远程仓库 **Private 起步**，确认历史干净后再公开。
3. exe 走 **Release 附件**，仓库只放源码。
