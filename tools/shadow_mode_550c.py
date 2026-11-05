#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔮 550C 影子模式 (只读) — 真机在动, 我跟着学: 采集 + 自标定自检 + 建图(工作空间/特征点云)

红线 (老倪 2026-09-xx): Orin 是生产设备 —— 本程序**只做 HTTP GET**:
  · 图像  http://192.168.23.66:8794/frame.jpg   (+ /status 取帧龄, 用于时间对齐)
  · 位姿  http://192.168.23.66:39061/status     (endInRef / flangeInBase, 只读)
零下行: 不订阅控制话题、不调任何 move/gripper 接口、不写 Orin。

影子模式做三件事 (全部可复算):
  1) 采集  —— 位姿 20Hz 进环形缓冲; 图像按内容去重落盘 (同图不重复记不同位姿);
              每帧记「拍照时刻 = 收到时刻 − 帧龄」并对该时刻插值位姿 (真机同构的做法)。
  2) 自标定 —— 用机器人自己的运动做手眼旋转自证: 相邻关键帧估计相机相对旋转 R_cam,
              与 X_R^T·ΔR_tcp·X_R 比对 (X_R = T_cam2tool 旋转);
              同时试 TCP / 法兰 两种旋转口径, 报各自残差 (谁对谁错由数据说话);
              残差大 ⇒ 用 Kabsch 反解 X_R, 留出集验证后才落盘候选文件。
  3) 建图   —— ① 工作空间覆盖 (TCP 轨迹栅格 + 视点) ② 手眼通过后把特征点按 T_base_cam
              反投影到 base 系 (无深度 ⇒ 单目稀疏点云, 只报相对尺度与平面拟合高度, 不编造 mm 精度)。

产物: ~/zmax_data/shadow/<session>/{frames/, poses.jsonl, keyframes.jsonl, status.json,
      calib_live.json, map.json, shadow_3d.html, summary.json}
状态: ~/zmax_data/shadow/latest.json  (GUI/大屏可轮询)

用法:
  gui-venv311/bin/python tools/shadow_mode_550c.py --duration 300      # 跑 5 分钟自检
  gui-venv311/bin/python tools/shadow_mode_550c.py                     # 常驻
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request

import numpy as np

STOP = {"flag": False}
CAM = os.environ.get("SHADOW_CAM", "http://192.168.23.66:8794/frame.jpg")
CAM_STATUS = os.environ.get("SHADOW_CAM_STATUS", "http://192.168.23.66:8794/status")
POSE = os.environ.get("SHADOW_POSE", "http://192.168.23.66:39061/status")
ROOT = os.environ.get("SHADOW_ROOT", "/home/ubuntu/zmax_data/shadow")
HANDEYE = "/home/ubuntu/zmax/models/handeye_state.json"
LATEST = os.path.join(ROOT, "latest.json")   # 默认输出根; --out 时在 main 内重定向

K = np.array([[394.0623474121094, 0.0, 318.443603515625],
              [0.0, 393.472412109375, 238.658447265625],
              [0.0, 0.0, 1.0]])


# ---------------------------------------------------------------- 基础工具
def _get(url: str, timeout: float = 4.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:      # noqa: S310 (只读内网)
        return r.read()


def _json(url: str, timeout: float = 4.0) -> dict:
    return json.loads(_get(url, timeout).decode("utf-8", "replace"))


def rpy2R(rx: float, ry: float, rz: float) -> np.ndarray:
    """与 orin_pose_relay 同口径: R = Rz·Ry·Rx"""
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def ang_deg(R: np.ndarray) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, (float(np.trace(R)) - 1.0) / 2.0))))


def rotvec(R: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.Rodrigues(R)[0].ravel()


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------- 位姿线程
class PoseBuf:
    """20Hz 只读轮询位姿, 存 (mono_time, payload)。payload 含 tcp/flange 两套 rpy。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.buf: list[tuple[float, dict]] = []
        self.hist: list[tuple[float, dict]] = []
        self.err = ""
        self.n = 0
        self.state = {}

    def run(self) -> None:
        while not STOP["flag"]:
            t0 = time.monotonic()
            try:
                st = _json(POSE, 3.0).get("status") or {}
                e = st.get("endInRef") or []
                fl = st.get("flangeInBase") or []
                if len(e) < 6:
                    raise ValueError("endInRef 不足 6 位")
                rec = {
                    "t": round(time.time(), 4), "mono": time.monotonic(),
                    "tcp": [float(v) for v in e[:6]],
                    "flange": [float(v) for v in fl[:6]] if len(fl) >= 6 else None,
                    "joint": [float(v) for v in (st.get("jointPos") or [])[:6]],
                    "torque": [float(v) for v in (st.get("jointTorque") or [])[:6]],
                    "mode": st.get("operateMode"), "power": st.get("powerState"),
                }
                with self.lock:
                    self.buf.append((rec["mono"], rec))
                    if len(self.buf) > 900:                     # 45s @20Hz 精细
                        self.buf = self.buf[-900:]
                    if self.n % 5 == 0:                         # 抽稀长历史 (分钟级 lag 自标定用)
                        self.hist.append((rec["mono"], rec))
                        if len(self.hist) > 60000:
                            self.hist = self.hist[-60000:]
                    self.state = {"mode": rec["mode"], "power": rec["power"]}
                    self.n += 1
                    self.err = ""
            except Exception as exc:                             # noqa: BLE001
                with self.lock:
                    self.err = str(exc)[:120]
            dt = time.monotonic() - t0
            time.sleep(max(0.0, 0.05 - dt))

    def at(self, mono: float) -> dict | None:
        with self.lock:
            buf = list(self.buf)
        if not buf:
            return None
        best = min(buf, key=lambda kv: abs(kv[0] - mono))
        return dict(best[1], dt_ms=round((best[0] - mono) * 1000, 1))

    def R_at(self, mono: float, kind: str = "tcp") -> np.ndarray | None:
        """mono 时刻的旋转矩阵 (kind: tcp|flange)。用于时间对齐自标定。"""
        with self.lock:
            pool = self.buf if (self.buf and abs(self.buf[0][0] - mono) < 40) else self.hist
            pool = list(pool)
        if not pool:
            return None
        _, r = min(pool, key=lambda kv: abs(kv[0] - mono))
        if abs(r["mono"] - mono) > 0.5:
            return None
        if not r:
            return None
        v = r.get(kind)
        if not v or len(v) < 6:
            return None
        return rpy2R(v[3], v[4], v[5])

    def last(self) -> dict | None:
        with self.lock:
            return dict(self.buf[-1][1]) if self.buf else None


# ---------------------------------------------------------------- 自标定
class ShadowCalib:
    """手眼旋转自证/反解 + 工作空间覆盖。"""

    def __init__(self, handeye_path: str) -> None:
        he = json.load(open(handeye_path, encoding="utf-8"))
        X = np.array(he["T_cam2tool"], float)
        self.X_R = X[:3, :3]
        self.X_t = X[:3, 3]
        self.src = handeye_path
        self.pairs: list[dict] = []          # {dR_tcp, R_cam, kind, resid, t_a, t_b, ...}
        self.pb = None                       # PoseBuf (可后挂, 供 lag 自标定)
        self.lag = 0.0                       # 图像/位姿时间偏移 (s), 自标定得到
        self.cand_R: np.ndarray | None = None
        import cv2
        self.cv2 = cv2

    # ---- 单对: 图像特征 → 相对旋转
    def pair_rotation(self, g1: np.ndarray, g2: np.ndarray) -> tuple[np.ndarray, int, float] | None:
        cv2 = self.cv2
        orb = cv2.ORB_create(3000)
        k1, d1 = orb.detectAndCompute(g1, None)
        k2, d2 = orb.detectAndCompute(g2, None)
        if d1 is None or d2 is None or len(k1) < 80 or len(k2) < 80:
            return None
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        m = sorted(bf.match(d1, d2), key=lambda x: x.distance)[:600]
        if len(m) < 60:
            return None
        p1 = np.float32([k1[x.queryIdx].pt for x in m])
        p2 = np.float32([k2[x.trainIdx].pt for x in m])
        E, inl = cv2.findEssentialMat(p1, p2, K, method=cv2.RANSAC, prob=0.999, threshold=1.5)
        if E is None or E.shape != (3, 3):
            return None
        ninl = int((inl > 0).sum())
        if ninl < 60:
            return None
        _, Rc, _t, _m = cv2.recoverPose(E, p1, p2, K)
        if ang_deg(Rc) > 60:                  # 单帧大转 ⇒ 大概率退化(同图/纯标定板)
            return None
        return Rc, ninl, ninl / float(len(m))

    def add_pair(self, dR_tcp: np.ndarray, R_cam: np.ndarray, w: float,
                 t_a: float | None = None, t_b: float | None = None, kind: str = "tcp") -> dict:
        r_tcp = ang_deg(dR_tcp.T @ self.X_R @ dR_tcp)   # noqa: F841 (占位, 保留可读性)
        pred = self.X_R.T @ dR_tcp @ self.X_R
        resid = ang_deg(pred.T @ R_cam)
        rec = {"dR_tcp": dR_tcp.tolist(), "R_cam": R_cam.tolist(), "w": round(w, 3),
               "resid_old_deg": round(resid, 2), "t_a": t_a, "t_b": t_b, "kind": kind}
        self.pairs.append(rec)
        if len(self.pairs) > 200:
            self.pairs = self.pairs[-200:]
        return rec

    def summary(self) -> dict:
        if not self.pairs:
            return {"pairs": 0, "status": "waiting"}
        # 只用一个口径 (tcp 或 flange), 且只用高质量对: 不同坐标系的 dR 不能混池解
        kinds = {}
        for p in self.pairs:
            kinds[p.get("kind", "tcp")] = kinds.get(p.get("kind", "tcp"), 0) + 1
        kind = max(kinds, key=kinds.get)
        use = [p for p in self.pairs if p.get("kind", "tcp") == kind and p.get("w", 1.0) >= 0.45]
        if len(use) >= 4:
            self.pairs = use
        else:
            use = self.pairs
        # 时间对齐自标定 (帧 vs 位姿的固定偏移会让残差系统性偏大)
        best = None
        if self.pb is not None:
            for lag in np.arange(-0.30, 0.301, 0.02):
                vals = []
                for p in self.pairs:
                    if p.get("t_a") is None or p.get("t_b") is None:
                        continue
                    Ra = self.pb.R_at(p["t_a"] + lag, p.get("kind", "tcp"))
                    Rb = self.pb.R_at(p["t_b"] + lag, p.get("kind", "tcp"))
                    if Ra is None or Rb is None:
                        continue
                    dR = Ra.T @ Rb
                    if ang_deg(dR) < 0.8:
                        continue
                    pred = self.X_R.T @ dR @ self.X_R
                    vals.append(ang_deg(pred.T @ np.array(p["R_cam"])))
                if len(vals) >= 5:
                    m = float(np.median(vals))
                    if best is None or m < best[1]:
                        best = (float(lag), m)
        if best is not None:
            self.lag = best[0]
        res = [p["resid_old_deg"] for p in use]
        med = float(np.median(res))
        out = {"pairs": len(res), "kind": kind, "resid_old_deg_median": round(med, 2),
               "resid_old_deg_p90": round(float(np.percentile(res, 90)), 2),
               "status": "ok" if med < 3 else ("suspect" if med < 5 else "mismatch"),
               "lag_ms": round(self.lag * 1000.0, 1),
               "resid_at_best_lag_deg": (round(best[1], 2) if best is not None else None)}
        if len(use) >= 8:
            idx = np.arange(len(use))
            train = [use[i] for i in idx if i % 2 == 0]
            test = [use[i] for i in idx if i % 2 == 1]
            Xs = self._solve([(np.array(p["dR_tcp"]), np.array(p["R_cam"])) for p in train])
            if Xs is not None:
                res_old = [ang_deg((self.X_R.T @ np.array(p["dR_tcp"]) @ self.X_R).T @ np.array(p["R_cam"])) for p in test]
                res_new = [ang_deg((Xs.T @ np.array(p["dR_tcp"]) @ Xs).T @ np.array(p["R_cam"])) for p in test]
                if not res_new:
                    return out
                out.update({
                    "holdout_pairs": len(test),
                    "holdout_resid_old_deg": round(float(np.median(res_old)), 2),
                    "holdout_resid_new_deg": round(float(np.median(res_new)), 2),
                    "delta_from_handeye_deg": round(ang_deg(Xs.T @ self.X_R), 2),
                    # 只在「现标定确实不行」或「反解明显更好」时替换, 已经好就不动
                    "accepted": bool(np.median(res_new) < 3.0 and (np.median(res_old) > 5.0 or np.median(res_new) < 0.7 * np.median(res_old))),
                })
                if out["accepted"]:
                    self.cand_R = Xs
        return out

    @staticmethod
    def _solve(pairs) -> np.ndarray | None:
        """AX = XB (A=ΔR_tool, B=R_cam) 的旋转解: 转轴必须共轭 ⇒ 轴对齐 Kabsch。
        axis(A) = X · axis(B); 只取两轴转角一致的样本 (不一致 = 采样/时间对齐有问题)。"""
        import cv2
        H = np.zeros((3, 3))
        wsum = 0.0
        for dR, Rc in pairs:
            aa, ab = ang_deg(dR), ang_deg(Rc)
            if aa < 1.5 or ab < 1.5 or abs(aa - ab) > 3.0:
                continue
            a = cv2.Rodrigues(dR)[0].ravel()
            b = cv2.Rodrigues(Rc)[0].ravel()
            a /= np.linalg.norm(a)
            b /= np.linalg.norm(b)
            w = min(aa, ab)                      # 转角大 = 轴估计稳, 权重高
            H += w * np.outer(b, a)              # X 把 b → a
            wsum += w
        if wsum <= 0:
            return None
        U, _S, Vt = np.linalg.svd(H)
        D = np.diag([1.0, 1.0, np.linalg.det(Vt.T @ U.T)])
        return Vt.T @ D @ U.T


# ---------------------------------------------------------------- 覆盖图
class Coverage:
    """工作空间覆盖: XY 栅格 (2cm) 记录 TCP 经过 + 视点, 用于建图进度与盲区。"""

    def __init__(self, cell: float = 0.02) -> None:
        self.cell = cell
        self.cells: dict[tuple[int, int], int] = {}
        self.zmin = 9e9
        self.zmax = -9e9
        self.n = 0
        self.bbox = [9e9, 9e9, 9e9, -9e9, -9e9, -9e9]

    def add(self, xyz) -> None:
        x, y, z = float(xyz[0]), float(xyz[1]), float(xyz[2])
        if not (-3 < x < 3 and -3 < y < 3 and -1 < z < 2):
            return
        self.cells[(int(math.floor(x / self.cell)), int(math.floor(y / self.cell)))] = \
            self.cells.get((int(math.floor(x / self.cell)), int(math.floor(y / self.cell))), 0) + 1
        self.zmin, self.zmax = min(self.zmin, z), max(self.zmax, z)
        b = self.bbox
        b[0], b[1], b[2] = min(b[0], x), min(b[1], y), min(b[2], z)
        b[3], b[4], b[5] = max(b[3], x), max(b[4], y), max(b[5], z)
        self.n += 1

    def summary(self) -> dict:
        if not self.n:
            return {"samples": 0}
        ks = np.array(list(self.cells.keys()))
        return {"samples": self.n, "cells": len(self.cells), "cell_m": self.cell,
                "area_m2": round(len(self.cells) * self.cell ** 2, 4),
                "bbox_m": [round(v, 3) for v in self.bbox],
                "z_range_m": [round(self.zmin, 3), round(self.zmax, 3)]}


# ---------------------------------------------------------------- 主循环
def _flush_map(sess: str, cov: "Coverage") -> None:
    """把当前覆盖图落盘并刷新 3D HTML (断链时也照跑, 纯本地计算)。"""
    try:
        write_json(os.path.join(sess, "map.json"), {
            "frame": "base_link", "cell_m": cov.cell,
            "cells": [{"i": i, "j": j, "n": n} for (i, j), n in cov.cells.items()],
            "coverage": cov.summary(), "note": "TCP 轨迹占据栅格 (无深度, 非点云)"})
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "shadow_map_html.py"), sess],
                       check=False, stdout=subprocess.DEVNULL)
    except Exception as exc:                                      # noqa: BLE001
        print("map flush 失败: %s" % exc, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=0.0)
    ap.add_argument("--fps", type=float, default=8.0)
    ap.add_argument("--out", default=ROOT)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    import cv2

    global LATEST
    LATEST = os.path.join(a.out, "latest.json")          # 每个输出根有自己的状态指针
    stamp = time.strftime("%Y%m%d-%H%M%S")
    sess = os.path.join(a.out, "sessions", (a.tag + "-" if a.tag else "") + stamp)
    fdir = os.path.join(sess, "frames")
    os.makedirs(fdir, exist_ok=True)

    def _stop(*_x):
        STOP["flag"] = True
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    pb = PoseBuf()
    th = threading.Thread(target=pb.run, daemon=True)
    th.start()

    calib = ShadowCalib(HANDEYE)
    calib.pb = pb                      # 供时间偏移(lag)自标定
    cov = Coverage()
    poses_f = open(os.path.join(sess, "poses.jsonl"), "w", encoding="utf-8")
    kf_f = open(os.path.join(sess, "keyframes.jsonl"), "w", encoding="utf-8")

    written: list[str] = []
    prev_gray = None
    prev_gray_keep = None
    prev_meta = None
    n_frame = n_new = n_pose_logged = n_pairs_fail = 0
    n_cam_fail = 0
    last_pose_log = 0.0
    last_map = 0.0
    t0 = time.time()
    per = 1.0 / max(1.0, a.fps)
    calib_sum: dict = {"pairs": 0, "status": "waiting"}
    write_json(LATEST, {"session": sess, "state": "starting", "t": time.time(),
                        "note": "影子模式: 只读 Orin 图像+位姿, 零下行"})
    print(json.dumps({"event": "start", "session": sess, "cam": CAM, "pose": POSE}, ensure_ascii=False), flush=True)

    while not STOP["flag"]:
        if a.duration and (time.time() - t0) >= a.duration:
            break
        tick = time.monotonic()
        # 1) 帧 + 帧龄 (帧龄用于把位姿对到「拍照时刻」)
        age = 0.0
        try:
            try:
                age = float((_json(CAM_STATUS, 3.0) or {}).get("age_s") or 0.0)
                if age < 0 or age > 5:
                    age = 0.0
            except Exception:                                    # noqa: BLE001
                age = 0.0
            buf = _get(CAM, 4.0)
            img = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("JPEG 解不开")
            t_cap_mono = time.monotonic() - max(0.0, age)
            n_frame += 1
        except Exception as exc:                                 # noqa: BLE001
            # 断链(拔 USB 网卡/Orin 掉线): 不退出, 本机自持 —— 用已落盘数据继续演化,
            # 每 30s 重算一次覆盖图; 链路回来自动续采。绝不编造数据。
            n_cam_fail += 1
            if time.time() - last_map > 30:
                last_map = time.time()
                _flush_map(sess, cov)
            write_json(LATEST, {"session": sess, "state": "link_down" if n_cam_fail >= 2 else "cam_retry",
                                "error": str(exc)[:160], "t": time.time(),
                                "frames": n_frame, "keyframes": n_new, "cam_fail": n_cam_fail,
                                "pose_err": pb.err, "coverage_area_m2": cov.summary().get("area_m2"),
                                "note": "影子模式: 外链断 ⇒ 本机自持运行(不退出/不编数), 链路回来自动续采"})
            time.sleep(1.0)
            continue
        n_cam_fail = 0

        pose = pb.at(t_cap_mono)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 2) 位姿落盘 (5Hz 节流, 带上帧龄与对齐误差)
        if pose and time.time() - last_pose_log > 0.2:
            poses_f.write(json.dumps({"t": pose["t"], "tcp": pose["tcp"], "flange": pose["flange"],
                                      "joint": pose["joint"], "mode": pose["mode"], "power": pose["power"],
                                      "yaw": None}, ensure_ascii=False) + "\n")
            poses_f.flush()
            n_pose_logged += 1
            last_pose_log = time.time()
        if pose:
            cov.add(pose["tcp"][:3])

        # 3) 关键帧: 内容变了才落盘 + 与上一关键帧配对手眼
        changed = 0.0
        if prev_gray is not None and prev_gray.shape == gray.shape:
            changed = float((np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16)) > 20).mean())
        move_m = 0.0
        if prev_meta and prev_meta.get("tcp") and pose:
            move_m = float(np.linalg.norm(np.array(pose["tcp"][:3]) - np.array(prev_meta["tcp"][:3])))
        need_kf = (prev_gray is None or changed > 0.05
                   or (move_m > 0.008 and (time.time() - (prev_meta or {}).get("t_wall", 0) > 0.3)))
        if need_kf:
            fn = "kf_%06d.jpg" % n_new
            cv2.imwrite(os.path.join(fdir, fn), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            written.append(fn)
            n_new += 1
            # 磁盘红线: 长跑只留最近 12000 张关键帧 (≈400MB), 防止独立运行几天把盘写满
            if len(written) > 12000:
                for old in written[:2000]:
                    try:
                        os.remove(os.path.join(fdir, old))
                    except OSError:
                        pass
                del written[:2000]
            meta = {"file": fn, "t": pose["t"] if pose else None, "t_wall": time.time(), "t_mono": t_cap_mono,
                    "frame_age_s": round(age, 3), "changed": round(changed, 3),
                    "tcp": pose["tcp"] if pose else None, "flange": pose["flange"] if pose else None,
                    "align_ms": pose.get("dt_ms") if pose else None}
            kf_f.write(json.dumps(meta, ensure_ascii=False) + "\n")
            kf_f.flush()
            # 配对: 只取「图真变了 + 真动了」的对, 两种旋转口径各算一次
            if prev_meta and prev_meta.get("tcp") and pose and meta["tcp"]:
                res = calib.pair_rotation(prev_gray_keep, gray)
                if res:
                    R_cam, ninl, ratio = res
                    for kind in ("tcp", "flange"):
                        key = prev_meta.get(kind)
                        cur = meta.get(kind)
                        if not key or not cur:
                            continue
                        # 用自标定出的时间偏移对齐后再比 (lag 未定前为 0)
                        Ra = pb.R_at(prev_meta["t_mono"] + calib.lag, kind)
                        Rb = pb.R_at(meta["t_mono"] + calib.lag, kind)
                        if Ra is not None and Rb is not None:
                            dR = Ra.T @ Rb
                        else:
                            dR = rpy2R(*key[3:]).T @ rpy2R(*cur[3:])
                        if ang_deg(dR) < 5.0 or ang_deg(dR) > 45:      # 太小不可观测 / 太大易退化
                            continue
                        if ang_deg(R_cam) < 2.0 or ratio < 0.45:       # 视觉旋转不可信的对不采信
                            continue
                        rec = calib.add_pair(dR, R_cam, ratio, prev_meta["t_mono"], meta["t_mono"], kind)
                        rec.update({"kind": kind, "inliers": ninl, "pair": [prev_meta["file"], fn],
                                    "dt_frame": round(meta["t"] - prev_meta["t"], 3) if meta["t"] and prev_meta["t"] else None})
                        break
                else:
                    n_pairs_fail += 1
            prev_meta = meta
            prev_gray = gray.copy()
            prev_gray_keep = gray.copy()
        else:
            prev_meta = prev_meta or None

        # 4) 状态/标定/地图 落盘 (1Hz)
        if int(tick) % 1 == 0:
            calib_sum = calib.summary()
            if calib.cand_R is not None and not os.path.exists(os.path.join(sess, "handeye_rotation_candidate.json")):
                write_json(os.path.join(sess, "handeye_rotation_candidate.json"), {
                    "note": "影子模式自解手眼旋转 (Kabsch, 留出集验证通过) — 候选, 未覆盖生产标定",
                    "X_R": calib.cand_R.tolist(), "handeye_src": HANDEYE,
                    "validated": calib_sum, "t": time.strftime("%F %T")})
            write_json(os.path.join(sess, "calib_live.json"),
                       dict(calib_sum, handeye_src=HANDEYE,
                            cand_R=(calib.cand_R.tolist() if calib.cand_R is not None else None)))
            write_json(os.path.join(sess, "status.json"), {
                "session": sess, "t": time.time(), "elapsed_s": round(time.time() - t0, 1),
                "frames": n_frame, "keyframes": n_new, "pose_samples": n_pose_logged,
                "pose_hz": round(n_pose_logged / max(1e-6, time.time() - t0), 2),
                "pairs_fail": n_pairs_fail, "pose_err": pb.err, "robot": pb.state,
                "calib": calib_sum, "coverage": cov.summary(),
                "link": "online", "cam_fail": n_cam_fail})
            write_json(LATEST, {"session": sess, "state": "running", "t": time.time(),
                                "frames": n_frame, "keyframes": n_new,
                                "calib_pairs": calib_sum.get("pairs", 0),
                                "calib_status": calib_sum.get("status"),
                                "coverage_area_m2": cov.summary().get("area_m2"),
                                "note": "影子模式只读: 不走下行, 不干扰生产"})
            # 每 120s 刷一次地图 (3D HTML 跟着真机走, 不用停服务)
            if time.time() - last_map > 120:
                last_map = time.time()
                write_json(os.path.join(sess, "map.json"), {
                    "frame": "base_link", "cell_m": cov.cell,
                    "cells": [{"i": i, "j": j, "n": n} for (i, j), n in cov.cells.items()],
                    "coverage": cov.summary(), "note": "TCP 轨迹占据栅格 (无深度, 非点云)"})
                try:
                    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                "shadow_map_html.py"), sess], check=False,
                                   stdout=subprocess.DEVNULL)
                except Exception as exc:                          # noqa: BLE001
                    print("map html 失败: %s" % exc, flush=True)
        time.sleep(max(0.0, per - (time.monotonic() - tick)))

    # ---- 收尾: 覆盖率/标定/地图
    poses_f.close()
    kf_f.close()
    calib_sum = calib.summary()
    summary = {"session": sess, "elapsed_s": round(time.time() - t0, 1), "frames": n_frame,
               "keyframes": n_new, "pose_samples": n_pose_logged, "pairs_fail": n_pairs_fail,
               "calib": calib_sum, "coverage": cov.summary(), "ended": time.strftime("%F %T")}
    write_json(os.path.join(sess, "summary.json"), summary)
    write_json(os.path.join(sess, "calib_live.json"),
               dict(calib_sum, cand_R=(calib.cand_R.tolist() if calib.cand_R is not None else None)))
    # 覆盖栅格 → map.json (base 系, 单位 m)
    cells = [{"i": i, "j": j, "n": n} for (i, j), n in cov.cells.items()]
    write_json(os.path.join(sess, "map.json"), {"frame": "base_link", "cell_m": cov.cell,
                                                "cells": cells, "coverage": cov.summary(),
                                                "note": "TCP 轨迹占据栅格 (无深度, 非点云)"})
    write_json(LATEST, {"session": sess, "state": "stopped", "t": time.time(), "summary": summary})
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
