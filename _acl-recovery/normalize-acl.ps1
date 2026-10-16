param(
  [string]$Root = 'E:\dsh_plugins\word-format-applier',
  [string]$LogDir = 'E:\dsh_plugins\word-format-applier\_acl-recovery',
  [string[]]$SkipPrefix = @(),
  [int]$BatchSize = 200,
  [switch]$DryRun
)
$ErrorActionPreference = 'Continue'

$expectedRoot = 'E:\dsh_plugins\word-format-applier'
$rootFull = (Get-Item -LiteralPath $Root -Force).FullName
if (-not $rootFull.Equals($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "Scope violation: $rootFull" }
if (-not (Test-Path -LiteralPath $LogDir)) { $null = New-Item -ItemType Directory -Path $LogDir -Force }

$me    = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$meSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$SYSTEM = 'S-1-5-18'
$ADMINS = 'S-1-5-32-544'
$SD_ALL = [System.Security.AccessControl.AccessControlSections]::Access -bor `
          [System.Security.AccessControl.AccessControlSections]::Owner -bor `
          [System.Security.AccessControl.AccessControlSections]::Group
$FULLMASK = 2032127

$logFile = Join-Path $LogDir ("normalize-log-{0}.txt" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
function Log($m) { $l = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m; $l | Add-Content -LiteralPath $logFile -Encoding UTF8; Write-Host $l }

function Get-AceSddl($ace) {
  $sid = $null
  if ($ace.IdentityReference -is [System.Security.Principal.SecurityIdentifier]) { $sid = $ace.IdentityReference.Value }
  else { try { $sid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $sid = $ace.IdentityReference.Value } }
  $type = if ($ace.AccessControlType -eq 'Allow') { 'A' } else { 'D' }
  $flags = ''
  if ($ace.IsInherited -or $ace.InheritanceFlags -ne [System.Security.AccessControl.InheritanceFlags]::None) {
    $f = $ace.InheritanceFlags
    if (($f -band [System.Security.AccessControl.InheritanceFlags]::ContainerInherit) -ne 0) { $flags += 'OI' }
    if (($f -band [System.Security.AccessControl.InheritanceFlags]::ObjectInherit) -ne 0) { $flags += 'CI' }
    if (($ace.PropagationFlags -band [System.Security.AccessControl.PropagationFlags]::InheritOnly) -ne 0) { $flags += 'IO' }
    if (($ace.PropagationFlags -band [System.Security.AccessControl.PropagationFlags]::NoPropagateInherit) -ne 0) { $flags += 'NP' }
  }
  "($type;$flags`ID;0x{0:x};;;$sid)" -f [int]$ace.FileSystemRights
}

# 依据父目录可继承 ACE + 我的完全控制 + SYSTEM/Administrators，生成目标 SDDL
function Get-TargetSddl($path, $isDir) {
  $acl = Get-Acl -LiteralPath $path
  $ownerS = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
  $groupS = $null; try { $groupS = $acl.GetGroup([System.Security.Principal.SecurityIdentifier]).Value } catch { }
  $s = "O:$ownerS"; if ($groupS) { $s += "G:$groupS" }
  $s += 'D:AI'
  if ($isDir) {
    $s += "(A;OICI;FA;;;$meSid)(A;OICI;FA;;;$SYSTEM)(A;OICI;FA;;;$ADMINS)"
  } else {
    $s += "(A;;FA;;;$meSid)(A;;FA;;;$SYSTEM)(A;;FA;;;$ADMINS)"
  }
  $parent = [System.IO.Path]::GetDirectoryName($path)
  if ($parent -and (Test-Path -LiteralPath $parent)) {
    foreach ($ace in (Get-Acl -LiteralPath $parent).Access) {
      if ($ace.AccessControlType -ne 'Allow') { continue }
      # 只取“会向下继承”的 ACE（继承来的，或显式带继承标志的）
      $f = $ace.InheritanceFlags
      if (-not $ace.IsInherited -and $f -eq [System.Security.AccessControl.InheritanceFlags]::None) { continue }
      if ($ace.PropagationFlags -band [System.Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
      $s += (Get-AceSddl $ace)
    }
  }
  return $s
}

function Apply-Sddl($path, $isDir, $sddl) {
  if ($isDir) {
    $sec = New-Object System.Security.AccessControl.DirectorySecurity
    $sec.SetSecurityDescriptorSddlForm($sddl, $SD_ALL)
    (New-Object System.IO.DirectoryInfo($path)).SetAccessControl($sec)
  } else {
    $sec = New-Object System.Security.AccessControl.FileSecurity
    $sec.SetSecurityDescriptorSddlForm($sddl, $SD_ALL)
    (New-Object System.IO.FileInfo($path)).SetAccessControl($sec)
  }
}

Log "START normalize root=$rootFull dryRun=$($DryRun.IsPresent) skip=$($SkipPrefix -join ',')"

$queue = New-Object System.Collections.Generic.List[object]
$skipped = 0
foreach ($it in (Get-ChildItem -LiteralPath $rootFull -Force -Recurse -ErrorAction SilentlyContinue)) {
  $skip = $false
  foreach ($p in $SkipPrefix) { if ($it.FullName.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)) { $skip = $true; break } }
  if ($skip) { $skipped++; continue }
  $queue.Add($it)
}
Log "queue=$($queue.Count) skipped=$skipped"

$sw = [Diagnostics.Stopwatch]::StartNew()
$okCount = 0; $failCount = 0; $noopCount = 0
$failures = New-Object System.Collections.Generic.List[object]
$batchNo = 0
for ($i = 0; $i -lt $queue.Count; $i += $BatchSize) {
  $batchNo++
  $end = [Math]::Min($i + $BatchSize - 1, $queue.Count - 1)
  $slice = $queue[$i..$end]
  $bOk = 0; $bFail = 0; $bNoop = 0
  $bSw = [Diagnostics.Stopwatch]::StartNew()
  foreach ($it in $slice) {
    $isDir = [bool]$it.PSIsContainer
    try {
      $now = Get-Acl -LiteralPath $it.FullName
      $ownerSid = $now.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
      $hasMine = $false; $hasSandbox = $false
      foreach ($ace in $now.Access) {
        $sid = $null
        if ($ace.IdentityReference -is [System.Security.Principal.SecurityIdentifier]) { $sid = $ace.IdentityReference.Value }
        else { try { $sid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $sid = $ace.IdentityReference.Value } }
        if ($sid -eq $meSid -and $ace.AccessControlType -eq 'Allow' -and (([int]$ace.FileSystemRights -band $FULLMASK) -eq $FULLMASK)) { $hasMine = $true }
        if ($sid -and ($sid.StartsWith('S-1-4-') -or $sid -eq 'S-1-1-0')) { $hasSandbox = $true }
      }
      if ($hasMine -and -not $hasSandbox -and $ownerSid -eq $meSid -and -not $now.AreAccessRulesProtected) { $bNoop++; $noopCount++; continue }
      $target = Get-TargetSddl $it.FullName $isDir
      if (-not $DryRun) { Apply-Sddl $it.FullName $isDir $target }
      $bOk++; $okCount++
    } catch {
      $bFail++; $failCount++
      $failures.Add([pscustomobject]@{ Path = $it.FullName; Error = $_.Exception.Message })
    }
  }
  Log ("batch {0,3}  {1}-{2}  fixed={3} noop={4} fail={5}  {6}s" -f $batchNo, $i, $end, $bOk, $bNoop, $bFail, [int]$bSw.Elapsed.TotalSeconds)
  # 每批抽样 3 个验证
  $probe = @()
  foreach ($idx in @($i, [int](($i + $end) / 2), $end)) { if ($idx -ge $i -and $idx -le $end) { $probe += $queue[$idx].FullName } }
  $txt = @()
  foreach ($pp in ($probe | Select-Object -Unique)) {
    try {
      $pa = Get-Acl -LiteralPath $pp
      $ownOk = $false; try { $ownOk = ($pa.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -eq $meSid) } catch { }
      $mineOk = $false; $sandboxLeft = 0
      foreach ($ace in $pa.Access) {
        $sid = $null
        if ($ace.IdentityReference -is [System.Security.Principal.SecurityIdentifier]) { $sid = $ace.IdentityReference.Value }
        else { try { $sid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $sid = $ace.IdentityReference.Value } }
        if ($sid -eq $meSid -and $ace.AccessControlType -eq 'Allow' -and (([int]$ace.FileSystemRights -band $FULLMASK) -eq $FULLMASK)) { $mineOk = $true }
        if ($sid -and ($sid.StartsWith('S-1-4-') -or $sid -eq 'S-1-1-0')) { $sandboxLeft++ }
      }
      $txt += ("{0}:owner={1},myFA={2},sandbox={3},prot={4}" -f (Split-Path -Leaf $pp), $ownOk, $mineOk, $sandboxLeft, $pa.AreAccessRulesProtected)
    } catch { $txt += ("{0}:READFAIL" -f (Split-Path -Leaf $pp)) }
  }
  Log ("         samples: " + ($txt -join ' | '))
  if ($batchNo % 5 -eq 0) { Log ("         progress {0}/{1}  elapsed={2}s" -f $end, $queue.Count, [int]$sw.Elapsed.TotalSeconds) }
}

$summary = [pscustomobject]@{
  DryRun = [bool]$DryRun; Root = $rootFull; Batches = $batchNo
  Queued = $queue.Count; Skipped = $skipped
  Fixed = $okCount; Noop = $noopCount; Failed = $failCount
  ElapsedSec = [int]$sw.Elapsed.TotalSeconds; LogFile = $logFile
  Failures = $failures.ToArray()
}
$sp = Join-Path $LogDir ("normalize-summary-{0}{1}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $(if ($DryRun) { '-dryrun' } else { '' }))
[System.IO.File]::WriteAllText($sp, [string]($summary | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding($false)))
Log ("DONE fixed={0} noop={1} fail={2} elapsed={3}s summary={4}" -f $okCount, $noopCount, $failCount, [int]$sw.Elapsed.TotalSeconds, $sp)
"SUMMARY_JSON=$sp"
