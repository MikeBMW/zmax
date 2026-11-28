$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$exe  = 'D:\ZMAX\Z-MAX_Console.exe'
$cam  = 'D:\ZMAX\server\cam_live_stream.py'
$args = "`"$cam`" --port 8793 --local2-url `"http://10.163.149.123:8812/frame.jpg`" --local2-label `"🎥 中央相机 (Intel 8812)`" --local2-fps 8"

Write-Host ("启动: " + $args)
Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory 'D:\ZMAX' -WindowStyle Hidden
Start-Sleep -Seconds 9

$n = @(Get-CimInstance Win32_Process -Filter "Name='Z-MAX_Console.exe'" |
        Where-Object { $_.CommandLine -like '*cam_live_stream*' }).Count
Write-Host ("worker 数量: " + $n)
try {
    $s = Invoke-RestMethod -Uri 'http://127.0.0.1:8793/stats' -TimeoutSec 8
    foreach ($k in 'local', 'local2') {
        $v = $s.$k
        Write-Host ("  {0,-7} online={1,-5} fps={2,-6} label={3}" -f $k, $v.online, $v.fps, $v.label)
    }
} catch {
    Write-Host ("  取 stats 失败: " + $_.Exception.Message)
}
