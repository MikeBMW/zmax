# Z-MAX console launcher
# - starts the exe with cwd=D:\ZMAX and ZMAX_ROOT/ZMAX_REPO set (same contract as 启动控制台.bat)
# - single instance: brings the running window to front instead of starting a second one
# - kills orphaned worker processes (parent gone) that still hold 8793/8797/8802
# - nudges the window once so the home page "Modules" grid reflows (known cold-start UI bug)

Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Zw {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool repaint);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$exe  = 'D:\ZMAX\Z-MAX_Console.exe'
$root = 'D:\ZMAX'

if (-not (Test-Path $exe)) {
    [void][System.Windows.Forms.MessageBox]::Show("Z-MAX_Console.exe not found under $root", 'Z-MAX')
    return
}

$procs = @(Get-CimInstance Win32_Process -Filter "Name='Z-MAX_Console.exe'")
$main  = @($procs | Where-Object { $_.CommandLine -notmatch '\.py' })

# --- already running: raise the existing window, do not start a second instance
if ($main.Count -gt 0) {
    $h = (Get-Process -Id $main[0].ProcessId -ErrorAction SilentlyContinue).MainWindowHandle
    if ($h -ne $null -and $h -ne 0) {
        [void][Zw]::ShowWindow([IntPtr]$h, 9)
        [void][Zw]::SetForegroundWindow([IntPtr]$h)
        # 首页「功能模块」冷启动会被压成 0 高 (ReflowCardRow 不 reflow) ⇒ 点图标也算一次"修一下"
        Start-Sleep -Milliseconds 600
        $r = New-Object Zw+RECT
        [void][Zw]::GetWindowRect([IntPtr]$h, [ref]$r)
        $w = $r.Right - $r.Left
        $ht = $r.Bottom - $r.Top
        if ($w -gt 400) {
            [void][Zw]::MoveWindow([IntPtr]$h, $r.Left, $r.Top, $w - 160, $ht, $true)
            Start-Sleep -Milliseconds 1200
            [void][Zw]::MoveWindow([IntPtr]$h, $r.Left, $r.Top, $w, $ht, $true)
        }
    }
    return
}

# --- orphaned workers (their parent process is gone) hold the service ports
$ids = @($procs | ForEach-Object { $_.ProcessId })
$orphans = @($procs | Where-Object { $_.CommandLine -match '\.py' -and ($ids -notcontains $_.ParentProcessId) })
foreach ($w in $orphans) { Stop-Process -Id $w.ProcessId -Force -ErrorAction SilentlyContinue }
if ($procs.Count -gt 0) { Start-Sleep -Seconds 2 }

$env:ZMAX_ROOT = $root + '\'
$env:ZMAX_REPO = $root
# 2026-11-25: 手臂相机(D405)取帧源 —— 本机 rokae/orin 转发口(18792)没起, 直接连 Orin 的 JPEG 通道。
#   cam_live_stream.py 的 arm_http_worker 用 ZMAX_ARM_HTTP_FALLBACK 作为候选源(逗号分隔, 失败自动切下一条)。
$env:ZMAX_ARM_HTTP_FALLBACK = 'http://192.168.23.66:8792/frame.jpg,http://192.168.23.66:8794/frame.jpg'
# 位姿真值: 本机 tcp_out/latest.json 常年不存在 ⇒ 用 Orin 珞石桥 39061 (endInRef, 5Hz)。
$env:ZMAX_ORIN_SDK_URL = 'http://192.168.23.66:39061/status'
# 2026-11-25: nvidia-smi 静默包装 (首页硬件卡每 ~2s 调一次 → 每次闪一个控制台黑窗)
#   D:\ZMAX\_stubs\nvidia-smi.exe = winexe 包装, 真实转发系统 nvidia-smi, 不创建控制台窗口
$env:PATH = Join-Path $root '_stubs' | ForEach-Object { if (Test-Path $_) { "$_;$env:PATH" } else { $env:PATH } }

# ── 2026-11-26 v5.50.786: 工位总览(8793) 必须**在主程序之前**起 ────────────────────────
#   理由: 主程序自己会拉一版"裸"的 cam_live_stream (只有 --port 8793, 没有 local2),
#         而且它不看端口是否已被占用。先起带参数的这份, 主程序那份 bind 失败就退出了,
#         页面用的就是带参数的这个。
#   中央相机 = Intel 550C 的 USB 顶摄: http://192.168.23.70:8812/frame.jpg (640x480)
#   ⚠ 关键: 不设 ZMAX_CAM_LOCAL=1 的话, --no-local2 默认 = not(env) = True,
#           local / local2 两路都会被**静默跳过** —— 页面那格永远"无帧"且没有任何报错。
$env:ZMAX_CAM_LOCAL = '1'
try {
    if (-not (Get-NetTCPConnection -LocalPort 8793 -State Listen -ErrorAction SilentlyContinue)) {
        $cam = if (Test-Path "$root\server\cam_live_stream.py") { "$root\server\cam_live_stream.py" } else { "$root\tools\cam_live_stream.py" }
        Start-Process -FilePath $exe -ArgumentList "`"$cam`" --port 8793 --local2-url `"http://192.168.23.70:8812/frame.jpg`" --local2-label `"🎥 中央相机 (Intel 8812)`" --local2-fps 8" -WorkingDirectory $root -WindowStyle Hidden
        Start-Sleep -Milliseconds 1800
    }
} catch { }

# ── 2026-11-26: 卡拉比丘流形 (8810) —— 画布工具栏「🧿 弦」按钮的目标服务 ──────────────
#   按钮点了先探活 8810, 服务没起只会给一句"不可达"。这里随控制台一起拉起,
#   端口已听就跳过。只读服务, 不下发任何动作, 也不开窗口。
try {
    if (-not (Get-NetTCPConnection -LocalPort 8810 -State Listen -ErrorAction SilentlyContinue)) {
        $cy = if (Test-Path "$root\server\cy_slice_server.py") { "$root\server\cy_slice_server.py" } else { "$root\tools\cy_slice_server.py" }
        Start-Process -FilePath $exe -ArgumentList "`"$cy`"" -WorkingDirectory $root -WindowStyle Hidden
    }
} catch { }

# 2026-11-25: 禁弹窗守护 —— 已停用。
#   根因已用 IFEO 静默转发根治 (HKLM\...\Image File Execution Options\nvidia-smi.exe / ps.exe
#   → D:\ZMAX\_stubs\ife_wrap.exe, 子进程带 CREATE_NO_WINDOW, 根本不产生控制台窗口)。
#   保留下面几行仅作历史参考: 这层 WinEvent hook 守护长期跑会自己崩(18:50 就是这样崩的),
#   反而成了新的弹窗来源。
# 禁止弹窗守护(nopop)已停用: 根因改用 IFEO 静默转发根治, 那层 WinEvent hook 长期跑会自己崩。

$p = Start-Process -FilePath $exe -WorkingDirectory $root -PassThru

# 2026-11-25: 本机微型服务 —— 产品大屏(8799) / AR 3D(8797)。冻结包里**没有**这两个常驻进程
#   (local_services.py 的注释明说), 而界面的「产品服务」「AR 3D」按钮直接依赖它们 ⇒ 点了打不开。
#   这里随控制台一起用自带解释器拉起(stdlib 脚本, 不依赖机器上装 Python); 端口已在听就跳过。
try {
    if (-not (Get-NetTCPConnection -LocalPort 8799 -State Listen -ErrorAction SilentlyContinue)) {
        # 5.50.786: 标准服务统一走 server\ (不存在则回落 tools\, 保持老包兼容)
        $srv = if (Test-Path "$root\server\dashboard_server.py") { "$root\server\dashboard_server.py" } else { "$root\tools\dashboard_server.py" }
        Start-Process -FilePath $exe -ArgumentList "`"$srv`"" -WorkingDirectory $root -WindowStyle Hidden
    }
} catch { }
try {
    if (-not (Get-NetTCPConnection -LocalPort 8797 -State Listen -ErrorAction SilentlyContinue)) {
        $srv = if (Test-Path "$root\server\tcp_ar_server.py") { "$root\server\tcp_ar_server.py" } else { "$root\tools\tcp_ar_server.py" }
        Start-Process -FilePath $exe -ArgumentList "`"$srv`" --port 8797" -WorkingDirectory $root -WindowStyle Hidden
    }
} catch { }
# --- wait for the REAL main window: the first window is a loading window titled
#     "Z-MAX_Console"; the console itself comes up as "XSpace ..." later.
$deadline = (Get-Date).AddSeconds(180)
$h = [IntPtr]::Zero
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 700
    $pr = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
    if (-not $pr) { return }
    $pr.Refresh()
    if ($pr.MainWindowHandle -ne 0 -and $pr.MainWindowTitle -match 'XSpace') { $h = [IntPtr]$pr.MainWindowHandle; break }
}
if ($h -eq [IntPtr]::Zero) { return }

# --- let the home page build, then force reflows (cards are clipped to height 0 otherwise).
#     Twice: once right after show (first paint), once after the async cards land.
#     5.50.786: 6+12+12 → 3+5+5 秒 (总 32.4s → 13.2s)。老倪反馈"打开很慢/要点两次":
#       旧脚本在主窗口出现后还要静默跑 30 秒的 MoveWindow, 期间窗口会被缩 160px 再还原,
#       点击正好落在这两次改尺寸之间就丢 → 感觉"点一次没反应"。
Start-Sleep -Seconds 3
for ($k = 0; $k -lt 2; $k++) {
    $r = New-Object Zw+RECT
    [void][Zw]::GetWindowRect($h, [ref]$r)
    $w = $r.Right - $r.Left
    $ht = $r.Bottom - $r.Top
    if ($w -gt 400) {
        [void][Zw]::MoveWindow($h, $r.Left, $r.Top, $w - 160, $ht, $true)
        Start-Sleep -Milliseconds 700
        [void][Zw]::MoveWindow($h, $r.Left, $r.Top, $w, $ht, $true)
    }
    Start-Sleep -Seconds 5
}
