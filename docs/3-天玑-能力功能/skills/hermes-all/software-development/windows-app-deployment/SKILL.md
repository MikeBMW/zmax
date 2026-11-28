---
name: windows-app-deployment
description: "Use when installing or auditing a Windows app deployment."
version: 1.4.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [windows, deployment, porting, pyinstaller, paths, verification]
---

# Windows App Deployment (install, port, verify)

## When to Use

- The user runs an installer/unzip on Windows and it reports access-denied or permission
  errors on files inside the app directory.
- A packaged app starts but cannot find its own files (missing project/config/database) on
  a machine it "worked on before" — especially right after a Linux→Windows port.
- A packaged app runs, but one section of its UI is empty (blank card grid, empty list) or a
  card says "取不到 / not available" — see §5 before touching any data.
- The page loads (HTTP 200) yet every camera/media tile is blank, or a feature button opens a
  port nobody listens on — see §12.
- Every device in the app reads offline, or the user asks "can you see <IP>?" / "is the robot
  connected?" — see §8 and `references/hardware-and-network-commissioning.md`.
- Many identical windows (or many copies of the app's own exe) appear when the user opens a
  project or triggers a heavy action — see §9.
- Another application (video call, browser preview, capture tool, vendor SDK) can no longer
  open the camera, microphone or a serial port while the app runs — see §10.
- The user wants a desktop shortcut, or the app only behaves when launched from the right
  directory with the right root env var — see §3.
- The user says "it crashed again" / "it is stuck": helpers still running, nothing in the event
  log — see §11 and `references/process-lifecycle-and-hangs.md`.
- The user asks whether a deployment is complete or in sync with the source repo / another
  machine.

Class of work: putting a packaged app (PyInstaller onedir, Electron, zip-of-a-directory)
onto a Windows machine and proving the result is complete and consistent — including ports
of an app that was packaged on Linux. Applies to third-party/company software, not just
Hermes itself.

## 1. Unpack only after the app is stopped

`Expand-Archive -Force` (and most installers) **delete each existing file before writing
it**. A running instance holds its `.pyd`/`.dll`/`.js` mapped, so the delete raises
`UnauthorizedAccessException` / "Access to the path ... is denied" — and the installer
*continues*, leaving the old file in place. Result: a silently **mixed install**
(new exe + old runtime libraries), which shows up later as unexplained crashes.

Procedure:

1. List every process of the app incl. child helpers:
   `Get-CimInstance Win32_Process | Where-Object { $_.Name -match '<app>' } | Select ProcessId,ParentProcessId,Name,CommandLine`
   — GUI apps usually spawn server/worker children that also hold files.
2. **Ask before killing** when the children are doing real work (camera streams, robot
   services, renders). One line: what will be interrupted, then wait.
3. Kill **by process name**, not by the parent's PID tree, and re-check none remain before
   unpacking (`Get-CimInstance Win32_Process | Where Name -match '<app>' | ForEach Stop-Process`).
   Server children outlive a killed GUI and keep their ports, so the *next* launch starts
   "fine" and then silently shows empty panels. After relaunch, confirm the listening ports
   belong to children of the **new** parent, not to an orphan.
4. Do not call a relaunch failed because ports are silent seconds later: a frozen Qt /
   PyInstaller GUI can spend 30–60 s building its canvas before spawning any worker (§3: wait
   for the real window title, not just a non-zero handle).
5. Verify no mixed install by timestamp clustering, not by "it started fine":
   `ls -la --time-style=long-iso <app>/_internal | head` plus
   `find <dir> -type f -newermt '<start>' | wc -l` vs older count. Two clusters on a
   re-install means some files were skipped; re-extract over a *deleted* runtime dir.
6. Confirm the package still exists before promising a clean reinstall — installers often
delete their temp zip. If it is gone, say so and ask the user to re-transfer rather than
performing a half-extract.

## 2. A stored POSIX path beats any working-directory fix

Symptom: the app reports a missing file at `<Drive>:\data\...` while the real file is at
`<Drive>:\<AppRoot>\data\...`, and launching from the right directory or setting the
root env var changes nothing.

Mechanism: the path was written on Linux as an absolute path (`/home/<user>/<app>/...`) or
built as `root + "/rel"`. On Windows `os.path.join(root, "/data/...")` **discards `root`**
because a right-hand side starting with `/` is drive-rooted, and `abspath("/x")` anchors to
the current drive. So the app-root segment disappears silently.

Diagnosis order (cheap to expensive):

1. `grep -rn '"/data/\|/home/[a-z]' --include=*.json --include=*.yaml config flows` and
   `sqlite3`/python-sqlite query of any path columns (`select * from projects`,
   `mw_project.canvas_path`, `module_code.file`) — find the literal Linux path.
2. Do **not** keep chasing the cwd/env root once the app's own log prints a correct `cwd=`:.
   A correct cwd with a wrong absolute path proves the path came from data, not from the
   environment.
3. Find the app's own trace log and read the `pid=` lines — it names both the resolved root
   and the path it actually opened. A frozen app can keep *two* path systems: one honouring
   the launcher's root env var, one defaulting to `~/<app>` (`expanduser`), so its trace
   files land under `C:\Users\<user>\<app>\...` while the exe runs from `D:\<AppRoot>`.
   That log, plus the pid of the instance you just started, beats every inference. Some
   builds deliberately support `app.exe -c "exec(open(probe.py).read())"` argv dispatch —
   use it to print the resolved root before writing any fix.

Fixes, in preference order:

- **Rewrite the stored paths** to relative (`data/database/...`, no leading slash) — this is
  the real fix and covers every feature that reads them (save, open-source, canvas load).
  Back up the DB first and close the app (SQLite lock).
- **Junction workaround** when you cannot touch the data or the code yet:
  `rmdir <Drive>:\data\database\x` (must be empty) then point it at the real directory with
  PowerShell `New-Item -ItemType Junction -Path <Drive>:\data\database\x -Target <Drive>:\<AppRoot>\data\database\x`.
  Prefer that form over `cmd mklink /J` when driving from bash: inside double quotes `mklink`
  eats `\$var` and happily creates a junction whose target is the literal text `$var`, and
  the only symptom is a path that still does not exist.
  Verify with `os.path.realpath()` on the joined path, and tell the user it is a scratch
  fix: it only covers the directories you junctioned, so other stored paths
  (`/home/.../src/...` → `<Drive>:\src\...`) stay broken.
- Report the class of defect to whoever builds the package (the next build reintroduces it)
  and list the leftovers you found, so it is one fix per release instead of one per page.

## 3. Launch through the shipped launcher

If the deployment ships a `.bat` that does `cd /d "%~dp0"` + `set VAR=%~dp0`, that is the
contract: start it through the bat, never by double-clicking the exe. Tell-apart:
`ParentProcessId` pointing at `explorer.exe` means the exe was started directly; a `cmd.exe`
parent means the launcher ran. When the root env var matters, set it in the launching shell
before `Start-Process -FilePath ... -WorkingDirectory ...` so the child inherits it.

**Build the launcher the deployment should have shipped** when the user asks for a desktop
shortcut or keeps launching the exe by hand. Chain with no console flash:
`.lnk` → `wscript.exe "<root>\launch_app.vbs"` → `powershell -NoProfile -ExecutionPolicy
Bypass -WindowStyle Hidden -File <root>\launch_app.ps1`, icon from the exe. The PowerShell, in
this order:

1. set the root env var(s) and pass `-WorkingDirectory <root>`;
2. if a **bare-exe** process already exists, `ShowWindow`+`SetForegroundWindow` it and exit —
   no second instance, no port fight;
3. kill workers whose `ParentProcessId` is not in the process list (orphans from a dead GUI
   squat on the service ports and make the next launch show empty panels — see §1.3);
4. start the exe, then wait for the **real** window (pitfall below) before doing anything else;
5. only then the post-start workaround (reflow nudge, restore size).

Hardcode the app-specific bits (root, product window title) in the script, keep the script
ASCII-only — PowerShell 5.1 reads a BOM-less UTF-8 `.ps1` as ANSI and a stray Chinese
character in a string literal breaks the quoting at parse time. **Keep it CRLF as well**: a
`.ps1` saved with LF-only line endings makes PowerShell miss the here-string terminator, so an
embedded `Add-Type @"..."@` block is parsed as script and the launcher dies at parse time —
symptom is *nothing* starting (no exe, no services) and, because it runs hidden, no visible
error. Tool-driven edits (`write_file`/`patch`) can flip the file to LF silently. Check every
time before trusting it:
`$e=$null; $null=[System.Management.Automation.Language.Parser]::ParseFile('<path>',[ref]$null,[ref]$e); $e`
and re-normalise with a one-liner that rewrites `\n` → `\r\n`. Ready-to-copy pair:
`templates/single-instance-launcher.ps1` + `templates/single-instance-launcher.vbs`
(create the `.lnk` with `$_ = (New-Object -ComObject WScript.Shell).CreateShortcut(<path>)`,
`TargetPath = wscript.exe`, `Arguments = "<root>\launch_app.vbs"`, icon from the exe).

**`MainWindowHandle` non-zero does not mean "the UI is up".** A frozen Qt app first shows a
loading window, usually titled with the exe name, and only seconds later the real window
(a product title). Acting on the first handle — resize nudge, screenshot, "read the panel" —
hits the splash: the nudge does nothing and the screenshot is a loader. Poll
`$p.MainWindowTitle` until it matches the expected product title, then wait a few seconds
for the page to build, and re-read the handle: it changes when the real window is created.

## 4. Prove completeness instead of trusting the install report

A deployment note listing file counts is a claim — verify it:

```bash
for d in config src models docs; do printf "%-8s repo=%s disk=%s\n" "$d" \
  "$(git ls-tree -r --name-only HEAD -- $d | wc -l)" "$(find $d -type f | wc -l)"; done
```

Then separate real content drift from noise (details in
`references/sync-and-completeness-audit.md`):
`git diff --ignore-cr-at-eol --stat -- <dir>` and `git diff --summary -- <dir>` —
`812 mode change, 0 insertions, 0 deletions` means the content is identical and only the
executable bit differs on NTFS. Never report those files as "modified".

Also inventory what the deployment intentionally left out (`git ls-tree --name-only HEAD`
minus what is on disk): a runtime-only copy legitimately omits `tests/`, `tools/`, `.github/`,
`requirements*` — but call out the two that bite: a missing `.gitattributes` makes every
sync back to the repo noisy, and missing source dirs mean documentation that names
`tools/foo.py` cannot be checked on the Windows side.

## 5. An empty panel is diagnosed from the app's own source, not from data

A blank module grid, an empty list, or a "取不到 / not available" card is **not** evidence
that data is missing. Seeding or junctioning more directories first is usually wasted work.
Order that pays:

1. **Read the code that builds the panel**, at the deployed commit, from the git remote — a
   runtime-only copy omits `tools/` but
   `raw.githubusercontent.com/<owner>/<repo>/<commit>/<path>` still serves it. The local
   `git rev-parse HEAD` gives the commit; list the GUI directory through the contents API
   when you do not know the file name. These sources carry the project's own bug notes
   ("卡片全不见", "取不到") plus the reason.
2. **A hardcoded card list means the data is fine** — then the section is empty for a layout
   reason, not a data reason.
3. **Layout-collapse signature:** section title renders, zero children under it, rest of the
   page fine. In Qt that is a reflow that never ran (width 0/1 at `showEvent`) →
   `minimumSizeHint` 0 → the parent squeezes the grid to zero height. Prove it by forcing a
   resize (P/Invoke `MoveWindow` shrink then restore, screenshot after), then tell the user
   the manual equivalent (drag the window edge / maximize + restore) and that the durable fix
   belongs in the panel's `showEvent`/`resizeEvent`.
4. **A "取不到" card usually shells out to something the deployment never shipped** —
   `ROOT/<dev-venv>/bin/python`, `tools/<script>.py`, a local service port. Read the module,
   list the invoked paths, `Test-Path` each one, and say which are absent; a missing Linux
   venv is a packaging-side fix (run the script with the frozen exe as interpreter, or read
   the same numbers from `config/` + DB), never a junction.

Corollary: a root-detection helper may require several sibling directories to exist
(e.g. both `src/<pkg>` and `tools/`) and **silently falls back to a guessed directory** when
one is missing, so every path derived from it points somewhere plausible and wrong. Read the
helper before blaming the data.

**A stream fed by a local sampler file nobody writes.** `/status` reporting `online:false, fps:0,
src:""` for a camera or a robot pose is usually not hardware: the worker is parked in a branch
waiting for a file (`.../tcp_out/latest.json`, `ss_live/*.png`, `/dev/shm/*.raw`) that a
container/sampler never produced on this host, and it waits forever without logging anything. Read
the worker's argument parser and its start-up branch before touching the device or the network.
Two consequences:

- **You cannot add CLI flags** — the frozen main program decides how it spawns the helper. Make the
external `.py` self-sufficient instead: default the source list inside the script, and when the
local path is absent fall back to the live remote endpoint that the other node already serves (the
upstream bridge is usually still running). Then verify through the service's own `/status` payload,
not a screenshot of the page.
- **Name the source that actually delivered.** Return it in the payload (`src: "<bridge>/endInRef"`)
and keep the stale/fresh flag honest, so neither you nor the user mistakes a fallback for the
original chain coming back. A silent fallback that is missing from the telemetry is the same as a
silent failure.

## 6. A slow start is measured, not guessed

Startup complaints are almost never "the packager". Get the phase split first, then sample
stacks — CPU-bound work inside the app is invisible to disk/network arguments.

1. Timeline: `Start-Process` + poll `MainWindowHandle`, `MainWindowTitle`, service ports, and
the app's own log stamps. That separates "exe start" from "UI up" from "services up".
2. Sample the process with the **formatted** perf class:
`Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -Filter "IDProcess=<pid>"`
(`PercentProcessorTime`, `IOReadBytesPersec`, `WorkingSet`). The `PerfRawData_*` class returns
cumulative raw counters — divided naively they read as absurd MB/s and send you chasing a
phantom disk problem. If CPU is pegged and IO stays ~0, the app is computing — profile it.
`py-spy` is a single exe:
download the `py_spy-*-win_amd64.whl` from GitHub releases, unzip the wheel, and run
`py-spy.exe record -p <pid> -d 45 -f raw -o raw.txt --rate 60 --nonblocking`; aggregate the
raw stacks in Python (last frame per line × count). One function holding >60% of samples is
the answer, no further guessing.
3. Frozen-app probes: `app.exe <script.py>` (the argv-dispatch trick) times any candidate
cost in-process — imports, `os.walk`, JSON, sqlite, WMI. That rules the suspects out in one
run (a 24 MB onedir exe can boot its interpreter in <0.3 s).
4. Read the offending function, don't trust its docstring: a claimed optimization that never
reached the default arguments (`def f(step=16, cap=1024)` under a comment saying "step 32,
cap 256") reproduces the original 45 s cost. Patching the deployed `.py` in place needs no
repackage — but **confirm the on-disk copy is the one being imported**, because a PyInstaller
build serves modules from the compiled PYZ first: a top-level module that also exists as
`_internal/<mod>.py` keeps running the old compiled code, while a package module reached via a
`sys.path` insert of `_internal/src` does take effect. Verify with behaviour that cannot be
cached (a log value, a timing line), never with the file's mtime — a patch that "applied
fine" and changed nothing is the normal failure here. When the file is shadowed, disable the
feature instead of rewriting it (§10). Then commit the same change upstream or the next build
brings it back — how to hand that patch over when you have no push access is in
`references/upstream-patch-delivery.md`.
5. **Rule out the antivirus before rewriting anything**: cumulative `MsMpEng` CPU in the
   thousands while the app's own threads are idle, plus an empty `(Get-MpPreference).ExclusionPath`,
   means real-time scanning of the tree is the lag. Commands, the reversible removal and the other
   one-off perf levers: `references/process-lifecycle-and-hangs.md` §4. It is a lever, not a root
   cause — never present it as the explanation for a hang you did not otherwise explain.

## 7. Do not trust `ping` for reachability on Windows

A ping can report `0% loss` while no route exists (VPN/endpoint agents answer ICMP), and
open ICMP says nothing about the service port. Confirm with
`Get-NetRoute -DestinationPrefix '<subnet>/24'` and a real TCP connect
(`(New-Object Net.Sockets.TcpClient).ConnectAsync($h,$p).Wait(900)` on the actual service
ports). When the peer is a dual-boot system on the same disk, there is no network path at
all: say so plainly and hand over a checksum manifest instead of hunting for SSH.

## 8. Everything offline: commission the link, then the chain

1. **NIC first.** `169.254.x/16` on the plant adapter = link up, no DHCP → assign a static
   address in the device subnet; choose the adapter by description, not `ifIndex`.
2. **Ports open ≠ device connected.** Prove the chain from the service's own telemetry (a
   controller IP plus joint state in a `/status` payload; the frame endpoint's own age header when
   it has one). Such a JPEG endpoint is often HTTP/1.0 with **no** `Content-Length` and no age
   header, so `curl -w '%{size_download}'` returns `bytes=0` on a perfectly good frame — save it
   (`curl -s -o f.jpg`) and check size plus the `ffd8` JPEG magic, or read it with python
   `urllib`. Judging "empty" from curl's counter sends you rebuilding a service that works.
3. **Read the service's 503 JSON** — it names the missing sub-service or the empty frame
   source; quote it instead of guessing.
4. **Relaunch the app afterwards** — it keeps a cached offline state and a per-source backoff,
   and ports owned by another machine stay closed by design.

Identification recipes (SSH/HTTP banners, per-service URLs) and this cell's address map:
`references/hardware-and-network-commissioning.md`.

## 9. Same-named windows are the app running its own helper scripts

Symptom: opening a project (or any heavy action) throws up a burst of windows titled like the
app, and a process listing shows several copies of the same exe.

Mechanism: a PyInstaller onedir build doubles as its own interpreter — `app.exe
<path>.py args` runs that script through argv dispatch — so every helper
(`_internal/tools/*.py`: server, camera stream, render worker, task binder) is a **fresh copy
of the exe**, not a python.exe. Any spawn site that omits `creationflags` gets its own console
window. The bug is the split inside one codebase: some sites pass `CREATE_NO_WINDOW`
(0x08000000) and some pass nothing.

**Two different animals wear this symptom — measure before choosing a fix.** A burst of windows
titled after the exe can be (i) helper consoles keyed to a timer, or (ii) the GUI's *own*
start-up windows: the **bare** exe (no `.py` argument) creating hundreds of distinct `Qt*`
windows in the first seconds, each shown once. Count unique `hwnd` per pid — one pid owning
hundreds of them means (ii): no spawn-site `creationflags` patch helps there, and hiding them
externally (polling + `SW_HIDE`) was measured to make start-up slower and leave a pile of
taskbar entries, so it had to be rolled back. What works is a source-level guard that wraps
`show` / `setVisible` / `showNormal` / `showMaximized` / `showFullScreen` and sets
`WA_DontShowOnScreen` on parentless, untitled widgets — then a rebuild. Skill
`windows-gui-console-popup` (诊断 step 0 divides the two animals) carries the guard and the
rebuild recipe.

1. Read command lines, not window titles — `exe <x>.py` is a self-invocation helper, bare `exe`
   is the real GUI. Commands and the one-edit wrapper that hides every spawn site:
   `references/process-lifecycle-and-hangs.md` §1. Short form: count `shell=True` against
   `CREATE_NO_WINDOW` in the GUI sources and hand the packaging owner file:line, not "it
   blinks"; the fix is `creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0`.
   Until that rebuild lands, the local stopgap that works for case (i) is **IFEO-redirect the polled
   console tool** to a GUI-subsystem forwarder — it survives absolute paths and bare command
   names, which a `PATH` wrapper does not. Do not stack a polling hider on the app's own
   start-up windows (§9 (ii)): it was measured to make start-up worse. IFEO recursion and
   extension pitfalls: `references/process-lifecycle-and-hangs.md` §5.
2. **Never tell the user to close those windows** — each one is a service. Closing it kills the
   port (station overview, camera stream, AR render) and the UI section goes empty until the app
   is restarted; that is also how orphaned workers end up squatting ports later.
3. Ports held by these helpers identify them: `Get-NetTCPConnection -State Listen` → owning PID →
   command line, which doubles as the fastest proof of what a "mystery" window is doing.

## 10. A helper that grabs an exclusive device blocks the user's other apps

Symptom: video calls, camera previews or a vendor SDK can no longer open the camera (same for
microphone or a COM/serial port) while the app is running, and the app itself reports nothing.

Mechanism: Windows webcams are exclusive. One of the app's helper services opens the default
device and streams from it permanently, so every other process gets "device busy". Its own log
typically shows it grabbing `video0` / device index 0 even when the source it really wants is
dead — it is holding the device for nothing. Permission (`Allow`/`Deny`) is a *different*
question; check it, but do not stop there.

1. Prove who holds it from the per-app consent store instead of guessing — commands and the
   `LastUsedTimeStop = 0` semantics are in
   `references/hardware-and-network-commissioning.md` §7. Report the holder's exe path.
2. Identify the helper by its listening port or command line (§9.1) and say out loud that it is
   a service before you stop it.
3. **Before disabling the helper at all, read its argument parser.** These services usually
   already ship the switch — `--no-local`, `--no-local2`, `--no-camera`, `--no-mic` — and the
   fix is to make its default "off" (`default=not os.environ.get("APP_CAM_LOCAL")`) so the
   service still runs. Prefer this: a running helper keeps the HTTP surface other pages poll
   (`/station/status`, `/state.json`), so the UI keeps its data while the device stays free.
   Renaming the script does keep the device free, but it also removes that surface, so every
   card fed by it starts failing (`references/process-lifecycle-and-hangs.md` §3).
4. **Check who polls the endpoint before you kill it.** `grep -rn '<port>' <gui sources>` and
   look for a background thread doing `urlopen` on it. A poller with a 2.5 s timeout retrying
   every 2 s forever is invisible in CPU terms but shows up in every stack dump, and the page
   it feeds reads "not available" permanently.
5. Make "off by default" survive restarts even when no flag exists, preferring the option that
   fails **fast**: renaming the helper script so the launcher's script lookup misses returns in
   milliseconds, while a stub that exits leaves the launcher waiting out its port timeout on
   every single start. Add an env gate on the spawn helper as a second line of defence — only
   if that module is the one actually imported (§6.4).
6. State the trade-off in the same breath: with that service off, the page it feeds (station
   overview, live view, AR render) goes offline, and re-enabling is one rename plus a relaunch.

## 11. The GUI vanished while its workers stayed

Symptom the user reports as "crashed again": the window is gone, the helper services are still
alive and still hold their ports, and Windows logged **nothing** — no `Application Error` 1000,
no `AppHang` 1002, no `ReportArchive` entry, no dump. That is **terminated, not crashed**.

1. **The app's own console window is the app.** A console-subsystem exe (most frozen Python
   builds) gets a console window titled after the exe at start-up; closing that black window
   ends the process silently while its helpers keep running — exactly this signature. Ask it as
   a question instead of hunting for a bug, and start it window-less once the user agrees.
2. **Instrument before asking for a repro, and keep it armed**: exit-code wrapper + a
   `Win32_ProcessStopTrace` watcher. Recipes and exit-code meanings:
   `references/process-lifecycle-and-hangs.md` §2. A watcher with a fixed lifetime expires
   between two incidents — re-arm it when the user says it happened again.
3. **When it is "stuck" rather than gone, dump stacks instead of sampling CPU**: `py-spy dump
   --pid <pid>`, 5-6 times ~2 s apart. An idle `MainThread` in the event loop means the freeze is
   elsewhere; a worker parked in `create_connection` on every dump is a dead endpoint. Table:
   `references/process-lifecycle-and-hangs.md` §3.
4. Order of evidence when nothing is logged: exit code > stderr tail > main-thread stack >
   orphan list. Say which one you have; do not present "it looks like a crash" as a finding.

## 12. A page that loads but shows nothing (media wiring, not the camera)

Server-side `/status` reports every source `online:true` with a fresh frame, yet the page shows
blank tiles. The service is fine; the page is asking the wrong host/port.

1. **Read the page's own DOM, not a screenshot**: in the browser dump
   `Array.from(document.querySelectorAll('img')).map(i => [i.id, i.getAttribute('src'), i.naturalWidth])`.
   `naturalWidth === 0` on every tile while `curl -o f.jpg /snapshot/...` returns a real JPEG
   (check `ffd8`) proves the browser is fetching somewhere else.
2. **Dual-port design vs single-port deployment** is the usual cause: the page builds media URLs
   from a helper (`const _mb=()=>'//'+host+':8791'`) because on the original host one process
   listened on two ports, while this build is started with only one. Every media request then
   hits a closed port. Fix the helper to same-port relative URLs — the service usually already
   serves the same streams there.
3. **A hot-reloaded page can shadow your fix**: a service that prefers an external
   `web/<page>.html` over its embedded copy will silently switch to that file the moment one
   exists next to the helper — reverting URL edits that were made to the embedded copy. After
   editing a page, confirm *which* copy is served (`curl` the page, grep for your edit) and
   update both.
4. **Overlay/snapshot tiles are optional layers**: `/snapshot/overlay_<cam>.jpg` returns 503
   whenever the overlay worker wasn't started (it usually isn't). Fall back to the raw frame in
   the snapshot handler rather than propagating the error.
5. **A feature button that opens nothing is an unbundled service**: frozen packages ship the GUI
   but not the small stdlib servers the buttons point at. Add port-check-then-start to the
   launcher, using the app's own exe as interpreter. Launcher snippet, the sibling-asset trap
   (start the `tools/` copy, not `_internal/tools/`) and the page-shadow checklist:
   `references/frozen-app-local-services-and-media.md`.

Accept with `naturalWidth` / byte counts read from the real page, never with the service's own
`online:true`.

## 13. How to report back

This user judges an answer by the evidence inside it, and asks "why" again until the mechanism
is named. Every finding gets: the mechanism in one sentence, the measurement that proves it
(stack-sample share, log line, registry value, port → PID → command line), what you changed on
disk, and the one decision left for them. Numbers before paragraphs: "53 s → 0.7 s, 97% of
samples in `_max_alloc_mb`" ends the discussion; "much faster now" starts it over.

**Do the work, don't hand over a to-do list.** This user answers "动手" / "好" and expects the
kill, the patch, the restart and the shortcut to already be done — with the one-line warning
about what gets interrupted *before* you do it, not a numbered procedure for them to follow.
When they are being actively disrupted (windows popping over their work, cursor jumping while
they type, "烦死了"), stop the offending process with one command first and only then keep
diagnosing: every extra diagnostic tool call while they are being interrupted makes it worse,
and one long chain of probes reads as more noise, not more diligence.
Only leave a step manual when it needs their credentials or their judgement (an SSH account you
must not guess, a security setting they may not want changed).

When you fix something in a deployed tree, also say where the durable fix lives and hand over a
patch or a file:line to the packaging owner — a local edit dies at the next install, and the
next rebuild silently reverts anything patched outside the source tree (notably the helper
scripts under `_internal/tools/`, which the build regenerates from `tools/*.py`). Before
delegating the rebuild to another machine or a person, check whether it can be done **here**:
the repo's CI workflow usually spells out python version, dependencies and the exact
pyinstaller command, which is enough to rebuild locally (full recipe: the `pyinstaller-rebuild`
reference inside the `windows-gui-console-popup` skill).

## 14. Verify by state, never by taking their screen

The user is usually sitting in front of the machine you are fixing. Anything that creates a
window takes focus away from what they were typing or clicking — they will tell you to stop,
and the diagnostic value never justified it.

- **Do not launch the app, its launcher, a browser page, or any GUI "just to confirm it
  works".** Read state instead: `Get-NetTCPConnection -LocalPort <p> -State Listen`,
  `curl` the endpoint, `Get-Process | Select MainWindowTitle`, the service's own `/status`.
  A window title in a process listing proves the same thing a screenshot would.
- If a launch is genuinely required (timing a cold start, §6), say it will pop up first, or do
  it while they are away. Starting it for them closes whatever they had open.
- Restarting or replacing the exe is theirs to trigger when they are present: leave the file
  ready and hand over one command.
- Screen-driving tools (`MoveWindow`, `SetForegroundWindow`, simulated clicks, coordinate taps)
  are for when the user asks you to drive the desktop — not for self-verification.
- The tension with §13 is real, and the split is: **do** everything that does not touch their
  screen (patch, restart services, replace files after they close the app, verify by
  telemetry); **hand over** exactly the action that has to happen in front of them.

## 15. Inventory a peer host before deploying anything to it

"Copy all the services onto the other machine" is almost never the right first move. In a
plant a peer host usually already runs a full stack, and what is broken is one config value.

1. `systemctl list-unit-files --type=service | grep -iE '<app>'` and
   `systemctl list-units --state=running` — how much already runs.
2. `ss -ltn` — which ports are already served. The service may be up and merely wrong.
3. `ls -d ~/*<app>*` plus `du -sh` — which tree is live. A host with half a dozen dated copies
   means one is canonical and the rest are archives; the running unit's `WorkingDirectory`
   names the real one.
4. Compare that unit's `Environment=` against the code's own
   `os.environ.get("KEY", <default>)`. A unit that never set the variable silently falls back
   to a default pointing at nothing and reads a stale file: symptom is "service up, data days
   old" (`age_s` in the hundreds of thousands, `stale:true`). The fix is one `Environment=`
   line plus `daemon-reload && restart` — **not** a redeploy over a tree that was tuned for a
   different OS.
5. Cross-OS code is not interchangeable even for the "same" service: a Linux side carries
   `sudo docker --network host`, `.so` SDKs, and systemd dependencies that a Windows copy
   would silently break. Prefer config edits; deploy code only where the component genuinely
   does not exist — and say what you checked before deciding that.

