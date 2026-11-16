# awesun_health.ps1 - read-only health snapshot for Oray AweSun / SunLogin on Windows.
# ASCII-only output (GBK console safe). Does NOT start/stop/restart anything.
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File awesun_health.ps1
$ErrorActionPreference = 'SilentlyContinue'

function Sec($t) { Write-Output ''; Write-Output ('== ' + $t + ' ==') }

Sec 'PROCESSES'
$procs = Get-CimInstance Win32_Process -Filter "Name='AweSun.exe' or Name='awesun_guard.exe'"
if (-not $procs) { Write-Output 'none (client not running)' }
foreach ($p in $procs) {
  $cl = [string]$p.CommandLine
  $mode = 'gui'
  if ($cl -match '--mod=service')   { $mode = 'service' }
  elseif ($cl -match '--mod=watch') { $mode = 'watch' }
  elseif ($cl -match 'awesun_guard'){ $mode = 'guard' }
  elseif ($cl -match '--admin=1')   { $mode = 'gui-admin' }
  Write-Output ('pid={0} mode={1} start={2}' -f $p.ProcessId, $mode, $p.CreationDate)
}

Sec 'SERVICES'
foreach ($n in 'AweSunService','SunloginService') {
  $s = Get-Service $n
  if ($s) {
    Write-Output ('name={0} status={1} starttype={2}' -f $s.Name, $s.Status, $s.StartType)
    $qc = sc.exe qc $n | Select-String 'BINARY_PATH_NAME'
    if ($qc) { Write-Output ('  ' + (($qc -join ' ') -replace '\s+', ' ')) }
  } else { Write-Output ('name={0} not installed' -f $n) }
}
Write-Output 'note: an upgraded install leaves SunloginService as a dead shell; AweSunService is the live one.'

Sec 'ONLINE (only these lines mean reachable)'
$svc = $procs | Where-Object { $_.CommandLine -match '--mod=service' } | Select-Object -First 1
if ($svc) {
  $conn = Get-NetTCPConnection -OwningProcess $svc.ProcessId -State Established
  if ($conn) {
    foreach ($c in $conn) { Write-Output ('established -> {0}:{1} (service pid {2})' -f $c.RemoteAddress, $c.RemotePort, $svc.ProcessId) }
  } else { Write-Output 'NO established outbound connection from service pid (offline)' }
} else { Write-Output 'NO service-mode process running (offline)' }

Sec 'NEWEST SERVICE LOG'
$dirs = @(
  (Join-Path $env:ProgramFiles 'Oray\AweSun\log'),
  (Join-Path $env:APPDATA      'Oray\AweSun\log')
)
$best = $null
foreach ($d in $dirs) {
  foreach ($f in (Get-ChildItem $d -Filter 'awesun_service*.log' -ErrorAction SilentlyContinue)) {
    if (-not $best -or $f.LastWriteTime -gt $best.LastWriteTime) { $best = $f }
  }
}
if ($best) {
  Write-Output ('file=' + $best.FullName)
  Write-Output ('mtime=' + $best.LastWriteTime)
  Write-Output ('service pid start=' + $(if ($svc) { $svc.CreationDate } else { 'n/a' }))
  Write-Output '-- if mtime/service-start indicate a dead run, the live log is in the OTHER dir --'
  Select-String -Path $best.FullName -Pattern 'change status to|logon slsvr|online disconnected|SERVICE_CONTROL_STOP' |
    Select-Object -Last 12 | ForEach-Object { Write-Output ('  ' + ([string]$_.Line).Trim()) }
} else { Write-Output 'no awesun_service*.log found' }
