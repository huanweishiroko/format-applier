param(
  [string]$Root = 'E:\dsh_plugins\word-format-applier',
  [string]$LogDir = 'E:\dsh_plugins\word-format-applier\_acl-recovery',
  [int]$BatchSize = 250,
  [int]$MaxBatches = 0,
  [switch]$DryRun,
  [switch]$SkipRoot
)
$ErrorActionPreference = 'Continue'

$expectedRoot = 'E:\dsh_plugins\word-format-applier'
$rootFull = (Get-Item -LiteralPath $Root -Force).FullName
if (-not $rootFull.Equals($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Scope violation: '$rootFull' is not '$expectedRoot'"
}
if (-not (Test-Path -LiteralPath $LogDir)) { $null = New-Item -ItemType Directory -Path $LogDir -Force }

$me    = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$meSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$logFile = Join-Path $LogDir ("fix-log-{0}.txt" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$sw = [Diagnostics.Stopwatch]::StartNew()

function Log($msg) {
  $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg
  $line | Add-Content -LiteralPath $logFile -Encoding UTF8
  Write-Host $line
}

# 判定一个显式 ACE 是否属于要清除的沙箱标记
function Test-SandboxAce($ace) {
  $sid = $null
  try { $sid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }
  catch { $sid = $ace.IdentityReference.Value }
  if ($sid -and ($sid.StartsWith('S-1-4-') -or $sid.StartsWith('S-1-5-') -or $sid.StartsWith('S-1-16-'))) { return $true }
  if ($sid -eq 'S-1-1-0' -and $ace.AccessControlType -eq 'Deny') { return $true }   # Everyone:(DENY)(DC)
  if ($ace.IdentityReference.Value -eq 'Everyone' -and $ace.AccessControlType -eq 'Deny') { return $true }
  return $false
}

function Normalize-One($item, [switch]$WhatIfOnly) {
  $res = [ordered]@{}
  $res['Path'] = $item.FullName
  $res['Kind'] = $(if ($item.PSIsContainer) { 'dir' } else { 'file' })
  $res['Ok'] = $false
  $res['Removed'] = 0
  $res['Before'] = $null
  $res['After'] = $null
  $res['Error'] = $null
  try {
    $acl = Get-Acl -LiteralPath $item.FullName
    $res['Before'] = $acl.Sddl
    $new = $acl
    if ($item.PSIsContainer) {
      $new.SetAccessRuleProtection($false, $false)
    } else {
      # 文件：确保继承开启（与父目录保持一致）
      $new.SetAccessRuleProtection($false, $false)
    }
    $removed = 0
    foreach ($ace in $acl.Access) {
      if (-not $ace.IsInherited -and (Test-SandboxAce $ace)) {
        $null = $new.RemoveAccessRuleSpecific($ace)
        $removed++
      }
    }
    # 兜底：若显式 ACE 里仍有别人给的 deny，也一并清掉（只清非继承）
    foreach ($ace in $acl.Access) {
      if (-not $ace.IsInherited -and $ace.AccessControlType -eq 'Deny') {
        if ($new.RemoveAccessRuleSpecific($ace)) { $removed++ }
      }
    }
    # 显式授予当前用户完全控制（继承标志：容器给 OI|CI，文件不加）
    $inherit = [System.Security.AccessControl.InheritanceFlags]::None
    if ($item.PSIsContainer) {
      $inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    }
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
      $meSid,
      [System.Security.AccessControl.FileSystemRights]::FullControl,
      $inherit,
      [System.Security.AccessControl.PropagationFlags]::None,
      [System.Security.AccessControl.AccessControlType]::Allow)
    $null = $new.AddAccessRule($rule)
    # 所有权
    $null = $new.SetOwner((New-Object System.Security.Principal.NTAccount($me)))
    $res['Removed'] = $removed
    $res['After'] = $new.Sddl
    if (-not $WhatIfOnly) {
      Set-Acl -LiteralPath $item.FullName -AclObject $new
    }
    $res['Ok'] = $true
  } catch {
    $res['Error'] = $_.Exception.GetType().Name + ': ' + $_.Exception.Message
  }
  return [pscustomobject]$res
}

Log "START fix  root=$rootFull  dryRun=$($DryRun.IsPresent)  batch=$BatchSize  user=$me"

$queue = New-Object System.Collections.Generic.List[object]
if (-not $SkipRoot) { $queue.Add((Get-Item -LiteralPath $rootFull -Force)) }
foreach ($it in (Get-ChildItem -LiteralPath $rootFull -Force -Recurse -ErrorAction SilentlyContinue)) { $queue.Add($it) }
Log "queue size = $($queue.Count)"

$results = New-Object System.Collections.Generic.List[object]
$batchNo = 0
$totalRemoved = 0
$failCount = 0
for ($i = 0; $i -lt $queue.Count; $i += $BatchSize) {
  $batchNo++
  if ($MaxBatches -gt 0 -and $batchNo -gt $MaxBatches) { Log "MaxBatches=$MaxBatches reached, stop."; break }
  $end = [Math]::Min($i + $BatchSize - 1, $queue.Count - 1)
  $slice = $queue[$i..$end]
  $batchSw = [Diagnostics.Stopwatch]::StartNew()
  $bOk = 0; $bFail = 0; $bRemoved = 0
  foreach ($it in $slice) {
    $r = Normalize-One $it -WhatIfOnly:$DryRun
    $results.Add($r)
    if ($r.Ok) { $bOk++; $bRemoved += $r.Removed } else { $bFail++; $failCount++ }
  }
  $totalRemoved += $bRemoved
  # 每批抽样验证 3 项
  $samples = @()
  foreach ($idx in @($i, [int](($i + $end) / 2), $end)) {
    if ($idx -ge $i -and $idx -le $end) { $samples += $queue[$idx].FullName }
  }
  $sampleTxt = @()
  foreach ($sp in ($samples | Select-Object -Unique)) {
    try {
      $sa = Get-Acl -LiteralPath $sp
      $sidOk = $false
      try { $sidOk = ($sa.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -eq $meSid) } catch { }
      $myFull = $false
      foreach ($ace in $sa.Access) {
        if ($ace.AccessControlType -ne 'Allow') { continue }
        $asid = $null
        try { $asid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $asid = $ace.IdentityReference.Value }
        if ($asid -eq $meSid -and (([int]$ace.FileSystemRights -band 2032127) -eq 2032127)) { $myFull = $true }
      }
      $sampleTxt += ("{0} ownerOk={1} myFull={2} protected={3}" -f (Split-Path -Leaf $sp), $sidOk, $myFull, $sa.AreAccessRulesProtected)
    } catch { $sampleTxt += ("{0} READ-FAIL {1}" -f (Split-Path -Leaf $sp), $_.Exception.Message) }
  }
  Log ("batch {0,3}  range {1}-{2}  ok={3} fail={4} removedAce={5}  {6}s" -f $batchNo, $i, $end, $bOk, $bFail, $bRemoved, [int]$batchSw.Elapsed.TotalSeconds)
  Log ("         samples: " + ($sampleTxt -join '  |  '))
}

$summary = [pscustomobject]@{
  DryRun = [bool]$DryRun
  Root = $rootFull
  Batches = $batchNo
  Processed = $results.Count
  Failed = $failCount
  RemovedAces = $totalRemoved
  ElapsedSec = [int]$sw.Elapsed.TotalSeconds
  LogFile = $logFile
  Failures = @($results | Where-Object { -not $_.Ok } | Select-Object -First 50)
}
$summaryPath = Join-Path $LogDir ("fix-summary-{0}{1}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $(if ($DryRun) { '-dryrun' } else { '' }))
$json = [string]($summary | ConvertTo-Json -Depth 6)
[System.IO.File]::WriteAllText($summaryPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Log ("DONE processed={0} failed={1} removedAce={2} elapsed={3}s summary={4}" -f $results.Count, $failCount, $totalRemoved, [int]$sw.Elapsed.TotalSeconds, $summaryPath)
"SUMMARY_JSON=$summaryPath"
