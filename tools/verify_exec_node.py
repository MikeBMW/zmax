#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: ⚙️ 执行器节点 n_exec (l2_daemon) 真的在工程图里、且接的是真数据。

📚 2026-10-18 老倪: 「l2_daemon 也要做一个节点，我要看到。放在哪里比较好？」

七条硬约束 (少一条就是"装饰节点", 老倪零容忍):
  ① 工程库里 n_exec 存在, 层 = L2, 源码指向 tools/l2_daemon.py
  ② 端口齐全: in1/in2/out1, 类型 PlanSegments / SafetyLimit / ActuationCommand
  ③ 连线是真连线: n_moveit.out1→n_exec.in1, sslimit.out1→n_exec.in2, n_exec.out1→ssact.in1
  ④ n_moveit 已改成"运动规划 (plan)"语义 (不再是 MoveIt 专属名)
  ⑤ 执行器进程在跑 (argv 精确匹配, 不用 pgrep -f 自匹配)
  ⑥ exec_state.json 帧龄 ≤5s (5Hz 发布) + phase 合法
  ⑦ Trace 里 n_exec 至少 3 条信号有实测值 (不是一排 '—')

用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_exec_node.py
"""
import json
import os
import sys
import time

sys.path[:0] = ["tools/gui", "src", "."]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OK = BAD = 0
PHASES = {"idle", "accepted", "planned", "dispatching", "arrived", "blocked"}


def chk(tag, cond, detail=""):
    global OK, BAD
    if cond:
        OK += 1
        print("  ✅ %-38s %s" % (tag, detail))
    else:
        BAD += 1
        print("  ❌ %-38s %s" % (tag, detail))
    return cond


def proc_alive():
    import glob
    for p in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            argv = [a for a in open(p, "rb").read().decode("utf-8", "ignore").split("\x00") if a]
        except Exception:                                                # noqa: BLE001
            continue
        if argv and "python" in os.path.basename(argv[0]) and any(a.endswith("tools/l2_daemon.py") for a in argv[1:]):
            return int(os.path.basename(os.path.dirname(p)))
    return 0


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication([])
    from lerobot.middleware import db

    rows = {r["node_id"]: r for r in db.node_rows()}

    print("① 工程库节点")
    ne = rows.get("n_exec")
    chk("n_exec 存在", bool(ne), ne.get("name") if ne else "缺失")
    if ne:
        chk("层 = L2", ne.get("layer") == "L2", str(ne.get("layer")))
        chk("源码指向 l2_daemon", "l2_daemon.py" in str(ne.get("source")), str(ne.get("source")))

    print("② 端口与类型")
    if ne:
        ins = {i["port"]: i for i in (ne.get("ins") or [])}
        outs = {o["port"]: o for o in (ne.get("outs") or [])}
        from lerobot.middleware import topic_types as tt
        chk("in1/in2/out1 齐全", set(ins) == {"in1", "in2"} and "out1" in outs, "in=%s out=%s" % (sorted(ins), sorted(outs)))
        chk("in1 类型 PlanSegments", "PlanSegments" in (tt.type_of_topic("ss.node.n_exec.in1") or ""),
            tt.type_of_topic("ss.node.n_exec.in1"))
        chk("out1 类型 ActuationCommand", "ActuationCommand" in (tt.type_of_topic("ss.node.n_exec.out1") or ""),
            tt.type_of_topic("ss.node.n_exec.out1"))
        chk("端口含 out2 (执行结果)", "out2" in outs, str(sorted(outs)))

    print("③ 连线 (真连线, 不是装饰)")
    if ne:
        ins = {i["port"]: (i.get("from") or []) for i in (ne.get("ins") or [])}
        outs = {o["port"]: (o.get("to") or []) for o in (ne.get("outs") or [])}
        chk("n_moveit → n_exec.in1", "n_moveit" in ins.get("in1", []), str(ins.get("in1")))
        chk("sslimit → n_exec.in2", "sslimit" in ins.get("in2", []), str(ins.get("in2")))
        chk("n_exec.out1 → ssact", "ssact" in outs.get("out1", []), str(outs.get("out1")))
        # 📚 2026-10-18 老倪: 「建议接状态校正器，按照你的建议做」
        chk("n_exec.out2 → ssinnov (状态校正器)", "ssinnov" in outs.get("out2", []), str(outs.get("out2")))
        chk("out2 类型 ExecResult", "ExecResult" in (tt.type_of_topic("ss.node.n_exec.out2") or ""),
            tt.type_of_topic("ss.node.n_exec.out2"))

    print("④ plan 节点语义")
    nm = rows.get("n_moveit") or {}
    chk("n_moveit 显示名含 plan", "plan" in str(nm.get("name") or "").lower(), str(nm.get("name")))
    chk("n_moveit 层 = L2", nm.get("layer") == "L2", str(nm.get("layer")))

    print("⑤ 执行器进程")
    pid = proc_alive()
    chk("l2_daemon 在跑", pid > 0, "pid=%s" % pid)

    print("⑥ 执行器状态文件 (5Hz)")
    sp = os.path.expanduser("~/zmax/zmax_data/ss_live/exec_state.json")
    st = {}
    try:
        st = json.load(open(sp, encoding="utf-8"))
    except Exception as e:                                               # noqa: BLE001
        chk("exec_state.json 可读", False, str(e)[:60])
    if st:
        age = time.time() - float(st.get("t_pub") or st.get("t") or 0)
        chk("帧龄 ≤5s", age <= 5.0, "%.2fs" % age)
        chk("phase 合法", str(st.get("phase")) in PHASES, str(st.get("phase")))
        chk("有 seg/n_seg 字段", "seg" in st and "n_seg" in st, "seg=%s n_seg=%s" % (st.get("seg"), st.get("n_seg")))

    print("⑦ Trace 里有实测值")
    import dds_canoe
    v = dds_canoe.build_view(standalone=True)
    t0 = time.time()
    while time.time() - t0 < 3:
        app.processEvents()
        time.sleep(0.05)
    v._fill_trace_fixed(force=True)
    app.processEvents()
    vals = []
    for r in range(v.tb.rowCount()):
        if "ss_exec" in (v.tb.item(r, 2).toolTip() or ""):
            vals.append((v.tb.item(r, 2).text(), v.tb.item(r, 3).text()))
    live = [x for x in vals if x[1] not in ("—", "", None)]
    chk("n_exec 信号行 ≥3 且非空", len(live) >= 3, "行 %d · 有值 %d · %s" % (len(vals), len(live), live[:4]))
    chk("Tx 显示为节点名", all((v.tb.item(r, 7).text() or "") == "动作执行器"
                          for r in range(v.tb.rowCount())
                          if "ss_exec" in (v.tb.item(r, 2).toolTip() or "")), "动作执行器")

    print("⑧ 段表 (plan 节点输出)")
    pf = os.path.expanduser("~/zmax/zmax_data/runtime/plan/plan_latest.json")
    pl = {}
    try:
        pl = json.load(open(pf, encoding="utf-8"))
    except Exception as e:                                               # noqa: BLE001
        chk("plan_latest.json 可读", False, str(e)[:60])
    if pl:
        chk("段表有段且后端明确", int(pl.get("n") or 0) >= 1 and pl.get("backend") in ("rule", "moveit"),
            "n=%s backend=%s skill=%s" % (pl.get("n"), pl.get("backend"), pl.get("skill")))
        chk("段表有目标/speed", all(x.get("pos") and x.get("speed") for x in (pl.get("segs") or [])),
            "segs=%d" % len(pl.get("segs") or []))
    # 段表只在"规划那一刻"更新 (不跑命令就不变) ⇒ 判据看归属链路是否成立,
    # 不去追 Trace 里的实时值 (那会因帧龄自然消失, 属于正确行为, 不是缺陷)。
    from lerobot.middleware import attribution as attr
    chk("段表归属 运动规划 → 动作执行器",
        attr.tx_of("planlive.n") == "运动规划" and attr.rx_of("planlive.n") == "动作执行器"
        and attr.layer_of("planlive.n") == "L2",
        "%s → %s · %s" % (attr.tx_of("planlive.n"), attr.rx_of("planlive.n"), attr.layer_of("planlive.n")))

    print("\n%s (%d 项 · 红 %d)" % ("✅ 全部通过" if BAD == 0 else "❌ 有红", OK + BAD, BAD))
    return 0 if BAD == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
