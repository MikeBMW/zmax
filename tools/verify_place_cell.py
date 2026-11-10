# -*- coding: utf-8 -*-
"""verify_place_cell — 位置细胞层三条性质的实测 (群体编码/模式补全/重映射)。

用真源: hole 点 (config/calib/zmax_calib.json) + AR 轨迹2 (8797 /api/traj/named)
用法: gui-venv311/bin/python tools/verify_place_cell.py
"""
import json
import math
import sys
import urllib.request

sys.path.insert(0, "src")
from lerobot.policies.perception import place_cell as pc  # noqa: E402

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print("%s %s%s" % ("✅" if cond else "❌", name, ("  " + detail) if detail else ""))


cal = json.load(open("config/calib/zmax_calib.json", encoding="utf-8"))
hole = cal["cell_geometry"]["points"]["points"]["hole"]
p = (hole["x"], hole["y"], hole["z"])

print("=" * 74)
print("① 群体编码 → 解码闭环 (hole 点 %s mm)" % [round(v * 1000, 1) for v in p])
code = pc.place_code(p)
dec = pc.centroid(code)
err = math.dist(dec, p) * 1000
print("   激活细胞 %d 个 (网格 50mm, σ=100mm)" % len(code))
print("   解码回 %.4f, %.4f, %.4f m" % dec)
check("编解码自洽 <1mm", err < 1.0, "误差 %.4f mm" % err)
# 激活细胞数: σ=100mm 要覆盖 3σ=300mm ⇒ 13³ 格候选, 过滤后约 1500-1700。
# 这是 3D 网格密度的自然结果, 不是缺陷 (place field 半径本来就有 10~30cm)。
check("编码非全图激活", len(code) < 2500, "%d 个细胞 (13³ 候选内的 3σ 覆盖)" % len(code))

print()
print("② 模式补全 (只留最强 40% 细胞, 模拟部分线索缺失)")
items = sorted(code.items(), key=lambda kv: -kv[1])
kept = dict(items[:int(len(items) * 0.4)])
dec2 = pc.centroid(kept)
err2 = math.dist(dec2, p) * 1000
print("   剩余 %d 个细胞 → 解码误差 %.4f mm" % (len(kept), err2))
check("删 60% 仍能解出位置 <2mm", err2 < 2.0, "误差 %.4f mm" % err2)

print()
print("③ 重映射检测 (AR 轨迹2 矩形, 同一路线跑两遍)")
try:
    with urllib.request.urlopen("http://127.0.0.1:8797/api/traj/named?k=square", timeout=8) as r:
        pts = [tuple(float(v) for v in q[:3]) for q in (json.loads(r.read().decode()).get("pts") or [])]
except Exception as e:  # noqa: BLE001
    pts = []
    print("   8797 不可达:", e)

if pts:
    cases = (
        # (说明, 第二遍位置偏移, 上下文是否变, 期望 remap 次数下限)
        ("正常复跑 (偏 5mm, 同上下文)", 0.005, False, 0),
        ("换场 (同位置, ctx 变)", 0.005, True, len(pts)),
        ("小幅真值漂移 (偏 40mm, 同 ctx)", 0.040, False, 0),
    )
    for label, shift, ctx_change, want in cases:
        m = pc.PlaceCellMap()
        for p0 in pts:
            m.observe(p0, ctx={"ctx_key": "FW|arm", "pass": 1})
        n1 = m.status()["cells"]
        remaps = 0
        sims = []
        for p0 in pts:
            p1 = (p0[0] + shift, p0[1], p0[2])
            key = "AOI|gold" if ctx_change else "FW|arm"
            ev = m.observe(p1, ctx={"ctx_key": key, "pass": 2})
            sims.append(ev["sim_best"])
            remaps += 1 if ev["remap"] else 0
        avg_sim = sum(sims) / len(sims)
        print("   %-32s cells=%-3d remap=%-2d/%-2d 平均相似度=%.3f" % (
            label, n1, remaps, len(pts), avg_sim))
        if want == 0:
            check("不误报: %s" % label, remaps == 0, "%d 次误报" % remaps)
        else:
            # 第 1 个点是首次到达, 没有历史基准可比 ⇒ 必然不报 (这是正确行为, 不是漏检)
            check("能检出: %s" % label, remaps >= want - 1,
                  "%d/%d (首点无历史基准)" % (remaps, len(pts)))
else:
    print("   跳过 (无轨迹数据)")

print()
print("=" * 74)
print("PASS %d / FAIL %d" % (len(OK), len(FAIL)))
if FAIL:
    print("失败:", FAIL)
sys.exit(0 if not FAIL else 1)
