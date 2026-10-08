#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修 venv 控制台脚本的破损 shebang (家目录整合遗留)。

现象: gui-venv311/bin/* 的 shebang 仍指 /home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python
      (目录已搬进 zmax/) ⇒ 直接执行报 "cannot execute: required file not found"。
      `python -m <tool>` 不受影响, 但 `accelerate` / `hf` / `pyinstaller` 这类 CLI 会**静默失败**。
做法: 只改 shebang 首行; 改前备份 (.bak_shebang), 改后逐文件回读核验。
"""
import os
import shutil
import sys

VENV = "/home/ubuntu/zmax/gui-venv311"
WANT = f"#!{VENV}/bin/python"
OLD_PREFIXES = ("#!/home/ubuntu/lerobot-smolvla-lew/gui-venv311",
                "#!/home/ubuntu/zmax_rel/gui-venv311")
APPLY = "--apply" in sys.argv

fixed, skipped, touched = [], [], []
for name in sorted(os.listdir(os.path.join(VENV, "bin"))):
    p = os.path.join(VENV, "bin", name)
    if not os.path.isfile(p) or os.path.islink(p):
        continue
    try:
        with open(p, "rb") as f:
            first = f.readline()
    except Exception:
        continue
    if not first.startswith(b"#!"):
        continue
    line = first.decode("utf-8", "replace").rstrip("\n")
    if line == WANT:
        skipped.append(name)
        continue
    if not line.startswith(OLD_PREFIXES):
        continue
    # 保留原解释器后缀 (有的写 .../bin/python3)
    if APPLY:
        shutil.copy2(p, p + ".bak_shebang")
        data = open(p, "rb").read()
        rest = line.split("python", 1)[1] if "python" in line else ""
        new_first = (WANT + rest + "\n").encode()
        body = data.split(b"\n", 1)[1] if b"\n" in data else b""
        with open(p, "wb") as f:
            f.write(new_first + body)
        # 回读核验
        back = open(p, "rb").readline().decode().rstrip("\n")
        if back != WANT + rest:
            print(f"  ❌ 回读不一致 {name}: {back}")
            continue
        os.chmod(p, 0o755)
    touched.append(name)

print("=" * 60)
print(f"venv = {VENV}")
print(f"模式 = {'APPLY' if APPLY else 'DRY-RUN'}")
print(f"扫描 bin/ 可执行脚本: 破损待修 {len(touched)} 个 · 已正常 {len(skipped)} 个")
for t in touched:
    print("   ·", t)
if touched and not APPLY:
    print("(DRY-RUN, 未改动任何文件; 加 --apply 执行)")
