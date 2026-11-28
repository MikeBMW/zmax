$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = 'D:\ZMAX'
$exe  = 'D:\ZMAX\Z-MAX_Console.exe'

Get-CimInstance Win32_Process -Filter "Name='Z-MAX_Console.exe'" |
    Where-Object { $_.CommandLine -like '*tcp_ar_server*' } |
    ForEach-Object { Write-Host ("停止旧 8797: " + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3

$srv = Join-Path $root 'server\tcp_ar_server.py'
Start-Process -FilePath $exe -ArgumentList "`"$srv`" --port 8797" -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput "$root\zmax_data\logs\tcp_ar_8797.out.log" `
    -RedirectStandardError  "$root\zmax_data\logs\tcp_ar_8797.err.log"
Start-Sleep -Seconds 8

try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8797/' -TimeoutSec 8 -UseBasicParsing
    Write-Host ("8797 http=" + $r.StatusCode + " bytes=" + $r.RawContentLength)
} catch {
    Write-Host ("8797 失败: " + $_.Exception.Message)
}
Write-Host '--- err 尾 ---'
if (Test-Path "$root\zmax_data\logs\tcp_ar_8797.err.log") { Get-Content "$root\zmax_data\logs\tcp_ar_8797.err.log" -Tail 12 }
Write-Host '--- out 尾 ---'
if (Test-Path "$root\zmax_data\logs\tcp_ar_8797.out.log") { Get-Content "$root\zmax_data\logs\tcp_ar_8797.out.log" -Tail 8 }
