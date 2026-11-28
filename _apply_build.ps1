# apply_build.ps1 —— 把 dist_nounpack 的新包替换到 D:\ZMAX（老倪重启控制台时用）
#
# 用法：先【关掉 Z-MAX 控制台】（所有 Z-MAX_Console 进程），再双击本脚本 / 或跑：
#   powershell -NoProfile -ExecutionPolicy Bypass -File D:\ZMAX\_apply_build.ps1
#
# 它做四件事：
#   ① 确认控制台已经关干净（还开着就拒绝，避免半覆盖把 exe 弄坏）
#   ② 备份现有 Z-MAX_Console.exe + version.txt 到 _bak_<时间戳>\
#   ③ 复制新 exe 与 _internal\ 过去
#   ④ 报告新旧大小/时间，并提示可以重开控制台

$ErrorActionPreference = 'Stop'
$root = 'D:\ZMAX'
$src  = Join-Path $root 'tools\gui\dist_nounpack\Z-MAX_Console'

Write-Host '=== 1) 检查控制台是否已关闭 ===' -ForegroundColor Cyan
$procs = Get-Process Z-MAX_Console -ErrorAction SilentlyContinue
if ($procs) {
    Write-Host "❌ 还有 $($procs.Count) 个 Z-MAX_Console 进程在跑 (pid: $($procs.Id -join ', '))" -ForegroundColor Red
    Write-Host '   先关掉控制台（任务栏右下角退出 / 任务管理器结束进程），再跑本脚本。' -ForegroundColor Yellow
    Write-Host '   现在替换会把 exe 写坏（文件占用）。' -ForegroundColor Yellow
    exit 1
}
Write-Host '   ✓ 没有控制台进程' -ForegroundColor Green

Write-Host '=== 2) 检查新包 ===' -ForegroundColor Cyan
$newExe = Join-Path $src 'Z-MAX_Console.exe'
if (-not (Test-Path $newExe)) {
    Write-Host "❌ 新包不存在: $newExe" -ForegroundColor Red
    Write-Host '   先等打包跑完（看 tools\gui\dist_nounpack 是否生成）。' -ForegroundColor Yellow
    exit 1
}
$newT = (Get-Item $newExe).LastWriteTime
$newS = [math]::Round((Get-Item $newExe).Length / 1MB, 1)
$newAll = [math]::Round((Get-ChildItem $src -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "   新 exe: ${newS}MB  打包于 $newT   整包 ${newAll}MB" -ForegroundColor Green

Write-Host '=== 3) 备份旧版 ===' -ForegroundColor Cyan
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$bak = Join-Path $root "_bak_$stamp"
New-Item -ItemType Directory -Path $bak -Force | Out-Null
if (Test-Path (Join-Path $root 'Z-MAX_Console.exe')) {
    Copy-Item (Join-Path $root 'Z-MAX_Console.exe') $bak -Force
    Write-Host "   ✓ 旧 exe → $bak" -ForegroundColor Green
}
if (Test-Path (Join-Path $root 'VERSION.txt')) {
    Copy-Item (Join-Path $root 'VERSION.txt') $bak -Force
}

Write-Host '=== 4) 替换 exe 与 _internal ===' -ForegroundColor Cyan
Copy-Item $newExe (Join-Path $root 'Z-MAX_Console.exe') -Force
Write-Host '   ✓ Z-MAX_Console.exe' -ForegroundColor Green

$oldInt = Join-Path $root '_internal'
if (Test-Path $oldInt) {
    Write-Host '   旧 _internal 改名归档（不删，出事能退）…'
    Move-Item $oldInt (Join-Path $bak '_internal_old') -Force
}
Copy-Item (Join-Path $src '_internal') (Join-Path $root '_internal') -Recurse -Force
Write-Host '   ✓ _internal\' -ForegroundColor Green

Write-Host ''
Write-Host '=== 完成 ===' -ForegroundColor Green
Write-Host "   备份在: $bak"
Write-Host '   现在可以重开控制台（双击桌面「Z-MAX 控制台」）。'
Write-Host '   打开后：画布工具栏「🧮 状态空间」右边应该多一个紫色「🧿 弦」按钮。'
Write-Host ''
Write-Host '   如果按钮没有 / 控制台打不开，把 _bak 里的 Z-MAX_Console.exe 和 _internal_old 换回来即可。'
