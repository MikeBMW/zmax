#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⏱️ Z-MAX 550C 时间戳记录器 —— 图像 + 位姿 (只读, 绝不发机器人指令)

2026-10-30 老倪: 「550C 自主进化, 但不要发出机器人操作指令。但是 550C 要保持建图,
记录有时间戳的图像和位姿」

为什么单独一个进程:
  · 现成的 gs_autocap 是「臂动了才记」(触发式), 臂不动就一条也不记 ⇒ 满足不了"持续记录"
  · 本进程**无条件**按固定频率记录: 每拍一张图 + 一个位姿 + 三个时间戳 (抓图/位姿/写入)
  · 落盘给建图/3DGS/复盘用: 有图有位姿有时间 ⇒ 事后能重建任意时刻的相机位姿

数据契约 (每行 index.jsonl):
  {ts_grab, ts_pose, ts_wall, skew_ms, frame, src, wh, bytes,
   pose:{x,y,z,qx,qy,qz,qw,rx,ry,rz,frame}, img_age_s, pose_age_s, err}

源 (只读 HTTP, 均在 127.0.0.1, 不出本机):
  ros-bridge  8811 /frame.jpg  ← ROS /realsense/color/image_raw   (相机没插时 503)
  usb-cam     8812 /frame.jpg  ← /dev/video0 USB 相机              (现役可用)
  pose        8811 /pose       ← ROS /robot/tcp_pose (base_link, 真值)
"""
from __future__ import annotations

import io
import json
import os
import shutil
import time
import urllib.request

REC_ROOT = os.environ.get("REC_ROOT", os.path.expanduser("~/zmax_map/rec"))
REC_HZ = float(os.environ.get("REC_HZ", "2.0"))
REC_MAX_GB = float(os.environ.get("REC_MAX_GB", "20"))
STATUS = os.environ.get("REC_STATUS", "/dev/shm/zmax_rec/status.json")
POSE_URL = os.environ.get("REC_POSE_URL", "http://127.0.0.1:8811/pose")
SOURCES = [
    ("ros-bridge", "http://127.0.0.1:8811/frame.jpg"),
    ("usb-cam", "http://127.0.0.1:8812/frame.jpg"),
]
TIMEOUT = 3.0


def _jpeg_wh(b):
    """从 JPEG 头读宽高 (不引第三方库: 找 SOF0/1/2 段)"""
    try:
        i = 2
        n = len(b)
        while i < n - 9:
            if b[i] != 0xFF:
                i += 1
                continue
            m = b[i + 1]
            if m in (0xC0, 0xC1, 0xC2, 0xC3):
                h = (b[i + 5] << 8) | b[i + 6]
                w = (b[i + 7] << 8) | b[i + 8]
                return [w, h]
            if m in (0xD8, 0xD9):
                i += 2
                continue
            seg = (b[i + 2] << 8) | b[i + 3]
            i += 2 + max(2, seg)
    except Exception:                                          # noqa: BLE001
        pass
    return None


def _get(url, timeout=TIMEOUT):
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=timeout) as r:
        b = r.read()
    return b, time.time(), (time.time() - t0)


def _pose():
    try:
        b, ts, _ = _get(POSE_URL)
        d = json.loads(b.decode("utf-8", "replace"))
        return d, ts
    except Exception as e:                                    # noqa: BLE001
        return {"err": "%s: %s" % (type(e).__name__, e)}, time.time()


def _day_dir(ts=None):
    return os.path.join(REC_ROOT, time.strftime("%Y%m%d", time.localtime(ts or time.time())))


def _prune():
    """磁盘红线: 超出 REC_MAX_GB 就删最旧的一天 (只删 rec/ 下 YYYYMMDD 目录)"""
    try:
        days = sorted(d for d in os.listdir(REC_ROOT) if d.isdigit() and len(d) == 8)
        while days:
            total = 0
            for d in days:
                for root, _dirs, files in os.walk(os.path.join(REC_ROOT, d)):
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
            if total <= REC_MAX_GB * (1 << 30):
                return round(total / (1 << 30), 2)
            shutil.rmtree(os.path.join(REC_ROOT, days[0]), ignore_errors=True)
            days = days[1:]
    except Exception:                                          # noqa: BLE001
        pass
    return None


def _write_status(st):
    try:
        os.makedirs(os.path.dirname(STATUS), exist_ok=True)
        tmp = STATUS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, STATUS)
    except Exception:                                          # noqa: BLE001
        pass


def main():
    os.makedirs(REC_ROOT, exist_ok=True)
    period = 1.0 / max(REC_HZ, 0.1)
    n_ok = n_err = n_today = 0
    t_start = time.time()
    last_src = ""
    skews = []
    print("[rec] root=%s hz=%.1f max_gb=%.1f" % (REC_ROOT, REC_HZ, REC_MAX_GB), flush=True)
    while True:
        t_cycle = time.time()
        day = _day_dir(t_cycle)
        fdir = os.path.join(day, "frames")
        os.makedirs(fdir, exist_ok=True)
        line = {"ts_wall": round(t_cycle, 3), "frame": None, "src": None,
                "wh": None, "bytes": 0, "err": ""}
        # ① 图像: 上次可用的源优先试, 失败再顺序试其它源
        order = sorted(SOURCES, key=lambda s: 0 if s[0] == last_src else 1)
        for name, url in order:
            try:
                b, ts_grab, _dt = _get(url)
                if len(b) < 2000:
                    raise ValueError("frame too small %d" % len(b))
                fn = "%s_%03d_%s.jpg" % (time.strftime("%H%M%S", time.localtime(ts_grab)),
                                         int((ts_grab % 1) * 1000), name)
                with open(os.path.join(fdir, fn), "wb") as f:
                    f.write(b)
                line.update(ts_grab=round(ts_grab, 3), frame=os.path.join(time.strftime("%Y%m%d", time.localtime(ts_grab)), "frames", fn),
                            src=name, bytes=len(b), wh=_jpeg_wh(b))
                last_src = name
                break
            except Exception as e:                          # noqa: BLE001
                line["err"] = "%s:%s" % (name, type(e).__name__)
                continue
        # ② 位姿 (与图分开取: 图挂了也要有位姿连续性证据)
        p, ts_pose = _pose()
        line["ts_pose"] = round(float(p.get("ts") or ts_pose), 3)
        line["ts_pose_recv"] = round(ts_pose, 3)          # 收到位姿的本机墙钟
        line["pose"] = {k: p.get(k) for k in ("x", "y", "z", "qx", "qy", "qz", "qw", "rx", "ry", "rz", "frame")}
        line["pose_age_s"] = p.get("age_s")
        line["pose_stale"] = p.get("stale")
        # 🔴 2026-10-30 实测: /robot/tcp_pose 的 header 时间戳比 550C 墙钟快 51.3s (机器人控制器时钟)
        #   ⇒ 位姿-图像配准必须用「本机收到位姿的墙钟」(ts_pose_recv), header 戳单独留证 + 记漂移
        line["pose_clock_drift_ms"] = round((line["ts_pose"] - ts_pose) * 1000.0, 1)
        if line.get("ts_grab"):
            skew = (ts_pose - line["ts_grab"]) * 1000.0   # 图-位姿同拍差 (墙钟口径)
            line["skew_ms"] = round(skew, 1)
            skews = (skews + [abs(skew)])[-200:]
        # ③ 落盘 (一行一帧; fsync 由系统负责, 断电最多丢最后一拍)
        try:
            with open(os.path.join(day, "index.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
            n_ok += 1
            n_today += 1
        except Exception as e:                              # noqa: BLE001
            n_err += 1
            print("[rec] 写索引失败 %s: %s" % (type(e).__name__, e), flush=True)
        if not line.get("frame"):
            n_err += 1
            print("[rec] 无图 (%.1fs) %s" % (time.time() - t_start, line["err"]), flush=True)
        # ④ 状态 (供监控/页面读, 10 拍刷一次)
        if n_ok % max(1, int(REC_HZ * 2)) == 0:
            sk = sorted(skews)
            _write_status({"ok": bool(line.get("frame")), "t": round(time.time(), 3),
                           "hz": REC_HZ, "src": line.get("src"), "frame": line.get("frame"),
                           "n_ok": n_ok, "n_err": n_err, "n_today": n_today,
                           "skew_ms_p50": (round(sk[len(sk) // 2], 1) if sk else None),
                           "pose_clock_drift_ms": line.get("pose_clock_drift_ms"),
                           "pose_stale": line.get("pose_stale"),
                           "disk_gb": _prune(), "max_gb": REC_MAX_GB,
                           "root": REC_ROOT, "err": line.get("err") or ""})
        dt = time.time() - t_cycle
        time.sleep(max(0.0, period - dt))


if __name__ == "__main__":
    main()
