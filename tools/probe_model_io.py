"""抓全链每层节点的实际 I/O —— 用于整理 L2→L3→L4→L5→action 传递表.

只读: 不带真机下发 (ssact/n_exec 走 PURE 校验, 真机授权仍只在 8793)。
输出 zmax_data/ss_live/model_io_snapshot.json
"""
import sys, json, os, time
sys.path.insert(0, 'src')
from lerobot.middleware import load_project

GROUPS = [
    ("L2_perception", ["ssyolo", "ss2d3d", "ssaoi", "sssensor", "ssvlm"]),
    ("L2_plan",       ["ssplan", "sslat", "ssllm"]),
    ("L2_exec",       ["sslimit", "ssact", "n_exec", "ssff"]),
    ("L3",            ["ssdec"]),
    ("L4",            ["ss_mani_eng", "ssmani_c", "ssmani_p", "n_calib_mani", "ssintact", "ssintact_dec"]),
    ("L5",            ["n_vlm_llm", "n_dsvl", "ss_l5"]),
]

def trim(v, depth=0):
    """把输出裁成可读摘要: 数组保留前6个 + 长度, 字典保留一层。"""
    if isinstance(v, (list, tuple)):
        if len(v) > 8:
            return {"_len": len(v), "_head": [trim(x, depth+1) for x in v[:6]]}
        return [trim(x, depth+1) for x in v]
    if isinstance(v, dict):
        if depth >= 2:
            return {"_keys": list(v.keys())[:10]}
        return {k: trim(x, depth+1) for k, x in list(v.items())[:24]}
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, str) and len(v) > 160:
        return v[:160] + "…"
    return v

prj = load_project()
out = {"ts": time.time(), "t_str": time.strftime("%F %T"), "groups": {}}

for gname, ids in GROUPS:
    recs = []
    t0 = time.time()
    try:
        tr = prj.step(only=ids)
    except Exception as e:
        out["groups"][gname] = {"err": "%s: %s" % (type(e).__name__, e)}
        continue
    for t in tr:
        o = t.get("out") or {}
        recs.append({
            "id": t["id"],
            "status": t.get("status"),
            "ms": round(float(t.get("ms") or 0), 1),
            "ports": {k: trim(v) for k, v in o.items()},
        })
    out["groups"][gname] = {"elapsed_s": round(time.time() - t0, 2), "nodes": recs}
    print("%-14s %d 节点 %.1fs" % (gname, len(recs), time.time() - t0), flush=True)

p = "zmax_data/ss_live/model_io_snapshot.json"
os.makedirs(os.path.dirname(p), exist_ok=True)
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已写", p, os.path.getsize(p), "bytes")
