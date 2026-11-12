# 按名字点一个按钮 (UIAutomation), 用于远程 Windows 上驱动 GUI/网页按钮做取证。
# 为什么不用坐标: 图标按钮 OCR 出来是乱码, 点错一下就点了「停止/重启」; UIA 按 ControlType=Button + Name 子串定位, 与坐标无关。
#
# ⚠️ 必须在**登录用户的交互会话**里跑 (session 0 看不到用户桌面窗口), 用一次性计划任务:
#   $act = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File <this.ps1> -Match 仿真搬运'
#   $pr  = New-ScheduledTaskPrincipal -UserId '<机器>\<用户>' -LogonType Interactive -RunLevel Highest
#   Register-ScheduledTask -TaskName 'ZMAX_UIA' -Action $act -Principal $pr -Force; Start-ScheduledTask -TaskName 'ZMAX_UIA'
#   读结果文件 -> Unregister-ScheduledTask -TaskName 'ZMAX_UIA' -Confirm:$false
#
# 判据不认 "invoked" 这行: 点完去读页面/应用**自己上报的状态** (例 /api/ar_diag 的 trans 0->1), 别看有没有报错。
param(
  # Match='' = 只枚举不点击 (先看清这个页面上有哪些按钮再决定点哪个, 避免误点「停止/重启」)
  [string]$Match   = '',
  [string]$OutFile = "$env:TEMP\uia_click.txt"
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$out = @()
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condW = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window)
$wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condW)
$out += 'windows=' + $wins.Count
foreach ($w in $wins) {
  if (-not $w.Current.Name) { continue }
  $condB = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
  $btns = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condB)
  foreach ($b in $btns) {
    if ($Match -eq '' -or $b.Current.Name -like "*$Match*") {
      $out += "hit win='" + $w.Current.Name + "' btn='" + $b.Current.Name + "'"
      if ($Match -eq '') { continue }        # 枚举模式绝不下手
      try {
        $p = $b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $p.Invoke()
        $out += 'invoked'
      } catch {
        $out += 'invoke_failed: ' + $_.Exception.Message
      }
    }
  }
}
$out += 'matches=' + @($out | Where-Object { $_ -like 'hit *' }).Count
if (@($out | Where-Object { $_ -like 'hit *' }).Count -eq 0) {
  $out += 'no_match_hint: ① 不是交互会话(session 0 看不到用户窗口) ② 页面还没 load 完/不是当前 tab ③ 控件在跨进程 iframe 里(UIA 穿不进去) ④ 它根本不是 Button 而是 div+a'
}
$out -join "`n" | Set-Content -Path $OutFile -Encoding UTF8
$out -join "`n"
