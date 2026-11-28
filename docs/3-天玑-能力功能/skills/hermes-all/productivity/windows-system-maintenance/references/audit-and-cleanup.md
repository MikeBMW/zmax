# Where Windows space actually hides, and what is safe to delete

## Ranked by what pays off

1. `%LOCALAPPDATA%` and `%APPDATA%` — Chromium/Electron profile data and caches.
   Almost always the top result on a developer or office machine.
2. `C:\Program Files*` — real installs, rarely trimmable except by uninstalling.
3. `C:\Windows\WinSxS` — 15–20 GB typical, ~half is superseded-update backup.
   Only DISM may touch it.
4. `Documents` — IM clients store received files here (`xwechat_files`,
   `WXWork`), often several GB each.
5. User `Downloads` — usually small but full of installers and old revisions.

Ignore `Application Data` and `Local Settings` when listing the profile: they are
junctions to `AppData` and double-count it.

## The Electron / Chromium `Service Worker` cache leak

This is the single most valuable finding on a machine full of chat and browser
apps. The path is

    <profile>\Service Worker\CacheStorage

A healthy profile keeps this in the tens-to-hundreds of MB. Multi-GB means the
cache was never evicted — a known bug, not a sign the user did something wrong.
It appears in plain Chromium and in every Electron app that embeds a web view.
Observed in the same profile family:

| App | Path under the profile |
|---|---|
| Chromium | `User Data\Default\Service Worker\CacheStorage` |
| Feishu / Lark | `profile_explorer\Service Worker` |
| Feishu / Lark | `PartitionsV2\preview-file\WebStorage` (preview cache) |
| Teams / Slack / VS Code | `<profile>\Service Worker\CacheStorage` |

Deleting it only costs a re-fetch when a web app is next opened. The app must be
closed first — deletion against a running process partially fails.

### Feishu / Lark layout

`%APPDATA%\LarkShell\aha\users\<32-hex-account-id>\`

One directory per signed-in account. Inside each: `profile_explorer` (embedded
browser: `Cache`, `Code Cache`, `Service Worker`), `profile_main`, and
`PartitionsV2` (per-partition data, including `preview-file`). Old account
hashes with no recent activity are usually abandoned logins — check before
assuming they are live.

## Zero-risk deletions

Safe on any machine, no user data inside:

- `%LOCALAPPDATA%\Temp` and `C:\Windows\Temp` — filter to files older than a few
  days so in-use handles are skipped.
- `%APPDATA%\Tencent\WXWork\upgrade` — WeCom installer cache, often 1–2 GB.
- `%LOCALAPPDATA%\CrashDumps`, `\pip\cache`, `\Microsoft\Edge\User Data\Crashpad`.
- `C:\Windows\SoftwareDistribution\DeliveryOptimization` (often already empty).
- `C:\Windows\Logs\CBS` older than a month.
- Recycle bin, `C:\Windows.old`.

## Top-level `C:\` entries

A root listing is what users ask about ("C:\ 这些都是啥？"); have an answer per
entry rather than a raw size dump.

| Entry | What it is | Action |
|---|---|---|
| `hiberfil.sys` | hibernate image, ~40% of RAM | `powercfg /hibernate off` |
| `pagefile.sys`, `swapfile.sys` | virtual memory | never delete |
| `Recovery` | WinRE environment | never delete |
| `System Volume Information` | restore points / shadow copies | `vssadmin` only, report don't act |
| `$Recycle.Bin` | recycle bin | `Clear-RecycleBin -Force` |
| `Documents and Settings` | junction to `Users` | ignore — double-counts |
| `PerfLogs`, `inetpub`, `OneDriveTemp`, `temp` | empty scaffolding, 0 bytes | safe, gains nothing |
| `Aomei`, `Lenovo*`, vendor folders | leftovers from a tool's boot disk | usually safe |

- `hiberfil.sys` is hidden and easy to miss, and on a desktop it is often the
  single largest file on the drive. `powercfg /a` shows whether hibernate and
  fast startup are enabled. `powercfg /hibernate off` deletes the file and turns
  both off; `powercfg /hibernate on` restores them. It is a behaviour change, so
  say what it costs and give the revert command.
- Vendor boot images (`C:\Aomei\AomeiBoot.wim` + `.sdi`, vendor WinPE folders)
  run from several hundred MB to over a GB and matter only if that tool's
  recovery mode is booted. Removing them does not affect Windows boot.
- `vssadmin list shadowstorage` reports used / allocated / maximum. Deleting
  restore points removes a recovery capability — report the number, do not act.
- Empty vendor directories are 0 bytes. Deleting them is cosmetic; say that
  instead of presenting it as reclaimed space.

## WinSxS

`dism /Online /Cleanup-Image /AnalyzeComponentStore` reports total, shared with
Windows, and "backups and disabled features". That last figure is the theoretical
reclaim.

`dism /Online /Cleanup-Image /StartComponentCleanup [/ResetBase]` is the only
sanctioned action. If it returns `0x80070005`, an endpoint-security agent is
refusing the CBS session — retrying, stopping `wuauserv`, and re-running as SYSTEM
all fail the same way. Stop there, restart any service you stopped, and report it
as blocked rather than forcing the store.

## Removing a dead program

Confirm it is dead first (see the three signals in SKILL.md). Then pick the
strategy from the uninstall string:

- **MSI** (`MsiExec.exe /X{GUID}` or `/I{GUID}`):
  `msiexec /X{GUID} /qn /norestart`. Exit code `0` = removed,
  `1605` = product not installed (already gone).
- **Inno Setup** (`unins000.exe`, key ending `_is1`): run
  `unins000.exe /SILENT` if the file still exists; otherwise the install is
  already gone and only the registry key needs deleting.
- **Orphan** (install dir missing, uninstaller missing): `reg export` the key,
  `reg delete <key> /f`, and remove leftover `.lnk` under
  `%ProgramData%\Microsoft\Windows\Start Menu\Programs`,
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs`, and `%PUBLIC%\Desktop`.
- **Store apps**: `Remove-AppxPackage -Package <PackageFullName>`, then
  `Remove-AppxProvisionedPackage -Online` so it does not return for new users.

### When the user already deleted the program themselves

"I deleted the programs, now you clean up" is three separate jobs: the bytes are
still in the recycle bin, the registry and services still believe the program
exists, and shortcuts still point at it. Do all three in one pass.

**1. The bytes are in `$RECYCLE.BIN` on the drive they ran from.** That is the
entire space win, and it is irreversible — list the contents in the reply first.
The `$I*` files next to the `$R*` payloads carry the original path, size and
deletion time (8 B header, 8 B size, 8 B FILETIME, 4 B name length, then the path
as UTF-16LE):

```python
import glob, struct, datetime
for f in sorted(glob.glob(r"D:\$RECYCLE.BIN\S-1-5-*\$I*")):
    b = open(f, "rb").read(600)
    size = struct.unpack("<Q", b[8:16])[0]
    ts = struct.unpack("<Q", b[16:24])[0]
    when = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ts / 10)
    n = struct.unpack("<I", b[24:28])[0]
    path = b[28:28 + n * 2].decode("utf-16-le", "ignore").rstrip("\x00")
    print(size / 1024**3, when, path)
```

Then `Clear-RecycleBin -DriveLetter D -Force`, and confirm the directory is empty
and the drive's free-space delta matches.

**2. Orphaned uninstall entries.** A key whose `InstallLocation` and whose
`UninstallString` exe both no longer exist is dead: `reg export` it, `reg delete
<key> /f`, and tell the user where the backup landed.

**3. Orphaned services.** `Get-CimInstance Win32_Service -Filter "Name='X'"` shows
the `PathName`; if that exe is gone the service is a leftover that blocks a clean
reinstall. Stop it, then `sc.exe delete X`.

**4. Leftover profile data.** `%LOCALAPPDATA%\<app>`, `%APPDATA%\<app>`,
`%ProgramData%\<app>` — tens to hundreds of MB, delete with the rest.

**5. Broken shortcuts.** Walk `%USERPROFILE%\Desktop`, `%PUBLIC%\Desktop` and the
Start Menu, resolve each `.lnk` with `WScript.Shell.CreateShortcut().TargetPath`,
and delete only the ones whose target no longer exists. Report the target path of
each so the user can object.

**6. Startup entries.** For each `Run` value, `Test-Path` the directory the
executable lives in — not a space-split of the command line, which turns
`"C:\Program Files\App\app.exe" /flag` into `C:\Program` and makes every healthy
program look stale.

Afterwards re-query rather than assuming: service gone, no matching uninstall
entries, every `Run` target present, recycle bin empty.

### Store bloat that is safe to remove

Bing News, Bing Weather, Solitaire Collection, GamingApp, Xbox Gaming Overlay,
Xbox SpeechToText overlay, GetHelp, Windows Feedback Hub, Clipchamp, Todos,
YourPhone / CrossDevice.

### Do not remove

- VC++ / .NET runtimes and `VCLibs`-style frameworks — other software depends on
  them.
- Driver packages, `DolbyDigitalPlusDecoderOEM` (audio playback), Intel graphics
  and Thunderbolt control centers.
- `Microsoft.Paint`, `ScreenSketch`, `WindowsTerminal`, `ZuneMusic` (the modern
  Media Player), `SecHealthUI`.
- **WSL toolchain even when never launched**: `VcXsrv` (X server for WSL GUI) and
  `usbipd-win` (USB passthrough). They are configure-once infrastructure; a
  prefetch gap is not evidence of disuse. Tie the decision to whether
  `vscode-remote-wsl` / WSL distros exist rather than to run history.

## Judgement calls that look like cleanup but are not

- A large `.img` / `.vhdx` device snapshot in a backup folder is the user's
  restore point. Never remove it on size alone; it needs an explicit yes.
- Old versions of the same document are real revisions, not duplicates. Only an
  exact SHA256 match justifies calling two files the same.
- Files with recent modification dates are in active use even if the folder
  looks messy.
