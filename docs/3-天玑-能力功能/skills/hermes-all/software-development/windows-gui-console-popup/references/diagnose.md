# 诊断片段

## 5. 数窗口归属（决定走 IFEO 还是隐藏器）

用 §2 的 hook 记完窗口事件后，别只看总数：

```bash
# 全部 Qt 类顶层窗口，按 pid 分组
grep -a "Qt.*QWindowIcon" winhook.log | sed -E 's/.*pid=([0-9]+) .*/\1/' | sort | uniq -c | sort -rn
# 某个标题下有多少个**不同** hwnd（= 真创建了几个窗口）
grep -a "title='Z-MAX_Console'" winhook.log | sed -E 's/.*hwnd=([0-9]+).*/\1/' | sort -u | wc -l
```

判据：一个 pid 独自创建几百个唯一 hwnd ⇒ 程序自己的启动窗（隐藏器）；多个 pid、class 是 `ConsoleWindowClass` ⇒ 子进程控制台窗（IFEO）。

## 1. WMI 抓进程创建 + 父进程（PowerShell，需管理员）

```powershell
$q = New-Object System.Management.EventQuery "SELECT * FROM Win32_ProcessStartTrace"
$w = New-Object System.Management.ManagementEventWatcher $q
$w.Start()
$end = (Get-Date).AddSeconds(25)
while ((Get-Date) -lt $end) {
    try {
        $e = $w.WaitForNextEvent()
        if ($e.ProcessName -match 'nvidia-smi|^ps\.exe$|^cmd\.exe$|^conhost\.exe$') {
            $ppid = [int]$e.ParentProcessID
            $pname = '?'
            try { $pname = (Get-CimInstance Win32_Process -Filter "ProcessId=$ppid" -ErrorAction Stop).Name } catch { $pname = '(gone)' }
            '{0} {1} pid={2} parent={3}({4})' -f (Get-Date -Format 'HH:mm:ss'), $e.ProcessName, $e.ProcessID, $pname, $ppid
        }
    } catch { break }
}
$w.Stop()
```

判据：控制台程序会跟着一个 `conhost.exe`（parent 是它自己）。有 conhost = 真程序、会弹窗；没有 = 已走静默包装。

## 2. WinEvent 抓窗口（python，比 PowerShell 稳）

用 `ctypes` 包装 `SetWinEventHook(0x8002/0x8000, WINEVENT_OUTOFCONTEXT)`，回调里过滤 `idObject==0 && idChild==0 && GetParent(h)==0 && GetWindow(h,GW_OWNER)==0`（顶层窗口），记录 title/class/pid，用 `PeekMessageW` 泵消息。

**不要用 PowerShell 写这个 hook**：`Add-Type` 里的委托被 GC 回收后回调落到野指针，powershell.exe 以 `0xc000041d` / `BEX64` 崩溃，WerFault 弹出「Windows PowerShell 已停止工作」——排查工具本身变成新的弹窗源。

## 3. 读别的进程的 PATH（PEB）

`NtQueryInformationProcess(ProcessBasicInformation)` → PEB+0x20 = ProcessParameters → 在其 0x600 字节内按 8 字节对齐逐个当指针试读，找含 UTF-16 `PATH=` 的那块。偏移随版本变，别写死。

## 4. 包装 exe 是否真被调用

给包装加一句 `File.AppendAllText(hit_log, ...)`，重启目标程序后看日志：0 字节 = 没被调用（走绝对路径/裸命令名），有记录 = PATH 生效。这一条能省掉大量猜测。

## 6. 别用 `curl -w %{size_download}` 判断“有没有数据”

这些自建服务常是 HTTP/1.0、不带 `Content-Length`、写完就关连接，`curl -w '%{size_download}'` 会报 `bytes=0` 而实际数据已经返回（`http=200 bytes=0` 是假空）。判断“有没有图/有没有数据”用：

```bash
curl -s -m 10 "http://host:port/snapshot/arm.jpg" -o /tmp/f.jpg; ls -l /tmp/f.jpg; head -c 4 /tmp/f.jpg | xxd
```

或者直接用 python `urllib.request.urlopen(...).read()` 看 `len()` 和 JPEG 头 `ffd8`。差一点就会去修一个根本没坏的服务。
