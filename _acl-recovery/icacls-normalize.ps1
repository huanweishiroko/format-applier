param(
  [string]$Root = 'E:\dsh_plugins\word-format-applier',
  [string]$LogDir = 'E:\dsh_plugins\word-format-applier\_acl-recovery',
  [string[]]$SkipPrefix = @(),
  [int]$BatchSize = 300,
  [switch]$DryRun
)
$ErrorActionPreference = 'Continue'
$OutputEncoding = [Console]::OutputEncoding

$expectedRoot = 'E:\dsh_plugins\word-format-applier'
$rootFull = (Get-Item -LiteralPath $Root -Force).FullName
if (-not $rootFull.Equals($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "Scope violation: $rootFull" }
if (-not (Test-Path -LiteralPath $LogDir)) { $null = New-Item -ItemType Directory -Path $LogDir -Force }

$me    = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$meSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if ([string]::IsNullOrEmpty($meSid)) { $meSid = (whoami /user | Select-String -Pattern '(S-1-5-[\d\-]+)\s*$').Matches[0].Groups[1].Value }
if ([string]::IsNullOrEmpty($meSid)) { throw 'cannot resolve current user SID' }
$script:MeSid = $meSid
$SID_SANDBOX_A = 'S-1-4-966191722-319427645'
$SID_SANDBOX_B = 'S-1-4-600891134-409881891'
$FULLMASK = 2032127

$logFile = Join-Path $LogDir ("icacls-normalize-{0}.txt" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$script:DbgFile = Join-Path $env:TEMP ("icacls-dbg-{0}.txt" -f (Get-Date -Format 'HHmmss'))
$script:DebugDir = $false
function Log($m) { $l = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m; $l | Add-Content -LiteralPath $logFile -Encoding UTF8; Write-Host $l }

function Test-NeedFix($path, [bool]$isDir) {
  try {
    $a = Get-Acl -LiteralPath $path
    $ownOk = $false
    try { $ownOk = ($a.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -eq $meSid) } catch { }
    $hasMine = $false; $bad = 0
    foreach ($ace in $a.Access) {
      $sid = $null
      if ($ace.IdentityReference -is [System.Security.Principal.SecurityIdentifier]) { $sid = $ace.IdentityReference.Value }
      else { try { $sid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $sid = $ace.IdentityReference.Value } }
      if ($sid -eq $meSid -and $ace.AccessControlType -eq 'Allow' -and (([int]$ace.FileSystemRights -band $FULLMASK) -eq $FULLMASK)) { $hasMine = $true }
      if ($sid -and ($sid.StartsWith('S-1-4-') -or $sid -eq 'S-1-1-0')) { $bad++ }
    }
    if ($ownOk -and $hasMine -and $bad -eq 0 -and -not $a.AreAccessRulesProtected) { return $false }
    return $true
  } catch { return $true }
}

function Invoke-Icacls($arguments) {
  $out = & icacls @arguments 2>&1
  $code = $LASTEXITCODE
  return [pscustomobject]@{ Code = $code; Out = (($out | Out-String).Trim()) }
}

function Normalize-One($path, [bool]$isDir) {
  # 1) 先显式授予当前用户完全控制（此后才有 WRITE_DAC/WRITE_OWNER 可用）
  if ($isDir) { $grant = "*$($script:MeSid):(OI)(CI)F" } else { $grant = "*$($script:MeSid):F" }
  if ([string]::IsNullOrEmpty($grant)) { $grant = "*$($script:MeSid):F" }
  $dbg = "isDir=$isDir MeSid=<$($script:MeSid)> grant=<$grant> path=$path"
  $dbg | Add-Content -LiteralPath $script:DbgFile -Encoding UTF8
  $r1 = Invoke-Icacls @($path, '/grant:r', $grant)
  if ($r1.Code -ne 0) { return [pscustomobject]@{ Ok = $false; Step = 'grant'; Out = ($r1.Out + ' <<grant=' + $grant + '>>') } }
  # 2) 移除沙箱 SID 授权项（不存在时 icacls 返回非 0，可忽略）
  $null = Invoke-Icacls @($path, '/remove:g', "*$SID_SANDBOX_A", "*$SID_SANDBOX_B")
  # 3) 移除 Everyone 拒绝项
  $null = Invoke-Icacls @($path, '/remove:d', 'Everyone')
  # 4) 恢复从父目录继承
  $r4 = Invoke-Icacls @($path, '/inheritance:e')
  if ($r4.Code -ne 0) { return [pscustomobject]@{ Ok = $false; Step = 'inheritance'; Out = $r4.Out } }
  # 5) owner 不是本人时才取所有权
  $ownOk = $false
  try { $ownOk = ((Get-Acl -LiteralPath $path).GetOwner([System.Security.Principal.SecurityIdentifier]).Value -eq $meSid) } catch { }
  if (-not $ownOk) {
    $r5 = Invoke-Icacls @($path, '/setowner', $me)
    if ($r5.Code -ne 0) { return [pscustomobject]@{ Ok = $false; Step = 'setowner'; Out = $r5.Out } }
  }
  return [pscustomobject]@{ Ok = $true; Step = 'ok'; Out = '' }
}

Log "START icacls normalize root=$rootFull dryRun=$($DryRun.IsPresent) skip=$($SkipPrefix -join ',') user=$me"

$queue = New-Object System.Collections.Generic.List[object]
foreach ($it in (Get-ChildItem -LiteralPath $rootFull -Force -Recurse -ErrorAction SilentlyContinue)) {
  $skip = $false
  foreach ($p in $SkipPrefix) { if ($it.FullName.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)) { $skip = $true; break } }
  if (-not $skip) { $queue.Add($it) }
}
Log "queue=$($queue.Count)"

$sw = [Diagnostics.Stopwatch]::StartNew()
$fixed = 0; $noop = 0; $fail = 0
$failures = New-Object System.Collections.Generic.List[object]
$batchNo = 0
for ($i = 0; $i -lt $queue.Count; $i += $BatchSize) {
  $batchNo++
  $end = [Math]::Min($i + $BatchSize - 1, $queue.Count - 1)
  $bFixed = 0; $bNoop = 0; $bFail = 0
  $bSw = [Diagnostics.Stopwatch]::StartNew()
  foreach ($it in $queue[$i..$end]) {
    $isDir = [bool]$it.PSIsContainer
    if (-not (Test-NeedFix $it.FullName $isDir)) { $bNoop++; $noop++; continue }
    if ($DryRun) { $bFixed++; $fixed++; continue }
    $r = Normalize-One $it.FullName $isDir
    if ($r.Ok) { $bFixed++; $fixed++ } else { $bFail++; $fail++; $failures.Add([pscustomobject]@{ Path = $it.FullName; Step = $r.Step; Out = $r.Out }) }
  }
  Log ("batch {0,3}  {1}-{2}  fixed={3} noop={4} fail={5}  {6}s" -f $batchNo, $i, $end, $bFixed, $bNoop, $bFail, [int]$bSw.Elapsed.TotalSeconds)
  $probe = @($queue[$i].FullName, $queue[[int](($i + $end) / 2)].FullName, $queue[$end].FullName) | Select-Object -Unique
  $txt = @()
  foreach ($pp in $probe) {
    try {
      $pa = Get-Acl -LiteralPath $pp
      $ownOk = $false; try { $ownOk = ($pa.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -eq $meSid) } catch { }
      $mineOk = $false; $left = 0
      foreach ($ace in $pa.Access) {
        $sid = $null
        if ($ace.IdentityReference -is [System.Security.Principal.SecurityIdentifier]) { $sid = $ace.IdentityReference.Value }
        else { try { $sid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $sid = $ace.IdentityReference.Value } }
        if ($sid -eq $meSid -and $ace.AccessControlType -eq 'Allow' -and (([int]$ace.FileSystemRights -band $FULLMASK) -eq $FULLMASK)) { $mineOk = $true }
        if ($sid -and ($sid.StartsWith('S-1-4-') -or $sid -eq 'S-1-1-0')) { $left++ }
      }
      $txt += ("{0}[owner={1},myFA={2},bad={3},prot={4}]" -f (Split-Path -Leaf $pp), $ownOk, $mineOk, $left, $pa.AreAccessRulesProtected)
    } catch { $txt += ("{0}[READFAIL]" -f (Split-Path -Leaf $pp)) }
  }
  Log ("         samples: " + ($txt -join ' '))
}

$summary = [pscustomobject]@{
  DryRun = [bool]$DryRun; Root = $rootFull; Batches = $batchNo; Queued = $queue.Count
  Fixed = $fixed; Noop = $noop; Failed = $fail
  ElapsedSec = [int]$sw.Elapsed.TotalSeconds; LogFile = $logFile
  Failures = $failures.ToArray()
}
$sp = Join-Path $LogDir ("icacls-normalize-summary-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
[System.IO.File]::WriteAllText($sp, [string]($summary | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding($false)))
Log ("DONE fixed={0} noop={1} fail={2} elapsed={3}s summary={4}" -f $fixed, $noop, $fail, [int]$sw.Elapsed.TotalSeconds, $sp)
"SUMMARY_JSON=$sp"
