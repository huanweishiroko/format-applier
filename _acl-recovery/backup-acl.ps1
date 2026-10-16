param(
  [string]$Root = 'E:\dsh_plugins\word-format-applier',
  [string]$OutDir = 'E:\dsh_plugins\word-format-applier\_acl-recovery'
)
$ErrorActionPreference = 'Stop'

$expectedRoot = 'E:\dsh_plugins\word-format-applier'
$rootFull = (Get-Item -LiteralPath $Root -Force).FullName
if (-not $rootFull.Equals($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Scope violation: '$rootFull' is not '$expectedRoot'"
}
if (-not (Test-Path -LiteralPath $OutDir)) { $null = New-Item -ItemType Directory -Path $OutDir -Force }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$jsonPath = Join-Path $OutDir "pre-fix-$stamp.json"
$aclPath  = Join-Path $OutDir "pre-fix-$stamp.acl.txt"
$restore  = Join-Path $OutDir "restore-$stamp.ps1"
$me       = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$meSid    = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value

$items = New-Object System.Collections.Generic.List[object]
$readErrors = New-Object System.Collections.Generic.List[object]
$i = 0
$all = @((Get-Item -LiteralPath $rootFull -Force)) + @(Get-ChildItem -LiteralPath $rootFull -Force -Recurse -ErrorAction SilentlyContinue)
foreach ($it in $all) {
  $i++
  $rec = [pscustomobject]@{
    Path = $it.FullName
    Kind = $(if ($it.PSIsContainer) { 'dir' } else { 'file' })
    OwnerName = $null; OwnerSid = $null; GroupName = $null
    InheritanceProtected = $null
    AceCount = $null
    Sddl = $null
    ReadOk = $false
  }
  try {
    $acl = Get-Acl -LiteralPath $it.FullName
    $rec.OwnerName = $acl.Owner
    try { $rec.OwnerSid = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value } catch { }
    $rec.GroupName = $acl.Group
    $rec.InheritanceProtected = [bool]$acl.AreAccessRulesProtected
    $rec.AceCount = $acl.Access.Count
    $rec.Sddl = $acl.Sddl
    $rec.ReadOk = $true
  } catch {
    $readErrors.Add([pscustomobject]@{ Path = $it.FullName; Error = $_.Exception.Message })
  }
  $items.Add($rec)
}

$payload = [pscustomobject]@{
  Schema      = 'word-format-applier/acl-backup@1'
  Root        = $rootFull
  CapturedAt  = (Get-Date).ToString('o')
  CapturedBy  = $me
  CapturedSid = $meSid
  Note        = 'Sddl = Owner+Group+DACL (SACL/完整性标签需 SeSecurityPrivilege，普通令牌读不到，故未包含)'
  ItemCount   = $items.Count
  ReadErrors  = $readErrors.ToArray()
  Items       = $items.ToArray()
}
$json = [string]($payload | ConvertTo-Json -Depth 5)
[System.IO.File]::WriteAllText($jsonPath, $json, (New-Object System.Text.UTF8Encoding($false)))

# icacls /save 追加一份可被 icacls /restore 直接消费的备份（含完整性标签）
$saveOut = & icacls $rootFull /save $aclPath /T /C 2>&1
$saveText = ($saveOut | Out-String)

# 生成回滚脚本
$restoreBody = @'
param(
  [string]$BackupJson = "__JSON__",
  [string]$IcaclsBackup = "__ACL__"
)
$ErrorActionPreference = 'Continue'
Write-Host "== ACL 回滚 ==" -ForegroundColor Yellow
Write-Host "备份: $BackupJson"
$data = Get-Content -LiteralPath $BackupJson -Raw | ConvertFrom-Json
$ok = 0; $fail = 0
foreach ($rec in $data.Items) {
  if (-not $rec.ReadOk) { continue }
  if (-not (Test-Path -LiteralPath $rec.Path)) { Write-Host "SKIP(missing) $($rec.Path)"; continue }
  try {
    if ($rec.Kind -eq 'dir') { $sec = New-Object System.Security.AccessControl.DirectorySecurity }
    else                     { $sec = New-Object System.Security.AccessControl.FileSecurity }
    $sec.SetSecurityDescriptorSddlForm($rec.Sddl, [System.Security.AccessControl.AccessControlSections]::Access -bor [System.Security.AccessControl.AccessControlSections]::Owner -bor [System.Security.AccessControl.AccessControlSections]::Group)
    Set-Acl -LiteralPath $rec.Path -AclObject $sec
    $ok++
  } catch { $fail++; Write-Host "FAIL $($rec.Path): $($_.Exception.Message)" -ForegroundColor Red }
}
Write-Host "DACL/Owner 回滚完成: ok=$ok fail=$fail"
if (Test-Path -LiteralPath $IcaclsBackup) {
  Write-Host "如需还原完整性标签(SACL)，请在**管理员** PowerShell 中执行:" -ForegroundColor Cyan
  Write-Host "  icacls `"$($data.Root)`" /restore `"$IcaclsBackup`" /C"
}
'@
$restoreBody = $restoreBody.Replace('__JSON__', $jsonPath).Replace('__ACL__', $aclPath)
[System.IO.File]::WriteAllText($restore, $restoreBody, (New-Object System.Text.UTF8Encoding($false)))

# 验证落盘可读
$verify = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
$verOk = ($verify.ItemCount -eq $items.Count) -and ($verify.Items.Count -eq $items.Count) -and $verify.Root
$sampleOk = $true
$midIdx = [int]($items.Count / 2)
$lastIdx = $items.Count - 1
$probeIdx = New-Object System.Collections.Generic.List[int]
$probeIdx.Add(0); $probeIdx.Add($midIdx); $probeIdx.Add($lastIdx)
foreach ($n in $probeIdx) {
  if (-not $verify.Items[$n].Sddl) { $sampleOk = $false }
}
"=== BACKUP DONE ==="
"json      : $jsonPath  ($((Get-Item -LiteralPath $jsonPath).Length) bytes)"
"icacls    : $aclPath  ($((Get-Item -LiteralPath $aclPath).Length) bytes)  icacls-exit-summary: $(($saveOut | Select-Object -Last 1))"
"restore   : $restore  ($((Get-Item -LiteralPath $restore).Length) bytes)"
"items     : $($items.Count)  readOk=$((@($items | Where-Object { $_.ReadOk })).Count)  readErrors=$($readErrors.Count)"
"verify    : reparse-ok=$verOk  sddl-samples-ok=$sampleOk"
if (-not ($verOk -and $sampleOk -and ((Get-Item -LiteralPath $jsonPath).Length -gt 1000))) { throw 'backup verification FAILED' }
