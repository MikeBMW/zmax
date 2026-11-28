---
name: windows-system-maintenance
description: Use when slimming or reorganizing a Windows disk.
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [windows, disk-cleanup, uninstall, file-organization, powershell]
    related_skills: [computer-use]
---

# Windows System Maintenance

Auditing space, inventorying installed software, organizing files, and removing
what is provably dead — on a Windows host driven from bash/git-bash.

## When to Use

- User asks to clean up, slim down, or 瘦身 a Windows machine.
- Disk is filling up and they want to know which folder ate the space.
- "Delete the useless programs", "uninstall the broken ones", installed-app inventory.
- Organizing a cluttered Downloads / Desktop / Documents into categories.
- Reorganizing a whole drive into a target taxonomy ("D: 全部分类整理，最多 5 个
  文件夹、最多 3 层"), including duplicate removal and a rollback path.
- User asks to see the folder tree of a folder or of the whole drive.
- Not for: installing or configuring software, or GUI-desktop actions (use
  `computer-use` for those).

## Standing rules

- Read-only audit first, then an evidence-backed report, then explicit approval,
  then execute, then verify. Never delete user data or uninstall business
  software on inference alone.
- Every claim in the report carries a measured number. Say what was freed, what
  is blocked, what needs a decision. Do not narrate the process.
- Keep the decision list short: a numbered block in the reply body with exact
  sizes, answerable with one word ("删这三个"). Multi-question forms get ignored
  by this user — a 5-question form times out while a terse numbered list gets an
  immediate answer.
- Act on hard evidence instead of asking. Only escalate what is genuinely
  irreversible (a large backup image, a running app that must be closed, a
  program that may still be needed).
- Plain text, no markdown (CLI). Numbers aligned, sizes in MB/GB.
- Never uninstall these without an explicit instruction per item: camera/vision
  drivers (OPT), banking UKey + signing services, print clients, conferencing
  add-ins, IM clients (WeChat / WXWork / Feishu), Docker, VC++ redistributables.
- `reg export <key> <file> /y` before deleting any uninstall entry, and tell the
  user the backup path so they can double-click to restore.
- Never force WinSxS or servicing-stack operations. See the DISM pitfall.
- If a destructive command is blocked for lack of consent, do not retry or
  rephrase it. Report that it did not run and wait.

## Procedure

### 1. Baseline

```powershell
Get-CimInstance Win32_OperatingSystem | Select Caption,Version,BuildNumber,
  @{n='RAM_GB';e={[math]::Round($_.TotalVisibleMemorySize/1MB,1)}},LastBootUpTime
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select DeviceID,
  @{n='TotalGB';e={[math]::Round($_.Size/1GB,1)}},
  @{n='FreeGB';e={[math]::Round($_.FreeSpace/1GB,1)}}
```

Also check for `C:\hiberfil.sys`, `C:\pagefile.sys`, `C:\Windows.old`, and the
recycle bin (`(New-Object -ComObject Shell.Application).Namespace(10).Items().Count`).
`hiberfil.sys` is hidden, is roughly 40% of RAM, and is regularly the largest
single reclaimable file on a desktop — see `references/audit-and-cleanup.md` for
the `powercfg` toggle and what it costs.

### 2. Installed programs

Read all three uninstall hives and filter out `SystemComponent`:

```
HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*
HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*
HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*
```

Keep the raw objects (`UninstallString`, `QuietUninstallString`, `InstallLocation`,
`EstimatedSize`, `PSChildName` as the key name) and dump to JSON — `EstimatedSize`
is often wrong or 0, so treat it as a hint only.

### 3. Space audit, tiered

Measure directory sizes explicitly; never recursive-scan `C:\` root. See
`references/powershell-gotchas.md` for why and for the safe scoping pattern.

Order that finds the real hogs fastest:
1. `%LOCALAPPDATA%` and `%APPDATA%` one level deep (this is where it usually is).
2. `C:\Program Files`, `C:\Program Files (x86)`, `C:\ProgramData`.
3. User profile top-level, then `Documents` / `Downloads` / `Desktop`.
4. `C:\Windows\Temp`, `SoftwareDistribution\Download`, `WinSxS`, `Installer`.
5. Other drives, one level deep.
6. Files over ~300 MB across the main roots.

Skip junctions, and skip them by reparse tag — not by `is_symlink()`. `Application
Data` / `Local Settings` are junctions to `AppData`, and Python reports
`is_symlink() == False` for a junction, so a naive walk follows them and a 50 GB
profile reports three times its real size. Test `os.path.isjunction(path)` on
every directory entry (`scripts/dir_sizes.py` does, and prints `<junction>`
instead of a size). Then reconcile the top-level total against the drive's
used-bytes figure before putting any number in the report — a profile total that
exceeds the whole drive's used space is the signature of junction double-counting.

When the user asks what a drive's root contains ("C:\ 这些都是啥？"), answer with a
labelled inventory: every top-level entry, its measured size, and one clause on
what it is — system component, vendor install, leftover, or the user's own code.
Then split it into deletable / never-touch. `references/audit-and-cleanup.md` has
the entry-by-entry table.

### 4. Evidence for "unused" / "broken" programs

Three independent signals; a program is only "unusable" on evidence, not on a
stale `InstallLocation`:

- **Last run** — `C:\Windows\Prefetch\*.pf` last-write time, matched on the exe
  name. `NO RECORD` means never launched since prefetch was cleared.
- **Files present** — does `InstallLocation` exist, and does the uninstaller it
  names exist?
- **Binary search** — before calling anything an orphan, search for its exe under
  Program Files and the other drives. A program registered at a stale path is
  often alive somewhere else.

### 5. Report, then execute

Report in this order: already freed → blocked by the system → needs a decision →
deliberately untouched (and why). The "deliberately untouched" section prevents
the user re-asking about things you already judged.

Execute only approved items. Measure before/after and report actual reclaimed
bytes — claimed bytes you did not verify are a lie the user will catch.

### 6. File organization

Classify by intent, not by extension: contracts/commercial, project kickoff &
requirements, product & market, technical docs, meeting notes, papers & standards,
spreadsheets, receipts, supplier files, installers, media, uncategorized.
Generate a **preview** (target folder, count, size, sample filenames) and get
approval before moving anything. For a whole-drive job follow
`references/bulk-reorganization.md`: inventory once, dry-run the mapping table,
execute with a JSON move log, collapse depth, dedupe, verify, then purge.

Classify **top-level entries, not individual files.** A downloaded SDK or dataset
(`OPTControllerSDK-1.4.0/`, `lerobot示例数据/`) must move as one unit — pulling its
134 files into category folders destroys the package.

Leave in place: installed program dirs (`Program Files`, `Programs`, a bundled
Python), `$RECYCLE.BIN`, `System Volume Information`. A registry-referenced app
that moves breaks its shortcuts and uninstaller — name it as untouched rather
than moving it.

A "N levels max" constraint governs the taxonomy you build, not the inside of
code repos, SDKs or portable programs — those keep their own depth or they stop
running. Collapse deeper document folders by promoting the whole directory
(`15_它石\立项材料` -> `15_它石_立项材料`), never by scattering files into one flat
folder.

Move, do not copy, and write two artifacts next to the archive: a JSON move log
of `original -> new` pairs, and a generated `.ps1` that walks it in reverse.
Validate with `[ScriptBlock]::Create((Get-Content $p -Raw -Encoding UTF8))` before
telling the user it can undo the move.

Run an exact-duplicate pass (size bucket → MD5) before proposing dedup, scoped to
documents/media/installers. Inside one working folder the hit rate is usually
near zero — look-alikes like `合同 V1.1(1)(2)` are real revisions. Across many
download sources (chat exports, old archive folders, backups) the same file
typically sits in 2–4 places, and that is where the GB are.

## Pitfalls

- **DISM `/StartComponentCleanup` returning `0x80070005`** is a security-agent
  block, not a permission problem. Retry once; if it fails again, stop — do not
  escalate to SYSTEM scheduled tasks, and do not leave `wuauserv` / `usosvc`
  stopped (restart them and say so). Report the reclaimable figure as blocked.
- **Clearing an app cache requires the app closed.** Chromium/Electron cache
  deletion against a running process partially fails and can destabilize open
  tabs. Say up front that the app must be closed and let the user choose.
- **A big multi-app uninstall in one unattended command gets blocked.** Split
  destructive batches, and put the exact list in the reply for a one-word go-ahead.
- **A large `.img` / `.vhdx` / `.vdi` is usually sparse.** Deleting one that
  reports 119 GB can return only ~27 GB, because the logical size counts
  unallocated blocks. Never predict the win from the file size — delete it, then
  measure the drive's free-space delta and report that number.
- **`hiberfil.sys` is the biggest single reclaimable file on most desktops** and
  it is easy to miss because it is a hidden root *file*, not a folder. `powercfg
  /a` confirms hibernate and fast startup are on; `powercfg /hibernate off`
  deletes it outright. State that Fast Startup goes with it and give
  `powercfg /hibernate on` as the revert — it is a behaviour change, not a
  deletion.
- **Verify before "deleting" an item the user names.** It may already be gone
  from an earlier pass. `Test-Path` first, then report "already gone, 0 bytes"
  plus whether the owning app will recreate it — never imply a fresh deletion
  you did not perform.
- **Killing a stalled scan is correct.** A recursive size walk that runs past a
  few minutes will not finish; stop it, drop the offending root, re-scope. Any
  tree over ~100k files is beyond `du -sh` — walk it once in Python, dump a JSON
  inventory, and answer every later question from that file instead of re-walking.
- **`shutil.move` silently degrades to copy-then-delete.** When `os.rename`
  fails (path over MAX_PATH, ACL denial) it falls back to `copytree` + `rmtree`,
  leaving a half-copied destination and an intact source while printing thousands
  of per-file errors. Drive long-path trees through
  `robocopy src dst /E /MOVE /R:1 /W:1 /B` instead.
- **`robocopy /MOVE` leaves behind files it skipped as identical.** After a sync,
  confirm the destination is a superset by `{relpath: size}`, then purge the
  source with `robocopy <empty-dir> <source> /MIR`.
- **Never dedupe inside a code tree.** ROS `install/`, per-package meshes,
  `node_modules` and build outputs are byte-identical by design — a size-bucket
  pass there reports tens of GB of "waste" that is not waste.
- **Depth-collapse off-by-one.** Only re-home directories strictly deeper than
  the limit; applying the prefix logic to a directory already at the limit
  renames every file in it for no reason.
- **Moving a directory onto an existing directory nests it.** `shutil.move(a, b)`
  with `b` present puts `a` *inside* `b`; merge children explicitly when the
  target already exists.
- **Chinese/UTF-8 output from Python in this shell needs `PYTHONIOENCODING=utf-8`**,
  and `python -c` mangles Windows paths (`root='D:\'`). Write the script to a
  file and run it.
- **Never keep a helper script inside a directory the sweep will delete.** A pass
  over `%LOCALAPPDATA%\Temp` deletes the very script doing the pass and the next
  call dies with `can't open file ...`. Put inventories and probes in the session
  workspace or a dedicated folder outside every cleanup target, and let the wipe
  skip its own live log by name.
- **Do file operations on Chinese-named paths in Python, not in a `.ps1`.**
  PowerShell 5.1 decodes a BOM-less script as ANSI, so a Chinese literal inside
  `Test-Path -LiteralPath` resolves to nothing: `Test-Path` returns False, the
  delete is silently skipped, and the script still prints success — a fabricated
  deletion the user discovers later. Keep PowerShell for registry, services and
  `Clear-RecycleBin`; keep `os.path` / `shutil` for paths. See
  `references/powershell-gotchas.md`.
- **A `Run` or `UninstallString` value is quoted; never space-split it.**
  `"C:\Program Files\App\app.exe" /flag` splits to `C:\Program` and every
  installed program then reports as orphaned. Strip only the surrounding quotes,
  or `Test-Path` the directory instead of parsing the command line.

## Reporting the final number

Total reclaimed = end free space − start free space, per drive. Sum the
per-item deltas only when they agree with that figure. A per-item list that adds
up to more than the drive actually gained means an item was sparse or
overlapping — reconcile before reporting, never quote the sum of the parts.

## References

- `references/powershell-gotchas.md` — encoding/BOM traps, output capture, scan
  scoping, and PowerShell 5.1 syntax that silently breaks scripts.
- `references/audit-and-cleanup.md` — where Windows space actually hides, the
  Electron `Service Worker` cache leak, per-app cache paths, safe-to-delete
  lists, and orphan/removal recipes for MSI and Inno Setup products.
- `references/bulk-reorganization.md` — drive-scale reorganize: one-shot
  inventory, classify/override mapping, dry-run table, move log + reverse
  script, depth collapse, scoped dedupe, superset verification, long-path
  robocopy, purge, final tree report.
- `scripts/dir_sizes.py` — junction-aware per-child size table for one or more
  parents: `python dir_sizes.py "C:/Users/x/AppData/Local" "D:/"`. Prints totals,
  file counts, and caps the walk so a runaway tree cannot hang the call.
- `scripts/tree_view.py` — builds a self-contained collapsible HTML file tree
  plus a plain-text twin for any root:
  `python tree_view.py <root> <out.html> <out.txt> [max_files_per_dir]`.
