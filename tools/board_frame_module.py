"""board_frame_module.py — 模块在"板坐标系"里的位置 (不需要高精度手眼)

2026-11-02 老倪「只有位置, 能保证姿态么」→ 本模块补**姿态**输出 (位置口径一字未改):
  · 板法向 n = R[:,2] (相机系) ⇒ 孔轴方向 (孔垂直于板面)
  · 进给轴 = -n (工具 Z 朝板里走的方向)
  · 板内轴 ex = R[:,0] (孔阵列行方向, 由 20 点网格精确给出)
  · 工具姿态 R_tool = [ex, tz×ex, tz] (tz=-n) → 四元数 quat_xyzw (相机系)
  · 若存在手眼 T_base_cam, 同时给出 base_link 系四元数 (可直接进段表); 没有就只到相机系, 不冒充
绕孔轴的转角说明: 这里取"工具 X 对齐板行方向"(0°)。模块在料盘里的长边朝向由槽口几何定,
本模块不猜 —— 那段信息在 cell_points / 料盘配置里。
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/home/ubuntu/zmax/tools")
import handeye_solve_ls as HS                                       # noqa: E402
from ultralytics import YOLO                                        # noqa: E402

REPO = "/home/ubuntu/zmax"
HANDEYE_CANDIDATES = [os.path.join(REPO, "zmax_data/handeye_result.json"),
                      os.path.join(REPO, "zmax_data/calib/handeye.json"),
                      os.path.join(REPO, "zmax_data/real_cell_geometry.json")]


def quat_of(Rm):
    """旋转矩阵 → 四元数 [x,y,z,w] (单位化)。"""
    m = np.asarray(Rm, dtype=float)
    tr = float(np.trace(m))
    if tr > 0:
        s = (tr + 1.0) ** 0.5 * 2.0
        w, x, y, z = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = (1.0 + m[0, 0] - m[1, 1] - m[2, 2]) ** 0.5 * 2.0
        w, x, y, z = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = (1.0 + m[1, 1] - m[0, 0] - m[2, 2]) ** 0.5 * 2.0
        w, x, y, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = (1.0 + m[2, 2] - m[0, 0] - m[1, 1]) ** 0.5 * 2.0
        w, x, y, z = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    q = np.array([x, y, z, w], dtype=float)
    nq = float(np.linalg.norm(q)) or 1.0
    return q / nq


def tool_frame_from_board(R):
    """板旋转 R(板→相机) ⇒ (工具旋转矩阵, 板法向 n, 板内轴 ex, 进给轴 tz=-n)。"""
    R = np.asarray(R, dtype=float)
    ex = R[:, 0] / (np.linalg.norm(R[:, 0]) or 1.0)
    n = R[:, 2] / (np.linalg.norm(R[:, 2]) or 1.0)
    tz = -n
    tx = ex - np.dot(ex, tz) * tz              # 投影到 ⊥tz 平面, 保证正交
    tx = tx / (np.linalg.norm(tx) or 1.0)
    ty = np.cross(tz, tx)
    return np.column_stack([tx, ty, tz]), n, ex, tz


def handeye():
    """找手眼 (base←cam 的 R,t); 没有给 None —— 不猜, 不拿相机系冒充 base_link。"""
    for p in HANDEYE_CANDIDATES:
        if not os.path.exists(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:                                                   # noqa: BLE001
            continue
        for k in ("T_base_cam", "T_cam2base", "handeye"):
            v = d.get(k)
            if isinstance(v, dict) and ("R" in v) and ("t" in v):
                return np.array(v["R"], dtype=float), np.array(v["t"], dtype=float), p
    return None


def run(img_path, conf=0.25):
    im = cv2.imread(img_path)
    if im is None:
        return {"ok": False, "why": "图读不到: %s" % img_path}
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    pts, grid = HS.detect(g)
    if pts is None:
        return {"ok": False, "why": "板未检出"}
    Km, _ = HS._K()
    obj = HS.obj_points(grid, HS.SPACING_MM / 1000.0)
    R, t = HS._board_pose(pts, obj, Km)
    n = R @ np.array([0.0, 0.0, 1.0])
    Rt, nrm, ex, tz = tool_frame_from_board(R)
    q_tool = quat_of(Rt)
    tilt = float(np.degrees(np.arccos(min(1.0, abs(float(nrm[2]))))))
    out = {"ok": True, "板点": len(pts), "板距_m": round(float(np.linalg.norm(t)), 4),
           # ── 姿态 (2026-11-02): 孔轴 / 进给轴 / 工具四元数 ──
           "板法向(相机系)": [round(float(v), 5) for v in nrm],
           "板法向与相机Z夹角°": round(tilt, 3),
           "板内轴x(相机系)": [round(float(v), 5) for v in ex],
           "进给轴_工具Z(相机系)": [round(float(v), 5) for v in tz],
           "姿态quat_xyzw": [round(float(v), 6) for v in q_tool],
           "姿态frame": "cam",
           "绕孔轴转角°": 0.0}
    he = handeye()
    if he:
        Rb, _tb, pth = he
        out.update({"姿态quat_xyzw_base": [round(float(v), 6) for v in quat_of(Rb @ Rt)],
                    "handeye": pth, "姿态frame": "base_link"})
    else:
        out.update({"handeye": None,
                    "why_no_base": "无手眼 T_base_cam ⇒ 姿态只到相机系, 不许直接进段表(不混坐标系)"})

    m = YOLO(os.path.join(REPO, "models", "yolo_peg_live.pt"))
    r = m.predict(im, conf=conf, verbose=False)[0]
    if len(r.boxes) == 0:
        out.update({"ok": False, "why": "模块未检出",
                    "模块在板坐标 (x,y,mm)": None, "离板面mm": None})
        return out
    b = r.boxes[0]
    u, v = [float(x) for x in b.xyxy[0].tolist()][:2], [float(x) for x in b.xyxy[0].tolist()][2:]
    cx, cy = (u[0] + v[0]) / 2.0, (u[1] + v[1]) / 2.0
    K = Km
    ray = np.array([(cx - K[0, 2]) / K[0, 0], (cy - K[1, 2]) / K[1, 1], 1.0])
    lam = float(np.dot(n, t)) / float(np.dot(n, ray))
    p_cam = ray * lam
    p_board = R.T @ (p_cam - t)
    out.update({"模块在板坐标 (x,y,mm)": [round(float(p_board[0]) * 1000, 1),
                                         round(float(p_board[1]) * 1000, 1)],
                "离板面mm": round(float(p_board[2]) * 1000, 1), "框": [round(cx, 1), round(cy, 1)],
                "conf": round(float(b.conf[0]), 3)})
    return out


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/zmax/zmax_data/ss_live/cam_rs.png")
    res = run(p)
    print(p, "→")
    for k, v in res.items():
        print("   %-26s %s" % (k, v))
