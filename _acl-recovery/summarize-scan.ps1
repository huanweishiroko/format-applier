param(
  [string]$Json = 'E:\dsh_plugins\word-format-applier\_acl-recovery\scan-result.json',
  [string]$Out  = 'E:\dsh_plugins\word-format-applier\_acl-recovery\scan-summary.txt'
)
$d = Get-Content -LiteralPath $Json -Raw | ConvertFrom-Json
$root = $d.Root
$rootLen = $root.Length + 1
$lines = New-Object System.Collections.Generic.List[string]
function W($s) { $lines.Add([string]$s) }

W "ROOT=$($d.Root)  USER=$($d.User)"
W "SCANNED=$($d.ScannedAt)  ITEMS=$($d.TotalItems) dirs=$($d.TotalDirs) files=$($d.TotalFiles)"
W "ANOMALIES=$($d.AnomalyCount)  SCAN_ERRORS=$(@($d.ScanErrors).Count)"
W "TYPE_HISTOGRAM:"
foreach ($k in ($d.TypeHistogram.PSObject.Properties | Sort-Object { -$_.Value })) { W ("  {0,-24} {1}" -f $k.Name, $k.Value) }

W ""
W "=== TOP-LEVEL SUBTREE BREAKDOWN (anomaly counts) ==="
$agg = @{}
foreach ($a in $d.Anomalies) {
  $rel = $a.Path.Substring([Math]::Min($rootLen, $a.Path.Length))
  $top = ($rel -split '\\')[0]
  if (-not $agg.ContainsKey($top)) { $agg[$top] = @{ n = 0; types = @{}; dirs = 0; files = 0 } }
  $agg[$top].n++
  if ($a.Kind -eq 'dir') { $agg[$top].dirs++ } else { $agg[$top].files++ }
  foreach ($t in ($a.Types -split ',')) { if ($agg[$top].types.ContainsKey($t)) { $agg[$top].types[$t]++ } else { $agg[$top].types[$t] = 1 } }
}
foreach ($k in ($agg.Keys | Sort-Object)) {
  $v = $agg[$k]
  W ("  {0,-42} n={1,-6} dirs={2,-5} files={3,-6} :: {4}" -f $k, $v.n, $v.dirs, $v.files, (($v.types.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ' '))
}

W ""
W "=== DIRS WITH OWNER_NOT_ME (first 40) ==="
$i = 0
foreach ($a in ($d.Anomalies | Where-Object { $_.Kind -eq 'dir' -and $_.Types -match 'OWNER_NOT_ME' })) {
  $i++; if ($i -gt 40) { W "  ... (more)"; break }
  W ("  {0,-6} {1}" -f $a.Owner, $a.Path)
}

W ""
W "=== DIRS WITH SANDBOX_SID, by depth<=2 (all) ==="
foreach ($a in ($d.Anomalies | Where-Object { $_.Kind -eq 'dir' -and $_.Types -match 'SANDBOX_SID' })) {
  $rel = $a.Path.Substring([Math]::Min($rootLen, $a.Path.Length))
  $depth = ($rel -split '\\').Count
  if ($depth -le 3) { W ("  d{0} {1,-28} sids={2} :: {3}" -f $depth, $a.Types, $a.SpecialSids, $rel) }
}

W ""
W "=== DIRS WITH INHERITANCE_BLOCKED (all) ==="
foreach ($a in ($d.Anomalies | Where-Object { $_.Kind -eq 'dir' -and $_.Types -match 'INHERITANCE_BLOCKED' })) {
  $rel = $a.Path.Substring([Math]::Min($rootLen, $a.Path.Length))
  W ("  {0} :: {1}" -f $a.Types, $rel)
}

W ""
W "=== FILES (non-.venv) WITH ANOMALIES (grouped) ==="
$fg = @{}
foreach ($a in ($d.Anomalies | Where-Object { $_.Kind -eq 'file' -and $_.Path -notlike '*\.venv\*' })) {
  $dir = [System.IO.Path]::GetDirectoryName($a.Path).Substring([Math]::Min($rootLen, [System.IO.Path]::GetDirectoryName($a.Path).Length))
  if (-not $fg.ContainsKey($dir)) { $fg[$dir] = 0 }
  $fg[$dir]++
}
foreach ($k in ($fg.Keys | Sort-Object)) { W ("  {0,-70} {1}" -f $k, $fg[$k]) }

W ""
W "=== SPECIAL SID VALUES SEEN ==="
$sids = @{}
foreach ($a in $d.Anomalies) { if ($a.SpecialSids) { foreach ($s in ($a.SpecialSids -split '\|')) { if ($sids.ContainsKey($s)) { $sids[$s]++ } else { $sids[$s] = 1 } } } }
if ($sids.Count -eq 0) { W "  (none)" } else { foreach ($k in ($sids.Keys | Sort-Object)) { W ("  {0,-28} {1}" -f $k, $sids[$k]) } }

W ""
W "=== ROOT-LEVEL ANOMALY FILES (max 40, non-.venv, non-sandbox-only) ==="
$i = 0
foreach ($a in ($d.Anomalies | Where-Object { $_.Kind -eq 'file' -and $_.Path -notlike '*\.venv\*' })) {
  $i++; if ($i -gt 40) { break }
  W ("  {0} :: {1}" -f $a.Types, $a.Path)
}

$lines | Set-Content -LiteralPath $Out -Encoding UTF8
"summary written: $Out  ($($lines.Count) lines)"
