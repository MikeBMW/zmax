#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zmax 真机动作记录器 (48Hz, 只读)

影子模式专用: 只订阅 ROS 话题 + 只 GET 相机 JPEG, 绝不发布/不下发任何指令.

记录内容 (每集一个目录 rec48/YYYYMMDD/ep_HHMMSS/):
  stream.jsonl   48Hz: 末端位姿 + 全关节位置/速度 + 夹爪 + 当时的 AR 计划段
  frames/*.jpg   运动时 5Hz / 静止时 0.5Hz 的 8812 usb-cam 原图
  frames.jsonl   每帧: 文件名 / 大小 / 抓图墙钟 / 同时刻位姿 / 图-位姿偏差 ms
  meta.json      集级统计 (条数/实际频率/跨度/结束原因)

判据 (运行 60s 后 /dev/shm/zmax_rec48/status.json 可查):
  pose_hz≈48  joint_hz≈48  frame_hz 随运动  plan_hz>0  skew_p50<20ms

用法: python3 zmax_rec48.py            (systemd: zmax-rec48.service)
"""
import json
import os
import json as _json
import shutil
import threading
import time
import urllib.request

ROOT = os.environ.get("REC48_ROOT", "/home/intel/zmax_map/rec48")
STATUS = "/dev/shm/zmax_rec48/status.json"
FRAME_URL = os.environ.get("REC48_FRAME_URL", "http://127.0.0.1:8812/frame.jpg")
PLAN_PATH = os.environ.get("REC48_PLAN", "/home/intel/zmax_550c/zmax_data/ss_live/ar_cmd.json")
EP_SEC = float(os.environ.get("REC48_EP_SEC", "300"))
MAX_GB = float(os.environ.get("REC48_MAX_GB", "120"))
HZ_MOVE = float(os.environ.get("REC48_FRAME_HZ_MOVE", "5"))
HZ_IDLE = float(os.environ.get("REC48_FRAME_HZ_IDLE", "0.5"))
MOVE_MM = float(os.environ.get("REC48_MOVE_MM", "1.0"))

_lock = threading.Lock()
_snap = {"pose": None, "pose_t": 0.0, "joints": None, "joints_t": 0.0,
         "rjoints": None, "rjoints_t": 0.0,
         "grip": None, "grip_t": 0.0, "move_t": 0.0, "last_xyz": None}
_stats = {"pose": 0, "joint": 0, "grip": 0, "frame": 0, "plan": 0, "skew": []}


def _now():
    return time.time()


def _mkdir(p):
    os.makedirs(p, exist_ok=True)
    return p


class Episode:
    """一集: 独立目录 + 三个句柄"""

    def __init__(self, t0):
        day = time.strftime("%Y%m%d", time.localtime(t0))
        name = "ep_" + time.strftime("%H%M%S", time.localtime(t0))
        self.dir = _mkdir(os.path.join(ROOT, day, name))
        self.day = os.path.join(ROOT, day)
        self.t0 = t0
        self.n = {"stream": 0, "frame": 0, "plan": 0}
        self.f_stream = open(os.path.join(self.dir, "stream.jsonl"), "a", buffering=1)
        self.f_frame = open(os.path.join(self.dir, "frames.jsonl"), "a", buffering=1)
        self.f_plan = open(os.path.join(self.dir, "plan.jsonl"), "a", buffering=1)
        _mkdir(os.path.join(self.dir, "frames"))
        self.fidx = 0

    def write_stream(self, rec):
        self.f_stream.write(_json.dumps(rec, separators=(",", ":")) + "\n")
        self.n["stream"] += 1

    def write_plan(self, rec):
        self.f_plan.write(_json.dumps(rec, separators=(",", ":")) + "\n")
        self.n["plan"] += 1

    def write_frame(self, meta):
        self.f_frame.write(_json.dumps(meta, separators=(",", ":")) + "\n")
        self.n["frame"] += 1

    def frame_path(self):
        self.fidx += 1
        return os.path.join(self.dir, "frames", "f_%06d.jpg" % self.fidx), "f_%06d.jpg" % self.fidx

    def close(self, reason):
        dur = _now() - self.t0
        try:
            self.f_stream.close()
            self.f_frame.close()
            self.f_plan.close()
        except Exception:
            pass
        meta = {"episode": os.path.basename(self.dir), "t0": self.t0,
                "t_end": _now(), "duration_s": round(dur, 1),
                "rows": self.n, "end_reason": reason,
                "pose_hz": round(self.n["stream"] / max(dur, 1e-6), 1),
                "frame_hz": round(self.n["frame"] / max(dur, 1e-6), 2)}
        with open(os.path.join(self.dir, "meta.json"), "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        return meta


def _prune(cur_dir):
    """超限就删最老的集"""
    try:
        total = 0
        eps = []
        for day in sorted(os.listdir(ROOT)):
            dp = os.path.join(ROOT, day)
            if not os.path.isdir(dp):
                continue
            for ep in sorted(os.listdir(dp)):
                p = os.path.join(dp, ep)
                if not os.path.isdir(p):
                    continue
                sz = sum(os.path.getsize(os.path.join(r, f))
                         for r, _, fs in os.walk(p) for f in fs)
                eps.append((p, sz))
                total += sz
        limit = MAX_GB * 1024 ** 3
        for p, sz in eps:
            if total <= limit:
                break
            if os.path.abspath(p) == os.path.abspath(cur_dir):
                continue
            shutil.rmtree(p, ignore_errors=True)
            total -= sz
            print("[rec48] 清理旧集 %s (%.1fMB)" % (p, sz / 1e6), flush=True)
    except Exception as e:
        print("[rec48] prune err", e, flush=True)


def on_pose(msg):
    t = _now()
    p = msg.pose.position
    q = msg.pose.orientation
    st = msg.header.stamp
    with _lock:
        prev = _snap["last_xyz"]
        if prev is not None:
            d = ((p.x - prev[0]) ** 2 + (p.y - prev[1]) ** 2 + (p.z - prev[2]) ** 2) ** 0.5 * 1000
            if d > MOVE_MM:
                _snap["move_t"] = t
        _snap["last_xyz"] = (p.x, p.y, p.z)
        _snap["pose"] = {"x": p.x, "y": p.y, "z": p.z,
                         "qx": q.x, "qy": q.y, "qz": q.z, "qw": q.w,
                         "estamp": {"s": st.sec, "n": st.nanosec},
                         "frame": msg.header.frame_id}
        _snap["pose_t"] = t
        _stats["pose"] += 1


def _mk_joint_cb(key):
    def cb(msg):
        t = _now()
        st = msg.header.stamp
        with _lock:
            _snap[key] = {"name": list(msg.name),
                          "pos": [round(v, 6) for v in msg.position],
                          "vel": [round(v, 4) for v in msg.velocity] if msg.velocity else [],
                          "estamp": {"s": st.sec, "n": st.nanosec}}
            _snap[key + "_t"] = t
            _stats["joint" if key == "joints" else key] += 1
    return cb


def on_grip(msg):
    t = _now()
    with _lock:
        _snap["grip"] = float(msg.data)
        _snap["grip_t"] = t
        _stats["grip"] += 1


def cam_loop(stop):
    while not stop.is_set():
        t0 = _now()
        moving = (t0 - _snap["move_t"]) < 1.0
        hz = HZ_MOVE if moving else HZ_IDLE
        try:
            with urllib.request.urlopen(FRAME_URL, timeout=4) as r:
                jpg = r.read()
            tg = _now()
            if jpg[:2] == b"\xff\xd8" and len(jpg) > 2000:
                with _lock:
                    path, name = _EP.frame_path()
                    pose = _snap["pose"]
                    pt = _snap["pose_t"]
                    skew = round((tg - pt) * 1000, 1) if pose else None
                    if skew is not None:
                        _stats["skew"].append(skew)
                        if len(_stats["skew"]) > 500:
                            _stats["skew"] = _stats["skew"][-500:]
                    _stats["frame"] += 1
                with open(path, "wb") as f:
                    f.write(jpg)
                rec = {"ts": tg, "name": name, "bytes": len(jpg), "moving": moving,
                       "pose": pose, "pose_age_ms": round((tg - pt) * 1000, 1) if pose else None,
                       "skew_ms": skew}
                _EP.write_frame(rec)
        except Exception:
            pass
        stop.wait(max(0.02, (1.0 / hz) - (_now() - t0)))


def plan_loop(stop):
    last = None
    while not stop.is_set():
        try:
            st = os.stat(PLAN_PATH)
            key = (st.st_mtime_ns, st.st_size)
            if key != last:
                last = key
                with open(PLAN_PATH) as f:
                    d = json.load(f)
                keep = {k: d.get(k) for k in
                        ("seg", "a", "a_raw", "b", "u", "t_seg", "n_mods", "idx", "n")
                        if k in d}
                keep["ts"] = _now()
                _EP.write_plan(keep)
                _stats["plan"] += 1
        except Exception:
            pass
        stop.wait(0.15)


def main():
    global _EP
    _mkdir(ROOT)
    _mkdir(os.path.dirname(STATUS))
    _EP = Episode(_now())
    stop = threading.Event()

    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import JointState
    from std_msgs.msg import Float32
    from geometry_msgs.msg import PoseStamped

    rclpy.init()
    node = rclpy.create_node("zmax_rec48")
    node.create_subscription(JointState, "/joint_states", _mk_joint_cb("joints"), qos_profile_sensor_data)
    node.create_subscription(JointState, "/real_joint_states", _mk_joint_cb("rjoints"), qos_profile_sensor_data)
    node.create_subscription(Float32, "/gripper_pos", on_grip, qos_profile_sensor_data)
    print("[rec48] 订阅就绪, 输出 %s" % _EP.dir, flush=True)

    def _write(t):
        """每拍落一行: 位姿为主体, 带上当时最新的关节/夹爪"""
        with _lock:
            pose = _snap["pose"]
            if pose is None:
                return
            j = _snap.get("joints"); rj = _snap.get("rjoints"); g = _snap.get("grip")
            rec = {"ts": t, "pose": pose,
                   "j": j, "j_age_ms": round((t - _snap["joints_t"]) * 1000, 1) if j else None,
                   "rj": rj, "g": g,
                   "g_age_ms": round((t - _snap["grip_t"]) * 1000, 1) if g is not None else None,
                   "moving": (t - _snap["move_t"]) < 0.5}
        _EP.write_stream(rec)

    # 位姿回调里直接落 (48Hz): 订阅只挂一次, 存 + 写在同一回调
    def _pose_cb(msg):
        on_pose(msg)
        _write(_now())

    node.create_subscription(PoseStamped, "/robot/tcp_pose", _pose_cb, qos_profile_sensor_data)

    import rclpy.executors
    ex = rclpy.executors.SingleThreadedExecutor()
    ex.add_node(node)
    th = threading.Thread(target=ex.spin, daemon=True)
    th.start()
    threading.Thread(target=cam_loop, args=(stop,), daemon=True).start()
    threading.Thread(target=plan_loop, args=(stop,), daemon=True).start()

    t_status = 0.0
    while True:
        time.sleep(1.0)
        now = _now()
        if now - t_status >= 5:
            t_status = now
            dur = now - _EP.t0
            sk = sorted(_stats["skew"]) or [0]
            st = {"t": now, "ep": os.path.basename(_EP.dir),
                  "ep_age_s": round(dur, 1),
                  "rows": dict(_EP.n),
                  "pose_hz": round(_stats["pose"] / max(dur, 1e-6), 1),
                  "joints_hz": round(_stats["joints"] / max(dur, 1e-6), 1),
                  "frames": _stats["frame"],
                  "plan_updates": _stats["plan"],
                  "skew_p50_ms": sk[len(sk) // 2],
                  "moving": (_now() - _snap["move_t"]) < 1.0}
            tmp = STATUS + ".tmp"
            with open(tmp, "w") as f:
                json.dump(st, f)
            os.replace(tmp, STATUS)
        if now - _EP.t0 >= EP_SEC:
            m = _EP.close("rotate")
            print("[rec48] 换集 %s" % m, flush=True)
            _EP = Episode(_now())
            for k in list(_stats):
                _stats[k] = 0 if k != "skew" else _stats[k]
            _prune(_EP.dir)


if __name__ == "__main__":
    main()
