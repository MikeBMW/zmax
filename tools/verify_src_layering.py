# -*- coding: utf-8 -*-
"""判据: 分层归位 —— 核心逻辑在 src/, tools/gui 只留 GUI 与别名 shim, 死代码不再回流。

老倪 2026-10-17: 「控制台gui为什么那么多程序？是不是还有不合理的代码，你整合一下，
                自主迁移到工程的src中，没用的删掉」

跑法: ./gui-venv311/bin/python tools/verify_src_layering.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
PY = sys.executable

# 已归位清单: 旧名 → 真身 (相对仓库)
MOVED = {
    "state_space_sim_real": "src/lerobot/engine/runtime.py",
    "state_space_sim": "src/lerobot/engine/sim.py",
    "ss3d_live": "src/lerobot/engine/ss3d_live.py",
    "data_world": "src/lerobot/engine/data_world.py",
    "inference_server": "src/lerobot/serving/server.py",
    "inference_client": "src/lerobot/serving/client.py",
    "feature_dbc": "src/lerobot/features/dbc.py",
    "model_importer": "src/lerobot/features/importer.py",
    "docs_sync": "src/lerobot/ops/docs_sync.py",
    "simulink_ci": "src/lerobot/ops/flow_ci.py",
    "ppt_engine": "src/lerobot/ops/ppt_engine.py",
    "startup_probe": "src/lerobot/ops/startup_probe.py",
    "zmax_platform_info": "src/lerobot/ops/platform_info.py",
    "zmax_telemetry": "src/lerobot/ops/telemetry.py",
    "muscle_memory": "src/lerobot/skills/muscle_memory.py",
    "relay_middleware": "src/lerobot/middleware/relay.py",
    "dds_link_bus": "src/lerobot/middleware/link_bus.py",
    "dds_hw": "src/lerobot/middleware/dds_hw.py",
    "yolo_perception": "src/lerobot/perception/yolo.py",
    "gen_ss_obs_layout": "tools/gen/ss_obs_layout.py",
    "gen_ss_obs_layout2": "tools/gen/ss_obs_layout2.py",
    "gen_dual_brain_flow": "tools/gen/dual_brain_flow.py",
    "gen_llm_layer_topology": "tools/gen/llm_layer_topology.py",
}

# 允许留在 tools/gui 的零 Qt 文件 (附理由; 新增一个都要写明, 否则判据红)
ALLOW_IN_GUI = {
    "project_file": "项目文件读写, 直接依赖 GUI 的 model_tree/update_checker (迁移要先拆 GUI 依赖)",
    "data_space": "数据空间面板后端, 依赖 simulink_module (GUI 装配器)",
}

QT_KW = ("PyQt5", "pyqtgraph", "QtCore", "QtWidgets", "QtGui")
ok, bad = 0, []


def chk(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print(f"✅ {name}{(' · ' + extra) if extra else ''}")
    else:
        bad.append(name)
        print(f"❌ {name}{(' · ' + extra) if extra else ''}")


# ① 每个已归位模块: 真身存在 + tools/gui 只剩小 shim
for old, rel in MOVED.items():
    real = os.path.join(ROOT, rel)
    shim = os.path.join(GUI, old + ".py")
    have_real = os.path.isfile(real)
    shim_lines = len(open(shim, encoding="utf-8").read().splitlines()) if os.path.isfile(shim) else -1
    chk(f"{old:22s} 真身在 {rel}", have_real and 0 < shim_lines <= 40,
        f"shim {shim_lines} 行 / 真身 {os.path.getsize(real) // 1024 if have_real else 0} KB")

# ② 别名真的指向真身 (import 同一对象), 用真身所在解释器跑
bad_alias = []
for old, rel in MOVED.items():
    probe = ("import sys; sys.path[:0]=['tools/gui','src','tools/gen']\n"
             f"import {old} as M\nprint(M.__file__)")
    r = subprocess.run([PY, "-c", probe], capture_output=True, text=True, cwd=ROOT)
    _lines = (r.stdout or "").strip().splitlines()
    _file = _lines[-1] if _lines else ""       # 有些模块 import 时会打印, 取最后一行
    # 真身路径必须等于登记的相对路径 (不能是 tools/gui 里的那份)
    if r.returncode != 0 or os.path.realpath(_file) != os.path.realpath(os.path.join(ROOT, rel)):
        bad_alias.append(old)
chk("全部旧名 alias 到真身 (不是复制)", not bad_alias, f"异常 {bad_alias}" if bad_alias else f"{len(MOVED)}/{len(MOVED)}")

# ③ tools/gui 里不许再出现"零 Qt 的大块逻辑" (除 allowlist)
offenders = []
for fn in sorted(os.listdir(GUI)):
    if not fn.endswith(".py"):
        continue
    s = open(os.path.join(GUI, fn), encoding="utf-8").read()
    if any(k in s for k in QT_KW):
        continue
    if s.count("\n") + 1 > 150 and fn[:-3] not in ALLOW_IN_GUI:
        offenders.append(f"{fn}({s.count(chr(10)) + 1}行)")
chk("tools/gui 无未登记的零 Qt 大块逻辑", not offenders, f"越界 {offenders}" if offenders else "全部已归位或在 allowlist")

# ④ 死代码: 重复文件 / 空引用文件不再存在
chk("重复的 zmax_gui_launch.py 已删", not os.path.isfile(os.path.join(GUI, "zmax_gui_launch.py")))
chk("le_robot_home/le_robot_studio 已删",
    not os.path.isfile(os.path.join(GUI, "le_robot_home.py"))
    and not os.path.isfile(os.path.join(GUI, "le_robot_studio.py")))

# ⑤ 规模报告
gui_py = [f for f in os.listdir(GUI) if f.endswith(".py")]
gui_lines = sum(open(os.path.join(GUI, f), encoding="utf-8").read().count("\n") for f in gui_py)
src_new = 0
for rel in MOVED.values():
    p = os.path.join(ROOT, rel)
    if os.path.isfile(p):
        src_new += open(p, encoding="utf-8").read().count("\n")
print(f"\n📊 tools/gui: {len(gui_py)} 个文件 · {gui_lines} 行 | 已归位到 src//tools/gen: {src_new} 行")

print()
if bad:
    print(f"❌ 失败: {bad}")
    sys.exit(1)
print(f"✅ 全部通过 ({ok} 项)")
