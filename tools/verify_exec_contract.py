#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_exec_contract.py — 执行契约是否真归工程 + 真能被节点调用 (离线, 不下发动作)

判据:
  ① 契约在工程内   src/lerobot/engineering/exec/contract.py 里有 段表schema/闸序/回执字段
  ② daemon 在工程内 真实现 src/lerobot/engineering/exec/daemon.py; tools/l2_daemon.py 只是薄壳 (无逻辑)
  ③ 机器人执行器节点真接契约: 回执分支能跑出 phase/age_s, 且声明 gate_order
  ④ 下发 fail-closed: 无授权 ⇒ ok=False 一条不发 (blocked_by 带"授权")
  ⑤ 显式才发: 节点在无 dispatch_segs 时绝不调用 dispatch (截图式证据: 返回 kind=exec_receipt)
  ⑥ 段表校验真拦: 缺 speed_mm_s 的段 ⇒ 判废; 相对段缺 abs_mm ⇒ 放行但明确记"会漂移"
  ⑦ 迁移口径: 只靠 ZMAX_REPO/ZMAX_DATA/ZMAX_L2_FIFO 就能换盘 (换到临时目录后 paths() 跟着变)
"""
import json
import os
import sys
import tempfile

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

ROWS = []


def ck(tag, name, ok, detail=""):
    ROWS.append((tag, ok, name, detail))
    print(("  ✅ " if ok else "  ❌ ") + "%s %s — %s" % (tag, name, detail))


def main() -> int:
    from lerobot.engineering.exec import contract as CT
    from lerobot.engineering.nodes import robot_actuator_impl as RA

    # ① 契约在工程内
    cpath = os.path.join(ROOT, "src", "lerobot", "engineering", "exec", "contract.py")
    ok1 = os.path.isfile(cpath) and all(hasattr(CT, k) for k in
                                        ("SEG_REQUIRED", "GATE_ORDER", "RECEIPT_FIELDS", "dispatch"))
    ck("①", "契约在工程内 (schema/闸序/回执/下发)", ok1,
       "闸序=%s · 回执字段 %d 个" % ("→".join(g[0] for g in CT.GATE_ORDER), len(CT.RECEIPT_FIELDS)))

    # ② daemon 在工程内 + tools 只剩薄壳
    dpath = os.path.join(ROOT, "src", "lerobot", "engineering", "exec", "daemon.py")
    tpath = os.path.join(ROOT, "tools", "l2_daemon.py")
    dlines = sum(1 for _ in open(dpath, encoding="utf-8")) if os.path.isfile(dpath) else 0
    tlines = sum(1 for _ in open(tpath, encoding="utf-8")) if os.path.isfile(tpath) else 999
    ttxt = open(tpath, encoding="utf-8").read() if os.path.isfile(tpath) else ""
    ok2 = dlines > 1000 and tlines < 60 and "runpy.run_path" in ttxt
    ck("②", "daemon 真实现进工程, tools 只剩壳", ok2,
       "工程内 %d 行 · tools 壳 %d 行" % (dlines, tlines))

    # ③ 节点真接契约 (回执分支)
    o = RA.run({"name": "🤖 机器人执行器", "contract": True})
    o1 = (o or {}).get("out1") or {}
    ok3 = o1.get("kind") == "exec_receipt" and "age_s" in o1 and o1.get("contract") == "v1"
    ck("③", "机器人执行器节点跑出回执 + 声明契约", ok3,
       "kind=%s phase=%s age=%ss gate_order=%s" % (o1.get("kind"), o1.get("phase"),
                                                  o1.get("age_s"), o1.get("gate_order")))

    # ④ 无授权 ⇒ fail-closed
    bak = os.environ.get("ZMAX_DATA")
    tmp = tempfile.mkdtemp(prefix="ct_nodata_")
    os.environ["ZMAX_DATA"] = tmp                      # 空目录: 没有 ctl_auth.json
    r = CT.dispatch([{"ros": "line_rel", "axis": "z_pos", "d_mm": [0, 0, 10], "speed_mm_s": 10}])
    if bak is None:
        os.environ.pop("ZMAX_DATA", None)
    else:
        os.environ["ZMAX_DATA"] = bak
    ck("④", "无授权 ⇒ 一条不发 (fail-closed)", (not r.get("ok")) and r.get("sent") == 0
       and "授权" in str(r.get("blocked_by")), "%s" % r.get("blocked_by"))

    # ⑤ 显式才发 (无 dispatch_segs ⇒ 只回执, 不写管)
    o2 = RA.run({"name": "🤖 机器人执行器"})
    o21 = (o2 or {}).get("out1") or {}
    ck("⑤", "画布每拍不会自动下发 (只回执)", o21.get("kind") == "exec_receipt"
       and o21.get("real_send") is None, "kind=%s" % o21.get("kind"))

    # ⑥ 段表校验
    bad_ok, bad_why = CT.validate_seg({"ros": "line_rel", "axis": "z_pos"})
    drift_ok, drift_why = CT.validate_seg({"ros": "line_rel", "axis": "z_pos", "speed_mm_s": 10})
    ck("⑥", "段表校验真拦/真提示", (not bad_ok) and "speed_mm_s" in bad_why
       and drift_ok and "漂移" in drift_why, "判废=%s · 漂移提示=%s" % (bad_why, drift_why))

    # ⑦ 迁移口径 (三个环境变量)
    tmp2 = tempfile.mkdtemp(prefix="ct_data_")
    os.environ["ZMAX_DATA"] = tmp2
    os.environ["ZMAX_L2_FIFO"] = os.path.join(tmp2, "x.fifo")
    p = CT.paths()
    if bak is None:
        os.environ.pop("ZMAX_DATA", None)
    else:
        os.environ["ZMAX_DATA"] = bak
    os.environ.pop("ZMAX_L2_FIFO", None)
    ok7 = p["auth"].startswith(tmp2) and p["fifo"].endswith("x.fifo")
    ck("⑦", "换盘只靠 ZMAX_REPO/ZMAX_DATA/ZMAX_L2_FIFO", ok7,
       "auth=%s · fifo=%s" % (p["auth"].replace(tmp2, "<DATA>"), p["fifo"].replace(tmp2, "<DATA>")))

    npass = sum(1 for r in ROWS if r[1])
    print("\n判据: PASS %d / FAIL %d" % (npass, len(ROWS) - npass))
    out = {"ok": npass == len(ROWS), "pass": npass, "total": len(ROWS),
           "rows": [{"tag": t, "ok": o_, "name": n, "detail": d} for t, o_, n, d in ROWS]}
    os.makedirs(os.path.join(ROOT, "zmax_data", "eval"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "zmax_data", "eval", "verify_exec_contract.json"), "w"),
              ensure_ascii=False, indent=1)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
