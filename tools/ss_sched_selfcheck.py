#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_sched_selfcheck.py — 工艺规划判据: 引擎 sched_impl + 引导节点 n_geoplan (离线, 不动真机)

① 首拍 idle 不推进 (idle ≠ 这一步做完了)
② phase=arrived 推进一步 (step_i 0→1)
③ L2 被拦 ⇒ hold 且不推进 (why 带原因)
④ L2 状态过期 (>ZMAX_SCHED_STALE_S) ⇒ hold 且不推进
⑤ 连续到位 ⇒ 走完本元任务 9 步后切下一个元任务 (mt_i 0→1, mt_done+1)
⑥ 迁移: 只给 ZMAX_META_TASKS/ZMAX_SCHED_STATE 换到临时目录 ⇒ 同一份代码照常推进 (550C 换机不改码)
⑦ 配置找不到 ⇒ 明确 hold 报错, 不伪造进度
⑧ 工艺步骤从**引导节点 n_geoplan** 出得来 (无 obs 也算工艺; 位姿失败不影响工艺)
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = "/home/ubuntu/zmax"
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

ROWS = []


def ck(tag, name, ok, detail=""):
    ROWS.append((tag, ok, name, detail))
    print(("  ✅ " if ok else "  ❌ ") + "%s %s — %s" % (tag, name, detail))


def fresh_state(path):
    if os.path.exists(path):
        os.remove(path)


def run(node, ctx=None):
    return node.run(ctx or {})


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="sched_ck_")
    stp = os.path.join(tmp, "sched_state.json")
    os.environ["ZMAX_SCHED_STATE"] = stp
    os.environ.pop("ZMAX_META_TASKS", None)
    fresh_state(stp)

    from lerobot.engineering.nodes import sched_impl as N   # noqa: E402

    # ① 首拍: 执行层 idle (没活) ⇒ 不许推进
    o = run(N, {"in2": {"phase": "idle", "seg": 0, "n_seg": 0, "residual_mm": 0.0, "age_s": 0.2,
                        "blocked_by": ""}})
    ck("①", "首拍 idle 不推进", o["out3"]["event"] == "hold"
       and o["out1"]["step_i"] == 0 and o["out1"]["mt_id"] == "MT-01",
       "event=%s step_i=%s mt=%s · %s" % (o["out3"]["event"], o["out1"]["step_i"], o["out1"]["mt_id"],
                                          o["out3"]["why"]))

    # ② 到位 ⇒ 推进一步
    o = run(N, {"in2": {"phase": "arrived", "seg": 9, "n_seg": 9, "residual_mm": 0.3, "age_s": 0.1,
                        "blocked_by": ""}})
    ck("②", "arrived 推进一步", o["out3"]["event"] == "advance_step" and o["out1"]["step_i"] == 1,
       "event=%s step_i=%s step=%s" % (o["out3"]["event"], o["out1"]["step_i"], o["out1"]["step"]))

    # ③ 被拦 ⇒ hold 不推进
    before = o["out1"]["step_i"]
    o = run(N, {"in2": {"phase": "moving", "seg": 2, "n_seg": 9, "residual_mm": 40.0, "age_s": 0.2,
                        "blocked_by": "真动授权·8793 未授权"}})
    ck("③", "L2 被拦 ⇒ hold 不推进", o["out3"]["event"] == "hold" and o["out1"]["step_i"] == before
       and "被拦" in o["out3"]["why"],
       "event=%s step_i=%s why=%s" % (o["out3"]["event"], o["out1"]["step_i"], o["out3"]["why"][:60]))

    # ④ 状态过期 ⇒ hold 不推进
    o = run(N, {"in2": {"phase": "arrived", "seg": 9, "n_seg": 9, "residual_mm": 0.0, "age_s": 9.9,
                        "blocked_by": ""}})
    ck("④", "L2 状态过期 ⇒ hold 不推进", o["out3"]["event"] == "hold" and "过期" in o["out3"]["why"],
       "event=%s why=%s" % (o["out3"]["event"], o["out3"]["why"][:60]))

    # ⑤ 连续到位走完 MT-01 的 9 步 ⇒ 切 MT-02
    fresh_state(stp)
    run(N, {"in2": {"phase": "idle", "age_s": 0.1, "blocked_by": ""}})
    mt0 = None
    for _ in range(9):
        o = run(N, {"in2": {"phase": "arrived", "seg": 9, "n_seg": 9, "residual_mm": 0.2,
                            "age_s": 0.1, "blocked_by": ""}})
        mt0 = o
    ck("⑤", "MT-01 九步走完 → 切 MT-02", mt0["out1"]["mt_id"] == "MT-02"
       and mt0["out2"]["mt_done"] == 1,
       "mt=%s mt_done=%s mt_i=%s/%s" % (mt0["out1"]["mt_id"], mt0["out2"]["mt_done"],
                                        mt0["out1"]["mt_i"], mt0["out1"]["mt_n"]))

    # ⑥ 迁移: 配置与状态都换到临时目录, 代码不动
    cfg_src = N._meta_path()
    cfg_tmp = os.path.join(tmp, "ar_meta_tasks.json")
    shutil.copy(cfg_src, cfg_tmp)
    d = json.load(open(cfg_tmp, encoding="utf-8"))
    d["task_id"] = "TASK-MIGRATION-PROBE"
    json.dump(d, open(cfg_tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.environ["ZMAX_META_TASKS"] = cfg_tmp
    os.environ["ZMAX_SCHED_STATE"] = os.path.join(tmp, "sched_state2.json")
    N._CFG["mtime"] = 0.0
    o = run(N, {"in1": {"task_id": "TASK-MIGRATION-PROBE", "reset": True},
                "in2": {"phase": "arrived", "seg": 9, "n_seg": 9, "residual_mm": 0.1,
                        "age_s": 0.1, "blocked_by": ""}})
    ck("⑥", "换配置/状态路径 ⇒ 照常推进 (550C 可迁移)",
       o["out1"]["task_id"] == "TASK-MIGRATION-PROBE" and o["out3"]["event"] == "advance_step"
       and o["out2"]["cfg"] == cfg_tmp,
       "task=%s event=%s cfg=%s" % (o["out1"]["task_id"], o["out3"]["event"], os.path.basename(o["out2"]["cfg"])))

    # ⑦ 配置找不到 ⇒ 明确报错
    os.environ["ZMAX_META_TASKS"] = os.path.join(tmp, "不存在.json")
    N._CFG["mtime"] = 0.0
    N._CFG["path"] = ""
    o = run(N, {"in2": {"phase": "arrived", "age_s": 0.1, "blocked_by": ""}})
    ck("⑦", "配置缺失 ⇒ 明确 hold 报错 (不伪造进度)", o["out1"] is None
       and o["out3"]["event"] == "hold" and ("找不到" in o["out3"]["why"] or "读不到" in o["out3"]["why"]),
       "event=%s why=%s" % (o["out3"]["event"], o["out3"]["why"][:60]))

    # ⑧ 集成: 工艺步骤随「测地线规划引导」一起输出 (没 obs 时位姿 ok=False, 工艺仍要出)
    os.environ.pop("ZMAX_META_TASKS", None)
    os.environ["ZMAX_SCHED_STATE"] = os.path.join(tmp, "sched_state3.json")
    N._CFG["mtime"] = 0.0
    from lerobot.engineering.nodes import geo_plan_impl as GP   # noqa: E402
    g = GP.run({})
    ck("⑧", "引导节点输出工艺步骤 (craft)", isinstance(g.get("craft"), dict)
       and isinstance(g["craft"].get("step"), dict)
       and g["craft"]["step"].get("mt_id") and g.get("ok") is False,
       "craft.mt=%s step=%s | 位姿ok=%s (无 obs 应 False)" % (
           (g.get("craft") or {}).get("step", {}).get("mt_id"),
           (g.get("craft") or {}).get("step", {}).get("step"), g.get("ok")))

    os.environ.pop("ZMAX_META_TASKS", None)
    os.environ.pop("ZMAX_SCHED_STATE", None)

    npass = sum(1 for r in ROWS if r[1])
    print("\n判据: PASS %d / FAIL %d" % (npass, len(ROWS) - npass))
    out = {"ok": npass == len(ROWS), "pass": npass, "total": len(ROWS),
           "rows": [{"tag": t, "ok": o_, "name": n, "detail": d_} for t, o_, n, d_ in ROWS],
           "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    os.makedirs(os.path.join(ROOT, "zmax_data", "eval"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "zmax_data", "eval", "ss_sched_selfcheck.json"), "w"),
              ensure_ascii=False, indent=1)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
