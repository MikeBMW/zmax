#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 🧩 SAM3 掩膜 3D 必须**真进**「📡 融合定位建图」(而不是只算不用 = 老倪 2026-10-14 说的"悬着")。

背景 (实测): 🧩 开放词汇分割节点把掩膜 3D 写进 `_YOLO_CACHE['mask3d']` (base 系中心/足印/yaw),
但全仓**唯一的消费者是取证脚本本身** —— 融合定位建图节点不读它 ⇒ 掩膜算完就躺在缓存里。
本次接通口径 (零回退 + 不擅进默认档):
  ① 掩膜可用(同帧≤3s) ⇒ 作独立观测入 `_SS_STATE['seg_mask3d']` + 与框法**交叉校验**(偏差入状态);
  ② 要改写 39D 数值必须显式开闸 `ZMAX_FUSION_SEG=1`;
  ③ 无掩膜/掩膜过期 ⇒ 一个字段都不动, 日志如实写"本帧无"。

走**文档化执行入口** `engineering.runtime.execute_node_logic` (不是直接调函数), 4 组断言。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/zmax/src")
sys.path.insert(0, "/home/ubuntu/zmax")

NODE_NAME = "📡 融合定位建图"
res = []


class _Stub:
    def __init__(self):
        self.lines = []

    def _log(self, m):
        self.lines.append(str(m))


def _run():
    from lerobot.engineering import runtime
    from lerobot.engineering.nodes import library as L
    mod = _Stub()
    ok = runtime.execute_node_logic(mod, {"name": NODE_NAME, "params": {}})
    return ok, mod.lines, L


def _mk_mask(L, age_s=0.0, x=-0.12, y=0.34, z_mm=401.0):
    L._YOLO_CACHE["mask3d"] = {"光模块": {"center_base": [x, y, 0.401], "z_mm": z_mm,
                                       "xy_size_mm": [12.5, 8.0], "yaw_deg": 3.0,
                                       "area_px": 1500, "score": 0.93, "iou_yolo": 0.88,
                                       "src": "real:arm", "at": time.time()}}
    L._YOLO_CACHE["seg_masks"] = {"instances": [], "at": time.time() - age_s,
                                  "n_yolo_boxes": 1, "n_selected": 1, "src": "real:arm"}


def main():
    ok, lines, L = _run()
    assert ok, "节点未执行成功 (前置: 引擎/obs 依赖)"
    hit = [l for l in lines if "SAM3 掩膜 3D 观测" in l]
    res.append(("① 无掩膜 ⇒ 如实报『本帧无』且不改 39D", bool(hit) and "本帧无" in hit[0]))
    res.append(("①b 无掩膜 ⇒ 状态里没有 seg_mask3d", "seg_mask3d" not in L._SS_STATE))

    _mk_mask(L)
    os.environ.pop("ZMAX_FUSION_SEG", None)
    ok, lines, L = _run()
    hit = [l for l in lines if "SAM3 掩膜 3D 观测[" in l]
    res.append(("② 新鲜掩膜 ⇒ 日志出现掩膜 3D 观测行", ok and bool(hit)))
    seg = L._SS_STATE.get("seg_mask3d") or {}
    res.append(("②b 掩膜 3D 入 state (含足印 base 中心)", bool(seg) and "光模块" in seg))
    dev = L._SS_STATE.get("seg_mask3d_dev_mm")
    res.append(("②c 与框法交叉校验算出偏差 mm", isinstance(dev, (int, float)) and dev >= 0))
    res.append(("②d 默认档不改 39D 数值 (未证明提升不进默认档)", "seg_mask3d_used" not in L._SS_STATE))

    _mk_mask(L, age_s=9.0)
    ok, lines, L = _run()
    hit = [l for l in lines if "SAM3 掩膜 3D 观测" in l]
    res.append(("③ 掩膜过期(9s>3s) ⇒ 视为无, 不拿旧掩膜套新帧",
                bool(hit) and "本帧无" in hit[0] and not (L._SS_STATE.get("seg_mask3d"))))

    _mk_mask(L, x=-0.116, y=0.338, z_mm=407.0)
    os.environ["ZMAX_FUSION_SEG"] = "1"
    ok, lines, L = _run()
    used = L._SS_STATE.get("seg_mask3d_used")
    o39 = L._SS_STATE.get("obs39")
    filled = False
    try:
        filled = abs(float(o39[4]) - (-0.116)) < 1e-6 and abs(float(o39[5]) - 0.338) < 1e-6
    except Exception:                                                       # noqa: BLE001
        filled = False
    res.append(("④ ZMAX_FUSION_SEG=1 ⇒ 掩膜 3D 真填进 39D[4:6]", bool(used) and filled))
    os.environ.pop("ZMAX_FUSION_SEG", None)

    # ── L5 输入选项: 画布上 ss_seg → n_dsvl, 且 DeepSeek-VL 的上下文里真带上分割结果 ──
    import json as _json
    cv = _json.load(open("/home/ubuntu/zmax/flows/state_space_obs.json", encoding="utf-8"))
    nsd = {n["id"]: n for n in cv["nodes"]}
    lk = [l for l in cv["links"] if l.get("f") == "ss_seg" and l.get("t") == "n_dsvl"]
    fwd = bool(lk) and (int(nsd["ss_seg"]["x"]) + int(nsd["ss_seg"]["w"])) <= int(nsd["n_dsvl"]["x"])
    res.append(("⑤ 画布: 🧩SAM3 掩膜 → 🧿DeepSeek-VL 输入口 (前向线)", fwd and lk[0].get("t_port") == "in4"))

    from lerobot.engineering.nodes import library as L2
    ctx_ok = False
    try:
        _mk_mask(L2, x=-0.1, y=0.2)
        L2._YOLO_CACHE["seg_masks"]["instances"] = [{"label": "光模块", "area_px": 1200, "iou_yolo": 0.9}]
        c = L2._vlm_ctx({"name": "🧿 DeepSeek-V4-Flash", "params": {}})
        ctx_ok = bool((c.get("seg") or {}).get("n_instances") == 1
                      and (c.get("seg") or {}).get("labels") == ["光模块"]
                      and (c.get("seg") or {}).get("mask3d_base"))
    except Exception:                                                       # noqa: BLE001
        ctx_ok = False
    res.append(("⑥ DeepSeek-VL 上下文真带分割结果 (含掩膜 3D)", ctx_ok))

    try:
        L2._YOLO_CACHE.pop("mask3d", None)
        L2._YOLO_CACHE.pop("seg_masks", None)
        c2 = L2._vlm_ctx({"name": "🧿 DeepSeek-V4-Flash", "params": {}})
        res.append(("⑦ 无分割结果 ⇒ 上下文不加这一路 (零回退)", "seg" not in c2))
    except Exception:                                                       # noqa: BLE001
        res.append(("⑦ 无分割结果 ⇒ 上下文不加这一路 (零回退)", False))

    print("判据: 🧩 SAM3 掩膜 3D → 融合定位建图 真接通")
    for nm, good in res:
        print("  %s %s" % ("✓" if good else "✗", nm))
    print("判据汇总: %d/%d %s" % (sum(1 for _, g in res if g), len(res),
                                 "PASS" if all(g for _, g in res) else "FAIL"))
    return 0 if all(g for _, g in res) else 1


if __name__ == "__main__":
    sys.exit(main())
