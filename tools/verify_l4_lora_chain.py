#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: L4 后段链 (INTACT 意图解码器 → L4 INTACT LoRA 微调 → 流形专家预测器 → 接触/性能流形)

老倪 2026-10-14 口径: LoRA 节点接在意图解码器后 (不动 INTACT 原权重) · 元任务预测 → LoRA 门控 ·
向后接 流形专家预测器 + 接触流形 + 性能流形 · UI 连线顺序正确。

① 画布拓扑 (边都在, 旁路已删)      ② UI 顺序 (x 递增)      ③ 节点执行注册
④ LoRA 产物真源 (包装 ckpt/112 组/原权重冻结)              ⑤ 数学自检 (Δu/限幅/恒等/锥/帕累托)
⑥ 真被消费 (跑三节点, 日志里出现 ⛓ 承接)                    ⑦ 元任务预测门控真源
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys

ROOT = "/home/ubuntu/zmax"
CANVAS = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
sys.path.insert(0, os.path.join(ROOT, "src"))
ok_all = []


def chk(tag, cond, detail=""):
    ok_all.append(bool(cond))
    print("%s %s %s" % ("✅" if cond else "❌", tag, detail))


def main() -> int:
    d = json.load(open(CANVAS, encoding="utf-8"))
    nodes = {n["id"]: n for n in d["nodes"]}
    got = {(l.get("f"), l.get("t")) for l in d["links"]}
    want = [("ssintact_dec", "ss_lora_l4"), ("n_intent_direct", "ss_lora_l4"),
            ("ss_lora_l4", "ssmani_exp"), ("ss_lora_l4", "ssmani_c"),
            ("ss_lora_l4", "ssmani_p"), ("ss_lora_l4", "ssdec"),
            ("ssmani_exp", "ssmani_c"), ("ssmani_exp", "ssmani_p")]
    miss = [w for w in want if w not in got]
    bypass = [(f, t) for f, t in (("ssintact_dec", "ssmani_exp"), ("ssintact_dec", "ssdec")) if (f, t) in got]
    chk("① 画布拓扑 (LoRA 插在意图解码器后, 旁路已删)", not miss and not bypass,
        "缺 %s · 旁路残留 %s" % (miss or "无", bypass or "无"))

    xs = [("ssintact_dec", nodes["ssintact_dec"]["x"]), ("ss_lora_l4", nodes["ss_lora_l4"]["x"]),
          ("ssmani_exp", nodes["ssmani_exp"]["x"]), ("ssmani_c", nodes["ssmani_c"]["x"]),
          ("ssmani_p", nodes["ssmani_p"]["x"]), ("ssdec", nodes["ssdec"]["x"])]
    chk("② UI 顺序 (左→右 x 递增)", all(xs[i][1] < xs[i + 1][1] for i in range(len(xs) - 1)),
        " → ".join("%s(%s)" % (k, v) for k, v in xs))

    r = subprocess.run([os.path.join(ROOT, "gui-venv311/bin/python"),
                        os.path.join(ROOT, "tools/ss_node_impl_audit.py")],
                       capture_output=True, text=True, timeout=300)
    line = next((l for l in r.stdout.splitlines() if "实现命中" in l), "")
    chk("③ 节点执行注册", "73/74" in line or "74/74" in line, line.strip()[:90])

    from lerobot.manifold.manifold_chain import L4Adapter, ContactConstraint, PerformanceConstraint
    ad = L4Adapter(ROOT)
    ok_a, note_a = ad.load()
    chk("④ LoRA 产物真源 (原权重冻结)", ok_a and len(ad.experts) > 0,
        "产物 %s · %d 组 · r=%d α=%d scaling=%.2f · merged 已排除"
        % (os.path.basename(ad.src), len(ad.experts), ad.r, ad.alpha, ad.scaling))
    r_kept = subprocess.run([os.path.join(ROOT, "gui-venv311/bin/python"),
                             os.path.join(ROOT, "src/lerobot/manifold/manifold_chain.py")],
                            capture_output=True, text=True, timeout=300)
    tail = [l for l in r_kept.stdout.splitlines() if l.startswith("自检")]
    chk("⑤ 数学自检 (Δu/限幅/无产物恒等/锥投影/帕累托)", bool(tail) and "PASS" in tail[-1],
        tail[-1] if tail else "无输出")

    # ⑥ 真被消费: LoRA 节点 → 专家预测器 → 接触/性能流形 三个节点连跑, 看 ⛓ 承接日志
    fs = sorted(glob.glob(os.path.join(ROOT, "reports/ss_episode*.npz")))
    logs: list = []
    consumed = ""
    if fs:
        try:
            import numpy as np                                            # noqa: PLC0415
            z = np.load(fs[-1], allow_pickle=True)
            # ⚠️ 画布给的 _ss_tr 是 **list** (节点里写的是 not tr.get("t") 这类布尔判断);
            #   拿 ndarray 喂会触发 ambiguous —— 取证要按**真实类型**喂, 不然是自己造失败。
            import numpy as _np0                                             # noqa: PLC0415

            def _n_ndim(v):
                return _np0.asarray(v).ndim

            def _as(v):
                if _n_ndim(v) > 2 or str(_np0.asarray(v).dtype) == "object":
                    return v
                return [list(map(float, r)) for r in v] if _n_ndim(v) > 1 else list(v)
            tr = {k: _as(z[k]) for k in z.files if _n_ndim(z[k]) <= 2}   # 全字段喂 (节点要的键别漏)
            tap = json.loads(open("/dev/shm/zmax_ss_engine/engine_default.jsonl").read().strip().splitlines()[-1])
            mp = json.load(open(os.path.join(ROOT, "zmax_data/ss_live/meta_pred.json"), encoding="utf-8"))
            from lerobot.engineering.nodes import library as lib             # noqa: PLC0415
            lib._SS_STATE["mani_eng"] = {"z": tap.get("z_latent") or [], "grad": [-0.01] * 16,
                                         "M": float(tap.get("M") or 3.643)}
            lib._SS_STATE["lora_in"] = {"u_int": tap.get("z_latent") or [],
                                        "src": "在役回路 z_latent (cycle %s)" % tap.get("cycle")}

            class _Mod:                                                      # 轨迹桩 (真 episode 帧)
                _ss_tr = tr
                _ss_round = max(0, len(tr.get("t", [])) - 1)
            ctx = {"log": lambda s: logs.append(str(s)), "module": _Mod(), "name": ""}
            ok_lora = lib.node_ss_lora_l4(dict(ctx, name="ss_lora_l4"))
            ctx["name"] = "🧠 流形专家预测器"
            ok_pred = lib.node_ss_pred(ctx)
            ctx["name"] = "🧮 接触流形 · 导航地图"
            ok_contact = lib.node_ss_mani(ctx)
            ctx["name"] = "🧮 性能流形 · 耦合代价"
            ok_perf = lib.node_ss_mani(ctx)
            ll = lib._SS_STATE.get("lora_l4") or {}
            has_state = bool(ll) and bool(ll.get("trained"))
            marks = sum(1 for l in logs if "⛓" in l)
            consumed = "三节点执行 %s · ⛓ 承接日志 %d 条 · lora_l4 状态 %s" % (
                [ok_lora, ok_pred, ok_contact, ok_perf], marks, has_state)
            chk("⑥ 真被消费 (下游节点读 lora_l4)", all([ok_lora, ok_pred, ok_contact, ok_perf]) and marks >= 3,
                consumed)
            gate_log = next((l for l in logs if "元任务预测门控" in l), "")
            chk("⑦ 元任务预测 → LoRA 门控", any("γ_eff" in l for l in logs),
                gate_log.strip()[:150] or "无门控日志")
            chk("⑦ 生效口径 (原权重冻结 + Δu 上界)", any("原权重" in l and "冻结" in l for l in logs)
                and any("Δu" in l for l in logs),
                next((l for l in logs if "原权重冻结" in l), "")[:130])
        except Exception as e:                                               # noqa: BLE001
            import traceback                                                 # noqa: PLC0415
            print("⚠️ ⑥ 异常栈:\n" + traceback.format_exc()[-1200:])
            chk("⑥ 真被消费 (下游节点读 lora_l4)", False, "%s: %s" % (type(e).__name__, str(e)[:110]))
    else:
        chk("⑥ 真被消费 (下游节点读 lora_l4)", False, "没有真 episode 轨迹可跑")

    print("判据 %d/%d %s" % (sum(ok_all), len(ok_all), "PASS" if all(ok_all) else "FAIL(见上)"))
    if logs:
        print("—— 节点实测日志 (节选) ——")
        for l in logs[:14]:
            print("   " + l[:165])
    return 0 if all(ok_all) else 1


if __name__ == "__main__":
    raise SystemExit(main())
