# acl-health.ps1 - 工作区 ACL 体检（只读）
# 用途：Phase 2 每新建 desktop\ui / desktop\core 等目录后，或沙箱报错时，先跑这个。
# 用法：powershell -ExecutionPolicy Bypass -File .\_acl-recovery\acl-health.ps1
param(
  [string]$Root = 'E:\dsh_plugins\word-format-applier'
)
$ErrorActionPreference = 'Continue'
$meSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$FULL = 2032127
$WRITE_OWNER = 0x00080000
$WRITE_DAC = 0x00040000

function Get-SidOf($ref) {
  if ($ref -is [System.Security.Principal.SecurityIdentifier]) { return $ref.Value }
  try { return $ref.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { return $ref.Value }
}

$bad = New-Object System.Collections.Generic.List[object]
$n = 0
$all = @((Get-Item -LiteralPath $Root -Force)) + @(Get-ChildItem -LiteralPath $Root -Force -Recurse -ErrorAction SilentlyContinue)
foreach ($it in $all) {
  $n++
  $types = New-Object System.Collections.Generic.List[string]
  try {
    $a = Get-Acl -LiteralPath $it.FullName
    $ownOk = $false
    try { $ownOk = ($a.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -eq $meSid) } catch { }
    $myFull = $false; $wo = $false; $wd = $false
    foreach ($ace in $a.Access) {
      $sid = Get-SidOf $ace.IdentityReference
      if ($sid -and ($sid.StartsWith('S-1-4-') -or $sid -eq 'S-1-1-0')) { $types.Add('SANDBOX_OR_EVERYONE_ACE') }
      if ($ace.AccessControlType -eq 'Deny' -and $sid -eq 'S-1-1-0') { $types.Add('EVERYONE_DENY') }
      if ($sid -eq $meSid -and $ace.AccessControlType -eq 'Allow') {
        $b = [int]$ace.FileSystemRights
        if (($b -band $FULL) -eq $FULL) { $myFull = $true }
        if (($b -band $WRITE_OWNER) -ne 0) { $wo = $true }
        if (($b -band $WRITE_DAC) -ne 0) { $wd = $true }
      }
    }
    if (-not $ownOk) { $types.Add('OWNER_NOT_ME') }
    if (-not $myFull) { $types.Add('NO_MY_FULL_CONTROL') }
    if (-not $wo) { $types.Add('NO_WRITE_OWNER') }
    if (-not $wd) { $types.Add('NO_WRITE_DAC') }
    if ($a.AreAccessRulesProtected) { $types.Add('INHERITANCE_BLOCKED') }
  } catch {
    $types.Add('READ_ERROR')
  }
  if ($types.Count -gt 0) {
    $bad.Add([pscustomobject]@{ Path = $it.FullName; Types = (($types | Select-Object -Unique) -join ',') })
  }
}

"root      : $Root"
"user      : $meSid"
"scanned   : $n"
"unhealthy : $($bad.Count)"
foreach ($b in $bad) { "  [$($b.Types)] $($b.Path)" }
if ($bad.Count -eq 0) { "RESULT: HEALTHY" } else { "RESULT: NEEDS_FIX (run icacls-normalize.ps1)" }
