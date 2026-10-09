#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_project_archive.py — 工程存档 (.zmaxproj v2) 全流程取证

老倪: 「需要保存 状态空间工程的所有配置，包括画布的模型，右侧侧面栏的所有配置，标定，测量，
       以及主参数，都要有相应的文件，你来设计一下工程存档文件」

要证的不是"生成了个文件", 而是:
 ① 7 段真在: canvas/panel/calibration/master_param/measure/tasks/fingerprints, 内容与现场同源
 ② CLI 全链路: save → verify → inspect → explode(人看的文件) → diff
 ③ 漂移能被抓住: 改现场标定参数 → diff 报 calibration/master_param **漂移**并指出键
 ④ restore 默认**只回填画布+面板**, 标定真源 sha256 一个字节没变
 ⑤ `--with-calib --yes` 才恢复标定 (备份→写→回读), 恢复后 sha256 == 存档 sha256
 ⑥ 控制台在时 panel 段真读到 6 个运行开关 + 当前视图; apply_run_cfg 能把开关拨回去
 ⑦ v1 老存档仍可读 + 可升级 v2
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = "/home/ubuntu/zmax"
PY = os.path.join(ROOT, "gui-venv311/bin/python")
CLI = os.path.join(ROOT, "tools/project_archive.py")
TMP = "/tmp/zmax_arch_verify"
os.makedirs(TMP, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "tools/gui"))

FAIL = []
def chk(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        FAIL.append(msg)


def run(*args, expect=0):
    r = subprocess.run([PY, CLI] + list(args), capture_output=True, text=True, cwd=ROOT,
                       timeout=300, env={**os.environ, "PYTHONPATH": ""})
    if expect is not None and r.returncode != expect:
        print("     stdout:", (r.stdout or "")[-600:])
        print("     stderr:", (r.stderr or "")[-600:])
    return r


import project_file as PF     # noqa: E402

ARCH = os.path.join(TMP, "verify.proj")
MANIFOLD = os.path.join(ROOT, "config/calib/zmax_manifold.json")
_calib_bytes = open(MANIFOLD, "rb").read()          # 原始字节, 判据跑完复原

print("① 存档 7 段 (命令行存档 = 无控制台窗口, panel 段应诚实标注) ")
r = run("save", "--out", ARCH, "--note", "verify_project_archive 自测")
chk(r.returncode == 0 and os.path.exists(ARCH), "save 成功: %s" % (r.stdout or "").strip().splitlines()[0])
proj = json.load(open(ARCH, encoding="utf-8"))
SEC = ("canvas", "panel", "calibration", "master_param", "measure", "tasks", "fingerprints")
chk(proj.get("schema") == PF.SCHEMA, "schema = %s" % proj.get("schema"))
chk(all(isinstance(proj.get(s), dict) and proj.get(s) for s in SEC), "7 段都在: %s" % list(SEC))
chk(len(proj["canvas"]["nodes"]) > 0, "① canvas: %d 节点 / %d 连线" % (
    len(proj["canvas"]["nodes"]), len(proj["canvas"].get("links") or [])))
chk("控制台没打开" in ((proj["panel"].get("note") or "")), "② panel: 命令行存档诚实标注没读到开关: %s"
    % (proj["panel"].get("note") or "")[:40])
cal = proj["calibration"]
chk(set(os.path.basename(p) for p in cal["files"]) == {"zmax_calib.json", "zmax_manifold.json"},
    "③ calibration: %d 个真源文件带全文 + sha256" % len(cal["files"]))
chk(cal["uncalibrated"] == ["T_base_cam", "plane_z", "cell_geometry"],
    "③ 未标定项 = %s (与真源一致)" % cal["uncalibrated"])
chk(any("ss_geom_calib" in c for c in (cal.get("fix_cmds") or {}).values()), "③ 带现场标定命令")
mp = proj["master_param"]
chk(mp["M"] == 1.0 and mp["inertia"] is False, "④ master_param: M=%s inertia=%s" % (mp["M"], mp["inertia"]))
chk(bool(mp.get("node", {}).get("params")), "④ 带画布 M 节点 7 段快照 (%d 键)"
    % len((mp.get("node") or {}).get("params") or {}))
chk(bool((proj["measure"].get("measure_view") or {}).get("源")), "⑤ measure: measure_view 源 %d 条"
    % len((proj["measure"].get("measure_view") or {}).get("源") or []))
chk(len((proj["tasks"].get("content") or {}).get("tasks") or {}) == 5, "⑥ tasks: %d 个任务"
    % len((proj["tasks"].get("content") or {}).get("tasks") or {}))
chk(len(proj["fingerprints"]) >= 4, "⑦ fingerprints: %d 个真源文件" % len(proj["fingerprints"]))

print("\n② CLI: verify / inspect / explode / diff")
r = run("verify", ARCH)
chk(r.returncode == 0 and "自检通过" in r.stdout, "verify 自检通过")
r = run("inspect", ARCH)
chk("与当前现场" in r.stdout and "✅ canvas: 一致" in r.stdout, "inspect 逐段比对 (canvas/calib 一致)")
r = run("explode", ARCH, "--dir", os.path.join(TMP, "exploded"))
exp = os.path.join(TMP, "exploded")
want = ["canvas.json", "panel.json", "master_param.json", "measure.json", "tasks.json",
        "fingerprints.json", "MANIFEST.md", "calibration/zmax_calib.json", "calibration/zmax_manifold.json"]
chk(all(os.path.exists(os.path.join(exp, w)) for w in want), "explode 出人能看的文件: %s" % want)
man = open(os.path.join(exp, "MANIFEST.md"), encoding="utf-8").read()
chk("真源永远是仓库里的文件" in man, "MANIFEST 写明真源唯一 (快照 ≠ 真相)")
r = run("diff", ARCH)
chk("逐段一致" in r.stdout, "diff: 存档 == 现场 ✅")

print("\n③ 漂移能被抓住 (把真源 M 改成 1.5)")
code = ("import sys; sys.path.insert(0, %r); import zmax_params as zp;"
        "print(zp.write_manifold_M(1.5, None))" % os.path.join(ROOT, "tools"))
rr = subprocess.run([PY, "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=120,
                    env={**os.environ, "PYTHONPATH": ""})
chk(rr.returncode == 0, "现场 M 改成 1.5: %s" % ((rr.stdout or "").strip().splitlines() or [""])[-1][:80])
r = run("diff", ARCH)
chk("⚠️ calibration: 漂移" in r.stdout, "diff 报 calibration 漂移")
chk("master_param: 漂移" in r.stdout, "diff 报 master_param 漂移")
chk("M: 存档 1.0 → 现场 1.5" in r.stdout, "diff 指出具体键: M 1.0 → 1.5")

print("\n④ restore 默认只回填画布+面板 (标定真源不许动)")
h_before = PF.sha256_file(MANIFOLD)
r = run("restore", ARCH)
chk(r.returncode == 0 and "画布已写回" in r.stdout, "restore (无 --with-calib) 成功")
chk(PF.sha256_file(MANIFOLD) == h_before, "标定真源 sha256 未变 (默认不覆盖标定 ✅)")
chk("标定/主参数未恢复" in r.stdout, "输出里明说标定/主参数未恢复")
r = run("diff", ARCH)
chk("calibration: 漂移" in r.stdout, "漂移仍在 (因为没恢复) —— 符合预期")

print("\n⑤ --with-calib --yes 才恢复 (备份→写→回读)")
r = run("restore", ARCH, "--with-calib")
chk(r.returncode == 2 and "必须同时给 --yes" in r.stdout, "不给 --yes 时拒绝执行 (防误点)")
r = run("restore", ARCH, "--with-calib", "--yes")
chk("all_ok=True" in r.stdout, "恢复输出 all_ok=True")
chk(PF.sha256_file(MANIFOLD) == proj["calibration"]["files"]["config/calib/zmax_manifold.json"]["sha256"],
    "回读 sha256 == 存档 sha256 (三段纪律)")
chk(json.load(open(MANIFOLD, encoding="utf-8"))["M"] == 1.0, "真源 M 回到存档值 1.0")
baks = [f for f in os.listdir(os.path.join(ROOT, "config/calib")) if ".bak_" in f]
chk(len(baks) >= 1, "恢复前留了备份: %s" % sorted(baks)[-1:])
r = run("diff", ARCH)
chk("逐段一致" in r.stdout, "恢复后 diff: 存档 == 现场 ✅")

print("\n⑥ 控制台在时 panel 段真读到 6 开关 + 视图; apply 能拨回去")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication                     # noqa: E402
import simulink_module as SM                                 # noqa: E402
app = QApplication(sys.argv)
m = SM.SimulinkModule(); m.resize(2000, 1200); m.show()
m.load_flow_file(os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json"))
app.processEvents()
panel = PF.collect_panel(m, page=7)
chk(len(panel["run_switches"]) == 6, "panel.run_switches 真读到 6 个开关")
chk(panel.get("view") == "mparam" and panel.get("view_index") == 0,
    "panel 记下当前视图 = %s (index %s)" % (panel.get("view"), panel.get("view_index")))
chk(panel.get("canvas_stack_index") == 7, "panel 记下画布栈索引 (加载后切回画布页用)")
ARCH2 = os.path.join(TMP, "with_gui.proj")
r2 = PF.save_project(ARCH2, sim=m, page=7, note="带控制台")
p2 = json.load(open(ARCH2, encoding="utf-8"))
chk(len(p2["panel"]["run_switches"]) == 6 and p2["panel"]["view"] == "mparam",
    "带控制台存档: panel 段有 6 开关 + 视图")
chk(p2["measure"]["bus"]["mode"], "measure.bus 记下总线模式 = %s" % p2["measure"]["bus"]["mode"])
before = m.chk_engine_demo.isChecked()
m.chk_engine_demo.setChecked(not before)
n, skip = PF.apply_run_cfg(m, p2["run_cfg"])
chk(m.chk_engine_demo.isChecked() == before, "apply_run_cfg 把开关拨回存档状态 (写回 %d 项)" % n)
app.processEvents()

print("\n⑦ v1 老存档仍能读 + 升级 v2")
v1 = os.path.join(ROOT, "reports/projects/状态空间工程_20261008_1101.zmaxproj")
if os.path.exists(v1):
    s = PF.read_summary(v1)
    chk(s["schema"] == PF.SCHEMA_V1 and s["canvas_ok"], "v1 老文件 read_summary 能读 (schema %s)" % s["schema"])
    up = os.path.join(TMP, "upgraded.proj")
    r = run("upgrade", v1, "--out", up)
    chk(os.path.exists(up), "升级写出: %s" % up)
    p3 = json.load(open(up, encoding="utf-8"))
    chk(p3["schema"] == PF.SCHEMA and p3.get("upgraded_from") == PF.SCHEMA_V1,
        "升级后 schema=v2 且记录来源 v1")
    chk(p3["canvas"] == json.load(open(v1, encoding="utf-8"))["canvas"], "升级不动原画布内容")
else:
    chk(False, "找不到 v1 老存档样本")

print("\n⑧ 🗂 总工程 (zmax_space): 集成式打开一次全回填")
CANVAS_J = os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json")
_canvas_bytes = open(CANVAS_J, "rb").read()
SPACE = os.path.join(TMP, "zmax_space.proj")
r = run("space-save", "--out", SPACE)
chk(r.returncode == 0 and "kind=zmax_space" in r.stdout, "space-save 写出总工程 (kind 标记 + 集成段)")
sp = json.load(open(SPACE, encoding="utf-8"))
chk(sp.get("kind") == PF.KIND_SPACE and sp.get("integrated") == list(PF.INTEGRATED_SECTIONS),
    "总工程 kind=%s · 集成段 %s" % (sp.get("kind"), sp.get("integrated")))
# 🗂 后缀: 默认 .proj; 老 .zmaxproj 仍能读 (内容识别, 不看后缀)
chk(PF.EXT == ".proj", f"工程文件后缀 = {PF.EXT} (老倪: 后缀就该是 proj)")
chk(os.path.basename(PF.SPACE_NAME) == "zmax_space.proj", f"总工程默认名 {PF.SPACE_NAME}")
_old = os.path.join(TMP, "legacy_name.zmaxproj")
shutil.copy(SPACE, _old)
chk(PF.read_summary(_old)["kind"] == PF.KIND_SPACE and PF.is_space(_old),
    "旧后缀 .zmaxproj 的档案照样能读/认得出 (rename 前的老文件不作废)")

chk(PF.is_space(SPACE) and PF.read_summary(SPACE)["kind"] == PF.KIND_SPACE,
    "read_summary 能认出总工程 (老「加载工程文件」据此走集成式)")
# 搅乱三处: 标定 M, 活跃任务, 画布 (改一个节点坐标)
run("restore", SPACE, "--with-calib", "--yes")         # 先保证 M=1.0
code = ("import sys; sys.path.insert(0, %r); import zmax_params as zp; zp.write_manifold_M(2.5, None)"
        % os.path.join(ROOT, "tools"))
subprocess.run([PY, "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=120,
               env={**os.environ, "PYTHONPATH": ""})
subprocess.run([PY, os.path.join(ROOT, "tools/ss_task_bind.py"), "--activate", "TASK-02-HANDLE"],
               capture_output=True, text=True, cwd=ROOT, timeout=180,
               env={**os.environ, "PYTHONPATH": ""})
flows = PF._flows()
dcur, _ = flows.load_canvas()
dcur["nodes"][0]["x"] = float(dcur["nodes"][0].get("x") or 0) + 37.0
flows.save_canvas(dcur, reason="verify_mutate")
md5_mut = PF.canvas_md5(dcur)
chk(PF.canvas_md5(flows.load_canvas()[0]) == md5_mut, "现场已搅乱: 画布节点坐标 +37 / M=2.5 / 活跃 TASK-02")
r = run("space-open", SPACE, "--yes")
chk(r.returncode == 0 and "ok=True" in r.stdout, "space-open 集成式打开 ok=True")
for want in ("标定 zmax_calib.json", "标定 zmax_manifold.json", "主参数: M=1.0", "任务:", "画布:", "面板:"):
    chk(want in r.stdout, "报告含 %s" % want)
chk(PF.canvas_md5(flows.load_canvas()[0]) == sp["canvas_fingerprint"]["md5"], "画布已回填到总工程那一份 (md5 相同)")
chk(json.load(open(MANIFOLD, encoding="utf-8"))["M"] == 1.0, "主参数 M 回到 1.0")
chk(json.load(open(os.path.join(ROOT, "config/ss_task_binding.json"), encoding="utf-8")).get("active_task")
    == (sp["tasks"]["content"].get("active_task")), "活跃任务回到 %s" % sp["tasks"]["content"].get("active_task"))
r = run("diff", SPACE)
chk("逐段一致" in r.stdout, "集成式打开后 diff: 总工程 == 现场 ✅")
r = run("space-show", SPACE)
chk("① canvas" in r.stdout and "⑦ fingerprints" in r.stdout, "space-show 列出 7 段")

print("\n⑨ GUI: 菜单两项 + 带控制台存总工程 (panel 段 6 开关)")
_acts = [a.text() for a in m.findChildren(type(m.findChild(type(None)) or object))] if False else []
from PyQt5.QtWidgets import QAction as _QA                            # noqa: E402
import studio as ST                                                   # noqa: E402
win = ST.StudioMainWindow()          # 真建主窗口 (菜单在它身上, 不在画布模块上)
app.processEvents()
menu_txt = [a.text() for a in win.findChildren(_QA)]
chk(any("保存总工程" in t for t in menu_txt), "主窗口 文件菜单有「🗂 保存总工程」 (%d 项菜单)" % len(menu_txt))
chk(any("打开总工程" in t for t in menu_txt), "主窗口 文件菜单有「🗂 打开总工程」")
chk(callable(getattr(win, "_save_space_file", None)) and callable(getattr(win, "_open_space_file", None)),
    "两个处理函数已绑上菜单")
SPACE2 = os.path.join(TMP, "zmax_space_gui.proj")
r2 = PF.save_space(SPACE2, sim=m, page=7, note="GUI 存总工程")
p2s = json.load(open(SPACE2, encoding="utf-8"))
chk(len(p2s["panel"]["run_switches"]) == 6 and p2s["panel"].get("view") == "mparam",
    "带控制台保存: panel 6 开关 + 视图 mparam")
chk(bool((p2s.get("master_param") or {}).get("node", {}).get("params")), "总工程含画布 M 节点快照")
chk(p2s["schema"] == PF.SCHEMA and PF.is_space(p2s), "总工程 schema/kind 正确")

# 复原现场真源
open(MANIFOLD, "wb").write(_calib_bytes)
open(CANVAS_J, "wb").write(_canvas_bytes)
chk(open(CANVAS_J, "rb").read() == _canvas_bytes, "画布真源已复原到测试前 (bit 级)")
chk(PF.sha256_file(MANIFOLD) == proj["calibration"]["files"]["config/calib/zmax_manifold.json"]["sha256"],
    "现场真源已复原到存档状态 (bit 级)")

print("\n" + "═" * 64)
print("❌ 失败 %d 项" % len(FAIL) if FAIL else "✅ 全部通过 — 7 段存档 / CLI 全链路 / 漂移可抓 / 默认不覆盖标定")
sys.stdout.flush()
os._exit(1 if FAIL else 0)
