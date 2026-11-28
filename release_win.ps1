# release_win.ps1 — Windows 发布一条龙（闸 → 提交打 tag → CI → 下载校验 → 替换重启）
#
# 用法（在 D:\ZMAX 下，PowerShell）：
#   .\release_win.ps1 -Version 5.50.787                    # 只做闸 + 提交打 tag + 推 + 等 CI + 下载校验（不动在跑的窗口）
#   .\release_win.ps1 -Version 5.50.787 -Apply             # 再加：停控制台 → 备份 → 换包 → 重启 → 验收
#   .\release_win.ps1 -Tag v5.50.786 -SkipCommit           # 已有 tag：直接从 CI 下载并校验/替换
#   .\release_win.ps1 -GateOnly                            # 只跑本地闸（快）
#
# 设计原则
#   · 每一步都先取证再动手；任何一步失败立刻停，不硬着头皮往下走。
#   · 换包前必须 0 个 Z-MAX_Console 进程；备份目录 _bak_<时间戳>，可回滚。
#   · 下载走断点续传 + 重试（外网这条链路实测会断）。
#
param(
    [string]$Version = "",
    [string]$Tag = "",
    [switch]$Apply,
    [switch]$SkipCommit,
    [switch]$GateOnly,
    [int]$CIPollMinutes = 45
)

$ErrorActionPreference = 'Stop'
$root = 'D:\ZMAX'
$repo = 'D:\ZMAX'
$exe  = Join-Path $root 'Z-MAX_Console.exe'
$work = 'D:\_build'
$api  = 'https://api.github.com/repos/MikeBMW/zmax'

function Step($n, $msg) { Write-Host ""; Write-Host ("=== $n) $msg") -ForegroundColor Cyan }
function Ok($msg)   { Write-Host ("   ✓ " + $msg) -ForegroundColor Green }
function Bad($msg)  { Write-Host ("   ✗ " + $msg) -ForegroundColor Red }
function Warn($msg) { Write-Host ("   ! " + $msg) -ForegroundColor Yellow }

# ---------------------------------------------------------------- 1) 本地闸
Step 1 '本地闸（版本一致性 / 软链 / 弹窗）'
Push-Location $repo
try {
    if ($Version -eq "" -and $Tag -eq "") {
        $Version = (Select-String -Path 'tools\gui\update_checker.py' -Pattern 'CURRENT_VERSION\s*=\s*"v([\d.]+)"').Matches[0].Groups[1].Value
        Warn "未指定 -Version，取源码里的 $Version"
    }
    if ($Version -ne "") {
        $hits = @()
        $hits += (Select-String -Path 'tools\gui\update_checker.py' -Pattern "v$Version" -Quiet)
        $hits += (Select-String -Path 'tools\gui\version_sync.py'     -Pattern "$Version" -Quiet)
        $hits += (Select-String -Path 'tools\gui\studio.py'           -Pattern "$Version" -Quiet)
        $hits += (Select-String -Path 'VERSION.md'                    -Pattern "$Version" -Quiet)
        if ($hits -contains $false) { Bad "版本 $Version 在 update_checker/version_sync/studio/VERSION.md 里没全落地: $($hits -join ',')"; throw "版本号不一致" }
        Ok "版本 $Version 四处一致"
    }

    $bad = & git ls-tree -r -l HEAD | Select-String '^120000 blob' | ForEach-Object {
        $f = ($_ -split '\s+', 5)
        if ([int]$f[3] -gt 200) { $f[4] }
    }
    if ($bad) { Bad ("软链闸失败（软链目标串=整份文件，打包机 checkout 会 Filename too long）: " + ($bad -join ', ')); throw "软链闸" }
    Ok '软链闸通过（无 120000 且 >200B 的条目）'

    python tools/ci/check_console_popup.py --paths tools server src
    if ($LASTEXITCODE -ne 0) { throw "弹窗闸失败：GUI 侧有会闪黑窗的子进程调用" }
    Ok '弹窗闸通过'

    if (-not (Test-Path 'tools\gui\portal_urls.py')) { Warn 'tools\gui\portal_urls.py 不在（产品服务候选链会缺）' }
}
finally { Pop-Location }

if ($GateOnly) { Ok '只跑闸，结束'; return }

# ---------------------------------------------------------------- 2) 提交 + tag
if (-not $SkipCommit) {
    Step 2 "提交并打 tag v$Version"
    Push-Location $repo
    try {
        $dirty = & git status --porcelain | Where-Object { $_ -notmatch '^\?\?' }
        if ($dirty) {
            & git add -u
            foreach ($f in @('tools\gui\portal_urls.py', 'tools\gui\nowin.py',
                             'tools\ci\check_console_popup.py', 'tools\ci\fix_symlink_shims.py')) {
                if (Test-Path $f) { & git add $f }
            }
            # ⚠ git add -u 会把「同步解引用过的软链 shim」再写坏（mode 120000 + 整份内容），
            #   打包机 checkout 直接 Filename too long ⇒ add 完立刻自愈一次。
            python tools\ci\fix_symlink_shims.py --fix | Out-Host
            & git add -u
            & git -c user.name='Mike.Ni' -c user.email='mike@zmax.local' commit -q -m "release(v$Version): Windows 发布"
            Ok "已提交 $(git log --oneline -1)"
        } else { Warn '工作区没有已跟踪改动' }
        $Tag = "v$Version"
        & git tag -d $Tag 2>$null | Out-Null
        & git push origin ":refs/tags/$Tag" 2>$null | Out-Null
        & git tag -a $Tag -m "v$Version Windows 发布"
        & git push origin main 2>&1 | Select-Object -Last 1
        & git push origin $Tag 2>&1 | Select-Object -Last 1
        Ok "已推 main + $Tag"
    } finally { Pop-Location }
}
if ($Tag -eq "") { $Tag = "v$Version" }

# ---------------------------------------------------------------- 3) 等 CI
Step 3 "等 CI 出包（$Tag，最多 $CIPollMinutes 分钟）"
$deadline = (Get-Date).AddMinutes($CIPollMinutes)
$runId = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 20
    try {
        $runs = Invoke-RestMethod -Uri "$api/actions/runs?per_page=5" -TimeoutSec 20
        $run = $runs.workflow_runs | Where-Object { $_.head_branch -eq $Tag } | Select-Object -First 1
        if (-not $run) { Write-Host '   … 还没创建 run'; continue }
        $runId = $run.id
        Write-Host ("   run " + $runId + " " + $run.status + " / " + $run.conclusion)
        if ($run.status -eq 'completed') { break }
    } catch { Warn ("查 CI 失败: " + $_.Exception.Message) }
}
if (-not $runId) { throw '等不到 CI run' }
$final = Invoke-RestMethod -Uri "$api/actions/runs/$runId" -TimeoutSec 20
if ($final.conclusion -ne 'success') {
    Bad "CI 失败: $($final.conclusion)  → 看 https://github.com/MikeBMW/zmax/actions/runs/$runId"
    throw "CI 失败"
}
Ok "CI 成功 run=$runId"

# ---------------------------------------------------------------- 4) 下载 + 校验
Step 4 '下载免解包版并校验（断点续传）'
New-Item -ItemType Directory -Path $work -Force | Out-Null
$zip = Join-Path $work "zmax_$Version.zip"
$rel = Invoke-RestMethod -Uri "$api/releases/tags/$Tag" -TimeoutSec 20
$asset = $rel.assets | Where-Object { $_.name -like '*nounpack.zip' } | Select-Object -First 1
if (-not $asset) { throw "Release 上没有 nounpack 资产" }
$want = [int64]$asset.size
for ($i = 1; $i -le 10; $i++) {
    $have = if (Test-Path $zip) { (Get-Item $zip).Length } else { 0 }
    if ($have -ge $want) { break }
    Write-Host ("   第 $i 轮：已有 " + [math]::Round($have/1MB,1) + " MB / " + [math]::Round($want/1MB,1) + " MB")
    & curl.exe -sSL -C - --retry 3 --retry-all-errors -m 2400 -o $zip $asset.browser_download_url
}
$have = (Get-Item $zip).Length
if ($have -ne $want) { throw "下载不完整: $have / $want" }
Ok ("下载完成 " + $have + " 字节（与 Release 声明一致）")

$dst = Join-Path $work "extract"
Remove-Item $dst -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $dst -Force | Out-Null
& "$env:SystemRoot\System32\tar.exe" -xf $zip -C $dst
if ($LASTEXITCODE -ne 0) { throw '解包失败（要用 Windows 自带 tar/bsdtar，GNU tar 不认 zip）' }
$newExe = Join-Path $dst 'Z-MAX_Console.exe'
$ver = (Get-Item $newExe).VersionInfo.FileVersion
if ($ver -ne $Version) { throw "包里 exe 版本 $ver ≠ $Version" }
Ok "包内 exe 文件版本 = $ver"
if (-not (Test-Path (Join-Path $dst '_internal'))) { throw '包内缺 _internal' }
Ok "_internal 存在（$( @(Get-ChildItem (Join-Path $dst '_internal') -Recurse -File).Count ) 个文件）"

# ---------------------------------------------------------------- 5) 替换（可选）
if (-not $Apply) {
    Warn "未加 -Apply：包已下好校验完，位置 $dst ，需要换包时重跑加 -Apply"
    return
}
Step 5 '停控制台 → 备份 → 换包 → 重启'
$procs = @(Get-Process Z-MAX_Console -ErrorAction SilentlyContinue)
if ($procs.Count -gt 0) {
    Warn ("要关掉 " + $procs.Count + " 个 Z-MAX_Console 进程（含 8793/8797/8799/8802 worker）")
    $procs | Stop-Process -Force
    Start-Sleep -Seconds 4
    if (@(Get-Process Z-MAX_Console -ErrorAction SilentlyContinue).Count -gt 0) { throw '还有进程没退干净，先手工关掉' }
}
Ok '进程已全关'

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$bak = Join-Path $root "_bak_$stamp"
New-Item -ItemType Directory -Path $bak -Force | Out-Null
Copy-Item $exe $bak -Force
if (Test-Path (Join-Path $root '_internal')) { Move-Item (Join-Path $root '_internal') (Join-Path $bak '_internal_old') -Force }
Copy-Item $newExe (Join-Path $root 'Z-MAX_Console.exe') -Force
Copy-Item (Join-Path $dst '_internal') (Join-Path $root '_internal') -Recurse -Force
Ok "已换包，备份在 $bak"

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'launch_zmax.ps1') | Out-Null
Start-Sleep -Seconds 25
$ports = 8793, 8797, 8799, 8802
foreach ($p in $ports) {
    $code = & curl.exe -sS -o NUL -m 5 -w '%{http_code}' "http://127.0.0.1:$p/"
    Write-Host ("   端口 $p → $code")
}
$v = (Get-Item $exe).VersionInfo.FileVersion
Ok "在役 exe 版本 = $v"
Warn '黑窗复查：python <skill>/scripts/winhook.py 40，期望 0 个窗口 show 事件'
