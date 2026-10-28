#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""save_release_5_50_740.py — 保存数据 + 归档 v5.50.740 (沿用 archive_release_* 约定)

产出两处:
  docs/data_snapshots/<date>_状态同步_v5.50.740_<主题>/   判据实跑输出 + git ref + 变更说明
  zmax_data/release_5.50.740_<date>/                     代码/唯一依据/证据 + MANIFEST.md + sha256sums.txt
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = "/home/ubuntu/zmax"
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
VER = "v5.50.740"
DAY = time.strftime("%Y%m%d")
TOPIC = "核心归位到src+调试停跳+跨平台打包+三产品同步"
SNAP = os.path.join(ROOT, "docs", "data_snapshots", f"{DAY}_状态同步_{VER}_{TOPIC}")
REL = os.path.join(ROOT, "zmax_data", f"release_5.50.740_{DAY}")

JUDGES = [
    ("integrity", ["tools/ci/integrity_check.py"]),
    ("verify_src_layering", ["tools/verify_src_layering.py"]),
    ("verify_engine_location", ["tools/verify_engine_location.py"]),
    ("verify_product_dev_profiles", ["tools/verify_product_dev_profiles.py"]),
    ("verify_product_ui", ["tools/verify_product_ui.py"]),
    ("verify_config_page_product_sync", ["tools/verify_config_page_product_sync.py"]),
    ("verify_product_release_factory", ["tools/verify_product_release_factory.py"]),
    ("verify_signal_panel", ["tools/verify_signal_panel.py"]),
    ("verify_trace_cols", ["tools/verify_trace_cols.py"]),
]

CODE = [
    "src/lerobot/engine/runtime.py", "src/lerobot/engine/sim.py", "src/lerobot/engine/ss3d_live.py",
    "src/lerobot/engine/data_world.py",
    "src/lerobot/serving/server.py", "src/lerobot/serving/client.py",
    "src/lerobot/features/dbc.py", "src/lerobot/features/importer.py",
    "src/lerobot/ops/docs_sync.py", "src/lerobot/ops/flow_ci.py", "src/lerobot/ops/ppt_engine.py",
    "src/lerobot/ops/startup_probe.py", "src/lerobot/ops/platform_info.py", "src/lerobot/ops/telemetry.py",
    "src/lerobot/skills/muscle_memory.py",
    "src/lerobot/middleware/relay.py", "src/lerobot/middleware/link_bus.py", "src/lerobot/middleware/dds_hw.py",
    "src/lerobot/perception/yolo.py",
    "tools/verify_src_layering.py", "tools/verify_engine_location.py",
    "tools/bump_version.py", "tools/ci/integrity_check.py",
    "tools/gui/canoe_graphic.py", "tools/gui/studio.py", "tools/gui/state_space_sim.py",
    ".github/workflows/build-win-exe.yml",
]
TRUTH = [
    "config/platform/zmax_product.json", "defaults/config/platform/zmax_product.json",
    "config/platform/dds_topic_types.json", "config/platform/zmax_platform.json",
    "data/database/zmax/sources/canvas/state_space_obs.json",
    "data/database/zmax/zmax_engineering.db",
]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def cp(rel, base):
    src = os.path.join(ROOT, rel)
    if not os.path.isfile(src):
        return False
    dst = os.path.join(base, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return True


os.makedirs(SNAP, exist_ok=True)
os.makedirs(os.path.join(REL, "evidence"), exist_ok=True)

# ① 判据实跑
lines = []
for name, cmd in JUDGES:
    t0 = time.time()
    r = subprocess.run([PY] + cmd, cwd=ROOT, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    tail = [l for l in out.strip().splitlines() if l.strip()][-3:]
    open(os.path.join(SNAP, f"judge_{name}.txt"), "w", encoding="utf-8").write(out)
    ok = r.returncode == 0
    lines.append((name, ok, tail[-1] if tail else ""))
    print(f"{'✅' if ok else '❌'} {name:34s} {time.time() - t0:5.1f}s  {tail[-1][:80] if tail else ''}")
open(os.path.join(REL, "evidence", "criteria_output.txt"), "w", encoding="utf-8").write(
    "\n\n".join(f"$ {' '.join(c)}\n" + open(os.path.join(SNAP, f"judge_{n}.txt"), encoding="utf-8").read()
                for n, c in JUDGES))

# ② git ref
g = subprocess.run(["git", "describe", "--tags", "--always"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
open(os.path.join(SNAP, "git_ref.txt"), "w", encoding="utf-8").write(f"version: {VER}\ntag/describe: {g}\nHEAD: {h}\n")

# ③ 代码 + 唯一依据
n_code = sum(1 for f in CODE if cp(f, REL))
n_truth = sum(1 for f in TRUTH if cp(f, os.path.join(REL, "truth")))
cp("VERSION.md", REL)

# ④ 说明
prod = json.load(open(os.path.join(ROOT, "config/platform/zmax_product.json"), encoding="utf-8"))
note = f"""# {VER} · {TOPIC}

- 版本: {VER} ({"判据全否见 judge_*.txt"})
- git: {h[:12]} · {g}
- 三产品: 550A/550B/550C 随包发布 · 唯一依据 updated={prod.get("updated")} · 现役 active={prod.get("active_product")}

## 本轮改了什么
1. 核心归位: RealStateSpaceSim(4240 行) + 22 个零 Qt 模块迁入 src/lerobot/{{engine,ops,serving,features,skills,perception,middleware}}
   与 tools/gen/; tools/gui 只留 GUI 与 ≤40 行别名 shim (sys.modules 换真身)
2. 删死代码: zmax_gui_launch.py (与 studio.py 逐字节相同, 15819 行) / le_robot_home.py / le_robot_studio.py
3. 调试停跳: 调试器连上时不启动 _HwFetcher/_StatusLightFetcher, 线程内未捕获异常只落盘
4. pyqtgraph 加固: setData(skipFiniteCheck=True) + refresh 重入闸 + Y 量程去级联
5. 跨平台: 23 个 shim 路径探测兼容 _MEIPASS; Windows/macOS 打包 job 补 engine/ops/serving/features/skills/
   perception/middleware + tools/gen
6. 判据修正: verify_product_ui ⑨ 改「唯一依据↔工程库同源」不再预先固定 89/190; verify_config_page_product_sync
   改读 _star_facts 摘要 (「当前 X」已不在左树文本)

## 判据
""" + "\n".join(f"- {'✅' if ok else '❌'} {n}: {t}" for n, ok, t in lines) + """

## 已知未过 (非本轮引入)
- verify_product_consistency ⑤ topic 签名单射性: 157 topic 落 21 个签名, 自 10-13 起同样 1 项红,
  属结构性建模 (报告内已注明超出数据一致性范围)。
"""
open(os.path.join(SNAP, "NOTE.md"), "w", encoding="utf-8").write(note)
open(os.path.join(REL, "MANIFEST.md"), "w", encoding="utf-8").write(note + f"""

## 归档内容
- 代码 {n_code} 个 · 唯一依据 {n_truth} 个 (truth/) · 判据输出 evidence/criteria_output.txt
""")

# ⑤ sha256sums
rows = []
for dp, _, fns in os.walk(REL):
    for fn in sorted(fns):
        if fn == "sha256sums.txt":
            continue
        p = os.path.join(dp, fn)
        rows.append(f"{sha(p)}  {os.path.relpath(p, REL)}")
open(os.path.join(REL, "sha256sums.txt"), "w", encoding="utf-8").write("\n".join(rows) + "\n")

print(f"\n快照: {SNAP}")
print(f"归档: {REL} · 代码 {n_code} · 唯一依据 {n_truth} · sha256 行 {len(rows)}")
