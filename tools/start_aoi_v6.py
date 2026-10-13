#!/usr/bin/env python3
"""经反向通道在工控机 192.168.23.23 上: 停自愈任务 + 停旧的 10082/10083 + 起现役版 + 验收。

老倪 2026-09-28: 「你启动吧，我刚才启动v6失败了」
  —— 他起失败的最可能原因: 旧实例还占着 10082/10083(端口被占 ⇒ 新进程起不来),
     以及 ZMAX_AOI_KeepAlive(每分自愈)会在几十秒内把旧的再拉回来。
  所以本条命令的顺序是: ①先关自愈任务(否则白干) ②按端口属主停旧进程 ③起两个 ④40秒后验收端口。

⚠ 2026-10-13 修: 原先硬编码 `..._work_v6.py`。2026-10-12 已上线 v20, v6 文件在工控机上已删
  ⇒ 本脚本会"成功启动"两个不存在的文件(日志里才看出来)。现改为**直接取
  tools/aoi_remote_deploy.py 里的 FILENAME_10082/FILENAME_10083**(部署与启动同一真源),
  以后升版本只改那一处, 这里不会再悄悄过期。

通道状况: 反向通道是活的(2026-10-13 核: /agent/beat 新鲜 + echo awake 有回执)。
  本脚本 wait=45s; 返回 <<TIMEOUT ...>> 才表示工控机没接单, 只能就地手动。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
import aoi_remote_deploy as A  # noqa: E402

F_FINGER = A.FILENAME_10082
F_SURFACE = A.FILENAME_10083

PS = r"""
$out = @()

# ① 关掉自愈任务(名字按 ZMAX/AOI 关键字匹配, 列出来一并报回)
$tasks = Get-ScheduledTask -EA SilentlyContinue | Where-Object { $_.TaskName -like '*ZMAX*' -or $_.TaskName -like '*AOI*' }
foreach ($x in $tasks) {
  $out += ("task {0} = {1}" -f $x.TaskName, $x.State)
  try { Disable-ScheduledTask -TaskName $x.TaskName -EA Stop | Out-Null; $out += ("disabled " + $x.TaskName) }
  catch { $out += ("disable FAIL " + $x.TaskName + " : " + $_.Exception.Message) }
}

# ② 按端口属主停掉旧的 10082 / 10083
foreach ($p in 10082, 10083) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue
  if ($c) { Stop-Process -Id $c.OwningProcess -Force -EA SilentlyContinue; $out += ("stopped {0} pid {1}" -f $p, $c.OwningProcess) }
  else { $out += ("{0} not listening" -f $p) }
}
Start-Sleep -Seconds 5

# ③ 起现役两个(文件名来自 aoi_remote_deploy.py, 不在本文件硬编码)
$d = 'D:\xspace\ultralytics_AOI'
$py = Join-Path $d 'venv\Scripts\python.exe'
$sh = New-Object -ComObject WScript.Shell
$sh.Run(("cmd /c cd /d {0} && {1} __F_FINGER__ > {0}\__F_FINGER__.log 2>&1" -f $d, $py), 0, $false) | Out-Null
$sh.Run(("cmd /c cd /d {0} && {1} __F_SURFACE__ > {0}\__F_SURFACE__.log 2>&1" -f $d, $py), 0, $false) | Out-Null
$out += "started both"
Start-Sleep -Seconds 40

# ④ 验收: 端口 + 现役进程数
foreach ($p in 10082, 10083) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue
  if ($c) { $out += ("{0} -> up pid {1}" -f $p, $c.OwningProcess) } else { $out += ("{0} -> DOWN" -f $p) }
}
$out += ("running live python procs: " + ((Get-CimInstance Win32_Process -Filter "Name='python.exe'" -EA SilentlyContinue | Where-Object { $_.CommandLine -like '*cam_*_work_v20.py*' } | Measure-Object).Count))
$out -join " | "
""".replace("__F_FINGER__", F_FINGER).replace("__F_SURFACE__", F_SURFACE)


def main() -> int:
    print("  通道参数: HUB=%s  OUT_DIR=%s" % (A.HUB, A.OUT_DIR))
    print("  下发中(最多等 45s; 工控机 agent 若已死会返回 TIMEOUT)…")
    r = A.remote(PS, wait=45, label="start_v6")
    txt = str(r)
    print("  === 工控机回执 ===")
    if txt.startswith("<<TIMEOUT"):
        print("  ✗ 工控机没接单:", txt)
        print("  ⇒ 通道仍是死的, 无法远程启动; 需要在工控机上就地执行(见 /tmp/start_v6_manual.ps1)")
        return 2
    if txt.startswith("<<ENQUEUE_FAIL"):
        print("  ✗ 入队失败:", txt)
        return 3
    for part in txt.replace("\r", "").split("|"):
        part = part.strip()
        if part:
            print("   ", part)
    print("  === 回执结束 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
