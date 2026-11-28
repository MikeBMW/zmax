# Bulk drive reorganization

Taking a messy drive and producing a small, predictable taxonomy: N top folders,
D levels deep, duplicates gone, everything reversible. Companion to section 6 of
SKILL.md.

## Target design decisions (settle these before touching anything)

| Bucket | Goes where | Why |
|---|---|---|
| documents (pptx/docx/pdf/xlsx) | `01_文档资料\<intent>` | the only part that is actually being "classified" |
| project/client material | `02_项目资料\<project>` | keep client grouping intact |
| code repos, notebooks, datasets | `03_代码工程\<repo>` | internal depth preserved |
| installers, SDKs, portable apps | `04_软件安装\<安装包\|SDK\|便携程序>` | never mixed with docs |
| images, video, diagrams, 3D | `05_素材资源\<type>` | cheap to classify by extension |
| installed programs, recycle bin, System Volume Information | stay put | registry/shortcut references |

Ask the user exactly two things before executing: whether installed-program dirs
may move, and whether code trees may be flattened. Everything else is your call.
A five-question form gets ignored; one terse numbered list gets an answer.

## Phase 0 — Inventory once

Walk the drive a single time in Python (`os.walk`, skip `$RECYCLE.BIN` and
`System Volume Information`) and write a JSON of `(rel_dir, name, size, ext)`.
Report from it: bytes/files per top-level dir, extension histogram, depth
distribution, and the deepest subtrees. `du -sh` on a 100k+ file tree does not
finish inside a 300 s tool timeout, and re-walking for every question wastes
minutes.

```python
for dp, dn, fn in os.walk(root):
    dn[:] = [d for d in dn if d not in {'$RECYCLE.BIN', 'System Volume Information'}]
    ...
json.dump(files, open(scratch / 'scan.json', 'w', encoding='utf-8'), ensure_ascii=False)
```

Run with `PYTHONIOENCODING=utf-8`; write the script to a file rather than
`python -c` (backslashes and Chinese literals both break inline).

## Phase 1 — Build the plan, dry-run it

One list of `(KIND, src, dst)`:

- `DIR_MOVES` — explicit pairs for every directory you already understand
  (archive folders already categorized, `_光引擎\01_工艺流程`, `静界`, SDK zips…).
  Order matters: move a parent's children out first when the parent is also moving.
- `LOOSE_DIRS` — the few directories holding loose files (drive root, chat
  download dump, old `备份`); each file goes through `classify()`.
- `OVERRIDE` — a hand-written `{filename: target}` dict consulted before
  `classify()`. This is where quality comes from.

`classify()` order: installer extensions → archives (SDK-looking archives to
`SDK`, else `技术资料\压缩包`) → images/video → code extensions → keyword rules
in priority order (contract → requirement → meeting → product/market → paper →
technical → table) → `00_待归类`.

Expect the keyword engine to dump ~15–20% of files into `00_待归类`. Print the
mapping table for **every** loose file, read it, and convert each mis-triage into
an `OVERRIDE` entry; then read the leftover `00_待归类` list and classify those by
hand too. Two or three files may genuinely stay uncategorized — that is fine.

Never build and execute the plan in one shot: dry-run prints
`count -> destination` per target plus the full file table, review it, then re-run
with `--go`.

## Phase 2 — Execute with a log

```python
def uniq(dst):                     # collision -> "name (2).ext"
    ...
def move(src, dst):
    if os.path.isdir(src) and os.path.isdir(dst):   # MERGE, do not nest
        for n in os.listdir(src):
            move(os.path.join(src, n), os.path.join(dst, n))
        return
    final = uniq(dst); log.append({'src': src, 'dst': final})
    os.makedirs(os.path.dirname(final), exist_ok=True)
    shutil.move(src, final)
```

Same-volume moves are `os.rename` and effectively instant — 40 GB / 200k files
finishes in well under a minute. Log every pair to `D:\_整理日志.json`.

Generate the reverse script from the log at the end (reversed order,
`Move-Item -LiteralPath ... -Force`, `New-Item -ItemType Directory -Force` for
the parent), then syntax-check it with
`[scriptblock]::Create((Get-Content -Raw 'D:\_还原整理.ps1'))`.

## Phase 3 — Depth collapse

Loop: find directories strictly deeper than the limit that contain files, take
the shallowest batch, rename each to `parent_dirname + '_' + dirname` inside the
grandparent, repeat until none remain. Renaming the directory keeps its files
together; pulling files up into one flat folder loses the grouping and produces
hundreds of `name (2)` collisions.

Leave code repos, SDKs and portable-program folders out of the collapse — they
carry their own depth by design.

## Phase 4 — Dedupe, scoped

- Size bucket → MD5. Keep the newest mtime, move the rest to
  `01_文档资料\99_重复待删\`, and let the user delete that folder after review.
  Never delete on your own authority.
- Directory-level dup: signature = `sorted((relpath, size))`; identical
  signatures mean a whole duplicate SDK/package — move one wholesale.
- Version series (`_v1/_v2/_v3`, `初稿`, `修订`) are history, not duplicates.
  Report the count, do not merge.
- Skip code trees entirely (see the pitfall in SKILL.md).

## Phase 5 — Verify, then purge leftovers

A partially finished move leaves a source tree next to a complete destination.
Before deleting anything, build `{relpath: size}` for both sides and require the
destination to be a **superset** (every source entry present with the same size).
Only then

```powershell
robocopy <empty-dir> <leftover-source> /MIR /R:0 /W:0   # empties it, handles long paths
Remove-Item -LiteralPath <leftover-source> -Recurse -Force
```

Deletion needs its own approval: one terse question with the exact figures
("D:\全息 4.04GB / D:\xspace 11.49GB，已逐文件核对，删掉吗？"). Do not bundle it
into the move command, and do not retry a blocked delete.

## Phase 6 — Report and let the user see the tree

Final report: top-level tree with file counts and sizes, what stayed (installed
programs, empty user-created folders), what still needs a decision
(`99_重复待删`, `00_待归类`), and the undo path. A plain-text tree beats prose.
Then run `scripts/tree_view.py` for the folder (and the drive) and give the user
the absolute paths — open it yourself with `file:///D:/...` and screenshot before
claiming it renders.

## Writing the artifacts

Put `_整理日志.json`, `_还原整理.ps1` and `_整理说明.txt` at the root of what you
reorganized, and the tree viewer next to the folder the user is working in. State
their absolute paths in plain text; there is no attachment channel.
