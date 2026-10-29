#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""流形引擎有效性 A/B 对照：同 probe、同输入、只切 ZMAX_MANI_ENG_OFF。

用法: python tools/mani_ab_compare.py /tmp/mani_open.json /tmp/mani_closed.json

快照结构: {"groups": {"<层>": {"elapsed_s":…, "nodes": [{"id","status","ms","ports"}]}}}

判据（只看数值差，不看日志措辞）:
  ① ss_mani_eng 状态 实现执行 → 直通        = 开关生效
  ② ssmani_c 输出是否变化                   = 流形输出有无传到接触流形
  ③ ssdec nominal_L3 / l4_cond_injected     = 有无一路传到动作
任一环数值相同 ⇒ 该环断路，不能宣称「有效」。
"""
import json
import sys


def flat_nodes(d):
    out = {}
    for _g, gv in (d.get("groups") or {}).items():
        for n in (gv.get("nodes") or []):
            nid = n.get("id")
            if nid:
                out[nid] = n
    return out


def portval(node, port="out1"):
    p = (node or {}).get("ports") or {}
    return p.get(port)


def walk_nums(o, prefix=""):
    """把端口值摊成 路径->标量，用于逐项比对。"""
    r = {}
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, (int, float)):
                r[prefix + k] = float(v)
            elif isinstance(v, (dict, list)):
                r.update(walk_nums(v, prefix + k + "."))
    elif isinstance(o, list):
        for i, v in enumerate(o[:12]):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                r[f"{prefix}[{i}]"] = float(v)
    return r


def main():
    op = json.load(open(sys.argv[1], encoding="utf-8"))
    cl = json.load(open(sys.argv[2], encoding="utf-8"))
    no, nc = flat_nodes(op), flat_nodes(cl)

    print("=" * 66)
    print("流形引擎 A/B 对照（同 probe 同输入，只切 ZMAX_MANI_ENG_OFF）")
    print("=" * 66)
    print(f"open={sys.argv[1]} ({op.get('t_str')}) 节点 {len(no)}")
    print(f"closed={sys.argv[2]} ({cl.get('t_str')}) 节点 {len(nc)}")

    print("\n① 开关生效性（本节点）")
    a, b = no.get("ss_mani_eng") or {}, nc.get("ss_mani_eng") or {}
    print(f"  open  : status={a.get('status')}  ms={a.get('ms')}")
    print(f"  closed: status={b.get('status')}  ms={b.get('ms')}")
    ok_switch = (a.get("status") != b.get("status")) or (a.get("ms") != b.get("ms"))
    print(f"  → 开关{'生效' if ok_switch else '未生效(!!)'}")

    print("\n② 流形输出本身（几何量）")
    for k in ("min_eig", "det_g", "kappa", "tau", "H", "geodesic_dev", "dim"):
        va, vb = (portval(a) or {}).get(k), (portval(b) or {}).get(k)
        if va is not None or vb is not None:
            print(f"  {k}: open={va} | closed={vb}")

    print("\n③ 直接下游 ssmani_c（接触流形 out1 → ssdec）")
    na, nb = walk_nums(portval(no.get("ssmani_c"))), walk_nums(portval(nc.get("ssmani_c")))
    keys = sorted(set(na) | set(nb))
    diffs = [(k, na.get(k), nb.get(k)) for k in keys
             if na.get(k) is not None and nb.get(k) is not None
             and abs(na[k] - nb[k]) > 1e-9]
    print(f"  可比数值 {len(keys)} 项 · 有差异 {len(diffs)} 项")
    for k, x, y in diffs[:10]:
        print(f"    {k}: open={x:.6g} closed={y:.6g} Δ={x - y:+.6g}")
    if keys and not diffs:
        print("    （逐项相同 ⇒ 流形开关对接触流形输出零影响）")

    print("\n④ 动作侧 ssdec")
    da, db = no.get("ssdec") or {}, nc.get("ssdec") or {}
    pa, pb = portval(da) or {}, portval(db) or {}
    for k in ("nominal_L3", "l4_cond_injected", "degraded", "nominal_src"):
        if k in pa or k in pb:
            same = pa.get(k) == pb.get(k)
            print(f"  {k}: open={pa.get(k)} | closed={pb.get(k)} → {'相同' if same else '不同'}")
    print(f"  ms: open={da.get('ms')} closed={db.get('ms')}")

    print("\n⑤ 执行侧 sslimit / ssact")
    for nid in ("sslimit", "ssact"):
        pa, pb = portval(no.get(nid)) or {}, portval(nc.get(nid)) or {}
        print(f"  {nid}: open u={pa.get('u_sat') or pa.get('action')} | "
              f"closed u={pb.get('u_sat') or pb.get('action')}")

    print("\n" + "=" * 66)
    if diffs or pa.get("nominal_L3") != pb.get("nominal_L3"):
        print("判读：下游有数值差 ⇒ 流形输出确实进了链路，可量化收益")
    else:
        print("判读：下游零差异 ⇒ 流形输出没有因果通到动作（计算有效 ≠ 因果有效）")
        print("      修法不是调参，是把 l4_cond 通道训进 L3 动作头")
    print("=" * 66)


if __name__ == "__main__":
    main()
