# Sync & Completeness Audit for a Deployed App Tree

Use when asked "is everything synced / did we copy everything" for an app directory that
was produced from a git repo (often on another OS or another machine).

## Baseline: counts against the deployment note

```bash
cd <AppRoot>
for d in config src models docs data _internal; do
  printf "%-8s %8s\n" "$d" "$(find $d -type f 2>/dev/null | wc -l)"
done
git log -1 --format='%h %ad %s' --date=short
git rev-parse --abbrev-ref HEAD
```

A count that matches the note exactly is the strongest single signal that the copy is
complete; a mismatch localizes the missing subtree in one step.

## Content vs noise

```bash
git diff --stat -- <dir>                   # insertions/deletions
git diff --ignore-cr-at-eol --stat -- <dir>
git diff --summary -- <dir> | awk '{print $1,$2}' | sort | uniq -c
```

- `N files changed, 0 insertions(+), 0 deletions(-)` → same content, metadata only.
- `mode change` lines → executable-bit / CRLF-normalisation artifacts of copying to NTFS;
  report them as such, never as edits.
- 0-line diff plus 0 missing tracked files (`git status --porcelain | grep -c '^ D'`) means
the tree equals that commit.

## Upstream drift

```bash
git fetch --quiet origin main
git log --oneline -1 HEAD..origin/main          # what upstream has beyond the deployment
git diff --stat HEAD..origin/main -- <dir>      # did that drift touch the tree in question?
```

Scope the diff to the directory the user asked about: "upstream is 1 commit ahead" is
uninteresting if that commit does not touch their docs.

## Untracked local additions

```bash
git status --porcelain -- <dir> | grep '^??' | sed 's/^?? //' | tr -d '"' \
  | cut -d/ -f1-2 | sort | uniq -c | sort -rn | head
```

Non-ASCII paths come back quoted with octal escapes — `tr -d '"'` plus `-z`/`core.quotePath=false`
(`git -c core.quotePath=false status ...`) keeps the grouping readable.

## Checksum manifest when the peer machine is unreachable

Generate on the Windows side, verify on the Linux/peer side — no shared filesystem needed:

```python
import hashlib, os
root = r"D:\App"
lines = []
for dp, _, fns in os.walk(os.path.join(root, "docs")):
    for fn in fns:
        p = os.path.join(dp, fn)
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
        lines.append(f"{h.hexdigest()}  {os.path.relpath(p, root).replace(chr(92), '/')}")
with open(os.path.join(root, "manifest.sha256"), "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(sorted(lines, key=lambda s: s.split('  ', 1)[-1])) + "\n")
```

Paths are relative to the app root with forward slashes, so verification is one command:

```bash
cd ~/app && sha256sum -c --quiet /path/to/manifest.sha256   # empty output = identical
```

Write the manifest *outside* the compared directory. If the non-ASCII filenames make
`sha256sum -c` report `No such file`, fall back to comparing hash **sets**
(`awk '{print $1}' | sort` on both sides) instead of path-keyed verification.

## Reporting

Split the answer into: (a) what is verified identical (with the number), (b) what drifted
upstream, (c) what the deployment intentionally omitted but will bite later, (d) what you
could not check and why. Never let (a) imply (d) was checked.
