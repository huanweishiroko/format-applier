param(
  [string]$Root = 'E:\dsh_plugins\word-format-applier',
  [string]$Out  = 'E:\dsh_plugins\word-format-applier\_acl-recovery\scan-result.json'
)
$ErrorActionPreference = 'Continue'
$Error.Clear()

$expectedRoot = 'E:\dsh_plugins\word-format-applier'
$rootFull = (Get-Item -LiteralPath $Root -Force).FullName
if (-not $rootFull.Equals($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Scope violation: resolved root '$rootFull' is not '$expectedRoot'"
}

$me      = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$meSid   = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$fullMask = 2032127   # FileSystemRights.FullControl
$woMask   = 0x00080000
$wdMask   = 0x00040000

$rows = New-Object System.Collections.Generic.List[object]
$scanErrors = New-Object System.Collections.Generic.List[object]

function Read-Row($Item) {
  $r = [ordered]@{
    Path = $Item.FullName; Kind = $(if ($Item.PSIsContainer) { 'dir' } else { 'file' })
    Owner = $null; OwnerOk = $null; Protected = $null; HasInherited = $null; HasExplicit = $null
    DirectFull = $null; InheritedFull = $null; WriteOwner = $null; WriteDac = $null
    SpecialSids = @(); EveryoneDenyDc = $false; LowLabel = $false; Error = $null
  }
  try {
    $acl = Get-Acl -LiteralPath $Item.FullName
    $ownerSid = $null
    try { $ownerSid = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value } catch { }
    if ([string]::IsNullOrEmpty($ownerSid) -and $acl.Owner) {
      try { $ownerSid = ([System.Security.Principal.NTAccount]$acl.Owner).Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $ownerSid = $null }
    }
    $r.OwnerOk = ($ownerSid -eq $meSid)
    $r.Owner   = $acl.Owner
    if (-not $r.Owner -and $ownerSid) { $r.Owner = $ownerSid }
    $r.Protected = [bool]$acl.AreAccessRulesProtected
    $sids = New-Object System.Collections.Generic.HashSet[string]
    $inheritedFull = $false
    foreach ($ace in $acl.Access) {
      $sid = $null
      if ($ace -is [System.Security.AccessControl.RegistryAccessRule] -or $ace.IdentityReference -is [System.Security.Principal.SecurityIdentifier]) {
        $sid = $ace.IdentityReference.Value
      } else {
        try { $sid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $sid = $ace.IdentityReference.Value }
      }
      if ($ace.IsInherited) { $r.HasInherited = $true } else { $r.HasExplicit = $true }
      if ($sid -and ($sid.StartsWith('S-1-4-') -or $sid.StartsWith('S-1-15-') -or $sid.StartsWith('S-1-16-'))) { $null = $sids.Add($sid) }
      $isEveryone = ($sid -eq 'S-1-1-0' -or $ace.IdentityReference.Value -eq 'Everyone')
      if ($isEveryone -and $ace.AccessControlType -eq 'Deny' -and (([int]$ace.FileSystemRights -band $wdMask) -ne 0)) { $r.EveryoneDenyDc = $true }
      if ($sid -and $sid.StartsWith('S-1-16-')) { $r.LowLabel = $true }
      if ($sid -eq $meSid) {
        $bits = [int]$ace.FileSystemRights
        if ($ace.AccessControlType -eq 'Allow') {
          if (($bits -band $woMask) -ne 0) { $r.WriteOwner = $true }
          if (($bits -band $wdMask) -ne 0) { $r.WriteDac = $true }
          if (($bits -band $fullMask) -eq $fullMask) {
            if ($ace.IsInherited) { $inheritedFull = $true } else { $r.DirectFull = $true }
          }
        }
      }
    }
    $r.InheritedFull = $inheritedFull
    $r.SpecialSids = @($sids)
    $r.WriteOwner = [bool]$r.WriteOwner; $r.WriteDac = [bool]$r.WriteDac
    $r.DirectFull = [bool]$r.DirectFull
    $r.HasInherited = [bool]$r.HasInherited; $r.HasExplicit = [bool]$r.HasExplicit
  } catch {
    $r.Error = $_.Exception.GetType().Name + ': ' + $_.Exception.Message
    $script:scanErrors.Add([pscustomobject]@{ Path = $Item.FullName; Error = $r.Error })
  }
  return [pscustomobject]$r
}

$rootItem = Get-Item -LiteralPath $rootFull -Force
$rows.Add((Read-Row $rootItem))
foreach ($it in (Get-ChildItem -LiteralPath $rootFull -Force -Recurse -ErrorAction SilentlyContinue)) {
  $rows.Add((Read-Row $it))
}

# 判定类型
foreach ($r in $rows) {
  $t = New-Object System.Collections.Generic.List[string]
  if ($r.Error) { $t.Add('ACCESS_ERROR') }
  elseif ($r.OwnerOk -eq $false) { $t.Add('OWNER_NOT_ME') }
  if (-not $r.Error) {
    if ($r.WriteOwner -ne $true) { $t.Add('MISSING_WRITE_OWNER') }
    if ($r.WriteDac   -ne $true) { $t.Add('MISSING_WRITE_DAC') }
    if ($r.DirectFull -ne $true -and $r.InheritedFull -ne $true) { $t.Add('NO_FULL_CONTROL_ACE') }
    if ($r.SpecialSids.Count -gt 0) { $t.Add('SANDBOX_SID') }
    if ($r.EveryoneDenyDc) { $t.Add('EVERYONE_DENY_DC') }
    if ($r.Protected -eq $true) { $t.Add('INHERITANCE_BLOCKED') }
  }
  $r | Add-Member -NotePropertyName Types -NotePropertyValue (($t) -join ',') -Force
}

$anom = $rows | Where-Object { $_.Types -ne '' }
$typeHist = @{}
foreach ($a in $anom) { foreach ($x in ($a.Types -split ',')) { if ($typeHist.ContainsKey($x)) { $typeHist[$x]++ } else { $typeHist[$x] = 1 } } }

# 按目录聚合异常数
$byDir = @{}
foreach ($a in $anom) {
  $d = [System.IO.Path]::GetDirectoryName($a.Path)
  if ([string]::IsNullOrEmpty($d)) { $d = $rootFull }
  if (-not $byDir.ContainsKey($d)) { $byDir[$d] = @{ dirs = 0; files = 0; types = @{} } }
  if ($a.Kind -eq 'dir') { $byDir[$d].dirs++ } else { $byDir[$d].files++ }
  foreach ($x in ($a.Types -split ',')) { if ($byDir[$d].types.ContainsKey($x)) { $byDir[$d].types[$x]++ } else { $byDir[$d].types[$x] = 1 } }
}

# 清理型异常（只需归一化，不算“坏”）
$cleanupTypes = @('MISSING_WRITE_OWNER','MISSING_WRITE_DAC','NO_FULL_CONTROL_ACE','INHERITANCE_BLOCKED','SANDBOX_SID','EVERYONE_DENY_DC','OWNER_NOT_ME')
$cleanup = $anom | Where-Object { $_.Types -ne '' -and -not ($_.Types -match 'ACCESS_ERROR') }
$confirmedBad = $anom | Where-Object { $_.Types -match 'ACCESS_ERROR|SANDBOX_SID|EVERYONE_DENY_DC' }

$result = [ordered]@{
  Root = $rootFull; User = $me; UserSid = $meSid
  ScannedAt = (Get-Date).ToString('s')
  TotalItems = $rows.Count
  TotalDirs = ($rows | Where-Object { $_.Kind -eq 'dir' }).Count
  TotalFiles = ($rows | Where-Object { $_.Kind -eq 'file' }).Count
  AnomalyCount = @($anom).Count
  ScanErrors = $scanErrors.ToArray()
  TypeHistogram = $typeHist
  DirGroups = $byDir
  Anomalies = @($anom | ForEach-Object { [pscustomobject]@{ Path=$_.Path; Kind=$_.Kind; Owner=$_.Owner; OwnerOk=$_.OwnerOk; WriteOwner=$_.WriteOwner; WriteDac=$_.WriteDac; DirectFull=$_.DirectFull; InheritedFull=$_.InheritedFull; Protected=$_.Protected; SpecialSids=($_.SpecialSids -join '|'); Types=$_.Types } })
}
$json = [string]($result | ConvertTo-Json -Depth 6)
[System.IO.File]::WriteAllText($Out, $json, (New-Object System.Text.UTF8Encoding($false)))
if (-not (Test-Path -LiteralPath $Out)) { throw "failed to write $Out" }

"=== SCAN SUMMARY ==="
"items     : $($rows.Count) (dirs $($result.TotalDirs) / files $($result.TotalFiles))"
"anomalies : $(@($anom).Count)   scanErrors: $($scanErrors.Count)"
"types     : " + (($typeHist.GetEnumerator() | Sort-Object -Property Value -Descending | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join '  ')
"json      : $Out"
"--- dirs containing SANDBOX_SID / EVERYONE_DENY_DC / INHERITANCE_BLOCKED (dir-level only) ---"
$anom | Where-Object { $_.Kind -eq 'dir' -and $_.Types -match 'SANDBOX_SID|EVERYONE_DENY_DC|INHERITANCE_BLOCKED' } | ForEach-Object { "  $($_.Types)  |  $($_.Path)" }
