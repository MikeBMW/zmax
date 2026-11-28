# Delivering an upstream patch from a Windows deployment

Use when the deployment is a copy of a repo you can read but not push to: you found or fixed a
defect on the running install (startup cost, spawn flags, POSIX paths, a layout bug) and the
user wants something the packaging side can merge.

Hand-writing a `.diff` from memory produces a patch that will not apply. Generate it from a
clone of the commit the deployment claims to be.

## 1. Sparse clone at the deployed commit

```bash
git clone --depth 1 --filter=blob:none --sparse <repo-url> <scratch>/patchwork
cd <scratch>/patchwork && git sparse-checkout set <gui-dir> <offending-module-dir>
git log -1 --format='%h %s'        # record the base commit in the note
```

Two directories are usually all you need. A full clone of a data-heavy repo costs minutes and
gigabytes for files the patch does not touch. Add the third path only when the fix spans it.

## 2. Edit the clone, never the deployed copy

The deployed tree has NTFS line-ending and exec-bit drift; a diff taken there is full of
mode changes and will not apply cleanly upstream. Keep the deployed-copy edits as a separate,
throwaway step for on-machine verification.

## 3. Cross-cutting fixes: one interception point beats N call sites

When the same defect appears at dozens of call sites (a spawn flag, a path helper, a timeout),
wrap the entry point once and note the alternative:

```python
if os.name == "nt" and not os.environ.get("<APP>_SHOW_HELPER_CONSOLE"):
    _orig = (subprocess.run, subprocess.Popen, subprocess.check_output, subprocess.call)
    def _hidden(kw):
        kw.setdefault("creationflags", 0x08000000)   # CREATE_NO_WINDOW
        return kw
    ...
```

`setdefault` so an explicit caller value still wins. In the note, state that the explicit
per-call variant is behaviorally identical in case the reviewer prefers it.

Every interception patch needs a **rollback switch** (an env var that restores the original
behavior) and a line in the note saying what it restores. That is what makes the patch
reversible when it turns out to hide diagnostics someone needed.

## 4. Prove the patch applies before sending it

```bash
git diff --stat                       # what you think you changed
 git diff > fix.patch                # the artifact
git checkout -- <paths>              # back to clean
git apply --check -v fix.patch        # must pass on a CLEAN tree
git apply fix.patch && git diff --stat  # and produce the same stat
```

`git apply --check` on a clean tree is the only thing that makes the patch trustworthy; it
also catches CRLF/whitespace damage from editing on Windows. `py_compile` (or the language
equivalent) every touched file before shipping.

## 5. The note is half the deliverable

Ship `<app-root>/_patches/<topic>/` containing the `.patch` and a Chinese-readable `说明.md`
(the user forwards the note, not the diff). It must carry:

- **one entry per bug**: symptom → mechanism → `file::function`; quote the offending default
  argument or flag, because that is what the reviewer checks first;
- **the measurement that found it** (sampler output, percentage of samples in one function)
  and the **after numbers** — a before/after table of milestones the user can re-run;
- **apply commands**, including `git apply --check`, the `--3way` fallback for a moved mainline,
  and a suggested commit message;
- **rollback switches** and what each restores;
- an explicit **verified / not verified** split: an in-place runtime patch is verified, the
  repackaged build is not — say so instead of implying a full regression ran;
- **leftovers found but not fixed**, so they get scheduled instead of rediscovered.

## 6. Say what you cannot do

No push access, no `gh`, no credentials means the user copies two files to the build machine.
State that plainly and give the exact apply commands — do not imply a PR was opened.
