# Single-instance launcher for a frozen GUI app (copy, then replace the three placeholders).
# Chain: .lnk -> wscript launch_app.vbs -> this script (hidden PowerShell, no console flash).
# Keeps the launcher ASCII-only: PowerShell 5.1 reads a BOM-less UTF-8 .ps1 as ANSI and a
# stray non-ASCII char inside a string literal breaks parsing.
#
# Placeholders:  <APP_ROOT>  <EXE_NAME>  <PRODUCT_TITLE>   (and the root env vars it needs)
# Behaviour:  correct cwd + root env  ->  single instance  ->  kill orphan workers  ->
#             wait for the REAL window  ->  post-start workaround (reflow nudge).

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

$exe    = '<APP_ROOT>\<EXE_NAME>'
$root   = '<APP_ROOT>'
$title  = '<PRODUCT_TITLE>'      # real window title; the first window is usually named after the exe

if (-not (Test-Path $exe)) {
    [void][System.Windows.Forms.MessageBox]::Show("$exe not found", 'Launcher')
    return
}

$procs = @(Get-CimInstance Win32_Process -Filter "Name='<EXE_NAME>'")
# a bare exe (no .py/.js argument) is the GUI; helpers are self-invocations with a script argument
$main  = @($procs | Where-Object { $_.CommandLine -notmatch '\.(py|js)' })

function Nudge($h) {
    # forces one Qt/Electron layout pass: cold-start panels that collapse to height 0 come back
    $r = New-Object Zw+RECT
    [void][Zw]::GetWindowRect($h, [ref]$r)
    $w = $r.Right - $r.Left; $ht = $r.Bottom - $r.Top
    if ($w -le 400) { return }
    [void][Zw]::MoveWindow($h, $r.Left, $r.Top, ($w - 160), $ht, $true)
    Start-Sleep -Milliseconds 1200
    [void][Zw]::MoveWindow($h, $r.Left, $r.Top, $w, $ht, $true)
}

if ($main.Count -gt 0) {
    $h = (Get-Process -Id $main[0].ProcessId -ErrorAction SilentlyContinue).MainWindowHandle
    if ($h -ne $null -and $h -ne 0) {
        [void][Zw]::ShowWindow([IntPtr]$h, 9)
        [void][Zw]::SetForegroundWindow([IntPtr]$h)
        Nudge ([IntPtr]$h)      # clicking the icon doubles as "fix the empty panel"
    }
    return
}

# orphans (parent gone) squat the service ports and make the next launch show empty sections
$ids = @($procs | ForEach-Object { $_.ProcessId })
foreach ($w in @($procs | Where-Object { $_.CommandLine -match '\.(py|js)' -and ($ids -notcontains $_.ParentProcessId) })) {
    Stop-Process -Id $w.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($procs.Count -gt 0) { Start-Sleep -Seconds 2 }

$env:<ROOT_ENV> = $root + '\'
$p = Start-Process -FilePath $exe -WorkingDirectory $root -PassThru

# MainWindowHandle != 0 does NOT mean the UI is up: wait for the product title
$deadline = (Get-Date).AddSeconds(180)
$h = [IntPtr]::Zero
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 700
    $pr = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
    if (-not $pr) { return }
    $pr.Refresh()
    if ($pr.MainWindowHandle -ne 0 -and $pr.MainWindowTitle -match [regex]::Escape($title)) {
        $h = [IntPtr]$pr.MainWindowHandle; break
    }
}
if ($h -eq [IntPtr]::Zero) { return }

Start-Sleep -Seconds 6          # let the page build
Nudge $h
Start-Sleep -Seconds 12
Nudge $h                        # twice: the home page is built asynchronously
