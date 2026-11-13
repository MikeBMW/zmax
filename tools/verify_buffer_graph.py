# -*- coding: utf-8 -*-
"""桌面缓冲区图验收: BufferGraph + MetricTensor + 时间张量 + 100D 投影 + SU(2) 朝向.

跑法: PYTHONPATH=src ./gui-venv311/bin/python tools/verify_buffer_graph.py
"""
import json
import math
import sys

import numpy as np

from lerobot.policies.left_right.state_space.buffer_graph import (
    DONE, PROCESSING, UNPROC, ZONE_FLASH, ZONE_INFEED, ZONE_OUTFEED,
    BufferGraph, BufferNode, build_default_graph, metric_for_zone,
)
from lerobot.policies.left_right.state_space.desktop_buffer_state100 import (
    SLICE100, STATE100_DIM, ALL_FIELDS, DesktopBuffer100,
)
from lerobot.policies.left_right.state_space.su2 import SU2Element

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + ("  | " + detail if detail else ""))


print("=" * 80)
print("① 拓扑与几何锚")
g = build_default_graph()
zones = {}
for n in g.nodes.values():
    zones[n.zone_type] = zones.get(n.zone_type, 0) + 1
check("槽位数 = 17 (8 infeed + 1 flash + 6 outfeed + 1 AOI + 1 scrap)", len(g.nodes) == 17, str(zones))
check("Flash_Port_01 在 flash 区", g.get("Flash_Port_01").zone_type == ZONE_FLASH)
check("infeed 锚 = 段表真值 (0.490,0.499,0.240)",
      np.allclose(g.get("Infeed_Slot_01").t, [0.490, 0.499, 0.240]), str(g.get("Infeed_Slot_01").t))

print("② 各向异性度规 (M·M⁻¹=I · 径向压紧 · 轴向放宽)")
mf = g.get("Flash_Port_01").metric
ratio = mf.radial_ratio()
M, Minv = mf.stiffness_matrix(), mf.step_matrix()
check("M·M⁻¹ = I (max|Δ|=%.2e)" % np.abs(M @ Minv - np.eye(3)).max(),
      np.allclose(M @ Minv, np.eye(3), atol=1e-12))
check("径向步长 = 自由区 ×%.3f" % ratio["radial_step_x"], abs(ratio["radial_step_x"] - 0.09) < 1e-9, str(ratio))
check("轴向步长 = 自由区 ×%.1f" % ratio["axial_step_x"], abs(ratio["axial_step_x"] - 36.0) < 1e-9)
grad_r, grad_z = np.array([1.0, 0, 0]), np.array([0, 0, -1.0])
sr = np.linalg.norm(mf.step(grad_r)) / np.linalg.norm(metric_for_zone(ZONE_INFEED).step(grad_r))
sz = np.linalg.norm(mf.step(grad_z)) / np.linalg.norm(metric_for_zone(ZONE_INFEED).step(grad_z))
check("同一径向梯度: 插入区/自由区 = %.3f (压紧)" % sr, abs(sr - 0.09) < 1e-9)
check("同一轴向梯度: 插入区/自由区 = %.1f (放宽)" % sz, abs(sz - 36.0) < 1e-9)

print("③ SE(3): 位置 ℝ³ + 朝向 SU(2), 不拿群装坐标")
n = g.get("Infeed_Slot_01")
n.t = n.target_t + np.array([0.001, 0.0, 0.0])
n.U = SU2Element.from_rotvec([0.0, 0.0, math.radians(2.0)])
pe = n.pose_error()
check("位置误差 = 1.000mm", abs(pe["d_mm"] - 1.0) < 1e-9, str(pe["d_vec_mm"]))
check("姿态误差 = 2.000° 物理角 (非 S³ 半角)", abs(pe["theta_deg"] - 2.0) < 1e-9, "%.6f°" % pe["theta_deg"])
check("未对位 aligned=False", pe["aligned"] is False)
n.U, n.t = n.target_U, n.target_t.copy()
check("对位后 aligned=True, θ=0, d=0", n.pose_error()["aligned"] and n.pose_error()["theta_deg"] < 1e-12)

print("④ SU(2) 只做朝向/收敛判据")
u10 = SU2Element.from_rotvec([0, 0, math.radians(10)])
check("θ(10° 旋转) = 10.000°", abs(math.degrees(u10.theta()) - 10.0) < 1e-9,
      "%.9f°" % math.degrees(u10.theta()))
check("U·U⁻¹ = I (θ=%.2e)" % (u10 * u10.inv()).theta(), (u10 * u10.inv()).theta() < 1e-12)
check("double-cover 距离对称: d(q,-q)=0", abs(u10.distance_fs(SU2Element(-u10.w, -u10.x, -u10.y, -u10.z))) < 1e-9)
sp = g.scene_pose()
check("全桌面朝向群合成是单位模长", abs(np.hypot(np.hypot(sp.w, sp.x), np.hypot(sp.y, sp.z)) - 1.0) < 1e-9)

print("⑤ 状态机 fail-closed (未注册转移一律抛错)")
g2 = build_default_graph()
for label, fn in (
    ("空槽不许 take", lambda: g2.take("Infeed_Slot_01")),
    ("非在制槽不许结算", lambda: g2.finish("Outfeed_Slot_01")),
    ("空槽不许下料", lambda: g2.clear("Outfeed_Slot_01")),
):
    try:
        fn()
        check(label, False)
    except ValueError as e:
        check(label + " (抛错: %s)" % str(e)[:28], True)
g2.put("Infeed_Slot_01", "item-A")
try:
    g2.put("Infeed_Slot_01", "item-B")
    check("非空槽不许覆盖", False)
except ValueError:
    check("非空槽不许覆盖 (抛错)", True)
check("put 后态 = OCCUPIED_UNPROCESSED", g2.get("Infeed_Slot_01").slot_state == UNPROC)
g2.take("Infeed_Slot_01")
check("take 后态 = PROCESSING", g2.get("Infeed_Slot_01").slot_state == PROCESSING)
try:
    g2.finish("Infeed_Slot_01", ok=True)
except ValueError:
    check("PROCESSING 可以结算 (不该抛错)", False)
check("finish 后态 = OCCUPIED_PROCESSED", g2.get("Infeed_Slot_01").slot_state == DONE)
try:
    g2.finish("Infeed_Slot_01", ok=True)
    check("重复结算被拒", False)
except ValueError:
    check("重复结算被拒 (抛错)", True)

print("⑥ 时间张量 + 异步双工 (插完立刻有下一条, 不许 WAIT)")
T0 = 1000.0
g3 = build_default_graph()
g3.put("Infeed_Slot_01", "p1", now=T0)
g3.put("Infeed_Slot_02", "p2", now=T0 + 1.0)
age = g3.get("Infeed_Slot_01").age(now=T0 + 2.5)
check("入队停留时间 = 2.500s", abs(age - 2.5) < 1e-9, "%.6f" % age)
w = g3.wait_times(now=T0 + 2.5)
check("平均等待 = (2.5+1.5)/2 = 2.000s", abs(w["mean_wait_s"] - 2.0) < 1e-9, str(w["per_slot_s"]))
i1 = g3.intents(now=T0 + 2.5)
check("首条意图 = LOAD, FIFO 取 Slot_01", i1["intent"] == "LOAD" and i1["source"] == "Infeed_Slot_01", str(i1["intent"]))
g3.take("Infeed_Slot_01", now=T0 + 3.0)
i_running = g3.intents(now=T0 + 4.0)
check("设备在刷时不许 WAIT: %s" % i_running["intent"], i_running["intent"] in ("PREP_NEXT", "LOAD", "THROTTLE"),
      str(i_running["intent"]))   # 还有 p2 可预取
g3.finish("Infeed_Slot_01", ok=True, now=T0 + 9.0)         # 刷写 6s
i2 = g3.intents(now=T0 + 9.01)
check("插完(DONE) 立刻给 UNLOAD", i2["intent"] == "UNLOAD", str(i2["intent"]))
check("UNLOAD 目标落在 outfeed 空槽", str(i2.get("target", "")).startswith("Outfeed_Slot_"), str(i2.get("target")))
g3.put("Outfeed_Slot_01", "p1", now=T0 + 10.0, state=DONE)
g3.clear("Outfeed_Slot_01", now=T0 + 10.0)
check("下料后 outfeed 计数回 0", g3.aggregate(now=T0 + 11)["outfeed_count"] == 0.0)
# 刷写失败 → 回 UNPROC (重试优先, 不排尾)
g3.put("Infeed_Slot_03", "p3", now=T0 + 11.0)
g3.take("Infeed_Slot_03", now=T0 + 12.0)
g3.finish("Infeed_Slot_03", ok=False, now=T0 + 18.0)
g3.get("Infeed_Slot_03").t_out = T0 + 18.0     # 标记"来自重试"
i3 = g3.intents(now=T0 + 18.1)
check("刷写失败件走 RETRY_FLASH 插队", i3["intent"] == "RETRY_FLASH", str(i3["intent"]))
check("重试件仍占 UNPROC 态", g3.get("Infeed_Slot_03").slot_state == UNPROC)

print("⑦ 队列入队/出队计数 = 100D 口径 (L=λW 自洽性)")
g4 = BufferGraph()
n_a = BufferNode("A", "tray", ZONE_INFEED, np.zeros(3), target_t=np.zeros(3))
n_b = BufferNode("B", "tray", ZONE_INFEED, np.zeros(3), target_t=np.zeros(3))
g4.add(n_a); g4.add(n_b)
for i in range(6):                      # 6 件, 每 2s 完成一件
    n_a.slot_state = UNPROC            # 借用同一槽做原型
    n_a.t_in = T0 + 10.0               # 在制 2s 后计数 (L=1, λ=0.5 ⇒ λW=1.0)
    g4.done_ts.append(T0 + i * 2.0)
ct = g4.cycle_time()
check("cycle_time = 2.000s (相邻完成差中位)", abs(ct - 2.0) < 1e-9, "%.6f" % ct)
check("uph = 1800 pph (窗口 60s 内 6 件 ⇒ 360)", abs(g4.uph(window_s=60.0, now=T0 + 12.0) - 360.0) < 1e-6,
      "%.1f" % g4.uph(window_s=60.0, now=T0 + 12.0))
ql = g4.queue_law(now=T0 + 12.0)
check("队列律 L=λW: L=%s λ=%s W=%s dev=%.3f" % (ql["L"], ql["lambda_per_s"], ql["W_s"], ql["dev"]),
      ql["ok"], json.dumps(ql, ensure_ascii=False))

print("⑧ 聚合 → 100D 投影 (前 55 位零回归)")
g5 = build_default_graph()
T1 = 2000.0
for i in range(4):
    g5.put("Infeed_Slot_%02d" % (i + 1), "i%d" % i, now=T1 + i)
g5.take("Infeed_Slot_01", now=T1 + 5); g5.finish("Infeed_Slot_01", ok=True, now=T1 + 11)
g5.put("Outfeed_Slot_01", "i0", now=T1 + 12)
agg = g5.aggregate(now=T1 + 13)
base55 = np.arange(55, dtype=np.float64) / 100.0
db = DesktopBuffer100()
x = db.fuse(obs55=base55, buf=agg, N=8, M=6, uph_target=900.0)
check("输出维度 = 100", x.size == STATE100_DIM)
check("前 55 位逐位不变 (零回归)", np.array_equal(x[:55], base55))
for name in ("infeed_count", "outfeed_count", "n_unproc", "n_inflight", "n_done", "scrap_ratio"):
    s = SLICE100[name]
    check("%s 写进 %d:%d = %s" % (name, s.start, s.stop, x[s][0]),
          abs(float(x[s][0]) - float(agg[name])) < 1e-12)
check("infeed_fill 派生 = 4/8 = 0.5", abs(float(db.get("infeed_fill")[0]) - 0.5) < 1e-12,
      "%.4f" % float(db.get("infeed_fill")[0]))
check("named 重组成 x 逐位相同",
      np.array_equal(np.concatenate([db.named[f.name] for f in ALL_FIELDS]), x))

print("⑨ 度规安全闸: 插入区不许放宽")
r1 = g5.relax_metric("Flash_Port_01", 1.2)
check("Flash 区放宽被拒 (fail-closed)", r1["ok"] is False, r1["why"])
r2 = g5.relax_metric("Infeed_Slot_02", 1.2)
check("Infeed 区放宽 1.2× 通过", r2["ok"] is True and abs(r2["sigma_radial"] - 1.2e-3) < 1e-12, str(r2))
r3 = g5.relax_metric("Infeed_Slot_03", 3.0)
check("放宽倍数 >2 被拒", r3["ok"] is False, r3["why"])

print("⑩ DDS 载荷往返 (通用 SSNodePort.json, 不新建 IDL)")
pay = g5.to_payload(now=T1 + 14)
js = json.dumps(pay, ensure_ascii=False, default=str)
g6 = BufferGraph.from_payload(json.loads(js))
check("节点数往返一致", len(g6.nodes) == len(g5.nodes), "%d -> %d" % (len(g5.nodes), len(g6.nodes)))
check("槽位坐标往返逐位相同",
      all(np.allclose(g6.get(k).t, g5.get(k).t) for k in g5.nodes))
check("槽位态往返一致",
      all(g6.get(k).slot_state == g5.get(k).slot_state for k in g5.nodes))
check("载荷含 intent/wait/queue_law 三块",
      all(k in pay for k in ("intent", "wait", "queue_law")), str(sorted(pay.keys())))
check("JSON 体积 < 64KB (可 10Hz 广播)", len(js.encode("utf-8")) < 65536, "%d B" % len(js.encode("utf-8")))

print("=" * 80)
print("PASS %d / FAIL %d" % (len(OK), len(FAIL)))
if FAIL:
    for f in FAIL:
        print("  ✗ " + f)
sys.exit(0 if not FAIL else 1)
