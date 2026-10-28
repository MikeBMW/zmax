#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🗺 550C 建图采集器: 臂相机帧 + TCP 真值成对落盘 (跑轨迹3时开着)。

为什么另写一个 (老倪 2026-10-26「你在550C中是自动记录图像和轨迹, 用于建图么?」):
  550C 上确实有 zmax-gs-ros-bridge(8811)/autotrain/gs-train/map-intel 这条链,
  但实测 8811 的 img_age/pose_age 都是 43257s、fps=0 —— 两路输入是死的, 跑一趟什么都没记。
  这个采集器不依赖 ROS topic, 直连两个 HTTP 唯一依据, 谁能用就用谁:
    · 图像: Orin D405 hub  http://192.168.23.66:8792/frame.jpg   (640x480 JPEG)
    · 位姿: Orin 桥        http://192.168.23.66:39061/status     (endInRef, 米)
  落盘: <out>/sessions/<YYYYmmdd-HHMMSS>/{frames/*.jpg, poses.jsonl, summary.json}
  停了(SIGTERM/Ctrl-C)会写 summary.json: 帧数/时长/实际帧率/TCP 包围盒/丢帧数。

用法:
  python tools/map_recorder_550c.py --out /home/intel/zmax_550c/zmax_data/mapping --hz 5
  python tools/map_recorder_550c.py --duration 10 --out /tmp/maprec   # 自检用
"""
import argparse
import json
import os
import signal
import sys
import time
import urllib.request

STOP = {"flag": False}


def _get(url, timeout=4.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:      # noqa: S310
        return r.read()


def _json(url, timeout=4.0):
    return json.loads(_get(url, timeout).decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/home/intel/zmax_550c/zmax_data/mapping")
    ap.add_argument("--cam", default="http://192.168.23.66:8792/frame.jpg")
    ap.add_argument("--pose", default="http://192.168.23.66:39061/status")
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--duration", type=float, default=0.0, help="0 = 一直采到 SIGTERM")
    ap.add_argument("--tag", default="", help="会话标签, 例如 traj3")
    ap.add_argument("--depth", default="http://192.168.23.66:8792/depth.png",
                    help="深度图 URL (置空不采); 3DGS 有深度就不用随机盒子初始点云")
    ap.add_argument("--no-depth", action="store_true")
    a = ap.parse_args()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = (a.tag + "-" + stamp) if a.tag else stamp
    sess = os.path.join(a.out, "sessions", name)
    fdir = os.path.join(sess, "frames")
    ddir = os.path.join(sess, "depth")
    os.makedirs(fdir, exist_ok=True)
    if a.depth and not a.no_depth:
        os.makedirs(ddir, exist_ok=True)
    pose_f = open(os.path.join(sess, "poses.jsonl"), "w", encoding="utf-8")

    def _stop(*_a):
        STOP["flag"] = True
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    per = 1.0 / max(0.2, a.hz)
    t0 = time.time()
    n = n_pose_fail = n_cam_fail = 0
    bbox = None
    last_ts = 0.0
    print(json.dumps({"event": "start", "session": sess, "hz": a.hz, "cam": a.cam}, ensure_ascii=False), flush=True)

    while not STOP["flag"]:
        if a.duration and (time.time() - t0) >= a.duration:
            break
        tick = time.time()
        # 1) 位姿真值
        pos = None
        try:
            st = _json(a.pose).get("status") or {}
            e = st.get("endInRef") or []
            if len(e) >= 3:
                pos = [round(float(e[i]) * 1000.0, 2) for i in range(3)]     # m → mm
                # 🔴 必须存姿态: 相机装在臂上, 位姿要做 T_base2tcp @ T_cam2tool 才能建 3DGS;
                #    只存 xyz 的 962 帧等于白采 (老倪问"两次够不够"时发现这个洞)。
                rpy = [round(float(e[i]), 5) for i in range(3, 6)] if len(e) >= 6 else None
                last_ts = float(st.get("ts") or time.time())
                if bbox is None:
                    bbox = [pos[:], pos[:]]
                else:
                    for k in range(3):
                        bbox[0][k] = min(bbox[0][k], pos[k])
                        bbox[1][k] = max(bbox[1][k], pos[k])
        except Exception:                                                    # noqa: BLE001
            n_pose_fail += 1
        # 2) 图像 (位姿拿到了才存, 保证成对)
        if pos is not None:
            try:
                jpg = _get(a.cam, timeout=3.0)
                if jpg[:2] != b"\xff\xd8":
                    raise ValueError("不是 JPEG (%dB)" % len(jpg))
                fp = os.path.join(fdir, "%06d.jpg" % n)
                with open(fp, "wb") as f:
                    f.write(jpg)
                dep_ok = False
                if a.depth and not a.no_depth:
                    try:
                        png = _get(a.depth, timeout=3.0)
                        if png[:4] == b"\x89PNG":
                            with open(os.path.join(ddir, "%06d.png" % n), "wb") as f:
                                f.write(png)
                            dep_ok = True
                    except Exception:                                        # noqa: BLE001
                        pass
                pose_f.write(json.dumps({"i": n, "ts": round(time.time(), 3),
                                         "tcp_mm": pos, "tcp_rpy": rpy,
                                         "file": os.path.basename(fp),
                                         "depth": dep_ok,
                                         "bytes": len(jpg)}, ensure_ascii=False) + "\n")
                pose_f.flush()
                n += 1
            except Exception:                                                # noqa: BLE001
                n_cam_fail += 1
        dt = time.time() - tick
        if dt < per:
            time.sleep(per - dt)

    pose_f.close()
    dur = round(time.time() - t0, 2)
    summ = {"session": sess, "t0": t0, "dur_s": dur, "frames": n,
            "hz_target": a.hz, "hz_real": round(n / dur, 2) if dur > 0 else 0,
            "cam_fail": n_cam_fail, "pose_fail": n_pose_fail,
            "tcp_bbox_mm": bbox, "last_pose_ts": last_ts,
            "cam": a.cam, "pose": a.pose}
    with open(os.path.join(sess, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False, indent=2)
    print(json.dumps({"event": "stop", **summ}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
