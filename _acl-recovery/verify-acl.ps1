param(
  [string]$Root = 'E:\dsh_plugins\word-format-applier',
  [string]$LogDir = 'E:\dsh_plugins\word-format-applier\_acl-recovery',
  [switch]$CleanPipDirs
)
$ErrorActionPreference = 'Continue'
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$meSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$FULL = 2032127
$WRITE_OWNER = 0x00080000
$WRITE_DAC = 0x00040000

$script:Pass = 0
$script:Fail = 0
$script:Lines = New-Object System.Collections.Generic.List[string]
function Check($id, $desc, [bool]$ok, $detail) {
  if ($ok) { $script:Pass++ } else { $script:Fail++ }
  $mark = if ($ok) { '[OK]  ' } else { '[FAIL]' }
  $line = "{0} {1,-42} {2} {3}" -f $mark, $desc, $detail, $id
  $script:Lines.Add($line)
  $line
}
function Get-SidOf($ref) {
  if ($ref -is [System.Security.Principal.SecurityIdentifier]) { return $ref.Value }
  try { return $ref.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { return $ref.Value }
}
function Get-OwnerSid($p) { try { return (Get-Acl -LiteralPath $p).GetOwner([System.Security.Principal.SecurityIdentifier]).Value } catch { return $null } }
function Test-MyFull($p) {
  try {
    foreach ($ace in (Get-Acl -LiteralPath $p).Access) {
      if ($ace.AccessControlType -ne 'Allow') { continue }
      if ((Get-SidOf $ace.IdentityReference) -eq $meSid -and (([int]$ace.FileSystemRights -band $FULL) -eq $FULL)) { return $true }
    }
    return $false
  } catch { return $false }
}
function Test-NoSandbox($p) {
  try {
    foreach ($ace in (Get-Acl -LiteralPath $p).Access) {
      $sid = Get-SidOf $ace.IdentityReference
      if ($sid -and ($sid.StartsWith('S-1-4-') -or $sid -eq 'S-1-1-0')) { return $false }
    }
    return $true
  } catch { return $false }
}
function Test-Bit($p, $mask) {
  try {
    foreach ($ace in (Get-Acl -LiteralPath $p).Access) {
      if ($ace.AccessControlType -ne 'Allow') { continue }
      if ((Get-SidOf $ace.IdentityReference) -eq $meSid -and (([int]$ace.FileSystemRights -band $mask) -eq $mask)) { return $true }
    }
    return $false
  } catch { return $false }
}

"===== VERIFY CHECKLIST ====="
$rootFull = (Get-Item -LiteralPath $Root).FullName
Check 'V0'  'Scope: root resolves to expected path' ($rootFull -eq 'E:\dsh_plugins\word-format-applier') $rootFull

$parser = Join-Path $Root 'desktop\parser'
$aclP = Get-Acl -LiteralPath $parser
Check 'V1a' 'desktop\parser WRITE_OWNER = True' (Test-Bit $parser $WRITE_OWNER) ('owner=' + (Get-OwnerSid $parser))
Check 'V1b' 'desktop\parser WRITE_DAC = True'   (Test-Bit $parser $WRITE_DAC)   ('protected=' + $aclP.AreAccessRulesProtected)
Check 'V1c' 'desktop\parser owner = current user' ((Get-OwnerSid $parser) -eq $meSid) (Get-OwnerSid $parser)
Check 'V1d' 'desktop\parser no sandbox/Everyone ACE' (Test-NoSandbox $parser) 'sandbox markers cleared'

# V2: real DACL write inside parser (same API path as SetNamedSecurityInfoW)
$canary = Join-Path $parser '.acl-write-canary.txt'
try {
  $srcFile = Join-Path $env:TEMP ('canary-{0}.txt' -f (Get-Date -Format 'HHmmss'))
  Set-Content -LiteralPath $srcFile -Value 'probe' -Encoding ASCII
  Move-Item -LiteralPath $srcFile -Destination $canary -Force
  Check 'V2a' 'create file inside desktop\parser' (Test-Path -LiteralPath $canary) $canary
  $sec = New-Object System.Security.AccessControl.FileSecurity
  $sddl = 'O:' + $meSid + 'G:' + $meSid + 'D:AI(A;;FA;;;' + $meSid + ')'
  $sec.SetSecurityDescriptorSddlForm($sddl, [System.Security.AccessControl.AccessControlSections]::Access -bor [System.Security.AccessControl.AccessControlSections]::Owner -bor [System.Security.AccessControl.AccessControlSections]::Group)
  (New-Object System.IO.FileInfo($canary)).SetAccessControl($sec)
  $after = Get-Acl -LiteralPath $canary
  Check 'V2b' 'write DACL+owner inside parser (SetNamedSecurityInfoW path)' ((Get-OwnerSid $canary) -eq $meSid) ('owner=' + $after.Owner)
  Remove-Item -LiteralPath $canary -Force
  Check 'V2c' 'cleanup canary file' (-not (Test-Path -LiteralPath $canary)) 'removed'
} catch {
  Check 'V2b' 'write DACL+owner inside parser' $false $_.Exception.Message
  if (Test-Path -LiteralPath $canary) { Remove-Item -LiteralPath $canary -Force -ErrorAction SilentlyContinue }
}

# V3: lightweight directory writability test (no pip; %TEMP% is unwritable on this host)
$testDir = Join-Path $Root 'desktop\__acl_test__'
$oldT = $env:TEMP; $oldP = $env:TMP
try {
  $null = New-Item -ItemType Directory -Path $testDir -Force
  Check 'V3a' 'create desktop\__acl_test__' (Test-Path -LiteralPath $testDir) $testDir
  $testFile = Join-Path $testDir 'write-test.txt'
  'test' | Out-File -FilePath $testFile -Encoding ascii
  $writable = Test-Path -LiteralPath $testFile
  Check 'V3b' 'desktop\__acl_test__ is writable' $writable ('writable_test=' + $(if ($writable) { 'PASS' } else { 'FAIL' }))
  $mine = Test-MyFull $testDir
  Check 'V3c' 'new dir inherited current-user full control' $mine 'inheritance ok'
  Remove-Item -LiteralPath $testFile -Force -ErrorAction SilentlyContinue
} catch {
  Check 'V3' 'directory writability test' $false $_.Exception.Message
} finally {
  $env:TEMP = $oldT; $env:TMP = $oldP
}
if (Test-Path -LiteralPath $testDir) { Remove-Item -LiteralPath $testDir -Recurse -Force -ErrorAction SilentlyContinue }
Check 'V3e' 'delete desktop\__acl_test__' (-not (Test-Path -LiteralPath $testDir)) 'removed'

# V4: pip leftover temp dirs
$pipDirs = @(Get-ChildItem -LiteralPath $Root -Directory -Force | Where-Object { $_.Name -match '^pip-(install|build-tracker|ephem-wheel-cache)-' })
$nonEmpty = @($pipDirs | Where-Object { @(Get-ChildItem -LiteralPath $_.FullName -Force -Recurse -ErrorAction SilentlyContinue).Count -gt 0 })
$allMine = @($pipDirs | Where-Object { Test-MyFull $_.FullName }).Count
Check 'V4a' 'pip leftover dirs removed / normalized' ($pipDirs.Count -eq 0 -or $allMine -eq $pipDirs.Count) ('count=' + $pipDirs.Count + ' withMyFull=' + $allMine)
Check 'V4b' 'pip leftover dirs are empty' ($nonEmpty.Count -eq 0) ('nonEmpty=' + $nonEmpty.Count)
if ($CleanPipDirs -and $nonEmpty.Count -eq 0) {
  foreach ($d in $pipDirs) { Remove-Item -LiteralPath $d.FullName -Recurse -Force -ErrorAction SilentlyContinue }
  $left2 = @(Get-ChildItem -LiteralPath $Root -Directory -Force | Where-Object { $_.Name -match '^pip-(install|build-tracker|ephem-wheel-cache)-' })
  Check 'V4c' 'delete 12 empty pip leftover dirs' ($left2.Count -eq 0) ('remaining=' + $left2.Count)
}

# V5: whole-tree summary
$n = 0; $noMine = 0; $bad = 0; $notOwner = 0; $prot = 0
foreach ($it in (Get-ChildItem -LiteralPath $Root -Force -Recurse -ErrorAction SilentlyContinue)) {
  $n++
  if (-not (Test-MyFull $it.FullName)) { $noMine++ }
  if (-not (Test-NoSandbox $it.FullName)) { $bad++ }
  if ((Get-OwnerSid $it.FullName) -ne $meSid) { $notOwner++ }
  try { if ((Get-Acl -LiteralPath $it.FullName).AreAccessRulesProtected) { $prot++ } } catch { }
}
Check 'V5a' 'whole tree: no sandbox/Everyone ACE' ($bad -eq 0) ('bad=' + $bad + ' of ' + $n)
Check 'V5b' 'whole tree: owner is current user' ($notOwner -eq 0) ('notMine=' + $notOwner)
Check 'V5c' 'whole tree: current user has full control' ($noMine -eq 0) ('missing=' + $noMine)
Check 'V5d' 'whole tree: DACL inheritance enabled' ($prot -eq 0) ('protected=' + $prot)

$okN = $script:Pass
$badN = $script:Fail
"===== TOTAL: $okN passed / $badN failed ====="
$summary = [pscustomobject]@{ At = (Get-Date).ToString('o'); Root = $Root; Pass = $okN; Fail = $badN; Lines = $script:Lines.ToArray() }
$sp = Join-Path $LogDir ('verify-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
[System.IO.File]::WriteAllText($sp, [string]($summary | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding($false)))
'VERIFY_JSON=' + $sp
