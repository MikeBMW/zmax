# Runtime behaviour of a frozen GUI: helpers, hangs, vanished processes, perf levers

Depth for SKILL.md §6 (slow start), §9 (same-named windows) and §11 (GUI gone, workers alive).

## 1. Self-invocation helpers

A PyInstaller onedir build doubles as its own interpreter: `app.exe <path>.py args` runs that
script through argv dispatch. So every helper (`_internal/tools/*.py`: HTTP server, camera
stream, render worker, task binder) is a **fresh copy of the exe**, not `python.exe`.

```powershell
Get-CimInstance Win32_Process | Where-Object Name -match '<app>' |
  ForEach-Object { "$($_.ProcessId) parent=$($_.ParentProcessId) $($_.CommandLine)" }
```

`exe <x>.py` = helper, bare `exe` = the real GUI. Ports identify them:
`Get-NetTCPConnection -State Listen` → owning PID → command line.

Each spawn site that omits `creationflags` gets its own console window (a frozen GUI has no
console, so Windows allocates one per child). A codebase typically splits: some sites pass
`CREATE_NO_WINDOW` (0x08000000), others pass nothing. Count them before theorising:

```bash
grep -c "shell=True"     tools/gui/*.py     # each one can pop a window
grep -c "CREATE_NO_WINDOW" tools/gui/*.py
```

The wrapper that fixes 27 sites with one edit, and its escape hatch:

```python
if os.name == "nt" and not os.environ.get("APP_SHOW_HELPER_CONSOLE"):
    _NO_WIN = 0x08000000
    _orig = (subprocess.run, subprocess.Popen, subprocess.check_output, subprocess.call)
    def _hide(kw):
        kw.setdefault("creationflags", _NO_WIN)      # never clobber a caller's own flags
        return kw
    subprocess.run, subprocess.Popen, subprocess.check_output, subprocess.call = (
        (lambda f: (lambda *a, **kw: f(*a, **_hide(kw))))(f) for f in _orig)
```

Closing any of those windows kills the service behind it — the page it feeds goes empty until
the app restarts, and the survivors squat the port for the next launch.

## 2. "It crashed again" with nothing in the event log

No `Application Error` 1000, no `AppHang` 1002, no `ReportArchive` entry, no dump ⇒ it was
**terminated**, not crashed. The app's own console window is the app: closing that black window
(a console-subsystem exe gets one at start-up, titled after the exe) ends the process silently
while its helpers keep running. Ask that as a question before hunting a bug.

Instrument and keep it armed:

```powershell
# wrapper that preserves the exit code (hidden window)
@echo off
cd /d <root> & set APP_ROOT=<root>\
app.exe > _console_out.log 2> _console_err.log
echo [%date% %time%] exit=%errorlevel% >> _exit.log
```

```powershell
# plus a stop-trace watcher (fixed lifetime — re-arm when it happens again)
Register-CimIndicationEvent -Query "SELECT * FROM Win32_ProcessStopTrace WHERE ProcessName = '<app>.exe'" -SourceIdentifier AppStop
```

Exit codes: `0xC0000005` access violation (real crash), `0`/`1` the app exiting itself,
`0xC000013A` Ctrl-C / console close.

## 3. Reading a hang with py-spy dump

```bash
py-spy dump --pid <pid>        # same win_amd64 wheel as the record workflow
```

Take 5-6 dumps ~2 s apart; one sample proves nothing, an identical stack six times does.

| What the dump shows | Meaning |
|---|---|
| `MainThread (idle)` in `main()` / Qt event loop | Event loop healthy — the lag is repaint cost, a device, or another app, not a lock |
| `MainThread` in a paint/layout frame repeatedly | Layout/repaint storm — check DPI and card count, not data |
| worker thread in `create_connection` / `urlopen` on every dump | A poller hammering a dead endpoint: 2.5 s timeout, retried forever, page reads "not available" |
| all threads `idle`, nothing scheduled | The app is waiting on something external (a device handle, a pipe) |

A poller stuck on a port you disabled yourself is the classic self-inflicted slowdown: before
killing a helper service, grep the GUI sources for that port and see who polls it.

## 4. Perf levers worth checking once

- **Antivirus**: `Get-Process MsMpEng | Select CPU` (cumulative seconds; thousands = a lot of
  scanning) and `(Get-MpPreference).ExclusionPath` (empty = no exclusion at all). A deployment
  tree with tens of thousands of files plus an app writing logs every second is a scanner's
  playground.
  `Add-MpPreference -ExclusionPath <root>,<home-alias> -ExclusionProcess <app>.exe`,
  undo with `Remove-MpPreference -ExclusionPath <root>`.
- **Renderer helpers** legitimately hold ~one core (8 Hz render + 50 Hz physics). Check the
  core count before calling it the cause: `(Get-CimInstance Win32_Processor).NumberOfLogicalProcessors`
  and a 3 s per-process CPU delta sample.
- **Repeat relaunches** leave one helper set per dead GUI. Count processes before blaming
  performance: three copies of the same worker on one machine is the usual "it got slower".

## 5. Stopping the flash without a repackage

When the rebuild is days away and the user is being interrupted every few seconds, two local
stopgaps make the app usable now. Both are band-aids: say so, and give the removal path.

**Find the polled console tool first.** A 20-60 s process-start watch filtered to the app's
children names the culprit — usually a GPU/temperature helper invoked on a timer (every 2 s of
polling = one console flash every 2 s, which the user experiences as "windows keep popping"):

```powershell
Register-CimIndicationEvent -Query "SELECT * FROM Win32_ProcessStartTrace" -SourceIdentifier W
do { $e = Wait-Event -SourceIdentifier W -Timeout 1
     if ($e) { $n = $e.SourceEventArgs.NewEvent
       "$($n.ProcessName) pid=$($n.ProcessID) parent=$($n.ParentProcessID)"
       Remove-Event -EventIdentifier $e.EventIdentifier } } while ($true)
```

**a) IFEO-redirect the polled tool (works even when the app calls it by absolute path).** Compile
a pass-through forwarder as a *GUI-subsystem* binary (a console binary re-creates the very window
you are removing) and register it as that tool's debugger:

```
HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\<tool>.exe
    Debugger = <root>\_stubs\ife_wrap.exe
```

Windows then invokes `ife_wrap.exe "<original path or bare command name>" <args...>` for **every**
caller. A wrapper earlier on `PATH` only catches lookups that go through `PATH` — an app calling
by absolute path, or spawning with a cached `shutil.which` result, never touches it, and its hit
log sits at 0 bytes while the window keeps flashing. `csc.exe` ships with .NET Framework:
`C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`.

```csharp
// csc /nologo /target:winexe /out:nvidia-smi.exe NvSmiSilent.cs
using System; using System.Diagnostics;
class W { static int Main(string[] a) {
  var psi = new ProcessStartInfo(@"C:\Windows\System32\nvidia-smi.exe", string.Join(" ", a));
  psi.UseShellExecute = false; psi.RedirectStandardOutput = true;
  psi.RedirectStandardError  = true; psi.CreateNoWindow = true;   // no child console either
  using (var p = Process.Start(psi)) {
    var o = p.StandardOutput.ReadToEnd(); var e = p.StandardError.ReadToEnd();
    p.WaitForExit(); Console.Out.Write(o); if (e.Length > 0) Console.Error.Write(e);
    return p.ExitCode; } } }
```

Three pitfalls, each one cost a hang or a silent failure:

1. **Recursion.** The forwarder must NOT launch the same-named exe — IFEO hijacks it again and the
   call spins forever (the caller hangs until its own timeout, and the hit log floods at ~50
   lines/second). Copy the real binary to `<root>\_stubs\real\<tool>-real.exe` first, launch that.
2. **`args[0]` can be a bare command name.** With `subprocess.run("tool ...", shell=True)` IFEO
   passes `tool` — no path, no `.exe`. `Path.GetExtension` is empty then; default it to `.exe` or
   the copy lookup misses and every call fails with "target not found".
3. **Keep a hit log** (`File.AppendAllText`, rotate at ~512 KB) and actually read it — it prints the
   resolved target and proves the redirect is live. Check output equality too: byte-identical
   stdout, or the card silently reads "—".

**b) Hiding the app's *own* start-up windows.** When the storm comes from the bare GUI (hundreds of
`Qt*` windows titled after the exe — §9 variant ii, one pid owning hundreds of distinct `hwnd`),
nothing prevents it; it can only be hidden. Use a **polling** hider, not a WinEvent hook: a C#
winexe that every 25 ms runs `EnumWindows` and, for `title == "<exe name>"` && class contains `Qt`
&& window > 40 px, calls `ShowWindow(h, SW_HIDE)`. No message pump, no delegate-lifetime trap, and
25 ms is fast enough for windows that live ~200 ms. Register it so it never depends on a launcher:
`schtasks /create /tn <name> /tr "\"<path>\hide.exe\" 86400" /sc onlogon /rl highest /f`, then
`schtasks /run /tn <name>`. A hider started through a wscript `sh.Run` did not stay alive; the same
command line via `Start-Process -PassThru` did — so always confirm with `Get-Process` **and** its
own log file instead of assuming. State the trade-off: the loading screen is hidden too, so the app
looks unresponsive for its whole start-up; offer "hide all / keep the first one / poll at 10 ms"
rather than deciding for the user.

## 6. Tooling pitfalls that cost the most time

- **PowerShell WinEvent hooks**: put the delegate in a `static` field of the Add-Type class
  (`[Cls]::Del = [Cls+WinEventDelegate]{ ... }`) and pass *that* to `SetWinEventHook`. A delegate
  created inline is collected → `AccessViolationException` that crashes the harness. And the
  nested type must be named in full (`[Cls+WinEventDelegate]`); `[Cls+D]` raises `TypeNotFound`
  and the run then reports "0 windows" — a false clean bill of health that hides the bug you were
  hunting.
- **Kill loops kill themselves**: `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine
  -match '<literal>' } | Stop-Process` also matches the shell running it, because that literal is
  in its own command line. Collect pids in one call, kill by pid in the next, or filter on `Name`
  only.
- **An empty `CommandLine` for a just-spawned pid does not mean "launched with no arguments"** —
  the query ran after the process already exited. Half-second-lived children *are* the spawn storm.
- **A frozen onedir exe cannot be relocated to act as an interpreter.** Copying `app.exe` to
  `<dev-venv>\bin\python.exe` to satisfy a hardcoded `[venv/bin/python, tool, --json]` call fails
  with `failed to load python dll`: the bootloader needs its `_internal/` sibling next to it. Each
  retry of that call pops another window, so the workaround worsens the reported symptom — fix the
  call site upstream instead.
