# PowerShell gotchas when driven from bash on Windows

## Non-ASCII in a .ps1 needs a UTF-8 BOM

Windows PowerShell 5.1 decodes a script file as ANSI when it has no BOM. Any
Chinese (or other non-ASCII) literal then gets mangled into invalid tokens and
the parser fails with errors that look unrelated to encoding:

    ȱ�ٽ����: '��          (string is missing the terminator)
    MissingEqualsInHashLiteral

Two ways out, in order of preference:

1. Keep the script pure ASCII — English identifiers, English messages — and pass
   any Chinese data in through a file or JSON instead of string literals.
2. If the script must contain non-ASCII, write it with a BOM:

```python
with io.open(r'C:\path\script.ps1', 'w', encoding='utf-8-sig') as f:
    f.write(ps_source)
```

`write_file` produces UTF-8 without BOM, so scripts written directly with it are
the ones that break. Verify before blaming the logic.

## Capturing output without corrupting it

`powershell ... > out.txt` from bash captures UTF-16LE and the file then reads as
binary. Write from inside PowerShell instead:

```powershell
# collect into a list, then write once
$out = New-Object System.Collections.Generic.List[string]
$out.Add('...')
[IO.File]::WriteAllLines($path, $out, [Text.UTF8Encoding]::new($false))
```

or `... | Out-File -FilePath $p -Encoding UTF8`.

Chinese console output is also garbled under the GBK code page. Do not diagnose
anything from the console text — dump to a UTF-8 file and read the file.

## PowerShell 5.1 syntax that silently breaks scripts

- `if`/`else` is a statement, not an expression. `(if ($x) {'a'} else {'b'})`
  fails inside a format string or assignment. Assign first, then use the variable.
- A counter mutated inside a function needs `$script:name`; a bare `$name`
  creates a function-local copy and the caller sees zero.
- `-Filter` on `Get-ChildItem` accepts only one pattern. Loop for several.
- `Get-ChildItem -Depth` requires `-Recurse` to be meaningful; combine them.

## Same trap in Markdown skills

A colon inside a YAML `description:` value breaks frontmatter parsing. Avoid
colons in the description line entirely.

## Scanning safely

`Get-ChildItem C:\ -Recurse` will appear to hang. `C:\Windows\WinSxS` alone has
millions of hardlinked entries and a full walk takes many minutes even on NVMe.

Rules:
- Enumerate named directories, never `C:\` root, and stop at a bounded depth.
- Skip `WinSxS` entirely for size accounting; `dism /Online /Cleanup-Image
  /AnalyzeComponentStore` reports it authoritatively in ~2 minutes.
- For a whole-tree byte total where you only need the number, `robocopy` is far
  faster than PowerShell enumeration:

```
robocopy "C:\path" NULL /L /E /BYTES /NFL /NDL /NC /NJH /XJ
```

  Its summary is localised **and GBK-encoded** on a Chinese Windows. Decoding it
  as UTF-8 yields mojibake, the line match silently fails, and every directory
  reports `??` with no error. Capture bytes and decode explicitly, matching the
  localised label as well as the English one:

```python
r = subprocess.run(['robocopy', path, 'NULL', '/L', '/E', '/BYTES',
                    '/NFL', '/NDL', '/NJH', '/NC', '/XJ', '/R:0', '/W:0'],
                   capture_output=True)
for line in r.stdout.decode('gbk', errors='replace').splitlines():
    s = line.strip()
    if s.startswith('字节') or s.startswith('Bytes'):
        nums = [p for p in s.replace(':', ' ').split() if p.isdigit()]
        total = int(nums[0])   # bytes
        break
```

  `robocopy` also counts hardlinked files once per link, so `Windows` + `WinSxS`
  over-report by several GB. Treat its totals as a ranking tool, and reconcile
  against the drive's used-bytes figure before quoting a sum.

- If a scan is already running past a few minutes, kill the process
  (`Stop-Process -Id <pid> -Force`) and re-scope. Waiting does not help.
- Enumerate before deleting: capture the child items into a variable, then pipe
  that to `Remove-Item`. Deleting while enumerating a live tree skips entries.

## Measuring reclaimed space honestly

Compute used bytes before and after the operation and report the delta. A
`Remove-Item` that silently skipped locked files reports no error, so an
unverified "freed 15 GB" claim will be wrong. Sizes from `EstimatedSize` in the
registry are frequently 0 or wildly off — always measure the directory on disk.
