# acl-heal.ps1 - workspace ACL self-heal (idempotent)
#
# Purpose: run once at the start of every new session. Detects sandbox SIDs,
#          Everyone DENY ACEs, missing WRITE_OWNER / WRITE_DAC for the current
#          user, non-self ownership and blocked inheritance, then clears them.
#
# Usage:
#   scan only : powershell -ExecutionPolicy Bypass -File .\_acl-recovery\acl-heal.ps1 -Check
#               (AGENTS.md writes it as "--check"; PowerShell needs the single-dash
#                form "-Check", or the alias "-c")
#   repair    : powershell -ExecutionPolicy Bypass -File .\_acl-recovery\acl-heal.ps1
#   with log  : powershell -ExecutionPolicy Bypass -File .\_acl-recovery\acl-heal.ps1 -LogDir <dir>
#
# Guarantees:
#   * idempotent - healthy items are never touched; N runs give the same result.
#   * never touches the 8 files under samples\ owned by BUILTIN\Administrators
#     (they need an elevated token; see docs\acl-fix.md).
#   * ACL only - no file content is ever modified.
#   * the source is pure ASCII on purpose: PowerShell 5.1 reads BOM-less files as
#     ANSI, and some CJK trailing bytes are 0x5C (backslash), which corrupts string
#     literals. Chinese file names are built from code points at runtime instead.
#   * this script never changes any system execution policy.

[CmdletBinding()]
param(
  [string]$Root = 'E:\dsh_plugins\word-format-applier',
  [Alias('c')]
  [switch]$Check,
  [string]$LogDir
)

$ErrorActionPreference = 'Continue'

# ---------- log ----------
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $LogDir) { $LogDir = Join-Path $Root '_acl-recovery' }
$script:logFile = $null
if (-not $Check) {
  if (-not (Test-Path -LiteralPath $LogDir)) { $null = New-Item -ItemType Directory -Path $LogDir -Force }
  $script:logFile = Join-Path $LogDir ('acl-heal-' + $stamp + '.log')
}
function Write-Out($msg) {
  Write-Host $msg
  if ($script:logFile) { Add-Content -LiteralPath $script:logFile -Value $msg -Encoding UTF8 }
}

# ---------- constants ----------
$script:expectedRoot = 'E:\dsh_plugins\word-format-applier'
$script:meSid  = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$script:meName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:FULLMASK    = 2032127      # FileSystemRights.FullControl
$script:WRITE_OWNER = 0x00080000
$script:WRITE_DAC   = 0x00040000
$script:SIDS_SANDBOX = @('S-1-4-966191722-319427645', 'S-1-4-600891134-409881891')
$script:SKIP_DIR = Join-Path $script:expectedRoot 'samples'

# the 8 elevation-only files (name built from code points to keep this file ASCII)
$cn = [string][char]0x6D4B + [char]0x8BD5 + [char]0x8F93 + [char]0x51FA   # "test output"
$script:SKIP_NAMES = @(
  ($cn + '.docx'), ($cn + '.report.json'),
  ($cn + '2.docx'), ($cn + '2.report.json'),
  ($cn + '3.docx'), ($cn + '3.report.json'),
  ($cn + '4.docx'), ($cn + '4.report.json')
)

# ---------- helpers ----------
function Get-SidOf($ref) {
  if ($ref -is [System.Security.Principal.SecurityIdentifier]) { return $ref.Value }
  try { return $ref.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { return $ref.Value }
}

function Test-SkipPath($path) {
  $dir = [System.IO.Path]::GetDirectoryName($path)
  if ([string]::IsNullOrEmpty($dir)) { return $false }
  if (-not $dir.TrimEnd('\').Equals($script:SKIP_DIR.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) { return $false }
  return ($script:SKIP_NAMES -contains [System.IO.Path]::GetFileName($path))
}

function Get-Issues($path) {
  $issues = New-Object System.Collections.Generic.List[string]
  try { $acl = Get-Acl -LiteralPath $path } catch { $issues.Add('READ_ERROR'); return $issues.ToArray() }

  $ownerOk = $false
  try { $ownerOk = ($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -eq $script:meSid) } catch { }
  if (-not $ownerOk) { $issues.Add('OWNER_NOT_ME') }

  $myFull = $false; $myWO = $false; $myWD = $false
  foreach ($ace in $acl.Access) {
    $sid = Get-SidOf $ace.IdentityReference
    if ($sid) {
      if ($script:SIDS_SANDBOX -contains $sid) { $issues.Add('SANDBOX_SID') }
      if ($sid -eq 'S-1-1-0' -and $ace.AccessControlType -eq 'Deny') { $issues.Add('EVERYONE_DENY') }
    }
    if ($sid -eq $script:meSid -and $ace.AccessControlType -eq 'Allow') {
      $bits = [int]$ace.FileSystemRights
      if (($bits -band $script:FULLMASK) -eq $script:FULLMASK) { $myFull = $true }
      if (($bits -band $script:WRITE_OWNER) -ne 0) { $myWO = $true }
      if (($bits -band $script:WRITE_DAC) -ne 0) { $myWD = $true }
    }
  }
  if (-not $myFull) { $issues.Add('NO_MY_FULL_CONTROL') }
  if (-not $myWO)   { $issues.Add('NO_WRITE_OWNER') }
  if (-not $myWD)   { $issues.Add('NO_WRITE_DAC') }
  if ($acl.AreAccessRulesProtected) { $issues.Add('INHERITANCE_BLOCKED') }
  return $issues.ToArray()
}

function Invoke-Icacls($arguments) {
  $out = & icacls @arguments 2>&1
  $code = $LASTEXITCODE
  return [pscustomobject]@{ Code = $code; Out = ($out | Out-String).Trim() }
}

function Repair-One($path, [bool]$isDir) {
  # 1) grant self full control first - later steps need WRITE_DAC/WRITE_OWNER
  if ($isDir) { $grant = '*$S$:(OI)(CI)F' } else { $grant = '*$S$:F' }
  $grant = $grant.Replace('$S$', $script:meSid)
  $r = Invoke-Icacls @($path, '/grant:r', $grant)
  if ($r.Code -ne 0) { return [pscustomobject]@{ Ok = $false; Step = 'grant'; Out = $r.Out } }
  # 2) drop sandbox SIDs (non-zero exit when absent is expected)
  $null = Invoke-Icacls @($path, '/remove:g', ('*' + $script:SIDS_SANDBOX[0]), ('*' + $script:SIDS_SANDBOX[1]))
  # 3) drop Everyone DENY
  $null = Invoke-Icacls @($path, '/remove:d', 'Everyone')
  # 4) re-enable inheritance
  $r = Invoke-Icacls @($path, '/inheritance:e')
  if ($r.Code -ne 0) { return [pscustomobject]@{ Ok = $false; Step = 'inheritance'; Out = $r.Out } }
  # 5) take ownership only if needed
  $ownerOk = $false
  try { $ownerOk = ((Get-Acl -LiteralPath $path).GetOwner([System.Security.Principal.SecurityIdentifier]).Value -eq $script:meSid) } catch { }
  if (-not $ownerOk) {
    $r = Invoke-Icacls @($path, '/setowner', $script:meName)
    if ($r.Code -ne 0) { return [pscustomobject]@{ Ok = $false; Step = 'setowner'; Out = $r.Out } }
  }
  return [pscustomobject]@{ Ok = $true; Step = 'ok'; Out = '' }
}

# ---------- main ----------
$rootFull = (Get-Item -LiteralPath $Root -Force).FullName
if (-not $rootFull.Equals($script:expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
  Write-Out ('SCOPE VIOLATION: resolved root is ' + $rootFull + ' , expected ' + $script:expectedRoot)
  exit 2
}

$mode = if ($Check) { 'CHECK' } else { 'HEAL' }
Write-Out ('acl-heal [' + $mode + '] ' + (Get-Date).ToString('s'))
Write-Out ('root   : ' + $rootFull)
Write-Out ('user   : ' + $script:meName + '  (' + $script:meSid + ')')
if ($script:logFile) { Write-Out ('log    : ' + $script:logFile) }

$all = @((Get-Item -LiteralPath $rootFull -Force))
$all += @(Get-ChildItem -LiteralPath $rootFull -Force -Recurse -ErrorAction SilentlyContinue)

$todo = New-Object System.Collections.Generic.List[object]
$skipped = New-Object System.Collections.Generic.List[object]
$healthy = 0
$typeHist = @{}
$sw = [Diagnostics.Stopwatch]::StartNew()

foreach ($it in $all) {
  $issues = @(Get-Issues $it.FullName)
  if ($issues.Count -eq 0) { $healthy++; continue }
  foreach ($t in $issues) { if ($typeHist.ContainsKey($t)) { $typeHist[$t]++ } else { $typeHist[$t] = 1 } }
  if (Test-SkipPath $it.FullName) {
    $skipped.Add([pscustomobject]@{ Path = $it.FullName; Issues = ($issues -join ',') })
    continue
  }
  $todo.Add([pscustomobject]@{ Path = $it.FullName; IsDir = [bool]$it.PSIsContainer; Issues = ($issues -join ',') })
}

Write-Out ('scanned: ' + $all.Count + '   healthy: ' + $healthy + '   needFix: ' + $todo.Count + '   skippedElevation: ' + $skipped.Count)
if ($typeHist.Count -gt 0) {
  $hist = ($typeHist.GetEnumerator() | Sort-Object -Property Value -Descending | ForEach-Object { $_.Key + '=' + $_.Value }) -join '  '
  Write-Out ('issue types: ' + $hist)
}
foreach ($s in $skipped) { Write-Out ('  SKIP  [' + $s.Issues + '] ' + $s.Path) }

if ($Check) {
  if ($todo.Count -gt 0) {
    foreach ($t in $todo) { Write-Out ('  TODO  [' + $t.Issues + '] ' + $t.Path) }
    Write-Out ('RESULT: NEEDS_FIX (' + $todo.Count + ' items) - run without -Check to repair')
    exit 1
  }
  Write-Out 'RESULT: HEALTHY (nothing to fix)'
  exit 0
}

$fixed = 0; $failed = 0
$failures = New-Object System.Collections.Generic.List[object]
$batchSize = 200
$batchNo = 0
for ($i = 0; $i -lt $todo.Count; $i += $batchSize) {
  $batchNo++
  $end = [Math]::Min($i + $batchSize - 1, $todo.Count - 1)
  $bOk = 0; $bFail = 0
  $bSw = [Diagnostics.Stopwatch]::StartNew()
  foreach ($t in $todo[$i..$end]) {
    $r = Repair-One $t.Path $t.IsDir
    if ($r.Ok) { $bOk++; $fixed++ }
    else {
      $bFail++; $failed++
      $failures.Add([pscustomobject]@{ Path = $t.Path; Issues = $t.Issues; Step = $r.Step; Out = $r.Out })
    }
  }
  Write-Out ('  batch ' + $batchNo + '  items ' + $i + '-' + $end + '  fixed=' + $bOk + ' fail=' + $bFail + '  ' + [int]$bSw.Elapsed.TotalSeconds + 's')
}

# re-check everything that was attempted
$remain = 0
foreach ($t in $todo) {
  if (@(Get-Issues $t.Path).Count -gt 0) { $remain++ }
}

Write-Out ('fixed: ' + $fixed + '   failed: ' + $failed + '   unhealthyAfter: ' + $remain + '   elapsed: ' + [int]$sw.Elapsed.TotalSeconds + 's')
foreach ($f in $failures) { Write-Out ('  FAIL [' + $f.Step + '] ' + $f.Path + ' :: ' + (($f.Out -split "`r?`n")[0])) }
if ($todo.Count -eq 0) { Write-Out 'RESULT: nothing to fix (already healthy)' }
elseif ($failed -eq 0) { Write-Out ('RESULT: fixed ' + $fixed + ' items') }
else { Write-Out ('RESULT: PARTIAL fixed=' + $fixed + ' failed=' + $failed) }
if ($failed -gt 0) { exit 1 }
exit 0
