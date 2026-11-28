# AOI 检测系统 自检脚本  (Z-MAX v5.50.786, 2026-11-26)
# 用法: 在工控机上右键 -> 使用 PowerShell 运行; 或者双击 AOI_check.bat
# 只读, 不改任何东西。结果同时打印到屏幕 + 存到桌面 AOI_check_<时间>.txt

$ErrorActionPreference = "SilentlyContinue"
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "AOI_check_$ts.txt"
$lines = New-Object System.Collections.ArrayList

function W($s) { Write-Host $s; [void]$lines.Add($s) }
function Line { W ("-" * 72) }

W "AOI 自检  $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  机器: $env:COMPUTERNAME"
W ""

# ---------- 1. 端口 ----------
Line
W "[1] 两个服务端口"
foreach ($p in 10082, 10083) {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen
    if ($c) {
        $proc = Get-Process -Id $c[0].OwningProcess
        W ("  :$p  在听   PID=$($c[0].OwningProcess)  进程=$($proc.ProcessName)")
        if ($proc.Path) { W ("        路径: $($proc.Path)") }
        if ($proc.StartTime) { W ("        启动: $($proc.StartTime)  (已运行 {0:N0} 分钟)" -f ((Get-Date) - $proc.StartTime).TotalMinutes) }
    } else {
        W "  :$p  没有监听 (服务没起 / 已停)"
    }
}
W ""

# ---------- 2. 所有 python 进程 ----------
Line
W "[2] 全部 python 进程 (判断是不是有守护在拉)"
$pys = Get-CimInstance Win32_Process -Filter "Name like '%python%'" |
       Select-Object ProcessId, Name, CommandLine
if ($pys) {
    foreach ($q in $pys) {
        W ("  PID {0,6}  {1}" -f $q.ProcessId, $q.Name)
        if ($q.CommandLine) { W ("            $($q.CommandLine.Substring(0, [Math]::Min(150, $q.CommandLine.Length)))") }
    }
} else {
    W "  没有 python 进程在跑"
}
W ""

# ---------- 3. 相机参数 ----------
Line
W "[3] 相机取像参数"
foreach ($p in 10082, 10083) {
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$p/param" -TimeoutSec 6
        $n = $r.now
        W ("  :$p  曝光={0}us  增益={1}dB  gamma={2}  机型={3}" -f $n.exposure_us, $n.gain_db, $n.gamma_val, $n.model)
        if ($n.sn) { W ("        SN: $($n.sn)") }
    } catch {
        W "  :$p  读不到 /param (这个服务可能没这个端点)"
    }
}
W "  标定参考: 金手指(10082) 3000us x 1.8dB   |   表面(10083) 20000us x 8dB"
W ""

# ---------- 4. 最后判决 ----------
Line
W "[4] 最后一次检测结果"
foreach ($p in 10082, 10083) {
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$p/last_result" -TimeoutSec 6
        W ("  :$p  n={0}  verdict={1}  缺陷={2}  用时={3}ms  type={4}" -f $r.n, $r.verdict, $r.count, $r.ms, $r.detect_type)
        if ($r.judge_ok -eq $false) { W "        !! judge_ok=false: $($r.judge_why)" }
        if ($r.saved_incoming) { W ("        存图: $($r.saved_incoming)") }
        # 金手指专有指标
        if ($null -ne $r.gold_cover) { W ("        gold_cover=$($r.gold_cover)  stripe_cols=$($r.stripe_cols)") }
    } catch {
        W "  :$p  还没有结果 (冷启动后第一次检测前是正常的)"
    }
}
W ""

# ---------- 5. 判读提示 ----------
Line
W "[5] 怎么读上面的结果"
W "  · verdict=OK 但 gold_cover=0 且 stripe_cols=0  => 画面里没产品, OK 是假阳性"
W "  · 曝光 20000us 以上 + 金手指 => 会死白(镀金镜面), 应改 3000us"
W "  · 曝光 3000us + 空背景 => 全黑是正常的, 等产品进画面才亮"
W ""

# ---------- 保存 ----------
$lines | Out-File -FilePath $out -Encoding UTF8
Write-Host ""
Write-Host "结果已保存: $out" -ForegroundColor Green
Write-Host "按任意键关闭..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
