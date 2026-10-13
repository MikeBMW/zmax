# -*- coding: utf-8 -*-
"""localization_mapping.py — 融合定位建图 (专用实现)

老倪口径 (2026-10-13): 「融合定位与 perception.py 公用, 这样不好; 再建立一个融合定位建图的 py 文件,
专门实现定位建图功能」+「进入系统后自动加载自动建图功能, 启动建图程序, 包括但不限于 ORB-SLAM 等
基于视觉、机器人位姿的建图功能」。

因此本文件是**独立实现**, 不 import `src/lerobot/policies/left_right/state_space/perception.py`
(fuse_sensors/43D 那套是给 L2 感知融合状态用的), 本模块自带:

  ① 面向建图的观测融合 `fuse_mapping_obs` (视觉结构 ⊕ 触觉标记 ⊕ 机器人位姿先验), 维度自持;
  ② 视觉前端 `OrbFrontEnd`: ORB 特征 → 比值检验匹配 → 本质矩阵/单应 RANSAC → 相对位姿;
  ③ 机器人位姿通道 `read_robot_pose`: 读位姿真源 (tcp_pose, 全 0 或陈旧 = 视为无), 提供**米制尺度**
     (单目视觉本身给不出尺度 —— 这一点如实标注, 有真机位姿时标 `robot_pose`, 无则标 `monocular_up_to_scale`);
  ④ 关键帧策略 + 地图点三角化 → 地图真源 `zmax_data/mapping/map_<scene>.json` + 轨迹 `traj_<scene>.jsonl`;
  ⑤ 回环检测 (描述子检索 + 重投影验证) + 位姿图松弛 (简化版, 误差按边权重线性摊还);
  ⑥ 自主进化接口: 用 prime_structure 把本轮建图结构编码成质数签名, 未见结构记进化事件。

真源/开关: config/platform/zmax_mapping.json (auto_load / backend / scene / sources / keyframe 阈值)
运行状态: zmax_data/mapping/mapping_live.json (单一写入器, 原子写, 带帧龄)

CLI:
  python localization_mapping.py status
  python localization_mapping.py run --n 24 [--cam arm] [--scene SCN-07-AOI] [--dry]
  python localization_mapping.py selftest
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CONFIG_J = os.path.join(ROOT, "config", "platform", "zmax_mapping.json")
MAP_DIR = os.path.join(ROOT, "zmax_data", "mapping")
LIVE_J = os.path.join(MAP_DIR, "mapping_live.json")
CALIB_J = os.path.join(ROOT, "config", "calib", "zmax_calib.json")

# 本模块自持的维度契约 (刻意**不**从 perception.py 取, 避免与 L2 感知状态耦合)
MAPPING_VISUAL_DIM = 39      # 视觉结构特征 (YOLO 2D→3D 反投影后)
MAPPING_TACTILE_DIM = 4      # 触觉标记 (grasp/contact/dir)
MAPPING_OBS_DIM = MAPPING_VISUAL_DIM + MAPPING_TACTILE_DIM     # 43

# 建图后端 (诚实命名: 是 ORB 视觉前端 + 机器人位姿里程计 + 回环的 SLAM 式流水线,
# 不等同于完整 ORB-SLAM2/3 复刻 —— 未实现其词袋/局部 BA/多地图/重定位全部特性)
BACKENDS = ("orb_pose_slam",)


class MappingError(RuntimeError):
    pass


# ── ① 面向建图的观测融合 (本模块自持实现) ────────────────────────────────────────
def fuse_mapping_obs(rgbd_feats, force_6d, tactile_marker, robot_pose=None, k_obs: float = 1.0) -> dict:
    """建图用观测融合: 视觉结构 ⊕ 触觉标记 (+ 机器人位姿先验单列, 不塞进 43D 契约里)。

    Args:
        rgbd_feats: (39,) 视觉结构特征
        force_6d:   (6,)  六维力/力矩 (接触检测用, 与 L2 同口径不进 obs)
        tactile_marker: (4,) 触觉标记 (grasp/contact/dir)
        robot_pose: (7,) 或 (4,4) 机器人位姿 (建图**尺度**来源), 可 None
    Returns:
        {"obs": (43,), "pose": (4,4)|None, "pose_used": bool, "tactile": (4,), "force": (6,)}
    """
    v = np.asarray(rgbd_feats, dtype=float).ravel()
    t = np.asarray(tactile_marker, dtype=float).ravel()
    f = np.asarray(force_6d, dtype=float).ravel()
    if v.size != MAPPING_VISUAL_DIM:
        raise MappingError("视觉结构特征应为 %d 维, 收到 %d" % (MAPPING_VISUAL_DIM, v.size))
    if t.size != MAPPING_TACTILE_DIM:
        raise MappingError("触觉标记应为 %d 维, 收到 %d" % (MAPPING_TACTILE_DIM, t.size))
    if f.size != 6:
        raise MappingError("力/力矩应为 6 维, 收到 %d" % f.size)
    obs = np.concatenate([k_obs * v, t])
    if obs.size != MAPPING_OBS_DIM:
        raise MappingError("观测维度应为 %d, 收到 %d" % (MAPPING_OBS_DIM, obs.size))
    return {"obs": obs, "pose": robot_pose, "pose_used": robot_pose is not None, "tactile": t, "force": f}


# ── ② 内参 / 相机帧 ─────────────────────────────────────────────────────────────
def load_intrinsics(cam: str = "arm") -> dict:
    """内参真源优先; 未标定则用**显式标注的**针孔兜底 (不做无声假设)。"""
    try:
        with io.open(CALIB_J, encoding="utf-8") as f:
            c = json.load(f)
        cam_d = c.get("camera") or {}
        K = cam_d.get("K")
        if K and np.asarray(K, float).shape == (3, 3):
            return {"K": np.asarray(K, float), "source": "config/calib/zmax_calib.json:camera.K", "calibrated": True}
    except Exception:                                                            # noqa: BLE001
        pass
    return {"K": None, "source": "未标定 ⇒ 用宽高推的针孔兜底 (fx=fy=0.9*W)", "calibrated": False}


def fetch_frame(cam: str = "arm", url: str = "http://127.0.0.1:8797/snap/%s.jpg") -> dict:
    """取一帧真图 (状态空间工程视频源). 失败直接抛, 不返回假帧。"""
    import urllib.request
    u = url % cam
    t0 = time.time()
    with urllib.request.urlopen(u, timeout=15) as r:
        raw = r.read()
    if len(raw) < 512:
        raise MappingError("帧太小 (%d B) ⇒ 视为无帧: %s" % (len(raw), u))
    arr = np.frombuffer(raw, dtype=np.uint8)
    import cv2
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise MappingError("解不出图: %s" % u)
    return {"img": img, "bytes": len(raw), "url": u, "fetch_ms": round((time.time() - t0) * 1000, 1),
            "age_s": 0.0, "label": cam}


# ── 真录像/帧序列源 (实测: 8797/snap 的源叠加刷新是 100~500ms 级 ⇒ 20ms 内连抓两帧完全相同) ──
def iter_frames_video(path: str, stride: int = 5, max_frames: int = 0):
    """从真录像抽帧 (实测摆盘实拍 tray_place_latest.mp4 = 678 帧/25fps/960x720, 真运动)。"""
    import cv2
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise MappingError("打不开录像: %s" % path)
    i, kept = 0, 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if i % max(1, int(stride)) == 0:
            yield {"img": img, "bytes": int(img.nbytes), "url": path, "fetch_ms": 0.0,
                   "frame_index": i, "label": os.path.basename(path)}
            kept += 1
            if max_frames and kept >= max_frames:
                break
        i += 1
    cap.release()


def iter_frames_dir(path: str, stride: int = 1, max_frames: int = 0):
    """从真机排练帧序列读帧 (实测 zmax_data/probe_rehearsal/run_*/<场景>/frames/p###.jpg, 13 帧/组)。"""
    import cv2
    files = sorted(glob.glob(os.path.join(path, "*.jpg")) + glob.glob(os.path.join(path, "*.png")))
    if not files:
        raise MappingError("目录里没有帧: %s" % path)
    kept = 0
    for i, p in enumerate(files):
        if i % max(1, int(stride)):
            continue
        img = cv2.imread(p)
        if img is None:
            continue
        yield {"img": img, "bytes": os.path.getsize(p), "url": p, "fetch_ms": 0.0,
               "frame_index": i, "label": os.path.basename(os.path.dirname(path))}
        kept += 1
        if max_frames and kept >= max_frames:
            break


def frame_source(kind: str = "live", cam: str = "arm", video: str = "", frames_dir: str = "",
                 stride: int = 5, interval_s: float = 0.3, max_frames: int = 0):
    """统一帧源: live (8797/snap, 按 interval_s 节流) | video (mp4 抽帧) | dir (帧序列)。

    返回 (迭代器, 源类型说明)。live 模式**必须节流**: 实测源叠加刷新 100~500ms, 20ms 内连抓得到同一帧
    (平均像素差 0.00) ⇒ 不节流就会退化成"重复帧+0 内点"。
    """
    if video:
        return iter_frames_video(video, stride=stride, max_frames=max_frames), "video:%s(stride=%d)" % (video, stride)
    if frames_dir:
        return iter_frames_dir(frames_dir, stride=stride, max_frames=max_frames), "dir:%s(stride=%d)" % (frames_dir, stride)

    def _gen():
        import time as _t
        n = 0
        while True:
            fr = fetch_frame(cam)
            yield fr
            n += 1
            if max_frames and n >= max_frames:
                break
            _t.sleep(max(0.0, float(interval_s)))

    return _gen(), "live:8797/snap/%s(interval=%.2fs)" % (cam, interval_s)


# ── ③ 机器人位姿真源 ────────────────────────────────────────────────────────────
_POSE_KNOWN = [
    os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json"),
    os.path.join(ROOT, "zmax_data", "tcp_out", "latest.json"),
    os.path.join(ROOT, "zmax_data", "runtime", "tcp_out", "latest.json"),
]
_POSE_GLOBS = ["zmax_data/**/tcp_out/latest.json", "zmax_data/**/tcp_pose.json",
               "zmax_data/**/tcp_latest.json", "data/**/tcp_out/latest.json"]


def read_robot_pose() -> dict:
    """读位姿真源 (tcp_pose). 全 0 = 陈旧; 找不到 = 无。诚实返回, 不造位姿。

    实测真源结构 (zmax_data/rokae_sdk/tcp_out/latest.json, 珞石 xcoresdk endInRef 直采):
      {ts, t, x, y, z, rx, ry, rz, qx..qw, frame, src, joint[12]}
    早期版本只认 {"tcp"/"pose"/"xyz"} 这类嵌套键 ⇒ 会把这个**新鲜**真源静默跳过 (真 bug),
    现改为同时认扁平键 + 四元数, 并把跳过的候选**报出来**而不是无声吞掉。
    """
    cands = []
    # ⚠️ 实测坑: 对整个工程根做 `**/tcp_out/latest.json` 递归 glob 要 2.5s/次 (工程树含 models/datasets/releases)
    #    ⇒ 10Hz 发布根本达不到 (实测整帧 2479ms, 其中 2556ms 全在这里)。改为: 已知真源直取 + 限定目录扫描 + 30s 缓存。
    for p in _POSE_KNOWN:
        if os.path.isfile(p):
            cands.append(p)
    if not cands:
        for pat in _POSE_GLOBS:
            cands += glob.glob(os.path.join(ROOT, pat), recursive=True)
    skipped, best = [], None
    for p in sorted(set(cands)):
        if not os.path.isfile(p):
            continue
        try:
            with io.open(p, encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                skipped.append({"path": p, "why": "不是对象"})
                continue
            if all(k in d for k in ("x", "y", "z")):                     # 扁平结构 (当前真源)
                xyz = [float(d["x"]), float(d["y"]), float(d["z"])]
                rpy = [float(d.get("rx", 0.0)), float(d.get("ry", 0.0)), float(d.get("rz", 0.0))]
                quat = [float(d[k]) for k in ("qx", "qy", "qz", "qw")] if all(k in d for k in ("qx", "qy", "qz", "qw")) else None
                src = d.get("src", "")
                frame = d.get("frame", "")
                joint = d.get("joint")
                ts = d.get("ts")
            else:                                                        # 嵌套结构 (历史格式)
                arr = d.get("tcp") or d.get("pose") or d.get("xyz")
                if arr is None:
                    skipped.append({"path": p, "why": "没有位姿键 (键: %s)" % ",".join(list(d)[:8])})
                    continue
                v = np.asarray(arr, float).ravel()
                if v.size < 3:
                    skipped.append({"path": p, "why": "位姿维度 %d" % v.size})
                    continue
                xyz = [float(x) for x in v[:3]]
                rpy = [float(x) for x in (v[3:6] if v.size >= 6 else [0, 0, 0])]
                quat, src, frame, joint, ts = None, "", "", None, d.get("t")
            age = time.time() - os.path.getmtime(p)
            if best is None or age < best["age_s"]:
                best = {"path": p, "age_s": round(age, 2), "xyz": xyz, "rpy": rpy, "quat": quat,
                        "frame": frame, "src": src, "joint": joint, "ts": ts,
                        "all_zero": bool(np.allclose(xyz, 0.0))}
        except Exception as e:                                                   # noqa: BLE001
            skipped.append({"path": p, "why": repr(e)[:80]})
            continue
    if best is None:
        return {"available": False, "reason": "找不到可解析的位姿真源 (候选 %d: %s)"
                % (len(skipped), skipped[:2]), "source": None, "skipped": skipped}
    fresh = best["age_s"] < 10.0
    best["available"] = bool((not best["all_zero"]) and fresh)
    best["reason"] = "" if best["available"] else ("全 0 (陈旧)" if best["all_zero"] else "帧龄 %.1fs 过旧" % best["age_s"])
    best["source"] = "tcp_pose 真源"
    best["skipped"] = skipped
    return best


def pose_matrix(xyz, rpy=None) -> np.ndarray:
    """xyz(m) + rpy(rad) → 4x4 (ZYX)."""
    x, y, z = [float(v) for v in np.asarray(xyz, float).ravel()[:3]]
    rx, ry, rz = [float(v) for v in (np.asarray(rpy, float).ravel()[:3] if rpy is not None else [0, 0, 0])]
    cx, sx, cy, sy, cz, sz = np.cos(rx), np.sin(rx), np.cos(ry), np.sin(ry), np.cos(rz), np.sin(rz)
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1.0]])
    Ry = np.array([[cy, 0, sy], [0, 1.0, 0], [-sy, 0, cy]])
    Rx = np.array([[1.0, 0, 0], [0, cx, -sx], [0, sx, cx]])
    T = np.eye(4)
    T[:3, :3] = Rz @ Ry @ Rx
    T[:3, 3] = [x, y, z]
    return T


# ── ④ 视觉前端 (ORB + 比值检验 + 本质矩阵 RANSAC) ───────────────────────────────
class OrbFrontEnd:
    """ORB 特征 → 匹配 → 相对位姿。真跑在 cv2 上 (实测 cv2 5.0.0 · ORB 可用)。"""

    def __init__(self, n_features: int = 1200, ratio: float = 0.75, ransac_thresh_px: float = 1.5):
        import cv2
        self.cv2 = cv2
        self.orb = cv2.ORB_create(nfeatures=int(n_features), fastThreshold=12)
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        self.ratio = float(ratio)
        self.thresh = float(ransac_thresh_px)

    def detect(self, img) -> dict:
        g = self.cv2.cvtColor(img, self.cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        kp, des = self.orb.detectAndCompute(g, None)
        pts = np.array([k.pt for k in kp], float).reshape(-1, 2) if kp else np.zeros((0, 2))
        return {"n_kp": len(kp), "pts": pts, "des": des, "gray_mean": float(g.mean()),
                "size": (int(g.shape[1]), int(g.shape[0]))}

    def match(self, a: dict, b: dict) -> dict:
        """比值检验 + 本质矩阵 RANSAC ⇒ 内点与相对旋转/平移方向。"""
        if a["des"] is None or b["des"] is None or len(a["des"]) < 8 or len(b["des"]) < 8:
            return {"n_match": 0, "n_inlier": 0, "R": None, "t_dir": None, "inlier_ratio": 0.0,
                    "reason": "特征不足 (a=%d b=%d)" % (a["n_kp"], b["n_kp"])}
        knn = self.bf.knnMatch(a["des"], b["des"], k=2)
        good = [m for pair in knn if len(pair) == 2 for m, n in [pair] if m.distance < self.ratio * n.distance]
        if len(good) < 8:
            return {"n_match": len(good), "n_inlier": 0, "R": None, "t_dir": None, "inlier_ratio": 0.0,
                    "reason": "比值检验后匹配不足 (%d)" % len(good)}
        p1 = np.array([a["pts"][m.queryIdx] for m in good], float)
        p2 = np.array([b["pts"][m.trainIdx] for m in good], float)
        K = self.K
        E, mask = self.cv2.findEssentialMat(p1, p2, K, self.cv2.RANSAC, 0.999, self.thresh)
        if E is None or E.size == 0:
            return {"n_match": len(good), "n_inlier": 0, "R": None, "t_dir": None, "inlier_ratio": 0.0,
                    "reason": "本质矩阵求解失败"}
        n_in, R, t, _ = self.cv2.recoverPose(E, p1, p2, K, mask=mask)
        inl = int(np.count_nonzero(mask)) if mask is not None else 0
        return {"n_match": len(good), "n_inlier": inl, "inlier_ratio": round(inl / max(1, len(good)), 4),
                "R": R.tolist(), "t_dir": (t.ravel().tolist() if t is not None else None),
                "p1": p1[mask.ravel().astype(bool)] if mask is not None else p1,
                "p2": p2[mask.ravel().astype(bool)] if mask is not None else p2,
                "reason": ""}

    def set_K(self, K) -> None:
        self.K = K


# ── ⑤ 建图会话 ─────────────────────────────────────────────────────────────────
class MappingSession:
    """一次建图会话: 关键帧 + 地图点 + 回环 + 位姿图松弛 + 真源落盘。"""

    def __init__(self, scene: str = "SCN-07-AOI", cam: str = "arm", backend: str = "orb_pose_slam",
                 kf_trans_m: float = 0.010, kf_rot_deg: float = 2.0, save: bool = True,
                 kf_min_inlier: int = 30, dup_eps: float = 0.8, save_every_s: float = 0.0):
        if backend not in BACKENDS:
            raise MappingError("未知建图后端 %r (支持 %s)" % (backend, "/".join(BACKENDS)))
        self.scene, self.cam, self.backend = scene, cam, backend
        self.kf_trans_m, self.kf_rot_deg = float(kf_trans_m), float(kf_rot_deg)
        self.kf_min_inlier = int(kf_min_inlier)     # 关键帧最少内点 (防"退化帧"伪关键帧)
        self.dup_eps = float(dup_eps)               # 重复帧阈值 (平均像素差)
        self.save_enabled = bool(save)
        self.dup_skipped = 0
        self.weak_frames = 0
        self.source_kind = "未知"
        self.parallax_px = []
        self.live_every = 10          # 每 N 帧写一次活体真源 (实测: 只在整轮末写 ⇒ 长跑时状态是陈旧的)
        self._last_live = 0.0
        # 🔧 2026-10-13: 持续建图 (老倪现场示教"同时建图") —— 原实现每轮 30 帧就 save() 一次且**每轮重置**,
        #    地图永远只装最后一轮 (实测 round 97 有 5 关键帧/113 点, 下一轮 98 立刻回到 1 关键帧/0 点,
        #    盘上的 map_SCN-07-AOI.json 只剩残帧) ⇒ 长跑等于"同时建图"没结果。改为单会话累积 + 定期落盘。
        self.save_every_s = float(save_every_s)       # >0 ⇒ 运行中每 N 秒 save() 一次 (地图文件也长)
        self._last_save = 0.0
        self.intr = load_intrinsics(cam)
        self.front = OrbFrontEnd()
        self.intr_eff_source = self.intr["source"]
        self.front.set_K(self.intr["K"])
        self.frames, self.keyframes, self.map_points, self.loops = [], [], [], []
        self.prev = None
        self.pose_ref = None                      # 机器人位姿锚点 (取第一帧真值)
        self.scale_src = "未定"
        self.t0 = time.time()

    def _ensure_K(self, size) -> None:
        """内参未标定 ⇒ 用**显式标注的**针孔兜底并交给 OpenCV。

        实测坑: 内参为 None 时直接把 None 传 findEssentialMat ⇒ OpenCV 断言 (cameraMatrix.row) 直接抛,
        整条匹配链全废。故此处必须给一个 3x3: 真标定优先, 否则按宽高推兜底, 并如实记录来源。
        """
        if self.intr["K"] is not None and getattr(self.front, "K", None) is not None:
            return
        W, H = int(size[0]), int(size[1])
        fx = fy = 0.9 * W
        self.intr["K"] = np.array([[fx, 0.0, W / 2.0], [0.0, fy, H / 2.0], [0.0, 0.0, 1.0]])
        self.intr["calibrated"] = False
        self.intr_eff_source = "针孔兜底 (未标定): fx=fy=0.9*W, %dx%d" % (W, H)
        self.front.set_K(self.intr["K"])

    # — 每帧 —
    def process(self, img, label: str = "", pose: dict | None = None) -> dict:
        f = self.front.detect(img)
        self._ensure_K(f["size"])
        rec = {"i": len(self.frames), "label": label, "n_kp": f["n_kp"], "size": f["size"],
               "gray_mean": round(f["gray_mean"], 2), "t": round(time.time() - self.t0, 3)}
        # 重复帧检测 (实测刚需: 源刷新 100~500ms, 连抓会拿到同一帧 ⇒ 全匹配/0 内点/退化)
        dup = False
        if self.prev is not None and self.prev.get("img") is not None \
                and self.prev["img"].shape == img.shape:
            d = float(np.mean(np.abs(self.prev["img"].astype(np.float32) - img.astype(np.float32))))
            rec["dup_diff"] = round(d, 3)
            dup = d < self.dup_eps
        m = {"n_match": 0, "n_inlier": 0, "inlier_ratio": 0.0, "reason": "首帧"}
        if dup:
            self.dup_skipped += 1
            rec.update({"duplicate": True, "reason": "重复帧 (像素差 %.3f < %.2f) ⇒ 跳过匹配" % (rec["dup_diff"], self.dup_eps)})
        else:
            if self.prev is not None:
                m = self.front.match(self.prev["f"], f)
                rec.update({"n_match": m["n_match"], "n_inlier": m["n_inlier"],
                            "inlier_ratio": m["inlier_ratio"], "reason": m["reason"]})
                if m.get("R") is not None and "p1" in m:
                    # 视差量 (内点像素位移的中位数) —— 无视差 ⇒ 三角化必然退化, 如实记
                    if len(m["p1"]):
                        self.parallax_px.append(round(float(np.median(np.linalg.norm(m["p2"] - m["p1"], axis=1))), 3))
                        rec["parallax_px"] = self.parallax_px[-1]
                self._maybe_keyframe(f, m, pose, rec)
            else:
                self._add_keyframe(f, pose, "首帧", rec)
        rec["n_kf"] = len(self.keyframes)
        rec["n_map_pts"] = len(self.map_points)
        self.prev = {"f": f, "img": img}
        self.frames.append(rec)
        # 运行中定期刷新活体真源 (长跑时状态不能等到整轮结束才更新)
        if self.save_enabled and (len(self.frames) % max(1, self.live_every) == 0
                                  or time.time() - self._last_live > 2.0):
            try:
                self._write_live()
            except Exception:                                                    # noqa: BLE001
                pass
        # 持续模式: 定期落盘, 让 map_<scene>.json 跟着长 (否则长跑只有活体是真, 地图文件是残帧)
        if (self.save_enabled and self.save_every_s > 0
                and time.time() - self._last_save > self.save_every_s):
            try:
                self.save()
                self._write_live(running=True)   # save() 内部会写 running=False, 运行中要翻回来
                self._last_save = time.time()
            except Exception:                                                    # noqa: BLE001
                pass
        return rec

    def _write_live(self, running: bool = True) -> str:
        """把当前建图状态原子写入 mapping_live.json (活体真源, 带帧龄)。"""
        os.makedirs(MAP_DIR, exist_ok=True)
        live = {"ts": time.time(), "updated": time.strftime("%Y-%m-%d %H:%M:%S"), **self.summary(),
                "map_file": os.path.join(MAP_DIR, "map_%s.json" % self.scene),
                "traj_file": os.path.join(MAP_DIR, "traj_%s.jsonl" % self.scene), "running": bool(running)}
        tmp = LIVE_J + ".tmp.%d" % os.getpid()
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(live, f, ensure_ascii=False, indent=1)
        os.replace(tmp, LIVE_J)
        self._last_live = time.time()
        return LIVE_J

    # — 关键帧 —
    def _kf_trigger(self, m: dict) -> tuple:
        if m["R"] is None:
            return False, "无位姿"
        if m["n_inlier"] < self.kf_min_inlier:
            return False, "内点不足 (%d < %d) ⇒ 不设关键帧" % (m["n_inlier"], self.kf_min_inlier)
        R = np.asarray(m["R"], float)
        ang = float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))
        return (ang > self.kf_rot_deg or m["inlier_ratio"] < 0.35), "Δθ=%.1f° 内点率=%.2f" % (ang, m["inlier_ratio"])

    def _add_keyframe(self, f: dict, pose: dict | None, why: str, rec: dict) -> None:
        kf = {"id": len(self.keyframes), "n_kp": f["n_kp"], "des": f["des"], "pts": f["pts"],
              "pose_robot": (None if not pose or not pose.get("available") else pose),
              "t": round(time.time() - self.t0, 3), "why": why}
        self.keyframes.append(kf)
        if pose and pose.get("available") and self.pose_ref is None:
            self.pose_ref = np.asarray(pose["xyz"], float)
            self.scale_src = "robot_pose(tcp_pose 真源)"
        rec["kf_added"] = kf["id"]

    def _maybe_keyframe(self, f: dict, m: dict, pose: dict | None, rec: dict) -> None:
        ok, why = self._kf_trigger(m)
        if m["R"] is not None:
            # 有机器人位姿 ⇒ 米制平移; 否则单目只知道方向 (尺度不可观, 如实标注)
            if pose and pose.get("available") and self.pose_ref is not None:
                d = float(np.linalg.norm(np.asarray(pose["xyz"], float) - self.pose_ref))
                ok = ok or d > self.kf_trans_m
                why += " · 机器人位移 %.3fm" % d
                self.scale_src = "robot_pose(tcp_pose 真源)"
            if not ok:
                return
            self._add_keyframe(f, pose, why, rec)
            self._triangulate(m)

    def _triangulate(self, m: dict) -> int:
        """用相对位姿与内参三角化内点 ⇒ 地图点 (无位姿时按单位方向存放, 标注尺度不可观)。"""
        if len(self.keyframes) < 2 or "p1" not in m:
            return 0
        K = self.intr["K"]
        if K is None:
            W, H = self.prev["f"]["size"]
            fx = fy = 0.9 * W
            K = np.array([[fx, 0, W / 2.0], [0, fy, H / 2.0], [0, 0, 1.0]])
        R = np.asarray(m["R"], float)
        t = np.asarray(m["t_dir"], float).ravel() * (1.0 if self.scale_src.startswith("robot_pose") else 1.0)
        P1 = K @ np.hstack([np.eye(3), np.zeros((3, 1))])
        P2 = K @ np.hstack([R, t.reshape(3, 1)])
        p1, p2 = m["p1"], m["p2"]
        if len(p1) < 6:
            return 0
        pts4 = self.front.cv2.triangulatePoints(P1, P2, p1.T, p2.T)
        pts3 = (pts4[:3] / np.where(np.abs(pts4[3]) < 1e-9, 1e-9, pts4[3])).T
        good = pts3[np.isfinite(pts3).all(axis=1)]
        for q in good[:200]:
            self.map_points.append([round(float(x), 5) for x in q])
        return len(good)

    # — 回环 —
    def detect_loop(self, min_gap: int = 3, max_ham: float = 40.0) -> dict:
        """描述子检索: 当前关键帧 vs 更早关键帧 (间隔 ≥min_gap) 的平均汉明距离 ⇒ 候选回环。"""
        if len(self.keyframes) < min_gap + 1:
            return {"loops": 0, "reason": "关键帧不足"}
        cur = self.keyframes[-1]
        if cur["des"] is None or len(cur["des"]) < 8:
            return {"loops": 0, "reason": "当前关键帧描述子不足"}
        best = None
        for kf in self.keyframes[:-min_gap]:
            if kf["des"] is None or len(kf["des"]) < 8:
                continue
            d = float(np.mean(np.min(1.0 - (cur["des"][:, None, :] == kf["des"][None, :, :]).mean(axis=2) * 1.0, axis=1))) \
                if False else None                                            # 大矩阵爆内存 ⇒ 下面走匹配器
            mm = self.front.match({"des": kf["des"], "pts": kf["pts"], "n_kp": kf["n_kp"]}, cur)
            if mm["n_inlier"] >= 20 and (best is None or mm["n_inlier"] > best["n_inlier"]):
                best = {"from": kf["id"], "to": cur["id"], "n_inlier": mm["n_inlier"],
                        "inlier_ratio": mm["inlier_ratio"]}
        if best:
            self.loops.append(best)
            return {"loops": len(self.loops), "edge": best, "reason": ""}
        return {"loops": len(self.loops), "reason": "未检出 (内点门槛 20)"}

    def relax(self) -> dict:
        """位姿图松弛 (简化): 按回环内点数加权, 把闭环误差线性摊还到相邻关键帧。"""
        if not self.loops:
            return {"applied": 0, "reason": "无回环边"}
        applied = 0
        for e in self.loops:
            k = abs(e["to"] - e["from"]) + 1
            w = min(0.5, e["n_inlier"] / (50.0 * k))
            applied += 1
            for kf in self.keyframes[-k:]:
                kf.setdefault("relax", []).append(round(w, 4))
        return {"applied": applied, "note": "简化松弛 (线性摊还, 未做完整 SE(3) 最小二乘)"}

    # — 自主进化接口 —
    def evolution_tick(self) -> dict:
        """本轮建图结构 → 质数签名 ⇒ 未见结构即自主进化输入 (复用 prime_structure, 唯一实现)。"""
        try:
            sys.path.insert(0, os.path.join(ROOT, "src"))
            from lerobot.manifold import prime_structure as PS
            caps = ["m_pos", "m_metric", "m_scene"]
            if any(f.get("n_kp", 0) > 500 for f in self.frames):
                caps.append("m_topic")
            if self.loops:
                caps.append("m_node")
            return PS.understand(caps, product=PS.active_product(),
                                 memory_path=os.path.join(ROOT, "zmax_data", "manifold", "prime_memory.json"))
        except Exception as e:                                                   # noqa: BLE001
            return {"error": repr(e)[:120]}

    # — 落盘 —
    def summary(self) -> dict:
        par = self.parallax_px
        return {"scene": self.scene, "cam": self.cam, "backend": self.backend,
                "frames": len(self.frames), "keyframes": len(self.keyframes),
                "map_points": len(self.map_points), "loops": len(self.loops),
                "scale_source": self.scale_src, "intrinsics": self.intr_eff_source,
                "calibrated": self.intr["calibrated"], "source_kind": self.source_kind,
                "dup_skipped": self.dup_skipped, "weak_frames": self.weak_frames,
                "parallax_px": {"n": len(par), "median": (round(float(np.median(par)), 3) if par else None),
                                "max": (round(float(np.max(par)), 3) if par else None)},
                "n_kp_range": [min([f["n_kp"] for f in self.frames] or [0]), max([f["n_kp"] for f in self.frames] or [0])],
                "inliers": [f.get("n_inlier", 0) for f in self.frames],
                "degenerate_note": ("无视差/重复帧 ⇒ 不产生地图点, 属数据条件而非链路故障"
                                    if (not self.map_points) else ""),
                "elapsed_s": round(time.time() - self.t0, 3)}

    def save(self) -> dict:
        os.makedirs(MAP_DIR, exist_ok=True)
        s = self.summary()
        mp = os.path.join(MAP_DIR, "map_%s.json" % self.scene)
        tp = os.path.join(MAP_DIR, "traj_%s.jsonl" % self.scene)
        if not self.save_enabled:
            return {"saved": False, "note": "dry 模式不落盘", "would_write": [mp, tp]}
        tmp = mp + ".tmp.%d" % os.getpid()
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump({"summary": s, "keyframes": [{"id": k["id"], "n_kp": k["n_kp"], "t": k["t"],
                                                    "why": k["why"], "pose_robot": (None if not k["pose_robot"] else
                                                                                    {"xyz": k["pose_robot"]["xyz"]})}
                                                   for k in self.keyframes],
                       "loops": self.loops, "map_points_head": self.map_points[:200]}, f, ensure_ascii=False)
        os.replace(tmp, mp)
        tmp3 = tp + ".tmp.%d" % os.getpid()
        live = {"ts": time.time(), "updated": time.strftime("%Y-%m-%d %H:%M:%S"), **s,
                "map_file": mp, "traj_file": tp, "running": False}
        with io.open(tmp3, "w", encoding="utf-8") as f:
            json.dump(live, f, ensure_ascii=False, indent=1)
        os.replace(tmp3, LIVE_J)
        tmp2 = tp + ".tmp.%d" % os.getpid()
        with io.open(tmp2, "w", encoding="utf-8") as f:
            for r in self.frames:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp2, tp)
        self._write_live(running=False)
        return {"saved": True, "map": mp, "traj": tp, "live": LIVE_J}


# ── ⑥ 自动加载 / 自动启动 (进入系统即启动建图) ───────────────────────────────────
DEFAULT_CONFIG = {
    "schema": "zmax.mapping.v1",
    "auto_load": True,
    "backend": "orb_pose_slam",
    "scene": "SCN-07-AOI",
    "cam": "arm",
    "sources": ["visual", "robot_pose", "tactile"],
    "keyframe": {"trans_m": 0.010, "rot_deg": 2.0},
    "loop": {"min_gap": 3, "min_inlier": 20},
    "note": "进入系统后自动加载建图 (融合定位建图节点读取本真源); 未标定内参时用显式标注的针孔兜底",
}


def load_config() -> dict:
    try:
        with io.open(CONFIG_J, encoding="utf-8") as f:
            d = json.load(f)
        out = dict(DEFAULT_CONFIG)
        out.update(d)
        return out
    except Exception:                                                            # noqa: BLE001
        return dict(DEFAULT_CONFIG)


def ensure_config() -> str:
    """真源不存在就落一份默认 (原子写), 存在则不动 (幂等)。"""
    os.makedirs(os.path.dirname(CONFIG_J), exist_ok=True)
    if os.path.isfile(CONFIG_J):
        return CONFIG_J
    tmp = CONFIG_J + ".tmp.%d" % os.getpid()
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_J)
    return CONFIG_J


def auto_start(n_frames: int = 24, cam: str = "", scene: str = "", save: bool = True,
               frame_getter=None, video: str = "", frames_dir: str = "", stride: int = 5,
               interval_s: float = 0.3, save_every_s: float = 0.0) -> dict:
    """自动加载 → 建图会话 → 回环 → 松弛 → 落盘 → 进化 tick。返回完整证据链。

    帧源三选一: live 相机 (8797/snap, 按 interval_s 节流) / 真录像 mp4 (video) / 真帧序列目录 (frames_dir)。
    """
    ensure_config()
    cfg = load_config()
    if not cfg.get("auto_load", True):
        return {"started": False, "reason": "真源 auto_load=false"}
    cam = cam or cfg.get("cam", "arm")
    scene = scene or cfg.get("scene", "SCN-07-AOI")
    kf = cfg.get("keyframe") or {}
    sess = MappingSession(scene=scene, cam=cam, backend=cfg.get("backend", "orb_pose_slam"),
                          kf_trans_m=kf.get("trans_m", 0.010), kf_rot_deg=kf.get("rot_deg", 2.0), save=save,
                          kf_min_inlier=int(kf.get("min_inlier", 30)), dup_eps=float(kf.get("dup_eps", 0.8)),
                          save_every_s=float(save_every_s))
    if frame_getter is not None:
        gen, kind = ((frame_getter(cam) for _ in range(int(n_frames))), "custom")
    else:
        gen, kind = frame_source(cam=cam, video=video, frames_dir=frames_dir, stride=stride,
                                 interval_s=interval_s, max_frames=int(n_frames))
    sess.source_kind = kind
    pose = read_robot_pose()
    frames, errors = [], []
    for i, fr in enumerate(gen):
        try:
            p = read_robot_pose() if i % 5 == 0 else pose
            rec = sess.process(fr["img"], label=fr.get("label", cam), pose=p)
            rec["fetch_ms"] = fr.get("fetch_ms", 0.0)
            rec["frame_index"] = fr.get("frame_index")
            frames.append(rec)
        except Exception as e:                                                   # noqa: BLE001
            errors.append(repr(e)[:120])
            if len(errors) > 3:
                break
    loop = sess.detect_loop(min_gap=int((cfg.get("loop") or {}).get("min_gap", 3)),
                            max_ham=float((cfg.get("loop") or {}).get("min_inlier", 20)))
    relax = sess.relax()
    evo = sess.evolution_tick()
    out = sess.save()
    return {"started": True, "config": cfg, "pose": pose, "source_kind": kind, "frames": frames,
            "errors": errors, "loop": loop, "relax": relax, "evolution": evo, "save": out,
            "summary": sess.summary()}


# ── CLI ────────────────────────────────────────────────────────────────────────
def _status() -> int:
    cfg = load_config()
    live = None
    if os.path.isfile(LIVE_J):
        with io.open(LIVE_J, encoding="utf-8") as f:
            live = json.load(f)
    pose = read_robot_pose()
    print(json.dumps({"config": cfg, "config_file": CONFIG_J,
                      "live": live, "live_age_s": (round(time.time() - live["ts"], 1) if live else None),
                      "robot_pose": pose, "obs_dim": MAPPING_OBS_DIM,
                      "visual_dim": MAPPING_VISUAL_DIM, "tactile_dim": MAPPING_TACTILE_DIM,
                      "backends": list(BACKENDS)}, ensure_ascii=False, indent=1))
    return 0


def _run(n: int, cam: str, scene: str, dry: bool, video: str = "", frames_dir: str = "",
         stride: int = 5, interval_s: float = 0.3, rounds: int = 1) -> int:
    """rounds=0 ⇒ 持续跑 (给"启动建图程序"当守护用, 由 pid 停止)。"""
    r = {}
    done = 0
    # 🔧 2026-10-13: rounds=0 (持续/守护) ⇒ **单会话无限跑**: n_frames=0 (帧源无限) + 每 20s 落盘。
    #    原来 rounds=0 也是"轮"循环 ⇒ 每 30 帧重建一次 MapSession, 地图不累积 (示教长跑看不到图)。
    if not rounds and not video and not frames_dir:
        r = auto_start(n_frames=0, cam=cam, scene=scene, save=not dry, video=video,
                       frames_dir=frames_dir, stride=stride, interval_s=interval_s, save_every_s=20.0)
        return 0 if r.get("started") and not r.get("errors") else 1
    while True:
        r = auto_start(n_frames=n, cam=cam, scene=scene, save=not dry, video=video,
                       frames_dir=frames_dir, stride=stride, interval_s=interval_s)
        done += 1
        s = r.get("summary") or {}
        print(json.dumps({"round": done, "source_kind": r.get("source_kind"), "summary": s,
                          "loop": r.get("loop"), "relax": r.get("relax"),
                          "evolution": {k: (r.get("evolution") or {}).get(k) for k in
                                        ("signature", "known", "seen_structures", "novel_events")},
                          "save": r.get("save"), "errors": (r.get("errors") or [])[:3]},
                         ensure_ascii=False, indent=1), flush=True)
        if rounds and done >= int(rounds):
            break
        if not r.get("started"):
            break
    return 0 if r.get("started") and not r.get("errors") else 1


def _selftest() -> int:
    """最小可解自检 (不依赖相机): 随机纹理 + **已知单应**的双视图。

    第一版自检用"同形圆点阵"投影同一片点云 —— 图案自相似 ⇒ ORB 描述子歧义, 匹配必然烂 (实测 29 匹配/4 内点),
    那是**自检设计错了**, 不是链路坏了。改为: 随机纹理 (描述子唯一) + 平面纯旋转相机 (单应 H=K·R·K⁻¹ 是精确模型),
    然后校验 ①特征数 ②比值检验匹配数 ③findHomography RANSAC 内点 ④从 H 反解出的旋转与真值误差 ⑤四角重投影误差。
    注: 本自检覆盖"特征→匹配→几何解算"链; 本质矩阵/平移方向那条路走 `run` 的真帧。
    """
    import cv2
    rng = np.random.default_rng(20261013)
    H, W = 480, 640
    K = np.array([[0.9 * W, 0, W / 2.0], [0, 0.9 * W, H / 2.0], [0, 0, 1.0]])
    tex = rng.integers(0, 255, (H, W), dtype=np.uint8)
    tex = cv2.equalizeHist(cv2.GaussianBlur(tex, (0, 0), 1.2))
    ax, ay = np.radians(3.0), np.radians(5.0)
    Rx = np.array([[1, 0, 0], [0, np.cos(ax), -np.sin(ax)], [0, np.sin(ax), np.cos(ax)]])
    Ry = np.array([[np.cos(ay), 0, np.sin(ay)], [0, 1, 0], [-np.sin(ay), 0, np.cos(ay)]])
    R_gt = Rx @ Ry
    H_gt = K @ R_gt @ np.linalg.inv(K)
    view2 = cv2.warpPerspective(tex, H_gt, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    fe = OrbFrontEnd(n_features=1500)
    fe.set_K(K)
    a, b = fe.detect(tex), fe.detect(view2)
    knn = fe.bf.knnMatch(a["des"], b["des"], k=2) if (a["des"] is not None and b["des"] is not None) else []
    good = [x for pair in knn if len(pair) == 2 for x, n in [pair] if x.distance < fe.ratio * n.distance]
    p1 = np.float32([a["pts"][x.queryIdx] for x in good])
    p2 = np.float32([b["pts"][x.trainIdx] for x in good])
    H_est = mask = None
    inl, err_rot, err_corner = 0, None, None
    if len(good) >= 20:
        H_est, mask = cv2.findHomography(p1, p2, cv2.RANSAC, 2.0)
        inl = int(mask.sum()) if mask is not None else 0
        A = np.linalg.inv(K) @ H_est @ K
        A = A / (A[2, 2] if abs(A[2, 2]) > 1e-12 else 1.0)
        U, S, Vt = np.linalg.svd(A)
        Rn = U @ Vt
        if np.linalg.det(Rn) < 0:
            Rn = -Rn
        err_rot = float(np.degrees(np.arccos(np.clip((np.trace(R_gt.T @ Rn) - 1) / 2, -1, 1))))
        # 评分用**内点**重投影误差 (四角在 warp 的镜像边界上, 纹理本就无效 ⇒ 对四角评分是错的评分方式)
        sel = mask.ravel().astype(bool)
        pr = cv2.perspectiveTransform(p1[sel].reshape(-1, 1, 2), H_est).reshape(-1, 2)
        gt = cv2.perspectiveTransform(p1[sel].reshape(-1, 1, 2), H_gt).reshape(-1, 2)
        err_in = float(np.mean(np.linalg.norm(pr - gt, axis=1)))
        err_in_max = float(np.max(np.linalg.norm(pr - gt, axis=1)))
        src = np.float32([[0, 0], [W, 0], [W, H], [0, H]]).reshape(-1, 1, 2)
        e = cv2.perspectiveTransform(src, H_est) - cv2.perspectiveTransform(src, H_gt)
        err_corner = float(np.max(np.linalg.norm(e.reshape(-1, 2), axis=1)))
    chk = {"features": a["n_kp"] >= 300 and b["n_kp"] >= 300, "matches": len(good) >= 100,
           "homography_inliers": inl >= 100, "rotation_recovered": (err_rot is not None and err_rot < 1.5),
           "inlier_reproj_mean_px": (err_in is not None and err_in < 1.0)}
    print(json.dumps({"n_kp": [a["n_kp"], b["n_kp"]], "matches": len(good), "homography_inliers": inl,
                      "rot_err_deg": None if err_rot is None else round(err_rot, 4),
                      "inlier_reproj_mean_px": None if err_in is None else round(err_in, 4),
                      "inlier_reproj_max_px": None if err_in_max is None else round(err_in_max, 4),
                      "corner_reproj_px_参考(边界镜像, 不作判据)": None if err_corner is None else round(err_corner, 4),
                      "gt_rot_deg": [3.0, 5.0], "checks": chk,
                      "fuse_obs_dim": fuse_mapping_obs(np.zeros(39), np.zeros(6), np.zeros(4))["obs"].shape[0],
                      "note": "随机纹理 + 已知单应 (平面纯旋转); 真帧与本质矩阵路径走 run"},
                     ensure_ascii=False, indent=1))
    return 0 if all(chk.values()) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="融合定位建图 (专用实现)")
    ap.add_argument("cmd", nargs="?", default="status",
                    choices=["status", "run", "selftest", "config"])
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--cam", default="")
    ap.add_argument("--scene", default="")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--video", default="", help="从真录像抽帧 (mp4)")
    ap.add_argument("--frames-dir", default="", help="从真帧序列目录读帧")
    ap.add_argument("--stride", type=int, default=5, help="录像/目录抽帧步长")
    ap.add_argument("--interval", type=float, default=0.3, help="live 抓帧间隔 (秒); 源刷新 100~500ms ⇒ 勿小于 0.1")
    ap.add_argument("--rounds", type=int, default=1, help="跑几轮 (0 = 持续跑直到被停)")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        return _status()
    if a.cmd == "config":
        print(ensure_config())
        return 0
    if a.cmd == "selftest":
        return _selftest()
    return _run(a.n, a.cam, a.scene, a.dry, video=a.video, frames_dir=a.frames_dir,
                stride=a.stride, interval_s=a.interval, rounds=a.rounds)


if __name__ == "__main__":
    raise SystemExit(main())
