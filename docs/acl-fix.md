# 工作区 ACL 归一修复记录（Phase 2 前的环境治理）

日期：2026-10-05
范围：`E:\dsh_plugins\word-format-applier\` 全树（仅改 ACL，未改任何文件内容）
执行者：`HUANWEI\zhangmeng`（非提权 token，Medium 完整性）

---

## 一、问题现象

1. Phase 0：工作区根目录命令启动失败。
2. Phase 1.5：`desktop\parser\` 缺 `WRITE_OWNER`，沙箱命令启动失败；报错点落在
   `SetNamedSecurityInfoW` 触发路径。

## 二、根因假设（已由扫描证实）

沙箱在部分目录上**显式写入**了自己的安全标记，且这些标记带 `(OI)(CI)` 会向下继承：

| 标记 | 含义 | 影响 |
| --- | --- | --- |
| `S-1-4-966191722-319427645` | 沙箱受限 SID，`(OI)(CI)(W,D,DC)` | 覆盖 6245 项 |
| `S-1-4-600891134-409881891` | 沙箱受限 SID（另一策略令牌） | `desktop\parser` 及其 5 个子项 |
| `Everyone:(CI)(DENY)(DC)` | 拒绝所有人写 DACL | 使 `SetNamedSecurityInfoW` 失败 |
| `Mandatory Label\Low Mandatory Level` | 低完整性标签 | 与 `DENY(DC)` 叠加，进一步阻断 ACL 写入 |

关键机制（本次实测确认）：

- **子对象的 DACL 约定会被父目录的可继承 ACE 覆盖**。只修父目录不动子项时，子项 ACL 不会自动
  重算；反之，对子项写入的自定义 DACL 也会被父目录的可继承 ACE 重新派生覆盖。因此必须逐项显式写。
- **对象上的显式 ACE 一旦被清掉，PowerShell 的 `SetAccessControl()` 会报"尝试执行未经授权的操作"**，
  而同样权限下 `icacls.exe` 可以成功 —— 这是本次选择 icacls 而非 .NET API 的直接原因。
  （两者请求的访问掩码不同；`icacls` 在 owner 已知时可用更小掩码打开对象。）
- **只写 Owner 段会失败**，必须与 Access 段一起写。

## 三、做了什么（关键动作）

1. **扫描**（只读，icacls / Get-Acl）：6399 项，异常类型分布
   `SANDBOX_SID=6245  MISSING_WRITE_OWNER=6362  MISSING_WRITE_DAC=6362  NO_FULL_CONTROL_ACE=6362  INHERITANCE_BLOCKED=12  OWNER_NOT_ME=8`
2. **备份**：全树 SDDL + Owner 落 JSON，另用 `icacls /save` 落一份可被 `/restore` 消费的 ACL 备份。
3. **归一**（`icacls-normalize.ps1`，逐项 5 步）：
   1. `icacls <path> /grant:r *<mySid>:(OI)(CI)F`（先给自己完全控制，后续步骤才有权限）
   2. `/remove:g *S-1-4-966191722-319427645 *S-1-4-600891134-409881891`
   3. `/remove:d Everyone`
   4. `/inheritance:e`（恢复继承）
   5. owner 非本人时 `/setowner`
   根目录的 DACL 另行用手工构造的 SDDL 一次性写正（保留 SYSTEM / Administrators）。
4. **清理**：删除 12 个空的 pip 残留临时目录（`pip-install-*`、`pip-build-tracker-*`、
   `pip-ephem-wheel-cache-*`，均继承断开且无当前用户 ACE）。

## 四、结果

- 全树 6391 项：**沙箱 SID / Everyone DENY = 0**，DACL 继承全部开启。
- 8 个例外：`samples\测试输出{,2,3,4}.docx` 及其 `.report.json`，owner 为
  `BUILTIN\Administrators`、DACL 为 `D:P`。本 token 中 Administrators 是 **deny-only**
  且无 `SeTakeOwnershipPrivilege`（`takeown /f` 明确报 "does not have ownership privileges"），
  `Authenticated Users:(M)` 只给到 Modify，因此 `WRITE_DAC` 被拒。**需提权修复**，未擅自提权。

  提权后一行修复（管理员 PowerShell）：

  ```powershell
  icacls "E:\dsh_plugins\word-format-applier\samples" /reset /T /C /Q
  ```

## 五、备份与回滚

| 产物 | 路径 |
| --- | --- |
| 修复前 ACL（JSON，6368 项） | `_acl-recovery\pre-fix-20261005-215848.json` |
| 修复前 ACL（icacls /save，含完整性标签） | `_acl-recovery\pre-fix-20261005-215848.acl.txt` |
| 回滚脚本 | `_acl-recovery\restore-20261005-215848.ps1` |

回滚（一行）：

```powershell
powershell -ExecutionPolicy Bypass -File "E:\dsh_plugins\word-format-applier\_acl-recovery\restore-20261005-215848.ps1"
```

> 注：回滚脚本恢复 Owner + DACL。完整性标签（SACL）需管理员执行
> `icacls "E:\dsh_plugins\word-format-applier" /restore "...\pre-fix-20261005-215848.acl.txt" /C`。

## 六、如何避免复发

1. **沙箱会重新施加标记**：改沙箱文件策略、或用受限令牌跑命令，都可能再次在目录上写入
   `S-1-4-*` / `Everyone:(DENY)(DC)` / 低完整性标签。出现"命令启动失败 / Access is denied"时，
   先跑体检，再跑归一，不要手工补单条权限。
2. **新建目录后立刻体检**：
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\_acl-recovery\acl-health.ps1
   ```
   输出 `RESULT: NEEDS_FIX` 时跑：
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\_acl-recovery\icacls-normalize.ps1
   ```
3. **不要在别的工具/沙箱里改本树权限**。树上的 `D:P`（继承断开）多半来自 pip 的
   `SetNamedSecurityInfoW`，只要树本身健康，pip 建出来的临时目录就不会反过来卡住自己。
4. **本机 `%TEMP%` 不可写**（Phase 1.5 已确认）。任何 pip / 构建调用前先重定向：
   ```powershell
   $env:TEMP = "E:\dsh_plugins\word-format-applier\.venv\pip-tmp"
   $env:TMP  = $env:TEMP
   ```
   该目录已创建并归一（含继承的当前用户完全控制）。
5. **执行策略**：本机 `CurrentUser=RemoteSigned`，未签名 .ps1 会拒绝执行。运行脚本请用
   `powershell -ExecutionPolicy Bypass -File <script>`，或用
   `& ([scriptblock]::Create((Get-Content <script> -Raw)))`，**不要改系统执行策略**。

## 七、工具脚本一览（均在 `_acl-recovery\`）

| 脚本 | 作用 |
| --- | --- |
| `acl-heal.ps1` | **自愈入口**：只扫 `-Check`（别名 `-c`）/ 直接跑则修复。幂等，跳过那 8 个需提权文件 |
| `acl-health.ps1` | 只读体检，列出不健康项与类型 |
| `icacls-normalize.ps1` | 逐项归一（幂等，已健康的项自动跳过） |
| `scan-acl.ps1` / `summarize-scan.ps1` | 全树 ACL 扫描与摘要 |
| `backup-acl.ps1` | 备份 ACL 并生成回滚脚本 |
| `verify-acl.ps1` | 验证清单（18 项） |

### 新会话自检（推荐固化到 AGENTS.md）

```powershell
# 先扫（只读）
powershell -ExecutionPolicy Bypass -File .\_acl-recovery\acl-heal.ps1 -Check
# 有 needFix 再修
powershell -ExecutionPolicy Bypass -File .\_acl-recovery\acl-heal.ps1
```

输出固定三行关键信息：`scanned / needFix / skippedElevation`、`fixed / failed / unhealthyAfter`、
`RESULT: ...`。判断口径：

- `RESULT: HEALTHY` 或 `nothing to fix (already healthy)` → 无需动作。
- `RESULT: NEEDS_FIX (N items)`（退出码 1）→ 跑修复模式。
- `RESULT: PARTIAL fixed=x failed=y`（退出码 1）→ 看 `FAIL [step] <path>`；若是 `samples\` 下那 8 个
  文件，属预期（需提权），其余情况才是新问题。

> AGENTS.md 里写成 `--check`：PowerShell 需要单横线，用 `-Check` 或别名 `-c`。
> 本脚本 `acl-heal.ps1` 已同时支持 `-Check` / `-c`。

### 设计要点（为什么这样写）

- **幂等**：先体检（`Get-Issues`），零 issue 的项直接跳过，不做任何 icacls 调用；
  修复后对本轮处理过的项复检，输出 `unhealthyAfter`。跑 N 次结果一致。
- **顺序关键**：`/grant:r` 必须最先（否则后续 `/setowner`、`/remove:g` 会因缺
  `WRITE_OWNER`/`WRITE_DAC` 直接 Access denied）。
- **跳过名单**：`samples\` 下 owner 为 `BUILTIN\Administrators` 的 8 个文件，
  以"父目录 + 文件名"精确匹配（不做模糊匹配，避免误伤）。
- **纯 ASCII 源码**：PowerShell 5.1 把无 BOM 的 .ps1 按 ANSI 读，CJK 末字节可能是 `0x5C`
  （`录` 就是），会吃掉后面的引号导致解析失败。脚本里中文文件名用 `[char]0x6D4B` 这类
  码点在运行时拼出，源码零非 ASCII 字节（已校验 `nonAsciiBytes=0`）。
- **不改系统**：不碰执行策略、不碰 `E:\dsh_plugins\` 本身、不碰其他项目。

### 修复分支回归验证（2026-10-05，隔离目录）

隔离目录 `E:\dsh_plugins\word-format-applier\.acl-regression\`，人为复刻 Phase 1.5 形态
（`icacls /inheritance:d` 断开继承 + `icacls /remove:g *<mySid>` 去掉自己的 ACE）：

| 步骤 | 命令 | 输出 | 退出码 | 预期 |
| --- | --- | --- | --- | --- |
| 3 | `acl-heal.ps1 -c` | `needFix: 2` + `RESULT: NEEDS_FIX (2 items)` | 1 | ✅ |
| 4 | `acl-heal.ps1` | `fixed: 2  failed: 0  unhealthyAfter: 0` + `RESULT: fixed 2 items` | 0 | ✅ |
| 5 | `acl-heal.ps1 -c` | `needFix: 0` + `RESULT: HEALTHY (nothing to fix)` | 0 | ✅ |

修复后该目录：`protected=False`、`HUANWEI\zhangmeng:(OI)(CI)(F)` 且继承生效（唯一条目，
无重复）。测完已 `rmdir`，收尾 `-c` 回到 `needFix: 0`。
注：`needFix: 2` 中的第二项是当时放在该目录里的 `before.sddl`（我自己为留痕建的），非脚本误报。



### 踩过的坑（本地知识，避免重复付费）

- PowerShell 5.1：`[ordered]@{ X = @($genericList) }` 抛 `ArgumentException 参数类型不匹配`
  （要写 `$list.ToArray()`）。
- PowerShell 5.1：`$x = if (...) { ... } else { ... }` 作为表达式赋值可能得到空值，改写成
  `if (...) { $x = ... } else { $x = ... }`。
- PowerShell 5.1：`"$me:(OI)(CI)F"` 里的 `$me:` 会被当成 scope 引用，必须写 `"${me}:(OI)(CI)F"`
  或直接用 `*<SID>:...`。
- `Split-Path -LiteralPath x -Parent` 在 PS 5.1 报 `AmbiguousParameterSet`，用 `-Path` 或不指定。
- 中文 .ps1 若被按 ANSI 误读，`录`（末字节 `0x5C`）会变成反斜杠并吃掉后面的引号，导致解析失败。
  关键脚本正文尽量用 ASCII。
