#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay_derive.py —— 把一轮真机采集快照派生成"可进化的结构化数据包"

输入: zmax_data/rokae_sdk/capture/run_*.json  (arm_step_traj.py 采集)
输出: <out>/derived/ 下 5 个文件
  1. points_mm.json      逐点表(mm 单位): i/t/tcp_mm/rpy/joints_deg/err/jump/seg/dur
  2. seg_stats.json      甘特分段统计: 每段 dur/n/pct/per_pt + 段间迁移
  3. trajectory_clean.json  只含成功点的干净轨迹(TCP 序列 + 关节序列), 供训练/进化直接用
  4. quality.json        质量门: 到位误差分布/超差点/时间异常点/单调性
  5. manifest.json       这次运行的元信息 + 文件清单 + md5, 便于追溯

为什么单独做派生(2026-11-15 老倪「根据保存的数据自主进化」):
  原始快照是"过程记录"(含调试字段、米单位、按点平铺);
  进化要的是"结构化样本"(mm、分段、异常隔离、可直接喂训练)。
  两层分开, 原始快照不动(证据), 派生可随时重算(配方在脚本里)。

用法:
  ./gui-venv311/bin/python tools/replay_derive.py \
      --run zmax_data/rokae_sdk/capture/run_20261115_145259.json \
      --out zmax_data/runs/LAST_20261115
"""
import argparse
import hashlib
import json
import os
import statistics as st
from collections import OrderedDict

# 与 tools/ss_meta_task_ar.py 的 _REPLAY_SEGS 同界(改一处必须同步另一处)
SEGS = [
    (0, 9, "抓取(合爪#9)"), (10, 15, "过渡/举升"), (16, 19, "扫码(对码)"),
    # 与 arm_step_traj.py / ss_meta_task_ar.py 同源: 扫码后 = 抓取光模块 → 举升 → 插入 → 拔出
    (20, 40, "抓取光模块"), (41, 90, "举升/转运"), (91, 113, "插入·松开·退回·抓环"),
    (114, 119, "拉环解锁·拽出"), (120, 144, "扫码(举高段)"),
    (145, 149, "过渡"), (150, 160, "金手指检测"), (161, 161, "过渡"),
    (162, 193, "表面检测"), (194, 197, "过渡"), (198, 204, "下放入盘"),
    (205, 205, "松开分拣(#205)"), (206, 214, "回位"),
]


def seg_of(i):
    for a, b, nm in SEGS:
        if a <= i <= b:
            return nm
    return "?"


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    raw = json.load(open(a.run, encoding="utf-8"))
    steps = raw.get("steps") or []
    cap = raw.get("_cap") or {}
    outd = os.path.join(a.out, "derived")
    os.makedirs(outd, exist_ok=True)

    # ── 1. 逐点表(mm) ──────────────────────────────────────────────────────
    pts = []
    for s in steps:
        tcp = s.get("tcp")
        pts.append(OrderedDict([
            ("i", s["i"]),
            ("t_wall", s.get("t_wall")),
            ("t_rel", s.get("t_rel")),
            # ★ endInRef 返回单位是【米】, 这里统一换成 mm(与 cell_points.json 同单位)
            ("tcp_mm", [round(v * 1000.0, 2) for v in tcp] if tcp else None),
            ("rpy_rad", s.get("rpy")),
            ("joints_deg", s.get("joints_after_deg")),
            ("target_deg", s.get("target_deg")),
            ("dur_s", s.get("secs")),
            ("err_deg", s.get("err_deg")),
            ("jump_deg", s.get("max_jump_deg")),
            ("seg", s.get("seg") or seg_of(s["i"])),
            ("ok", bool(s.get("ok"))),
            ("capture", (s.get("capture") or {}).get("jpg") or (s.get("capture") or {}).get("json")),
        ]))
    json.dump({"_unit": "tcp_mm=毫米, rpy=弧度, joints_deg=度",
               "_src": os.path.basename(a.run), "points": pts},
              open(os.path.join(outd, "points_mm.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ── 2. 分段统计 ───────────────────────────────────────────────────────
    by_i = {p["i"]: p for p in pts}
    total = sum(p["dur_s"] or 0.0 for p in pts if p.get("ok"))
    segs = []
    for i0, i1, nm in SEGS:
        sel = [by_i[i] for i in range(i0, i1 + 1) if i in by_i and by_i[i].get("ok")]
        if not sel:
            continue
        dur = sum(x["dur_s"] for x in sel)
        segs.append(OrderedDict([
            ("name", nm), ("i0", i0), ("i1", i1), ("n", len(sel)),
            ("dur_s", round(dur, 2)),
            ("pct", round(100.0 * dur / total, 2) if total else 0),
            ("per_pt_s", round(dur / len(sel), 3)),
            ("err_max_deg", round(max(x["err_deg"] for x in sel), 3)),
            # 段首/段尾 TCP, 便于看"这段从哪走到哪"
            ("tcp_from_mm", sel[0]["tcp_mm"]), ("tcp_to_mm", sel[-1]["tcp_mm"]),
            # 位移量(mm) —— 判断"慢是因为走得远还是因为动作慢"要靠它
            ("path_mm", round(sum(
                ((sel[k]["tcp_mm"][0] - sel[k - 1]["tcp_mm"][0]) ** 2 +
                 (sel[k]["tcp_mm"][1] - sel[k - 1]["tcp_mm"][1]) ** 2 +
                 (sel[k]["tcp_mm"][2] - sel[k - 1]["tcp_mm"][2]) ** 2) ** .5
                for k in range(1, len(sel))), 1) if len(sel) > 1 else 0.0),
        ]))
    json.dump({"_src": os.path.basename(a.run), "total_s": round(total, 2),
               "n_points": len(pts), "s_per_point": round(total / max(1, len(pts)), 4),
               "uph": round(3600.0 / total, 1) if total else 0, "segments": segs},
              open(os.path.join(outd, "seg_stats.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ── 3. 干净轨迹(只含成功点, 供训练/进化) ──────────────────────────────
    good = [p for p in pts if p.get("ok") and p.get("tcp_mm") and p.get("joints_deg")]
    json.dump({"_what": "干净轨迹: 只保留到位成功的点, TCP(mm)+关节(deg)+相对时间, 可直接喂训练",
               "_src": os.path.basename(a.run), "n": len(good),
               "t": [p["t_rel"] for p in good],
               "tcp_mm": [p["tcp_mm"] for p in good],
               "joints_deg": [p["joints_deg"] for p in good],
               "seg": [p["seg"] for p in good]},
              open(os.path.join(outd, "trajectory_clean.json"), "w", encoding="utf-8"),
              ensure_ascii=False)

    # ── 4. 质量门 ─────────────────────────────────────────────────────────
    errs = [p["err_deg"] for p in pts if p.get("err_deg") is not None]
    durs = [p["dur_s"] for p in pts if p.get("dur_s") is not None]
    tr = [p["t_rel"] for p in pts if p.get("t_rel") is not None]
    med = st.median(durs) if durs else 0
    slow = [{"i": p["i"], "dur_s": p["dur_s"], "jump_deg": p["jump_deg"], "seg": p["seg"]}
            for p in pts if p.get("dur_s") and med and p["dur_s"] > 3 * med]
    bad = [{"i": p["i"], "err_deg": p["err_deg"], "seg": p["seg"]}
           for p in pts if p.get("err_deg") is not None and p["err_deg"] > 0.6]
    q = OrderedDict([
        ("_src", os.path.basename(a.run)),
        ("n_points", len(pts)), ("n_ok", len(good)),
        ("all_in_position", len(good) == len(pts)),
        ("err_max_deg", round(max(errs), 3) if errs else None),
        ("err_avg_deg", round(sum(errs) / len(errs), 3) if errs else None),
        ("err_p95_deg", round(sorted(errs)[int(.95 * (len(errs) - 1))], 3) if errs else None),
        ("tol_deg", 0.6),
        ("over_tol_points", bad),
        ("dur_total_s", round(sum(durs), 2)), ("dur_median_s", round(med, 3)),
        ("dur_slow_points_gt3x_median", slow),
        ("t_monotonic", all(tr[k] <= tr[k + 1] for k in range(len(tr) - 1)) if len(tr) > 1 else None),
        ("t_span_s", round(tr[-1] - tr[0], 2) if len(tr) > 1 else None),
        ("verdict", "PASS" if (len(good) == len(pts) and not bad) else "CHECK"),
    ])
    json.dump(q, open(os.path.join(outd, "quality.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ── 5. manifest (先写一版, 再把自己也算进去重写) ──────────────────────
    def _files():
        out = []
        for root, _dirs, fs in os.walk(a.out):
            for fn in sorted(fs):
                p = os.path.join(root, fn)
                out.append({"path": os.path.relpath(p, a.out),
                            "bytes": os.path.getsize(p), "md5": md5(p)})
        return out

    src_md5 = md5(a.run)
    man_path = os.path.join(outd, "manifest.json")
    man = {
        "_what": "MT-08 215 点真机运行数据包清单(最后一次真实机器运行)",
        "run_id": os.path.basename(a.out),
        "source_snapshot": os.path.abspath(a.run),
        "source_md5": src_md5,
        "robot_ip": cap.get("robot_ip"), "host": cap.get("host"),
        "started_wall": cap.get("started_wall"), "ended_wall": cap.get("ended_wall"),
        "elapsed_s": cap.get("elapsed_s"),
        "speed": cap.get("speed"), "dwell_ms": cap.get("dwell_ms"),
        "n_frames": cap.get("n_frames"), "n_done": cap.get("n_done"),
        "n_ok": len(good),
        "total_motion_s": round(total, 2),
        "s_per_point": round(total / max(1, len(pts)), 4),
        "uph": round(3600.0 / total, 1) if total else 0,
        "captures": [p["capture"] for p in pts if p.get("capture")],
        "files": [],
    }
    # 两遍: 第一遍建立占位(让其他文件先落盘), 第二遍把 manifest 自身也纳入清单
    json.dump(man, open(man_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    man["files"] = _files()
    json.dump(man, open(man_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(json.dumps({"ok": True, "out": outd, "n_points": len(pts), "n_ok": len(good),
                      "total_s": round(total, 2), "verdict": q["verdict"],
                      "files": [f["path"] for f in man["files"]]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
