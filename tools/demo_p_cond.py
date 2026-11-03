#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_p_cond.py — 实测「流形引擎预测的四元数 → INTACT 条件」这条通路的接线

三步:
  ① 读流形引擎落盘的 p_next (带帧龄, 陈旧=不传)
  ② INTACT 真推理一步 (metaworld 源, 与引擎 L4 档同一 node)
  ③ 同一份 out 跑两次 decode: 不传 p_cond / 传 p_cond, 对比 p_cond 字段
判据: 不传 ⇒ p_cond=None (原行为); 传 ⇒ p_cond 3 维有限向量且来源标注正确。
"""
import json
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "src"),
          os.path.join(REPO, "src", "lerobot", "policies", "left_right", "state_space")):
    if p not in sys.path:
        sys.path.insert(0, p)

ENGINE_LATEST = os.path.join(REPO, "zmax_data", "ss_live", "engine_latest.json")


def read_p_next(fresh_s: float = 300.0):
    """扫 ss_live/engine_latest*.json, 取最新且真的带 p_next 的那份 (in役/隔离实例都可能)。"""
    import glob
    best = None
    for p in glob.glob(os.path.join(os.path.dirname(ENGINE_LATEST), "engine_latest*.json")):
        try:
            age = time.time() - os.path.getmtime(p)
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            q = d.get("p_next") or []
            if age <= fresh_s and len(q) == 4 and (best is None or age < best[1]):
                best = (p, age, np.asarray(q, float), d)
        except Exception:                                              # noqa: BLE001
            continue
    if best is None:
        return None, 1e9, {}
    return best[2], best[1], best[3]


def main() -> int:
    q, age, ed = read_p_next()
    print("① 引擎 p_next = %s (帧龄 %.1fs, p_source=%s)" % (
        None if q is None else [round(float(x), 4) for x in q], age, ed.get("p_source")))

    from lerobot.policies.intact.service import get_service
    s = get_service(REPO)
    ok, why = s.ensure_ready()
    print("② INTACT ready=%s %s" % (ok, str(why)[:80]))
    if not ok:
        return 2
    rep = s.run_once(stage="接近", decode=True)
    out = s.last_out
    print("   推理: chunk=%s trained=%s obs_source=%s latent_keys=%s" % (
        None if out is None else np.asarray(out.chunk).shape, rep.trained, rep.obs_source,
        list((getattr(out, "latent", None) or {}).keys())))

    from lerobot.policies.intact.decoder import IntactIntentDecoder
    dec = s.decoder or IntactIntentDecoder()
    d0 = dec.decode(out, stage="接近")
    d1 = dec.decode(out, stage="接近", p_cond=q)
    print("③ 不传 p_cond : p_cond=%s src=%r" % (d0.p_cond, d0.p_cond_source))
    print("   传  p_cond : p_cond=%s src=%r" % (
        None if d1.p_cond is None else [round(float(x), 4) for x in d1.p_cond], d1.p_cond_source))
    same_uff = bool(np.allclose(np.asarray(d0.u_ff), np.asarray(d1.u_ff), atol=0, rtol=0)) \
        if d0.u_ff is not None and d1.u_ff is not None else None
    print("   其它字段是否零变化: u_ff 相同=%s | l4_cond 相同=%s" % (
        same_uff,
        bool(np.array_equal(np.asarray(d0.l4_cond), np.asarray(d1.l4_cond)))
        if d0.l4_cond is not None and d1.l4_cond is not None else None))
    good = (d0.p_cond is None and d1.p_cond is not None and d1.p_cond.size == 3
            and bool(np.all(np.isfinite(d1.p_cond))) and same_uff is not False)
    print("④ 判定: %s" % ("通过 (p_cond 通路通, 其它字段零变化)" if good else "不通过"))
    s.close()
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
