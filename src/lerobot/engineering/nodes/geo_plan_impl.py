# ⚠️ 本文件是 L2 算法本体, 已迁到 src/lerobot/policies/left_right/state_space/plan_guide.py (老倪 2026-11-15: L2 算法统一放 state_space/)
# -*- coding: utf-8 -*-
"""🧭 测地线块规划 (Geodesic Chunk Planner) · 真实现  (registry key = n_geoplan)

口径 (老倪 2026-10-29):
    「YOLO → 融合定位 → 状态空间(obs) → 运动规划 ‖ 前馈MLP → 加权 → 动作调制器
      → 安全执行边界 → 原子技能派发 → 动作执行器 → 机器人」
    画布上原来只有「运动规划」(n_moveit = MoveIt 关节空间规划, 在技能之后)；
    这条链里的「运动规划」是**状态空间测地线块规划**, 与前馈 MLP 并列, 同在加权之前。
    本节点就是它 —— 与 n_moveit 是两个不同的东西, 名字和源码都分开, 不许混。

职责: obs43 → ManifoldEngine.project(潜空间) → 目标点(本段目标) → compute_geodesic(H 步)
      → readout 解码 (限幅) → 输出块 chunk[H,4] (dx,dy,dz,grip)。只算块, 不下发、不碰授权。

数学与块流水线**逐行同源** (tools/ss_chunk_pipeline.py::_chunk):
      path = navigator.compute_geodesic(p_now, goal, H);  a = path @ readout + readout_b;
      a = clip(a, action_lo, action_hi)

不造假:
  · 无 obs43 输入         → ok=False, err 说明缺哪个槽
  · 引擎/权重不可用       → ok=False, err 带异常类型
  · 引擎无目标点/project 空 → ok=False, err 如实说 (不出空块冒充成功)
  · readout 未标定         → decode="占位解码(未标定)" 明示, 不当作已标定结果
"""
from __future__ import annotations

import json
import math
import os
import time

import numpy as np

_ROOT = os.path.expanduser("~/zmax")
CKPT = os.path.join(_ROOT, "models", "manifold_engine.npz")
LATENT, STATE_DIM, ACTION_DIM = 16, 43, 4
MANIFOLD_M = 3.643
H_DEF = int(os.environ.get("ZMAX_GEOPLAN_H", "8"))

_ENG = None
_ENG_ERR = ""

# 🧭 工艺规划 (老倪 2026-11-01「测地线规划引导负责工艺规划」): 本节点每拍算
#   "现在该做哪个元任务的哪一步", 与 3D 引导位姿一起 output; 引擎纯逻辑, 不碰硬件。
_CRAFT = {"err": "未调用"}



def _engine():
    """懒加载 ManifoldEngine (单例)。失败不抛, 记错误文本由 run() 如实上报。"""
    global _ENG, _ENG_ERR
    if _ENG is not None:
        return _ENG
    try:
        from lerobot.manifold.manifold_engine import ManifoldEngine

        e = ManifoldEngine(manifold_type="su2", latent_dim=LATENT, state_dim=STATE_DIM,
                           action_dim=ACTION_DIM, manifold_M=MANIFOLD_M,
                           inertia=False, su2_tangent=True)
        if os.path.exists(CKPT):
            e.load(CKPT)
        _ENG = e
    except Exception as exc:                                             # noqa: BLE001
        _ENG_ERR = "%s: %s" % (type(exc).__name__, exc)
        _ENG = None
    return _ENG


def _obs(ctx):
    """从 ctx 取 obs43: ctx['in1'] 可以是 list/np.array(43) 或 {'obs':[...]} 或 {'state':[...]}"""
    v = (ctx or {}).get("in1")
    # 🔴 2026-11-01 实测: 常驻循环给的是 ctx[port] = {"value":…, "age_s":…, "fresh":…},
    #   原来只认 {"obs":…} 直塞 ⇒ 永远报"无 obs43 输入", 这条引导链一直空转。
    if isinstance(v, dict) and "value" in v:
        v = v.get("value")
    if isinstance(v, dict):
        v = v.get("obs") or v.get("state") or v.get("vec")
    if v is None:
        return None
    try:
        a = np.asarray(v, float).ravel()
    except Exception:                                                    # noqa: BLE001
        return None
    if a.size < STATE_DIM:
        return None
    return a[:STATE_DIM]


def _goal_state(obs, ctx):
    """目标态: 默认把 obs 的位置槽换成目标槽 obs[36:39] (与 env/前馈同一口径: 36:39 = 目标)。"""
    g = obs.copy()
    tgt = (ctx or {}).get("in2")
    if isinstance(tgt, dict):
        tgt = tgt.get("goal") or tgt.get("target") or tgt.get("pos")
    if tgt is not None:
        try:
            t = np.asarray(tgt, float).ravel()[:3]
            if t.size == 3:
                g[36:39] = t
        except Exception:                                                # noqa: BLE001
            pass
    g[0:3] = g[36:39]
    return g



# ── 🎯 唯一目标 3D 引导位姿 (老倪 2026-11-22: 「要输出唯一的目标 3D 引导位姿, 这个位姿是需要机器人抓取的目标」) ──
#   为什么原来不行: 老 _run_guides 出的是 guide = tcp + u*step —— 那是"下一小步", 一周期一个,
#   连续几拍就是几个不同位姿, 下游不知道"到底要去哪抓"; 姿态直接用当前 TCP 旋转, 与模块朝向无关。
#   现在: 全周期只认**一个**目标位姿 (位置 + 四元数), 其余量 (引导步/朝向量/预抓点) 全部由它派生。
#   位置来源 = 融合模块 (2D ⊕ 2D→3D ⊕ 状态反馈) 的 peg_xyz; 姿态来源 = peg_quat ——
#   按老倪的定义「抓取瞬间模块坐标系 ≡ tool1 坐标系」, 目标姿态就是模块姿态本身 (可乘一个工具对齐常量)。
PEG_POSE_URL = os.environ.get("ZMAX_PEG_POSE_URL", "http://127.0.0.1:8896/peg_pose")
TARGET_STALE_S = float(os.environ.get("ZMAX_TARGET_STALE_S", "1.5"))


def _q_mul(a, b):
    """四元数乘 (wxyz): a⊗b ⇒ 先转 b 再转 a。"""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([aw * bw - ax * bx - ay * by - az * bz,
                     aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw], float)


def _q_unit(q):
    if q is None:
        return None
    q = np.asarray(q, float).ravel()[:4]
    n = float(np.linalg.norm(q))
    return None if (n < 1e-6 or not np.all(np.isfinite(q))) else q / n


def _q_to_R(q):
    u = _q_unit(q)
    w, x, y, z = (1.0, 0.0, 0.0, 0.0) if u is None else u
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]], float)


def _align_quat():
    """工具对齐常量: 模块坐标系 → tool1 坐标系。默认单位阵 (老倪: 抓取时两者重合);
    现场若夹爪装歪, 用 ZMAX_GRASP_ALIGN_RPY="0,0,180" 补。"""
    txt = os.environ.get("ZMAX_GRASP_ALIGN_RPY", "").strip()
    if not txt:
        return np.array([1.0, 0.0, 0.0, 0.0])
    try:
        r, p, y = [float(v) * np.pi / 180.0 for v in txt.replace(";", ",").split(",")[:3]]
        cr, sr, cp, sp, cy, sy = np.cos(r / 2), np.sin(r / 2), np.cos(p / 2), np.sin(p / 2), np.cos(y / 2), np.sin(y / 2)
        return np.array([cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy,
                         cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy], float)
    except Exception:                                                   # noqa: BLE001
        return np.array([1.0, 0.0, 0.0, 0.0])


_PEG_CACHE = {"ts": 0.0, "doc": None}


def _peg_pose(ctx=None):
    """取融合模块的 6D 位姿: ctx 直塞优先, 否则读 :8896。

    常驻循环 10Hz, 每拍都打一次 HTTP 会在服务挂掉时每拍卡 0.4s ⇒ 加 0.2s 缓存,
    超时收到 0.25s。帧龄超 TARGET_STALE_S 仍判陈旧 (缓存不等于放行)。
    """
    now = time.time()
    if _PEG_CACHE["doc"] is not None and now - _PEG_CACHE["ts"] < 0.2:
        d = dict(_PEG_CACHE["doc"])
        d["_age_s"] = round(now - float(d.get("ts") or now), 2)
        return d
    v = (ctx or {}).get("in3") or (ctx or {}).get("peg_pose")
    if isinstance(v, dict) and "value" in v:
        v = v.get("value")
    if isinstance(v, dict) and "xyz" in v:
        return dict(v, _src="ctx")
    try:
        import urllib.request as _u
        with _u.urlopen(PEG_POSE_URL, timeout=0.25) as _r:
            d = json.loads(_r.read().decode())
        if d.get("ok"):
            age = time.time() - float(d.get("ts") or 0)
            if age <= TARGET_STALE_S:
                _PEG_CACHE.update({"ts": time.time(), "doc": d})
                d["_age_s"] = round(age, 2)
                d["_src"] = "fusion:%s" % PEG_POSE_URL
                return d
            return {"_err": "融合位姿陈旧 %.1fs" % age}
    except Exception as exc:                                            # noqa: BLE001
        return {"_err": "融合服务不可用: %s" % type(exc).__name__}
    return None


def _slot_geom(slot_id, tray="R"):
    """取槽位几何 (mm)。

    🔴 编号口径 (2026-11-22 老倪两次纠正后定死, 不许再混):
      R 盘 (右臂前面的料盘) = **示教编号**, 真源 config/points/tray_slots_14.json (x≈649 上排 / 517 下排)。
          示教点 cell_points.json 的"槽1..7"就是这套 (槽3 = 648.8,407.0,108.6)。
      L 盘 (左臂前面的料盘) = 只有 AR 围栏盒子「左槽N」(x≈490 下层 / 617 上层), 没有示教点。
      ⚠ tray_slots_14 的槽 1..7 与 AR 围栏的槽 8..14 是同一排 (x 差 ~158mm) —— 两套不能互相顶替,
        否则引导框会整体错一排 (画面上看起来"偏上")。
    z 口径: 体中心 = 盒底 + 模块厚/2。
    """
    tray = (tray or "R").upper()
    if tray == "R":
        tray_p = os.path.join(_ROOT, "config", "points", "tray_slots_14.json")
        with open(tray_p, encoding="utf-8") as fh:
            slots = {int(sl["id"]): sl for sl in json.load(fh).get("slots", [])}
        if int(slot_id) in slots:
            sl = slots[int(slot_id)]
            return {"x": float(sl["x"]), "y": float(sl["y"]), "z": float(sl["z"]),
                    "lx": float((sl.get("box") or {}).get("lx") or 72.0),
                    "lz": float((sl.get("box") or {}).get("lz") or 8.5),
                    "src": "tray_slots_14.json 槽%d (示教编号)" % int(slot_id)}
    nm = "左槽%d" % int(slot_id)
    fp = os.path.join(_ROOT, "zmax_data", "ar_rs", "fences.json")
    with open(fp, encoding="utf-8") as fh:
        items = (json.load(fh) or {}).get("items") or []
    for it in items:
        if (it.get("name") or "").strip() == nm and it.get("type") == "box" and it.get("p1"):
            p1, p2 = it["p1"], it["p2"]
            return {"x": (float(p1[0]) + float(p2[0])) / 2.0 * 1000.0,
                    "y": (float(p1[1]) + float(p2[1])) / 2.0 * 1000.0,
                    "z": min(float(p1[2]), float(p2[2])) * 1000.0,
                    "lx": 72.0, "lz": 8.5,
                    "src": "AR 围栏 %s (槽盒 %.1f×%.1fmm)" % (
                        nm, abs(float(p2[0]) - float(p1[0])) * 1000,
                        abs(float(p2[1]) - float(p1[1])) * 1000)}
    raise KeyError("槽位几何查不到: tray=%s slot=%s" % (tray, slot_id))

def target_pose(ctx=None, obs=None, hover_mm=None, slot_id=None, tray="R"):
    """**唯一**目标 3D 引导位姿 (机器人要抓的那个位姿)。位置 m, 姿态 wxyz, 基座系。

    派生量 (同一个目标算出来的, 不另立口径):
      approach  抓取进给方向 (默认 +Z 从上往下, ZMAX_GRASP_APPROACH 可改)
      pre       预抓点 = 目标 − approach·hover
      grasp_axis 夹爪需要对齐的模块长轴 (模块 X 轴), 派爪方向照它来
    返回值带 src/valid/sigma/age, 降级路径明写, 不静默。
    """
    hover = (float(os.environ.get("ZMAX_GUIDE_HOVER_MM", "40")) if hover_mm is None else float(hover_mm)) * 0.001
    # 🎯 指定槽位: 该槽没有实物/没检出时, 目标位姿由**槽位几何 + 排布朝向**给出, 并明标 valid=false
    #    (老倪 2026-11-22「输出位于槽位3的位姿」—— 要的是"该去抓哪", 不是"已经看见它")
    if slot_id is not None:
        try:
            from .unified_state55 import SLICE  # noqa: F401  (只为确认模块可导入, 不传值)
        except Exception:                                                   # noqa: BLE001
            pass
        try:
            g = _slot_geom(slot_id, tray)
        except Exception as exc:                                            # noqa: BLE001
            return {"node": "n_geoplan", "kind": "target_pose", "ok": False,
                    "valid": False, "err": "槽%d 几何取不到: %s" % (int(slot_id), exc)}
        # 朝向: 模块平躺, 长轴沿基座 ±X。右盘默认"金手指朝 −Y 侧" (与槽10 实测同向);
        #   左盘取**镜像** (正/反向摆盘 ⇒ 两盘朝向相反, 这是先验, 现场以 ZMAX_SLOT_XDIR_L 覆盖)。
        _isL = str(tray).upper() == "L"
        _env = "ZMAX_SLOT_XDIR_L" if _isL else "ZMAX_SLOT_XDIR"
        _dflt = "-1,0.15,0" if _isL else "-1,-0.15,0"
        xd_txt = os.environ.get(_env, _dflt).replace(";", ",")
        try:
            xd = np.array([float(v) for v in xd_txt.split(",")[:3]], float)
        except Exception:                                                   # noqa: BLE001
            xd = np.array([-1.0, 0.15, 0.0] if _isL else [-1.0, -0.15, 0.0])
        xd[2] = 0.0
        xd = xd / (np.linalg.norm(xd) + 1e-12)
        L = float(g.get("lx") or 72.0) / 1000.0
        Hm = float(g.get("lz") or 8.5) / 1000.0
        body = np.array([g["x"], g["y"], g["z"] + Hm * 500.0], float) / 1000.0
        # 🔴 2026-11-22 老倪「右3D引导位姿，应该跟光模块重合。向后一点」:
        #    之前 pos = 体中心 − L/2·xd (金手指端), 框从端部单向拉出去 72mm ⇒ 画面上比模块"靠前" 36mm。
        #    改成 pos = **体中心**(就是真机 TCP 落点、也是画面上那块模块的中心), 框由绘制端按中心对称展开,
        #    金手指端另存 head_mm 备查 (视觉定义仍在, 只是不再当位姿原点)。
        pos = body.copy()
        head = body - (L / 2.0) * xd
        y_ax = np.cross(np.array([0.0, 0.0, 1.0]), xd)
        R_slot = np.stack([xd, y_ax, np.array([0.0, 0.0, 1.0])], 1)
        # 🔴 2026-11-22: 姿态必须过**夹爪安装对齐** _align_quat(), 否则出来的是"模块本体姿态",
        #    不是 tool1 姿态 —— 实测 槽3 会差 25°, 机器人扫过去就是错的(老倪「抓取点位姿不对」)。
        q_slot = _q_mul(_quat_from_rot(R_slot.ravel()), _align_quat())
        # 🎯 抓取点(TCP 该去的点) = 模块**体中心**, 不是金手指端: 真机示教点(槽3 648.8,407.0,108.6)
        #    就是体中心口径; 实测录制里 槽2 抓取帧 TCP=649.85,454.1,112.7 与槽2 中心 648.3,452.4 差 1.5mm。
        #    2026-11-22 老倪又定一次: **位姿原点也要落在模块上**(「应该跟光模块重合」)⇒ pos = 体中心;
        #    金手指端只留 head_mm 备查, 不再当位姿原点。
        grasp = body
        pre_g = grasp - np.array([0.0, 0.0, -1.0]) * hover
        return {"node": "n_geoplan", "kind": "target_pose", "frame": "base_link", "unit": "m",
                "ok": True, "valid": False, "slot": int(slot_id),
                "arm": "L" if str(tray).upper() == "L" else "R",
                "tray": "L" if str(tray).upper() == "L" else "R",
                "slot_name": ("左槽%d" if str(tray).upper() == "L" else "槽%d") % int(slot_id),
                "geom_src": g.get("src"),
                "hover_mm": round(hover * 1000, 1),
                "pos": [round(float(v), 6) for v in pos],
                "pos_mm": [round(float(v) * 1000.0, 1) for v in pos],
                "grasp_mm": [round(float(v) * 1000.0, 1) for v in grasp],
                "head_mm": [round(float(head[i]) * 1000.0, 1) for i in range(3)],
                "grasp_src": "模块体中心 (与真机示教点位同口径)",
                "quat": None if q_slot is None else [round(float(v), 6) for v in q_slot],
                "quat_src": "模块姿态 × 夹爪安装对齐",
                "approach": [0.0, 0.0, -1.0],
                "pre_pos_mm": [round(float(pre_g[i]) * 1000.0, 1) for i in range(3)],
                "module_x_axis": [round(float(v), 4) for v in xd],
                "sigma_mm": None, "age_s": 0.0,
                "src": "%s%s 几何真值 + 排布朝向 (未观测实物 ⇒ valid=false)" % (
                    "左臂·左槽" if _isL else "右臂·槽", int(slot_id)),
                "note": "该槽当前没有检出实物; 位姿先验来自 %s, 可当引导目标, 不可当抓取真值%s" % (
                    g.get("src") or "tray_slots_14.json",
                    " 【左盘朝向取右盘镜像, 属先验: 现场若为反向摆放, 用 ZMAX_SLOT_XDIR_L 覆盖】" if _isL else "")}
    peg = _peg_pose(ctx)
    out = {"node": "n_geoplan", "kind": "target_pose", "frame": "base_link", "unit": "m",
           "hover_mm": round(hover * 1000, 1)}
    if isinstance(peg, dict) and "xyz" in peg:
        pos = np.asarray(peg.get("xyz"), float).ravel()[:3]
        q = _q_unit(peg.get("quat"))
        valid = bool(peg.get("valid")) and q is not None
        sigma = peg.get("sigma_mm")
        src = "%s · %s" % (peg.get("src"), peg.get("_src"))
        age = peg.get("_age_s")
        detail = peg.get("detail") or {}
        slot = detail.get("slot")
    else:
        # 降级: 位置用状态向量的 peg 槽, 姿态用当前 TCP 旋转 (明确标降级, 不当成真位姿用)
        if obs is None:
            return dict(out, ok=False, valid=False,
                        err=(peg or {}).get("_err", "无融合位姿且无 obs"))
        pos = np.asarray(obs[4:7], float).ravel()[:3]
        q = _quat_from_rot(obs[24:33])
        valid, sigma, src, age, slot = False, None, "降级: obs[4:7] + 当前 TCP 旋转", None, None
        out["degrade_reason"] = (peg or {}).get("_err", "无融合位姿")

    if pos.size != 3 or not np.all(np.isfinite(pos)):
        return dict(out, ok=False, valid=False, err="目标位置非法")
    if q is None and obs is not None:                 # 融合位姿无姿态 ⇒ 用当前 TCP 旋转兜底(标降级)
        q = _quat_from_rot(np.asarray(obs, float).ravel()[24:33])

    q_tool = _q_mul(q if q is not None else np.array([1.0, 0, 0, 0]), _align_quat())
    R_t = _q_to_R(q_tool)
    ap_env = os.environ.get("ZMAX_GRASP_APPROACH", "").strip()
    if ap_env:
        try:
            approach = np.asarray([float(v) for v in ap_env.split(",")[:3]], float)
            approach = approach / (np.linalg.norm(approach) + 1e-12)
        except Exception:                                               # noqa: BLE001
            approach = np.array([0.0, 0.0, -1.0])
    else:
        approach = np.array([0.0, 0.0, -1.0])      # 进给方向 = 从上往下 (模块在槽里平躺)
    # 🎯 抓取点(TCP) = 模块**体中心** = 金手指端 + (L/2)·X̂ ; 与真机示教点位同口径
    _L = 0.072
    try:
        _L = float((detail or {}).get("L_mm") or 72.0) / 1000.0 if isinstance(detail, dict) else 0.072
    except Exception:                                                   # noqa: BLE001
        _L = 0.072
    _xhat = R_t[:, 0] / (np.linalg.norm(R_t[:, 0]) + 1e-12)
    grasp = pos + _xhat * (_L / 2.0)
    pre = grasp - approach * hover                 # 预抓点 = 抓取点上方 hover (approach 是"朝向目标"的方向)

    out.update({
        "ok": True, "valid": valid,
        "pos": [round(float(v), 6) for v in pos],
        "pos_mm": [round(float(v) * 1000.0, 1) for v in pos],
        "grasp_mm": [round(float(v) * 1000.0, 1) for v in grasp],
        "grasp_src": "模块体中心 (与真机示教点位同口径)", 
        "quat": None if q_tool is None else [round(float(v), 6) for v in q_tool],
        "rpy_deg": [round(float(np.degrees(np.arctan2(R_t[2, 1], R_t[2, 2]))), 2),
                    round(float(np.degrees(-np.arcsin(np.clip(R_t[2, 0], -1, 1)))), 2),
                    round(float(np.degrees(np.arctan2(R_t[1, 0], R_t[0, 0]))), 2)],
        "approach": [round(float(v), 4) for v in approach],
        "pre_pos_mm": [round(float(v) * 1000.0, 1) for v in pre],
        "module_x_axis": [round(float(v), 4) for v in R_t[:, 0]],   # 夹爪两指要对齐的方向
        "sigma_mm": sigma, "slot": slot, "age_s": age, "src": src,
    })
    if q is None:
        out["quat_note"] = "模块姿态未观测 ⇒ 沿用当前 TCP 姿态, valid=false (只可当引导, 不可当抓取真值)"
    return out


def target_pose_pair(lslot=1, rslot=3, ctx=None, hover_mm=None):
    """**双臂成对**目标位姿 (老倪 2026-11-22「直接给出左右两个3D引导位姿」)。

    左臂 = 左盘 (AR 围栏「左槽N」几何) · 右臂 = 右盘 (tray_slots_14.json 槽N)。
    语义: 一对**同时成立或同时失效** (atomic=True) —— 一侧取不到几何就整对标 ok=false,
    不许一侧悄悄单飞, 否则又是一臂按旧目标、一臂按新目标。
    仍守"一个周期一个目标组": 组 = (L,R), 不是两个独立目标。
    """
    L = target_pose(ctx=ctx, slot_id=lslot, tray="L", hover_mm=hover_mm)
    R = target_pose(ctx=ctx, slot_id=rslot, tray="R", hover_mm=hover_mm)
    ok = bool(L.get("ok")) and bool(R.get("ok"))
    why = []
    if not L.get("ok"):
        why.append("左臂: %s" % L.get("err"))
    if not R.get("ok"):
        why.append("右臂: %s" % R.get("err"))
    return {"node": "n_geoplan", "kind": "target_pose_pair", "ok": ok, "atomic": True,
            "pair_id": "PAIR_%s" % time.strftime("%Y%m%d_%H%M%S"),
            "ts": round(time.time(), 3), "t_str": time.strftime("%F %T"),
            "L": L, "R": R,
            "why": "两侧同时给出 (左盘槽%d / 右盘槽%d); 任一侧取不到几何则整对失效" % (int(lslot), int(rslot))
                   if ok else "; ".join(why)}


def _vec3(v):
    try:
        return [float(v[0]), float(v[1]), float(v[2])]
    except Exception:                                                   # noqa: BLE001
        return None


def _left_arm_truth(ctx=None):
    """左臂真值 (mm)。单台真机只有一条臂 ⇒ 左臂真值只能从旁路来, 取不到就**明写没有**。

    来源优先级: env ZMAX_LARM_POSE_JSON → zmax_data/ss_live/left_arm_pose.json → ctx['in_larm']。
    """
    p = os.environ.get("ZMAX_LARM_POSE_JSON") or os.path.join(
        _ROOT, "zmax_data", "ss_live", "left_arm_pose.json")
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh) or {}
        v = _vec3(d.get("pos_mm") or d.get("tcp") or d.get("pos") or [])
        if v:
            return {"ok": True, "pos_mm": v, "src": os.path.relpath(p, _ROOT),
                    "age_s": round(time.time() - os.path.getmtime(p), 1)}
    except Exception:                                                   # noqa: BLE001
        pass
    v = _vec3(((ctx or {}).get("in_larm") or {}).get("value"))
    if v:
        return {"ok": True, "pos_mm": v, "src": "ctx.in_larm", "age_s": 0.0}
    return {"ok": False, "pos_mm": None, "src": None,
            "why": "左臂无真值来源 (单台真机只有一条臂; 需旁路读第二控制器或扩状态向量)"}


def _zone_of(y_mm, split_mm):
    return "L" if float(y_mm) >= float(split_mm) else "R"


def dual_arm_guide(ctx=None, lslot=None, rslot=None, hover_mm=None):
    """🤝 双臂协同 = **引导层一个目标组** (老倪 2026-11-22「代码写进测地线3D引导里」)。

    单台机器人两条臂在同一物理工作空间里, 围绕同一组任务(正反向摆盘)的实时动作配合。
    三条硬条件 (缺一条就降级并写明, 不许假装协同):
      ① 每拍双真值   右臂 = obs[0:3] (唯一真机) · 左臂 = 旁路真值, 取不到 ⇒ dual_truth.L=false
      ② 输出原子成对 pair_id + 同一 ts + 两侧 valid 各自标注; 一侧缺几何 ⇒ pair_valid=false (整对)
      ③ 共享区带 owner 左右盘按 y 分区 (ZMAX_ZONE_SPLIT_MM, 默认 600mm): 目标落错区 ⇒ cross_zone=true
         ⇒ hold=true (执行侧兜底: 后到者让一拍), 绝不让两臂同时抢同一区
    另给 min_gap_mm: 两个抓取点间距, 小于 ZMAX_DUAL_MIN_GAP_MM(默认 120) ⇒ 预警 (不分摊几何)。
    只算/只标, 不下发、不碰授权。
    """
    L_S = int(os.environ.get("ZMAX_DUAL_LSLOT", lslot if lslot is not None else 8))
    R_S = int(os.environ.get("ZMAX_DUAL_RSLOT", rslot if rslot is not None else 3))
    pair = target_pose_pair(L_S, R_S, ctx=ctx, hover_mm=hover_mm)

    obs = _obs(ctx)
    r_true = None
    if obs is not None:
        try:
            r_true = [float(obs[0]) * (1000.0 if abs(float(obs[0])) < 10 else 1.0),
                      float(obs[1]) * (1000.0 if abs(float(obs[1])) < 10 else 1.0),
                      float(obs[2]) * (1000.0 if abs(float(obs[2])) < 10 else 1.0)]
        except Exception:                                               # noqa: BLE001
            r_true = None
    l_true = _left_arm_truth(ctx)

    split = float(os.environ.get("ZMAX_ZONE_SPLIT_MM", 600.0))
    gL = _vec3((pair.get("L") or {}).get("grasp_mm"))
    gR = _vec3((pair.get("R") or {}).get("grasp_mm"))
    zone_L = _zone_of(gL[1], split) if gL else None
    zone_R = _zone_of(gR[1], split) if gR else None
    cross = bool(zone_L and zone_R and (zone_L != "L" or zone_R != "R"))
    gap = None
    if gL and gR:
        gap = round(((gL[0] - gR[0]) ** 2 + (gL[1] - gR[1]) ** 2 + (gL[2] - gR[2]) ** 2) ** 0.5, 1)
    min_gap = float(os.environ.get("ZMAX_DUAL_MIN_GAP_MM", 120.0))
    gap_warn = bool(gap is not None and gap < min_gap)

    hold = bool((not l_true.get("ok")) or cross or gap_warn or not pair.get("ok"))
    why = []
    if not pair.get("ok"):
        why.append("成对几何不全: %s" % pair.get("why"))
    if not l_true.get("ok"):
        why.append("左臂无真值 ⇒ 只做几何引导, 不做双臂时序协同")
    if cross:
        why.append("目标越区 (左臂目标 y=%s 落 %s 区 / 右臂 y=%s 落 %s 区)" % (
            gL[1] if gL else "?", zone_L, gR[1] if gR else "?", zone_R))
    if gap_warn:
        why.append("两抓取点间距 %.1fmm < %.0fmm" % (gap, min_gap))
    return {"node": "n_geoplan", "kind": "dual_arm_guide", "ok": bool(pair.get("ok")),
            "pair_id": pair.get("pair_id"), "ts": pair.get("ts"), "t_str": pair.get("t_str"),
            "atomic": True, "pair_valid": bool(pair.get("ok")),
            "dual_truth": {"R": bool(r_true), "L": bool(l_true.get("ok")),
                           "r_mm": r_true, "l_mm": l_true.get("pos_mm"), "l_src": l_true.get("src")},
            "zone": {"split_mm": split, "L_action": zone_L, "R_action": zone_R,
                     "owner": {"L": "L" if zone_L == "L" else None, "R": "R" if zone_R == "R" else None},
                     "cross_zone": cross},
            "min_gap_mm": gap, "gap_warn": gap_warn, "hold": hold, "why": "; ".join(why) or "两侧分区、目标组原子、各守本区",
            "L": pair.get("L"), "R": pair.get("R"),
            "task": "正反向摆盘 (左臂向左盘放/取, 右臂向右盘放/取), 同拍同一个目标组",
            "note": "只算/只标/只出证据; 运动下发仍走 sslimit→n_exec (需 8793 授权)"}


def publish_target(slot_id=None, ctx=None, path=None, fence=True, tray="R"):
    """把**唯一目标位姿**落成可观测产物 (AR 页面直接读, 不需要重启 8797)。

    两个落点:
      · zmax_data/ss_live/target_pose.json   规范 JSON (其他消费者/接口文档用)
      · zmax_data/ar_rs/fences.json 里的 id=TP1 元素  (AR 页 /api/fence 热读 ⇒ 前端画三轴+半透明模块)
    只写文件, 不下发任何运动指令。id=TP1 用 upsert, 反复发布不会堆垃圾。
    """
    t = target_pose(ctx=ctx, slot_id=slot_id, tray=tray)
    if not t.get("ok"):
        return {"ok": False, "err": t.get("err"), "pose": t}
    root = _ROOT
    _isL = str(tray).upper() == "L"
    p_json = path or os.path.join(root, "zmax_data", "ss_live",
                                  "target_pose_L.json" if _isL else "target_pose.json")
    os.makedirs(os.path.dirname(p_json), exist_ok=True)
    doc = {"ts": time.time(), "t_str": time.strftime("%H:%M:%S"), "pose": t}
    tmp = p_json + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p_json)

    out = {"ok": True, "json": p_json, "pose": t, "fence": None}
    if not fence:
        return out
    fp = os.path.join(root, "zmax_data", "ar_rs", "fences.json")
    try:
        with open(fp, encoding="utf-8") as fh:
            fd = json.load(fh) or {}
    except Exception:                                                       # noqa: BLE001
        fd = {"items": []}
    items = fd.get("items") or []
    pos = [float(v) for v in t["pos"]]
    q = t.get("quat") or [1.0, 0.0, 0.0, 0.0]
    R = _q_to_R(q)
    tip = [pos[i] + 0.072 * R[i, 0] for i in range(3)]          # 长轴另一端 (画出方向)
    slot_txt = (("左臂·左槽%d" if _isL else "右臂·槽%d") % t["slot"]) if t.get("slot") else "融合位姿"
    _fid = "TP2" if _isL else "TP1"
    it = {"id": _fid, "type": "points", "name": "🎯目标位姿 " + slot_txt,
          "arm": "L" if _isL else "R",
          "p1": [round(v, 5) for v in pos],
          "p2": [round(v, 5) for v in tip],
          "pts": [[round(v, 5) for v in pos], [round(v, 5) for v in tip]],
          "color": ("#4da3ff" if _isL else "#ffd23f"), "enabled": True, "n": 2,
          "note": "测地线规划引导·%s臂目标位姿 | %s" % (("左" if _isL else "右"), t.get("src")),
          "at": time.strftime("%F %T"),
          # 前端据此画带旋转的模块盒 + 三轴 (尺寸 mm)
          "pose": {"pos_m": pos, "quat": [round(float(v), 6) for v in q],
                   "dims_mm": [72.0, 18.35, 8.5],
                   "approach": t.get("approach"), "pre_pos_mm": t.get("pre_pos_mm"),
                   "valid": bool(t.get("valid")), "src": t.get("src"),
                   "slot": t.get("slot"), "arm": "L" if _isL else "R",
                   "label": ("左臂·左槽%d" if _isL else "右臂·槽%d") % t["slot"] if t.get("slot") else "融合位姿",
                   "ts": round(time.time(), 3)}}
    items = [x for x in items if str(x.get("id")) != _fid] + [it]
    fd["items"] = items
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    try:
        import shutil as _sh
        _sh.copy2(fp, fp + ".bak_targetpose")
    except Exception:                                                       # noqa: BLE001
        pass
    tmp2 = fp + ".tmp"
    with open(tmp2, "w", encoding="utf-8") as fh:
        json.dump(fd, fh, ensure_ascii=False, indent=1)
    os.replace(tmp2, fp)
    out["fence"] = {"file": fp, "id": "TP1", "items": len(items)}
    return out


# ── 📈 时间参数化平滑轨迹 (2026-10-29 老倪: 「要动作与回放的 UPH 轨迹一样平顺, 而且要由 L2 节点实际发出」) ──
#   为什么要它: 站内原来是 10Hz P 环 + 每拍重算速度 + 每拍 IK ⇒ 段首跳支/段间硬切/终点 snap,
#   实测右臂每拍 13~660mm 的台阶。UPH 之所以顺 = 它按**时间**插值 (u = t_in_seg / seg_t)。
#   这里把同一套"时间参数化"做成 L2 节点的输出: 五次多项式 S 曲线 (C2 连续, 首末加速度=0),
#   峰值速度/加速度由段标定 v_cap / a_max 反解 T ⇒ 轨迹本身就是平顺的, 执行端只按时间采样回放。
#   真源: v_cap = zmax_skill_physics.json 的段速度上限; a_max = F/m (同文件), 这里默认 2.0 m/s²。
def smooth_traj(p0, p1, v_cap=0.35, a_max=2.0, dt=0.02, min_T=None):
    """p0→p1 的 S 曲线轨迹 (五次多项式 s=10t³-15t⁴+6t⁵)。
    峰值: |v|max = 1.875·L/T, |a|max = 5.7735·L/T² ⇒ 反解 T ≥ max(1.875L/v_cap, √(5.7735L/a_max))。
    返回 {ok,T,dt,n,L_mm,v_peak_mm_s,a_peak_m_s2,pts[[x,y,z]…],vel[[vx,vy,vz]…],src}
    """
    import math as _m
    import numpy as _np
    a0 = _np.asarray(p0, float).ravel()[:3]
    a1 = _np.asarray(p1, float).ravel()[:3]
    if a0.size != 3 or a1.size != 3 or not (_np.all(_np.isfinite(a0)) and _np.all(_np.isfinite(a1))):
        return {"ok": False, "err": "端点非法"}
    d = a1 - a0
    L = float(_np.linalg.norm(d))
    if L < 1e-6:
        return {"ok": True, "T": 0.0, "dt": dt, "n": 1, "L_mm": 0.0,
                "v_peak_mm_s": 0.0, "a_peak_m_s2": 0.0, "pts": [a0.tolist()], "vel": [[0.0, 0.0, 0.0]],
                "src": "L2 n_geoplan.smooth_traj (零位移)"}
    v = max(0.02, float(v_cap))
    am = max(0.1, float(a_max))
    T = max(1.875 * L / v, _m.sqrt(5.7735 * L / am))
    if min_T:
        T = max(T, float(min_T))
    n = int(_m.ceil(T / dt)) + 1
    pts, vel = [], []
    for k in range(n):
        tau = min(1.0, k * dt / T)
        s = 10 * tau ** 3 - 15 * tau ** 4 + 6 * tau ** 5
        ds = (30 * tau ** 2 - 60 * tau ** 3 + 30 * tau ** 4) / T
        pts.append([round(float(x), 6) for x in (a0 + d * s)])
        vel.append([round(float(x), 6) for x in (d * ds)])
    return {"ok": True, "T": round(T, 4), "dt": dt, "n": n,
            "L_mm": round(L * 1000, 1),
            "v_peak_mm_s": round(1.875 * L / T * 1000, 1),
            "a_peak_m_s2": round(5.7735 * L / (T * T), 3),
            "pts": pts, "vel": vel,
            "src": "L2 n_geoplan.smooth_traj (S 曲线 五次多项式 C2)"}


def _quat_from_rot(flat):
    """obs[24:33] 的 3x3 旋转 (行主序) → [qw,qx,qy,qz]; 退化 (全 0/非正交) 返回 None。"""
    try:
        m = np.asarray(flat, float).ravel()[:9].reshape(3, 3)
    except Exception:                                                    # noqa: BLE001
        return None
    if not np.all(np.isfinite(m)) or abs(float(np.linalg.det(m))) < 1e-6:
        return None
    tr = float(m[0, 0] + m[1, 1] + m[2, 2])
    if tr > 0:
        s = (tr + 1.0) ** 0.5 * 2
        w, x = 0.25 * s, (m[2, 1] - m[1, 2]) / s
        y, z = (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = (1.0 + m[0, 0] - m[1, 1] - m[2, 2]) ** 0.5 * 2
        w, x = (m[2, 1] - m[1, 2]) / s, 0.25 * s
        y, z = (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = (1.0 + m[1, 1] - m[0, 0] - m[2, 2]) ** 0.5 * 2
        w, x = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s
        y, z = 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = (1.0 + m[2, 2] - m[0, 0] - m[1, 1]) ** 0.5 * 2
        w, x = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s
        y, z = (m[1, 2] + m[2, 1]) / s, 0.25 * s
    q = np.array([w, x, y, z], float)
    n = float(np.linalg.norm(q))
    return [round(float(v / n), 5) for v in q] if n > 1e-9 else None


def _craft(ctx=None):
    """工艺步骤 (元任务/第几步/推进判决) —— 委托工艺引擎 sched_impl.run(), 失败不拖垮引导。"""
    global _CRAFT
    try:
        from lerobot.middleware.nodes.impl import sched_impl as _S
        o = _S.run(ctx or {})
        _CRAFT = {"out1": o.get("out1"), "out2": o.get("out2"), "out3": o.get("out3")}
    except Exception as exc:                                            # noqa: BLE001
        _CRAFT = {"err": "%s: %s" % (type(exc).__name__, exc)}
    return _CRAFT


def _run_guides(ctx=None):
    """一个周期: obs43 → 测地线块 [H,4]。只规划, 不下发。"""
    out = {"node": "n_geoplan", "impl": "state_space/plan_guide.py:run", "h": H_DEF}
    obs = _obs(ctx)
    if obs is None:
        out.update({"ok": False, "err": "无 obs43 输入 (ctx['in1'] 需 43 维: obs[:39] + 触觉4)"})
        return out
    eng = _engine()
    if eng is None:
        out.update({"ok": False, "err": "引擎不可用: %s" % (_ENG_ERR or "ManifoldEngine 未建立")})
        return out
    try:
        p_now = eng.project(obs)
    except Exception as exc:                                             # noqa: BLE001
        out.update({"ok": False, "err": "project 失败: %s: %s" % (type(exc).__name__, exc)})
        return out
    p_now = (p_now or {}).get("p") if isinstance(p_now, dict) else p_now
    if p_now is None:
        out.update({"ok": False, "err": "project 返回空 (无潜空间坐标)"})
        return out
    gs = _goal_state(obs, ctx)
    try:
        gp = eng.project(gs)
        gp = (gp or {}).get("p") if isinstance(gp, dict) else gp
        if gp is None:
            out.update({"ok": False, "err": "目标态 project 返回空"})
            return out
        eng.goal_point = gp
        nav = eng.navigator.compute_geodesic(np.asarray(p_now, float).ravel(),
                                            np.asarray(gp, float).ravel(), H_DEF)
        path = np.asarray(nav["path"], float)
        act = []
        decode = "占位解码(未标定)"
        for p in path:
            if getattr(eng, "readout", None) is not None:
                a = np.asarray(p, float) @ eng.readout + eng.readout_b
                if getattr(eng, "action_lo", None) is not None:
                    a = np.clip(a, eng.action_lo, eng.action_hi)
                decode = "ridge 解码(限幅)"
            else:
                a = np.asarray(p, float)[:ACTION_DIM]
                decode = "占位解码(未标定)"
            act.append(np.asarray(a, float).ravel()[:ACTION_DIM])
        chunk = np.asarray(act, float)
    except Exception as exc:                                             # noqa: BLE001
        out.update({"ok": False, "err": "测地线规划失败: %s: %s" % (type(exc).__name__, exc)})
        return out
    # ── 唯一目标 3D 引导位姿: 全周期只认一个目标, 引导步/朝向量都由它派生 ──────────
    tcp = np.asarray(obs[0:3], float)
    peg = np.asarray(obs[4:7], float)
    hole = np.asarray(obs[36:39], float)
    use_hole = float(np.linalg.norm(hole - peg)) > 0.005
    tgt = target_pose(ctx, obs)
    if not tgt.get("ok"):
        out.update({"ok": False, "err": "目标位姿不可用: %s" % tgt.get("err")})
        return out
    goal_pos = np.asarray(tgt["pos"], float)                 # 抓取目标点本身 (不再自己加 hover)
    v_cap = float(os.environ.get("ZMAX_GUIDE_V_CAP", "0.35"))
    dt = float(os.environ.get("ZMAX_GUIDE_DT", "0.1"))
    d = goal_pos - tcp
    dist = float(np.linalg.norm(d))
    u = d / dist if dist > 1e-9 else np.zeros(3)
    cu = np.asarray(chunk[0][:3], float)
    cn = float(np.linalg.norm(cu))
    cos = float((cu / cn) @ u) if cn > 1e-9 else 0.0
    step = min(dist, v_cap * dt)
    guide_pos = tcp + u * step
    quat = tgt.get("quat") or _quat_from_rot(obs[24:33])
    out.update({"ok": True, "goal": [round(float(v), 5) for v in gs[36:39]],
                "p_now": [round(float(v), 5) for v in np.asarray(p_now, float).ravel()[:4]],
                "chunk": [[round(float(x), 5) for x in row] for row in chunk],
                "chunk0": [round(float(x), 5) for x in chunk[0]],
                "chunk_norm": round(float(np.linalg.norm(chunk[0][:3])), 5),
                "geodesic": nav.get("geodesic_kind"),
                "length": round(float(nav.get("length") or 0.0), 5),
                "decode": decode,
                "ckpt": os.path.relpath(CKPT, _ROOT) if os.path.exists(CKPT) else "(缺 ckpt)",
                # ★ 主输出: 唯一目标 3D 引导位姿 (要抓的那个位姿)
                "target_pose": tgt,
                "guide": {"pos_m": [round(float(v), 5) for v in guide_pos],
                          "pos_mm": [round(float(v) * 1000.0, 1) for v in guide_pos],
                          "quat": quat,
                          "axis": [round(float(v), 4) for v in u],
                          "cos_geodesic": round(cos, 3),
                          "step_mm": round(step * 1000.0, 1),
                          "dist_mm": round(dist * 1000.0, 1),
                          "tgt_src": tgt.get("src"),
                          "tgt_valid": bool(tgt.get("valid")),
                          "dir_src": ("测地线一致 (cos≥0.3)" if cos >= 0.3
                                      else "几何(目标位姿)主导: 测地线方向不一致 cos=%.2f" % cos),
                          "quat_src": ("目标位姿(融合模块 peg_quat)" if tgt.get("quat")
                                       else "姿态槽无效 ⇒ 保持当前姿态")},
                "insert_target": ({"pos_mm": [round(float(v) * 1000.0, 1) for v in hole]}
                                  if use_hole else None),
                # 下游「运动规划」(n_moveit) 认 ctx["in1"]["value"]["tcp"](mm)
                "value": {"tcp": [round(float(v) * 1000.0, 1) for v in guide_pos],
                          "pos_mm": [round(float(v) * 1000.0, 1) for v in guide_pos],
                          "target_pose": {"pos_mm": tgt.get("pos_mm"),
                                          "quat": tgt.get("quat"),
                                          "approach": tgt.get("approach"),
                                          "pre_pos_mm": tgt.get("pre_pos_mm"),
                                          "valid": tgt.get("valid"),
                                          "src": tgt.get("src")},
                          "frame": "base_link",
                          "src": "测地线规划引导 (唯一目标位姿 + 测地线方向)"}})

    return out


# ── 理想规划档 (2026-11-01 老倪: 「再从测地线规划引导节点给出理想规划, 保证300UPH, 保证L2的设计逻辑」)
#   现场没有 obs43 落盘 ⇒ 正常档 _run_guides 出不来 (ok=False, 直通)。
#   理想档不假装吃了 obs43: 几何取**执行器同一生成器** cycle_plan 的稳态段表 (与「全流程 UPH」逐段一致),
#   段内用 S² 大圆测地线采样出块 chunk[H,4] —— 输出仍走本节点的口语义 out1(引导位姿)/out2(块),
#   下游 sslimit/sssched 不用改。时序按理想剖面重计时 (抬升/横移 1000, 下落/插入/拔 300)。
IV_FAST, IA_FAST = 1000.0, 4000.0
IV_SLOW, IA_SLOW = 300.0, 2000.0
IPROC = ("insert", "grip", "release")
_IDEAL_CACHE = {"ts": 0.0, "doc": None}


def _ideal_on(ctx=None):
    """是否走理想档: ctx.params.ideal 或环境变量 ZMAX_GEO_IDEAL=1。"""
    try:
        pr = (ctx or {}).get("params") or {}
        if str((pr.get("ideal") if isinstance(pr, dict) else "")).lower() in ("1", "true", "on", "yes"):
            return True
    except Exception:                                                   # noqa: BLE001
        pass
    return os.environ.get("ZMAX_GEO_IDEAL", "0").strip().lower() in ("1", "true", "on", "yes")


def _seg_time(d_mm, kind):
    slow = kind in ("down", "insert", "pull")
    v, a = (IV_SLOW, IA_SLOW) if slow else (IV_FAST, IA_FAST)
    if d_mm <= 1e-9:
        return 0.0
    if d_mm > v * v / a:
        return d_mm / v + v / a
    return 2.0 * math.sqrt(d_mm / a)


def _geodesic_s2(a, b, h):
    """S² 大圆测地线: 方向 slerp + 半径线性 ⇒ 段内 h 个引导点 (mm)。"""
    ra = math.sqrt(sum(x * x for x in a)) or 1.0
    rb = math.sqrt(sum(x * x for x in b)) or 1.0
    ua = [x / ra for x in a]
    ub = [x / rb for x in b]
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(ua, ub))))
    om = math.acos(dot)
    out = []
    for i in range(h):
        t = 0.0 if h == 1 else i / (h - 1)
        r = ra + (rb - ra) * t
        if om < 1e-6:
            d = ua
        else:
            s1 = math.sin((1 - t) * om) / math.sin(om)
            s2 = math.sin(t * om) / math.sin(om)
            d = [s1 * x + s2 * y for x, y in zip(ua, ub)]
        n = math.sqrt(sum(x * x for x in d)) or 1.0
        out.append([d[0] / n * r, d[1] / n * r, d[2] / n * r])
    return out


def build_ideal_plan(h=8, refresh=60.0):
    """理想规划段表 (几何=执行器同一 cycle_plan 稳态窗口, 时序=理想剖面)。缓存 refresh 秒。"""
    now = time.time()
    if _IDEAL_CACHE["doc"] and now - _IDEAL_CACHE["ts"] < refresh:
        return _IDEAL_CACHE["doc"]
    from lerobot.middleware.nodes.impl import cycle_plan as _cp                                           # noqa: PLC0415
    doc = _cp.build()
    P = doc.get("plan") or doc.get("segments") or []
    L = doc.get("loop") or {}
    ks = L.get("ks") or [2, 3]
    # ⚠️ 段表里的 'k' 是**轮次号**(1,2,3…), loop.ks 比的是它; 动作类型在 'kind' —— 别混。
    kk = lambda s: s.get("k")                                                 # noqa: E731
    i0 = next(i for i, s in enumerate(P) if kk(s) == ks[0])
    i1 = max(i for i, s in enumerate(P) if kk(s) == ks[1])
    W = P[i0:i1 + 1]
    mods = int(L.get("mods") or 4)
    segs, clock = [], 0.0
    for s in W:
        kind = s.get("kind") or "move"
        a, b = s.get("a"), s.get("b")
        d = math.dist(a, b) if (a and b) else 0.0
        t = float(s.get("t") or 0.0) if (kind in IPROC or d <= 1e-9) else _seg_time(d, kind)
        pts = _geodesic_s2(a, b, h) if d > 1e-9 else [[a[0], a[1], a[2]] for _ in range(h)]
        chunk = [[round(p[0], 2), round(p[1], 2), round(p[2], 2),
                  round(t * (i / (h - 1)), 4) if h > 1 else 0.0] for i, p in enumerate(pts)]
        segs.append(dict(i=len(segs) + 1, kind=kind, label=s.get("label"), a=a, b=b,
                         len_mm=round(d, 1), t=round(t, 3), t0=round(clock, 3),
                         src_t=round(float(s.get("t") or 0.0), 3), chunk=chunk))
        clock += t
    tact = clock / mods if mods else clock
    doc = dict(ok=True, src="cycle_plan.build() 稳态窗口 loop.ks=%s" % (ks,),
               model=dict(v_fast=IV_FAST, a_fast=IA_FAST, v_slow=IV_SLOW, a_slow=IA_SLOW, H=h),
               cycle_s=round(clock, 3), tact_s=round(tact, 4),
               uph=round(3600.0 / tact, 1) if tact else 0.0, mods=mods, n_seg=len(segs),
               move_s=round(sum(x["t"] for x in segs if x["kind"] not in IPROC), 3),
               proc_s=round(sum(x["t"] for x in segs if x["kind"] in IPROC), 3),
               ok300=bool(tact and 3600.0 / tact >= 300.0), margin_s=round(12.0 - tact, 4),
               segs=segs)
    _IDEAL_CACHE.update(ts=now, doc=doc)
    return doc


def ideal_run(ctx=None):
    """理想档一个周期: 按时间取当前段 → out1 引导位姿, out2 块 chunk[H,4]。只规划不下发。"""
    h = int(((ctx or {}).get("params") or {}).get("H") or 8)
    doc = build_ideal_plan(h=h)
    el = time.time() % max(1e-6, doc["cycle_s"])          # 循环内相位
    cur = doc["segs"][-1]
    for s in doc["segs"]:
        if el <= s["t0"] + s["t"]:
            cur = s
            break
    u = 0.0 if cur["t"] <= 0 else min(1.0, max(0.0, (el - cur["t0"]) / cur["t"]))
    pos = [cur["a"][i] + (cur["b"][i] - cur["a"][i]) * u for i in range(3)]
    # 🧾 老倪 2026-11-01「规划引导只要发出工艺动作即可」:
    #   本节点对外的主口径 = **工艺动作** (第几步/什么动作/中文名/去哪/耗时/进度),
    #   不是 3D 位姿。tcp 只留作参考字段 (渲染/核对用), 下游按工艺动作推进。
    out1 = {"step_i": cur["i"], "step_n": doc["n_seg"],
            "action": cur["kind"], "label": cur["label"],
            "target_mm": [round(float(v), 2) for v in cur["b"]],
            "t_seg": cur["t"], "t0": cur["t0"], "u": round(u, 4),
            "carry": cur.get("carry_to"),
            "cycle_s": doc["cycle_s"], "tact_s": doc["tact_s"], "uph": doc["uph"],
            "ok300": doc["ok300"],
            "craft": {"craft_action": "%d/%d %s" % (cur["i"], doc["n_seg"], cur["label"] or cur["kind"]),
                      "action": cur["kind"], "target": [round(float(v), 2) for v in cur["b"]],
                      "dur_s": cur["t"], "prog": round((cur["t0"] + u * cur["t"]) / max(1e-9, doc["cycle_s"]), 4)},
            "tcp": [round(v, 2) for v in pos],
            "seg_i": cur["i"], "seg_n": doc["n_seg"], "kind": cur["kind"],
            # 理想档同样只给一个目标位姿 (姿态未参与理想规划 ⇒ quat=None, 明写不假装)
            "target_pose": {"pos_mm": [round(float(v), 2) for v in cur["b"]], "quat": None,
                            "approach": [0.0, 0.0, -1.0], "valid": False, "slot": None,
                            "src": "geo_ideal 段目标 (姿态未定)"},
            "src": "geo_ideal(测地线引导·工艺动作)"}
    out2 = {"H": h, "chunk": cur["chunk"], "seg_i": cur["i"], "kind": cur["kind"]}
    # 📄 落一份可观测产物 (常驻循环里没有日志行也能核对: 龄/段号/UPH 实时)
    try:
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))))   # src/lerobot/engineering/nodes/ → 仓库根
        _p = os.path.join(_root, "zmax_data", "ss_live", "geo_ideal_live.json")
        _tmp = _p + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as _fh:
            json.dump({"ts": time.time(), "t_str": time.strftime("%H:%M:%S"),
                       "step_i": cur["i"], "step_n": doc["n_seg"], "action": cur["kind"],
                       "label": cur["label"], "u": round(u, 4),
                       "target_mm": out1["target_mm"], "t_seg": cur["t"],
                       "craft_action": out1["craft"]["craft_action"],
                       "prog": out1["craft"]["prog"],
                       "cycle_s": doc["cycle_s"], "tact_s": doc["tact_s"], "uph": doc["uph"],
                       "ok300": doc["ok300"], "src": "geo_ideal(测地线引导·理想档)"},
                      _fh, ensure_ascii=False)
        os.replace(_tmp, _p)
    except Exception:                                                       # noqa: BLE001
        pass
    return {"out1": {"value": out1, "age_s": 0.0, "fresh": True},
            "out2": {"value": out2, "age_s": 0.0, "fresh": True},
            "ok": True, "ideal": True, "cycle_s": doc["cycle_s"], "tact_s": doc["tact_s"],
            "uph": doc["uph"], "ok300": doc["ok300"], "n_seg": doc["n_seg"],
            "status": "理想规划 %d 段 · 循环 %.2f s · 节拍 %.3f s/件 · %.0f UPH %s"
                      % (doc["n_seg"], doc["cycle_s"], doc["tact_s"], doc["uph"],
                         "≥300 ✓" if doc["ok300"] else "<300 ✗")}


def run(ctx=None):
    """🧭 测地线规划引导 = 3D 引导位姿 + 块 + **工艺步骤** (老倪 2026-11-01: 本节点负责工艺规划)。

    三条输出一起出, 下游各取所需:
      · out1.value.tcp     → 运动规划 n_moveit 认的引导位姿 (mm)
      · out2 (chunk)       → 加权/动作调制器
      · out1.craft         → 工艺步骤: 元任务/第几步/推进判决 (来自工艺引擎 sched_impl)
    工艺引擎坏了不影响引导位姿 (craft.err 明示, 不静默丢)。
    """
    if _ideal_on(ctx):
        out = ideal_run(ctx)
        try:
            c = _craft(ctx)
            # ⚠️ 别覆盖 out1.craft: 理想档的 craft 就是**本节点发出的工艺动作** (主口径)。
            #   工艺引擎 (sched_impl) 的结果另放 craft_engine, 两件事分开看。
            out["craft_engine"] = {"step": c.get("out1"), "progress": c.get("out2"),
                                   "event": c.get("out3"), "err": c.get("err")}
            if isinstance(c.get("out1"), dict):
                out["out1"]["value"]["craft_engine"] = c["out1"]
        except Exception as _e:                                         # noqa: BLE001
            out["craft"] = {"err": str(_e)[:120]}
        try:                                                            # 🤝 双臂协同 (理想档也要有)
            _d = dual_arm_guide(ctx)
            out["out3"] = {"value": _d.get("L"), "pair_id": _d.get("pair_id"), "arm": "L",
                           "ts": _d.get("ts"), "valid": bool((_d.get("L") or {}).get("ok")),
                           "age_s": 0.0, "fresh": True}
            out["out4"] = {"value": _d, "age_s": 0.0, "fresh": True}
            _o1 = out.get("out1")
            if isinstance(_o1, dict) and isinstance(_o1.get("value"), dict):
                _o1["value"].update({"pair_id": _d.get("pair_id"), "arm": "R",
                                     "pair_valid": _d.get("pair_valid"), "hold": _d.get("hold"),
                                     "peer_grasp_mm": (_d.get("L") or {}).get("grasp_mm"),
                                     "dual_truth": _d.get("dual_truth")})
        except Exception as _e2:                                        # noqa: BLE001
            out["out4"] = {"value": {"ok": False, "err": ("双臂协同失败: %s" % _e2)[:160]},
                           "age_s": 0.0, "fresh": True}
        globals()["LAST_STATUS"] = out.get("status") or ""
        return out
    out = _run_guides(ctx)
    c = _craft(ctx)
    out["craft"] = {"step": c.get("out1"), "progress": c.get("out2"),
                    "event": c.get("out3"), "err": c.get("err")}
    if isinstance(out.get("value"), dict) and isinstance(c.get("out1"), dict):
        out["value"]["craft"] = c["out1"]
    # 端口必须真产 (画布: n_geoplan.out1→sslimit.in3 3D 引导位姿 / out2→sssched.in9 块)
    #   原来 _run_guides 的 value/chunk 是扁平键, 画布声明的两个端口全空 (2026-11-10 实测)
    if not any(str(k).startswith("out") for k in out):
        _v = out.get("value")
        if isinstance(_v, dict) and "tcp" in _v and "pos_mm" not in _v:
            _v = dict(_v, pos_mm=_v.get("tcp"))
        out["out1"] = {"value": _v, "age_s": 0.0, "fresh": True}
        _ch = out.get("chunk") or []
        out["out2"] = {"H": out.get("h"), "chunk": _ch,
                       "chunk0": (_ch[0] if _ch else None),
                       "seg_i": out.get("i"), "kind": out.get("kind"),
                       "age_s": 0.0, "fresh": True}
    # 🤝 双臂协同 (老倪 2026-11-22「这个功能, 代码写进测地线3D引导里」):
    #   out1 仍是**右臂**唯一目标 (下游 sslimit→n_moveit 不用改), 只多带 pair_id/arm/peer;
    #   out3 = 左臂目标位姿 (与 out1 同 pair_id 同 ts, 成对); out4 = 协同证据 (双真值/分区/hold/间距)。
    #   左臂没有控制器通道 ⇒ out3 目前只进观测/画布, 不下发。
    try:
        _d = dual_arm_guide(ctx)
        out["out3"] = {"value": _d.get("L"), "pair_id": _d.get("pair_id"), "arm": "L",
                       "ts": _d.get("ts"), "valid": bool((_d.get("L") or {}).get("ok")),
                       "age_s": 0.0, "fresh": True}
        out["out4"] = {"value": _d, "age_s": 0.0, "fresh": True}
        _o1 = out.get("out1")
        if isinstance(_o1, dict) and isinstance(_o1.get("value"), dict):
            _o1["value"].update({"pair_id": _d.get("pair_id"), "arm": "R",
                                 "pair_valid": _d.get("pair_valid"), "hold": _d.get("hold"),
                                 "peer_grasp_mm": (_d.get("L") or {}).get("grasp_mm"),
                                 "dual_truth": _d.get("dual_truth")})
    except Exception as _e:                                             # noqa: BLE001
        out["out4"] = {"value": {"ok": False, "err": ("双臂协同失败: %s" % _e)[:160]},
                       "age_s": 0.0, "fresh": True}
    return out


LAST_STATUS = ""
