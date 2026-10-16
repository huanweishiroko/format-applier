param(
  [string]$BackupJson = "E:\dsh_plugins\word-format-applier\_acl-recovery\pre-fix-20261005-215848.json",
  [string]$IcaclsBackup = "E:\dsh_plugins\word-format-applier\_acl-recovery\pre-fix-20261005-215848.acl.txt"
)
$ErrorActionPreference = 'Continue'
Write-Host "== ACL 鍥炴粴 ==" -ForegroundColor Yellow
Write-Host "澶囦唤: $BackupJson"
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
Write-Host "DACL/Owner 鍥炴粴瀹屾垚: ok=$ok fail=$fail"
if (Test-Path -LiteralPath $IcaclsBackup) {
  Write-Host "濡傞渶杩樺師瀹屾暣鎬ф爣绛?SACL)锛岃鍦?*绠＄悊鍛?* PowerShell 涓墽琛?" -ForegroundColor Cyan
  Write-Host "  icacls `"$($data.Root)`" /restore `"$IcaclsBackup`" /C"
}