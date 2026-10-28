#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ar_aoi_bus.py — AR 场景 · 空间点位 + AOI 话题 信号总线 (单一点唯一依据 → 信号分析)

老倪 2026-10-11: 「状态空间工程里 外观质量检测 节点改名成 光学质量检测, **发出 AOI 相关的所有 topic**,
信号分析对应 **AR 场景下的所有空间点位置**」。

设计 (为什么这么落):
  · 「话题」在本平台 = 数据总线上的**信号**; 控制台「📈 信号分析」按 **来源前缀** 分组显示
    (`sstrace.` / `ds.` / `ros.` …)。本模块新增来源前缀 **`ar.`**, 落一份真值文件
    `zmax_data/ar_live/ar_aoi_live.json`, 页面把它当第 N 个 HOST_SOURCE 读 (零协议改动)。
  · **不造假**: 每个信号的值都从**真实生产者**取 —— 机器人 TCP 真值 / 示教点位台账 /
    RealSense 服务(8797)实测 / 工控机 AOI(10082)判决。取不到的键**不写**(不是写 0), 并在 meta 里记原因。
  · 写盘: 原子写 + `.bak_<ts>` 备份 + 回读校验; 与工具链里其它唯一依据一致。
  · 注册表 `config/topics/ar_aoi_signals.json` 由本模块 `spec` 生成/刷新 (信号含义/单位/唯一依据)。

用法:
    gui-venv311/bin/python tools/ar_aoi_bus.py spec        # 刷新并打印注册表
    gui-venv311/bin/python tools/ar_aoi_bus.py pull        # 从各唯一依据抓一轮 → 写 live 文件
    gui-venv311/bin/python tools/ar_aoi_bus.py watch -i 2  # 常驻, 每 2s 抓一轮
    gui-venv311/bin/python tools/ar_aoi_bus.py show        # 看当前 live 值/帧龄
    gui-venv311/bin/python tools/ar_aoi_bus.py publish --json '{"光学质量检测.判决": 1}'
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "zmax_data", "ar_live", "ar_aoi_live.json")
REGISTRY = os.path.join(ROOT, "config", "topics", "ar_aoi_signals.json")
TCP = os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
# 🦾 真机六维力 (2026-10-20 老倪: 「末端执行器的 x y z 和 插拔的侧向力, 显示出来, 来自于真实的机器人」)
#   单一写入器 = tools/rokae/ft_direct_sampler.py (珞石 xCoreSDK forceControl().getEndTorque, 只读, 不发运动)
#   口径: 写的是**基座系**分量 (frame=world) —— 插入轴 = base +x ⇒ 侧向力 = hypot(fy, fz)。
#   本总线只做换算, 不在这一层猜坐标系: frame 不是 world/base 就拒用(宁可这条通道空着)。
SRC_FT = "rokae_xcoresdk/getEndTorque (direct, read-only)"
FT = os.path.join(ROOT, "zmax_data", "rokae_sdk", "ft_out", "latest.json")
TEACH_D = os.path.join(ROOT, "reports", "aoi_points")
SPACE = os.path.join(ROOT, "data", "skills", "l2_atomic", "space_points.json")
AOI_STATE = os.path.join(ROOT, "zmax_data", "ar_aoi_state.json")
AOI_CONSOLE_STATE = os.path.join(ROOT, "reports", "aoi_console_state.json")
AR_UP = "http://127.0.0.1:8797"

# ── 注册表: 信号 → (组, 单位, 唯一依据说明) ─────────────────────────────────────────────
G_AR_PTS = "AR·空间点位 (基座系)"
G_AR_CAM = "AR·相机 (RealSense D435 · 相机系)"
G_AOI_GF = "AOI·金手指 (工控机 10082)"
G_AOI_SURF = "AOI·表面 (工控机 10083)"
G_AOI_NODE = "AOI·状态空间节点 (光学质量检测)"
# 🤖 2026-10-20 老倪: 「AR 场景…把机器人的状态机接上, 可以直接看到是否在插拔」⇒ 机器人状态机独立成组
G_ROBOT = "AR·机器人状态机 (插拔判定)"

SPEC = [
    # —— AR 空间点位 (基座系, 全部来自真值/台账) ——
    ("末端.x", G_AR_PTS, "m", "机器人 TCP 真值 zmax_data/rokae_sdk/tcp_out/latest.json (base_link, 50Hz)"),
    ("末端.y", G_AR_PTS, "m", "同上"),
    ("末端.z", G_AR_PTS, "m", "同上"),
    ("末端.帧龄_s", G_AR_PTS, "s", "TCP 真值文件写龄 (>1s 视为陈旧)"),
    ("金手指点1.x", G_AR_PTS, "m", "示教台账 reports/aoi_points/金手指点1.json (aoi_teach_point.py 记录)"),
    ("金手指点2.x", G_AR_PTS, "m", "示教台账 reports/aoi_points/金手指点2.json"),
    ("侧面点0.x", G_AR_PTS, "m", "示教台账 reports/aoi_points/侧面点0.json"),
    ("侧面点1.x", G_AR_PTS, "m", "示教台账 reports/aoi_points/侧面点1.json"),
    ("侧面点2.x", G_AR_PTS, "m", "示教台账 reports/aoi_points/侧面点2.json"),
    ("侧面点3.x", G_AR_PTS, "m", "示教台账 reports/aoi_points/侧面点3.json"),
    ("准备点.x", G_AR_PTS, "m", "示教台账 reports/aoi_points/准备点.json"),
    ("安全点1.x", G_AR_PTS, "m", "示教台账 reports/aoi_points/安全点1.json"),
    ("空间点1.x", G_AR_PTS, "m", "空间点唯一依据 data/skills/l2_atomic/space_points.json (真机实测 7 点)"),
    ("空间点7.x", G_AR_PTS, "m", "同上 (1~7 全套)"),
    ("叠加.点位数", G_AR_PTS, "个", "本轮实际载入的空间点数 (缺谁不补)"),
    # —— 插拔过程信号 (2026-10-20 老倪: 「把信号分析的 插拔的切向力、末端 x y z 速度, 加到信号波形上」) ——
    ("末端.vx", G_AR_PTS, "mm/s", "TCP 真值差分: latest.json 相邻两帧 (x2-x1)/Δt"),
    ("末端.vy", G_AR_PTS, "mm/s", "同上 (y 分量)"),
    ("末端.vz", G_AR_PTS, "mm/s", "同上 (z 分量)"),
    ("末端.切向力_N", G_AR_PTS, "N", "DDS zmax/ss_force_l2 的 x 分量 (插入轴 = base +x); 驱动无读数时不写该键。命名避开\"插拔\"二字: 信号名里出现插拔会被场景规则染成插拔场景绿"),
    # —— 🦾 真机六维力 (只来自机器人本身, 不是平台自算力) ——
    ("末端.轴向力_N", G_AR_PTS, "N", "真机六维力 fx (基座系 +x = 插入轴) ← zmax_data/rokae_sdk/ft_out/latest.json (tools/rokae/ft_direct_sampler.py, xCoreSDK getEndTorque, 只读); 力未接/陈旧时不写该键"),
    ("末端.侧向力_N", G_AR_PTS, "N", "真机六维力 侧向合力 = hypot(fy, fz) (垂直于插入轴, 基座系) ← 同上; 力未接/陈旧时不写该键"),
    ("末端.侧向力y_N", G_AR_PTS, "N", "真机六维力 fy (带符号, 基座系; 侧向左右) ← 同上"),
    ("末端.侧向力z_N", G_AR_PTS, "N", "真机六维力 fz (带符号, 基座系; 侧向上下) ← 同上"),
    ("末端.力帧龄_s", G_AR_PTS, "s", "六维力真值文件写龄 (>1s 视为陈旧); 采样器不在跑 ⇒ 不写(波形空), 不写 0 冒充"),
    # —— 六维力六分量全量 (老倪 2026-10-20 19:1x: 「三力三力矩齐全, 你把这些加入信号分析窗口」) ——
    ("末端.力x_N", G_AR_PTS, "N", "真机六维力 fx (基座系 +x = 插入轴/轴向) ← ft_out/latest.json ← xCoreSDK getEndTorque 只读 10Hz"),
    ("末端.力y_N", G_AR_PTS, "N", "真机六维力 fy (带符号, 基座系; 侧向左右)"),
    ("末端.力z_N", G_AR_PTS, "N", "真机六维力 fz (带符号, 基座系; 侧向上下)"),
    ("末端.力矩x_Nm", G_AR_PTS, "Nm", "真机六维力矩 tx (基座系) ← 同一帧, 与力同源同刻"),
    ("末端.力矩y_Nm", G_AR_PTS, "Nm", "真机六维力矩 ty (基座系)"),
    ("末端.力矩z_Nm", G_AR_PTS, "Nm", "真机六维力矩 tz (基座系)"),
    # —— 🤖 机器人状态机 (老倪 2026-10-20: 直接看到"是否在插拔") ——
    ("机器人.状态_码", G_ROBOT, "0=未连接/1=急停报警/2=未使能(伺服off)/3=手动/4=自动待机/5=自动运行",
     "tools/robot_state.py snapshot(): 控制器三查 tcp_out/state.json + 位姿 latest.json + 阶段 ss_live/skill_dispatch.json"),
    ("机器人.插拔中", G_ROBOT, "0=否/1=是",
     "当前阶段 ∈ {插入,拔出,插拔} 或 执行技能名含 insert/pull/插入 ⇒ 1; 阶段拿不到时不写该键(未知≠否)"),
    ("机器人.运动中", G_ROBOT, "0=停/1=动", "TCP 真值差分实测速度 >1mm/s (或控制器 op!=idle); 未连接时不写"),
    ("机器人.阶段_码", G_ROBOT, "0..7=接近/对位/下降/抓取/抬起/转移/插入/完成 · -1=未知",
     "ss_live/skill_dispatch.json stage (chunk_pipeline 每拍写) → 备路 skill_gate.json"),
    ("机器人.报警数", G_ROBOT, "个", "state.json n_err_recent = **历史**报警条数(不代表当前故障); 当前急停看 机器人.状态_码=1"),
    ("机器人.状态帧龄_s", G_ROBOT, "s", "state.json 写龄 (>5s 判未连接)"),
    # —— AR 相机 (RealSense, 相机系) ——
    ("相机.目标_x_m", G_AR_CAM, "m", "AR 服务 8797 /api/rs_pose (深度真值; 相机系, 非基座系)"),
    ("相机.目标_y_m", G_AR_CAM, "m", "同上"),
    ("相机.目标_z_m", G_AR_CAM, "m", "同上"),
    ("相机.深度_m", G_AR_CAM, "m", "同上一轮 (深度中位)"),
    ("相机.有效深度比", G_AR_CAM, "-", "同上 (有效深度点数/ROI 点数)"),
    ("相机.平面RMS_mm", G_AR_CAM, "mm", "同上 (PCA 平面残差, 反映面平整度)"),
    ("相机.帧数", G_AR_CAM, "帧", "AR 服务 /api/rs_info 累计帧数"),
    ("相机.帧龄_s", G_AR_CAM, "s", "AR 服务 /api/rs_info 最新帧龄"),
    ("相机.曝光_us", G_AR_CAM, "us", "AR 服务 /api/rs_exposure (设备回读真值)"),
    ("相机.增益", G_AR_CAM, "-", "同上"),
    # —— AOI 金手指 (工控机 10082, 判决/矩形/侧边修正) ——
    ("AOI.判决", G_AOI_GF, "0=OK/1=NG/2=未检", "工控机 10082 GET /last_result (经 8797 /api/aoi/inspect 落 zmax_data/ar_aoi_state.json)"),
    ("AOI.缺陷数", G_AOI_GF, "个", "同上"),
    ("AOI.推理_ms", G_AOI_GF, "ms", "同上 (工控机侧推理耗时)"),
    ("AOI.金手指根数", G_AOI_GF, "根", "工控机 /crop_info n_keys (逐帧会跳, 见技能 zmax-aoi-service)"),
    ("AOI.矩形中心_x", G_AOI_GF, "px", "工控机 /region quad → minAreaRect 中心"),
    ("AOI.矩形中心_y", G_AOI_GF, "px", "同上"),
    ("AOI.矩形宽_px", G_AOI_GF, "px", "同上 (minAreaRect)"),
    ("AOI.矩形高_px", G_AOI_GF, "px", "同上"),
    ("AOI.倾角_deg", G_AOI_GF, "deg", "同上 (minAreaRect 长边相对画面水平)"),
    ("AOI.侧边修正_dx_px", G_AOI_GF, "px", "工控机 /region 中心 vs 图心 → 侧边位置修正量 (px→mm 需现场雅可比)"),
    ("AOI.侧边修正_deg", G_AOI_GF, "deg", "同上 (反旋角 = -倾角)"),
    ("AOI.拍照_epoch", G_AOI_GF, "s", "本轮真拍时刻 (epoch)"),
    # —— AOI 表面 (10083) ——
    ("AOI.表面_判决", G_AOI_SURF, "0=OK/1=NG/2=未检", "工控机 10083 GET /last_result"),
    ("AOI.表面_缺陷数", G_AOI_SURF, "个", "同上"),
    # —— 状态空间「光学质量检测」节点自算 (本机 quality_check.py AOIQualityChecker) ——
    ("光学质量检测.判决", G_AOI_NODE, "0=PASS/1=FAIL", "画布节点「🔍 光学质量检测」运行时真调 src/lerobot/policies/yolo_3d/quality_check.py AOIQualityChecker.check()"),
    ("光学质量检测.缺陷数", G_AOI_NODE, "个", "同上 (实际=划伤数+污点数)"),
    ("光学质量检测.划伤数", G_AOI_NODE, "个", "同上 (scratch)"),
    ("光学质量检测.污点数", G_AOI_NODE, "个", "同上 (blob)"),
    ("光学质量检测.清晰度", G_AOI_NODE, "-", "同上 (focus = Var(∇²I); 低于 focus_min 判模糊 ⇒ 需重新对焦)"),
    ("光学质量检测.灰度偏差", G_AOI_NODE, "-", "同上 (gray_dev; 阈值判据)"),
    ("光学质量检测.边缘占比", G_AOI_NODE, "-", "同上 (edge_frac; 阈值判据)"),
    ("光学质量检测.取像体检", G_AOI_NODE, "0=ok/1=过曝/2=过暗/3=槽位冲白/4=未知", "同上 (quality.verdict; 取像不健康时先别谈缺陷判定)"),
]
KEYMAP = {k: (g, u, s) for k, g, u, s in SPEC}

# 组归属规则 (前缀 → 组): 台账里点位会增删, 按模式归组比逐条登记更稳 (spec 里的备注只覆盖核心信号)
GROUP_RULES = (
    ("AOI.表面", G_AOI_SURF),
    ("AOI.", G_AOI_GF),
    ("光学质量检测.", G_AOI_NODE),
    ("机器人.", G_ROBOT),
    ("相机.", G_AR_CAM),
    ("末端.", G_AR_PTS), ("金手指点", G_AR_PTS), ("侧面点", G_AR_PTS), ("准备点", G_AR_PTS),
    ("安全点", G_AR_PTS), ("空间点", G_AR_PTS), ("叠加.", G_AR_PTS),
)


def group_of(key):
    """信号 → 组名 (SPEC 优先, 否则按前缀规则)。"""
    if key in KEYMAP:
        return KEYMAP[key][0]
    for pre, g in GROUP_RULES:
        if key.startswith(pre):
            return g
    return "其它"


def unit_of(key):
    if key in KEYMAP:
        return KEYMAP[key][1]
    if key.endswith(".x") or key.endswith(".y") or key.endswith(".z") or "_m" in key:
        return "m"
    return "-"


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                             # noqa: BLE001
        return d


def _get_json(path, timeout=2.0):
    try:
        with urllib.request.urlopen(AR_UP + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:80])}


def _teach_points():
    """示教台账 → {(点名).x/y/z} (只收 pos 三轴齐的; 缺谁不补)。

    两种落盘格式都要认 (同一台账, 历史版本不同):
      · 新 (tools/aoi_teach_point.py 现写): 顶层 "point"/"pos"/"quat"
      · 旧: {"pose": {"pos": [...], "quat": [...]}} 且点名在 "name"
    """
    out, names, n = {}, [], 0
    if not os.path.isdir(TEACH_D):
        return out, names
    for fn in sorted(os.listdir(TEACH_D)):
        if not fn.endswith(".json") or ".history" in fn or ".retreat" in fn:
            continue
        d = _j(os.path.join(TEACH_D, fn)) or {}
        pos = d.get("pos")
        if not (isinstance(pos, list) and len(pos) == 3):
            pos = (d.get("pose") or {}).get("pos")
        if not (isinstance(pos, list) and len(pos) == 3):
            continue
        nm = str(d.get("point") or d.get("name") or fn[:-5])
        for ax, v in zip("xyz", pos):
            out["%s.%s" % (nm, ax)] = float(v)
        names.append(nm)
        n += 1
    return out, names


def _space_points():
    d = _j(SPACE, {}) or {}
    pts = d.get("points") or {}
    out = {}
    for nm, v in pts.items():
        pos = (v or {}).get("pos")
        if isinstance(pos, list) and len(pos) == 3:
            zh = ("空间点" + nm[5:]) if nm.startswith("space") and nm[5:].isdigit() else nm
            for ax, val in zip("xyz", pos):
                out["%s.%s" % (zh, ax)] = float(val)
    return out


def _aoi_state():
    d = _j(AOI_STATE, {}) or {}
    s, meta = {}, {}
    det = d.get("detect") or {}
    if det:
        v = (det.get("verdict") or "").upper()
        s["AOI.判决"] = {"OK": 0.0, "NG": 1.0, "FAIL": 1.0}.get(v, 2.0)
        if det.get("count") is not None:
            s["AOI.缺陷数"] = float(det["count"])
        if det.get("infer_ms") is not None:
            s["AOI.推理_ms"] = float(det["infer_ms"])
        cr = det.get("crop") or det.get("crop_info") or {}
        if isinstance(cr, dict) and cr.get("n_keys") is not None:
            s["AOI.金手指根数"] = float(cr["n_keys"])
    reg = d.get("region") or {}
    rect = reg.get("rect") or (reg.get("min_area_rect") or {})
    if isinstance(rect, dict) and rect:
        cx = rect.get("cx", rect.get("center", [None, None])[0] if isinstance(rect.get("center"), list) else None)
        cy = rect.get("cy", rect.get("center", [None, None])[1] if isinstance(rect.get("center"), list) else None)
        for key, val in (("AOI.矩形中心_x", cx), ("AOI.矩形中心_y", cy),
                         ("AOI.矩形宽_px", rect.get("w") or rect.get("width")),
                         ("AOI.矩形高_px", rect.get("h") or rect.get("height")),
                         ("AOI.倾角_deg", reg.get("angle_deg", rect.get("angle_deg")))):
            if val is not None:
                s[key] = float(val)
    sf = d.get("side_fix") or {}
    if isinstance(sf, dict):
        for key, val in (("AOI.侧边修正_dx_px", sf.get("dx_px")), ("AOI.侧边修正_deg", sf.get("angle_deg"))):
            if val is not None:
                s[key] = float(val)
    ts = d.get("epoch") or d.get("ts")
    if isinstance(ts, (int, float)):
        s["AOI.拍照_epoch"] = float(ts)
    elif isinstance(ts, str):
        try:
            s["AOI.拍照_epoch"] = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
        except Exception:                                                          # noqa: BLE001
            meta["AOI.拍照_epoch"] = "ts 字符串解析失败: %s" % ts
    surf = d.get("surface") or {}
    if surf:
        s["AOI.表面_判决"] = {"OK": 0.0, "NG": 1.0}.get((surf.get("verdict") or "").upper(), 2.0)
        if surf.get("count") is not None:
            s["AOI.表面_缺陷数"] = float(surf["count"])
    return s, meta, (d.get("ts") or "")


def _tcp():
    d = _j(TCP, {}) or {}
    s, meta = {}, {}
    for ax in "xyz":
        if d.get(ax) is not None:
            s["末端.%s" % ax] = float(d[ax])
    if d.get("ts"):
        age = time.time() - float(d["ts"])
        s["末端.帧龄_s"] = round(age, 3)
        if age > 1.0:
            meta["末端.*"] = "TCP 真值帧龄 %.2fs >1s (陈旧, 值照实给但别当实时)" % age
    return s, meta


CAM_ROI = "260,320,640,480"        # 料盘/台面区 (2026-10-11 视觉复核 + 区域 ROI 实测: 深度中位 1.000m/有效 93.7%)
                                   # 用工作区 ROI 而不是画面中心 —— 画面中心常落在桌面以上的背景(实测 2.2m)


def _ar_cam():
    s, meta = {}, {}
    pose = _get_json("/api/rs_pose?det=0&roi=" + CAM_ROI)
    if pose.get("ok"):
        c = pose.get("cam_center_mm") or [None, None, None]
        for k, v in (("相机.目标_x_m", c[0]), ("相机.目标_y_m", c[1]), ("相机.目标_z_m", c[2])):
            if v is not None:
                s[k] = round(float(v) / 1000.0, 4)
        if pose.get("depth_median_m") is not None:
            s["相机.深度_m"] = float(pose["depth_median_m"])
        if pose.get("valid_ratio") is not None:
            s["相机.有效深度比"] = float(pose["valid_ratio"])
        if pose.get("plane_rms_mm") is not None:
            s["相机.平面RMS_mm"] = float(pose["plane_rms_mm"])
    else:
        meta["相机.*"] = "AR 服务位姿不可用: %s" % (pose.get("err") or pose.get("err_rs") or "?")
    info = _get_json("/api/rs_info")
    if info.get("ok"):
        if info.get("frames") is not None:
            s["相机.帧数"] = float(info["frames"])
        if info.get("age_s") is not None:
            s["相机.帧龄_s"] = float(info["age_s"])
    exp = _get_json("/api/rs_exposure")
    if exp.get("ok"):
        if exp.get("exposure_us") is not None:
            s["相机.曝光_us"] = float(exp["exposure_us"])
        if exp.get("gain") is not None:
            s["相机.增益"] = float(exp["gain"])
    return s, meta


_VEL_CACHE = os.path.join(ROOT, "zmax_data", "ar_live", "_tcp_vel_cache.json")
_DDS_NODE = None


def _motion():
    """末端 x/y/z 速度: 用 TCP 真值相邻两帧差分 (同一份 latest.json, 不另采)。

    为什么缓存上一帧: 真值 50Hz, 而本总线 0.5~2Hz 拉一轮 ⇒ 每轮取到的都是"最新一帧",
    与上一轮比 Δt 可能是 0.5s(不是 20ms), 必须用真实 Δt 去除; 断流 >2s 不拿旧点硬算。
    """
    d = json.load(open(TCP, encoding="utf-8"))
    ts = float(d.get("ts") or 0)
    p = [float(d["x"]), float(d["y"]), float(d["z"])]
    out = {}
    try:
        prev = json.load(open(_VEL_CACHE, encoding="utf-8"))
    except Exception:                                                             # noqa: BLE001
        prev = None
    if prev and prev.get("p") and float(prev.get("ts") or 0) > 0:
        dt = ts - float(prev["ts"])
        if 0.002 <= dt <= 5.0:
            v = [(p[i] - float(prev["p"][i])) / dt * 1000.0 for i in range(3)]     # mm/s
            out["末端.vx"] = round(v[0], 3)
            out["末端.vy"] = round(v[1], 3)
            out["末端.vz"] = round(v[2], 3)
    try:
        json.dump({"ts": ts, "p": p}, open(_VEL_CACHE, "w", encoding="utf-8"))
    except Exception:                                                             # noqa: BLE001
        pass
    return out


_DDS_CACHE = {"t": 0.0, "v": None}
DDS_FORCE_EVERY_S = float(os.environ.get("ZMAX_DDS_FORCE_EVERY_S", "1.0"))


def _tangential_force():
    """插拔切向力 = DDS zmax/ss_force_l2 的 x 分量 (插入轴 = base +x)。

    诚实边界: 里萨如力控插入时力是**驱动内部闭环**执行的, 本机拿不到实时六维力;
    ss_force_l2 是本平台自己算的分层力(前馈加速器), 与驱动接触力不是同一个量。
    读不到就不写键(波形上该通道为空), 不写 0 冒充。
    """
    global _DDS_NODE
    if _DDS_NODE is None:
        sys.path.insert(0, os.path.join(ROOT, "dds"))
        os.environ.setdefault("CYCLONEDDS_URI", "file://%s/dds/cyclonedds_unicast.xml" % ROOT)
        from zmax_node import Node                                                # noqa: PLC0415
        _DDS_NODE = Node("ar_aoi_bus", domain=0)
    # 🔴 2026-10-20 老倪「信号分析总是断开, 保持信号连续」:
    #   take(timeout=0.30) 每轮阻塞 0.3s ⇒ pull() 全程 400ms ⇒ 总线最快 2Hz, 波形必然断成点。
    #   改: DDS 这一路**降频抓**(默认 1s 一次), 其余快源(六维力/位姿) 保持高频, 值用缓存。
    global _DDS_CACHE
    _now = time.time()
    if _DDS_CACHE.get("v") is None or _now - _DDS_CACHE.get("t", 0.0) >= DDS_FORCE_EVERY_S:
        # 首次要等 discovery(0.3s); 之后队列里没新帧就是空, 用 0.02s 立即返回 (否则每秒白等 0.3s ⇒ 波形卡顿)
        _to = 0.30 if _DDS_CACHE.get("v") is None else 0.02
        _DDS_CACHE = {"t": _now, "v": _DDS_NODE.take("ss_force_l2", timeout=_to) or []}
    msgs = _DDS_CACHE.get("v") or []
    if not msgs:
        return {}
    m = msgs[-1]
    # SSForceLayer 是 dataclass(不是 dict) ⇒ 用 getattr, 别用 .get()
    x = getattr(m, "x", None)
    if x is None:
        return {}
    out = {"末端.切向力_N": round(float(x), 4)}
    tx = getattr(m, "tx", None)
    if tx:
        out["插拔.力来源层"] = str(tx)[:16] if False else None  # 占位: 字符串不写数值通道
        out.pop("插拔.力来源层", None)
    return out


def _real_force():
    """🦾 真机六维力 → 轴向力 / 侧向力 (基座系, 插入轴 = base +x)。

    单一唯一依据 = `zmax_data/rokae_sdk/ft_out/latest.json`, 由 `tools/rokae/ft_direct_sampler.py`
    用珞石 xCoreSDK `forceControl().getEndTorque()` **只读**采样写出 (不发任何运动指令)。
    契约 (缺一项就整批不写, 绝不补 0):
      · frame ∈ {world, base, base_link}  —— 侧向力必须在基座系算, 工具系算出来是错量
      · 文件写龄 ≤ 1.0s                 —— 采样器停了就是没接, 波形该空着
      · fx/fy/fz 都在且是有限数
    信号名里**不出现「插拔/插入」**: 那两个词会被 sig_scene_tags 的关键词表染成插拔场景绿。
    """
    d = _j(FT, {}) or {}
    if not d:
        return {}, {"real_force": "未接: 无 %s (ft_direct_sampler.py 未运行 / 控制器 192.168.23.160 不在线)"
                          % os.path.relpath(FT, ROOT)}
    frame = str(d.get("frame") or "")
    if frame not in ("world", "base", "base_link"):
        return {}, {"real_force": "拒用: 力的参考系 = %r (侧向力只在基座系有物理意义)" % frame}
    ts = float(d.get("ts") or 0)
    age = time.time() - ts
    if age > 1.0:
        _why = str(d.get("err") or "")
        return {}, {"real_force": "未接: 力的真值帧龄 %.1fs > 1s%s"
                                 % (age, (" · 采样器最后错误: " + _why) if _why else " (采样器已停, 值不当实时用)")}
    fx, fy, fz = (d.get("fx"), d.get("fy"), d.get("fz"))
    if fx is None or fy is None or fz is None:
        return {}, {"real_force": "未接: 采样器报错 %s" % (d.get("err") or "缺 fx/fy/fz")}
    try:
        fx, fy, fz = float(fx), float(fy), float(fz)
    except Exception:                                                             # noqa: BLE001
        return {}, {"real_force": "未接: 力的分量不是数 (%r, %r, %r)" % (fx, fy, fz)}
    if not all(math.isfinite(v) for v in (fx, fy, fz)):
        return {}, {"real_force": "未接: 力的分量含 NaN/Inf"}
    tx = d.get("tx"); ty = d.get("ty"); tz = d.get("tz")
    out = {
        "末端.力帧龄_s": round(age, 3),
        "末端.力x_N": round(fx, 4),
        "末端.力y_N": round(fy, 4),
        "末端.力z_N": round(fz, 4),
        "末端.轴向力_N": round(fx, 4),                       # 插入轴 = base +x
        "末端.侧向力_N": round(math.hypot(fy, fz), 4),       # 垂直于插入轴的合力
        "末端.侧向力y_N": round(fy, 4),
        "末端.侧向力z_N": round(fz, 4),
    }
    if tx is not None and ty is not None and tz is not None:
        try:
            out["末端.力矩x_Nm"] = round(float(tx), 4)
            out["末端.力矩y_Nm"] = round(float(ty), 4)
            out["末端.力矩z_Nm"] = round(float(tz), 4)
        except Exception:                                                         # noqa: BLE001
            pass
    # ✅ 有真值时也写一句"这数是不是活的"(老倪: 实时数据必须标帧龄/来源; 别 silent)
    return out, {"real_force": "真机六维力 %s · 参考系 %s · 帧龄 %.2fs · 轴向 %.2fN 侧向 %.2fN"
                               % (SRC_FT, frame, age, fx, math.hypot(fy, fz))}


_RS_MOD = None


def _robot_state():
    """🤖 机器人状态机 → 数值信号 + 一行文字 (唯一依据唯一: tools/robot_state.py)。"""
    global _RS_MOD
    if _RS_MOD is None:
        import importlib.util
        _p = os.path.join(ROOT, "tools", "robot_state.py")
        _spec = importlib.util.spec_from_file_location("zmax_robot_state", _p)
        _m = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_m)
        _RS_MOD = _m
    st = _RS_MOD.snapshot()
    sig = {"机器人.状态_码": float(st.get("code") or 0)}
    if st.get("alarm_n") is not None:
        sig["机器人.报警数"] = float(st.get("alarm_n") or 0)
    if st.get("state_age_s") is not None:
        sig["机器人.状态帧龄_s"] = float(st["state_age_s"])
    if bool(st.get("connected")) and st.get("moving") is not None:
        sig["机器人.运动中"] = 1.0 if st["moving"] else 0.0
    if st.get("inserting") is not None:           # 未知就不写 (未知 ≠ 否)
        sig["机器人.插拔中"] = 1.0 if st["inserting"] else 0.0
    if (st.get("stage_idx") or -1) >= 0:
        sig["机器人.阶段_码"] = float(st["stage_idx"])
    return sig, {"robot": st.get("text") or ""}


def pull(publish_it=True, quiet=False):
    """从各唯一依据抓一轮 → 合并 → 写 live 文件 (取不到的键不写)。"""
    sig: dict = {}
    meta: dict = {}
    prov: dict = {}
    # 插拔过程信号 (速度 = TCP 差分; 切向力 = DDS ss_force_l2) —— 先跑, 让 tcp 的键被覆盖成同一帧的值
    try:
        mv = _motion()
        sig.update(mv)
        prov["motion"] = len(mv)
    except Exception as e:                                                        # noqa: BLE001
        meta["motion"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    try:
        tf = _tangential_force()
        sig.update(tf)
        prov["force"] = len(tf)
    except Exception as e:                                                        # noqa: BLE001
        meta["force"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    # 🦾 真机六维力 (轴向/侧向) —— 只在真值新鲜且在基座系时才写键, 否则 meta 里记"未接"
    try:
        rf, rm = _real_force()
        sig.update(rf)
        meta.update(rm)
        prov["real_force"] = len(rf)
    except Exception as e:                                                        # noqa: BLE001
        meta["real_force"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    try:
        rb, rm = _robot_state()
        sig.update(rb)
        meta.update(rm)
        prov["robot"] = len(rb)
    except Exception as e:                                                        # noqa: BLE001
        meta["robot"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    for fn, tag in ((_tcp, "tcp"),):
        try:
            d, m = fn()
            sig.update(d)
            meta.update(m)
            prov[tag] = len(d)
        except Exception as e:                                                    # noqa: BLE001
            meta[tag] = "%s: %s" % (type(e).__name__, str(e)[:100])
    try:
        d, names = _teach_points()                # 示教台账: (点位字典, 点位名列表)
        sig.update(d)
        prov["teach"] = {"n_signals": len(d), "points": names}
    except Exception as e:                                                        # noqa: BLE001
        meta["teach"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    try:
        d = _space_points()
        sig.update(d)
        prov["space"] = len(d)
    except Exception as e:                                                        # noqa: BLE001
        meta["space"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    try:
        a, m2, ts = _aoi_state()
        sig.update(a)
        meta.update(m2)
        prov["aoi_state_ts"] = ts
    except Exception as e:                                                        # noqa: BLE001
        meta["aoi_state"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    try:
        c, m3 = _ar_cam()
        sig.update(c)
        meta.update(m3)
        prov["ar_cam"] = len(c)
    except Exception as e:                                                        # noqa: BLE001
        meta["ar_cam"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    npt = sum(1 for k in sig if k.startswith(("金手指点", "侧面点", "准备点", "安全点", "空间点")))
    if npt:
        sig["叠加.点位数"] = float(npt)
    unknown = [k for k in sig if k not in KEYMAP]
    if unknown:
        meta["_未注册键"] = unknown[:12]
    if publish_it:
        r = publish(sig, meta=meta, prov=prov, quiet=quiet)
        r["n_signals"] = len(sig)
        r["n_points"] = npt
        return r
    return {"signals": sig, "meta": meta, "n_points": npt}


def publish(signals, meta=None, prov=None, quiet=False):
    """把信号并进 live 文件 (原子写 + .bak + 回读)。取不到的键不写, 不写 0 冒充。"""
    os.makedirs(os.path.dirname(LIVE), exist_ok=True)
    cur = _j(LIVE, {}) or {}
    _cs = cur.get("s")
    prev_s = dict(_cs) if isinstance(_cs, dict) else {}
    # 🆕 2026-10-20: 这里原本是纯 merge ⇒ SPEC 删掉的信号会永远赖在 live 里(实测删了 末端.速度/Δt 还在刷)。
    #   先按 KEYMAP(SPEC 生成) 过滤陈旧键, 再并本轮新值。KEYMAP 里的点位键不受影响。
    _drop = [k for k in prev_s if k not in KEYMAP]
    for k in _drop:
        prev_s.pop(k, None)
    if _drop and not quiet:
        print("  ⟲ 清掉 SPEC 已删除的陈旧信号 %d 个: %s" % (len(_drop), _drop[:6]))
    prev_s.update({k: v for k, v in signals.items() if isinstance(v, (int, float))})
    doc = {"ts": round(time.time(), 3), "t": time.strftime("%Y-%m-%d %H:%M:%S"),
           "s": prev_s, "age": {}, "meta": {"last_pull": meta or {}, "prov": prov or {},
                                            "registry": REGISTRY, "by": "ar_aoi_bus.py"},
           # 🥽 2026-10-20: groups 原来只覆盖 SPEC(KEYMAP) 里的键 ⇒ 台账点位(光模块插入口 等)
           #   在 live 里没有组名, 窗口只能把几十条点位丢进「AR 场景 · 其它信号」, 与注册表对不上。
           #   改为**每个真在发的键都按 group_of 归组**(注册表用的是同一套规则 ⇒ 两边一致)。
           "groups": {k: group_of(k) for k in prev_s}}
    now = time.time()
    for k in prev_s:
        doc["age"][k] = 0.0
    try:
        with open(LIVE, encoding="utf-8") as f:
            old = f.read()
        if old.strip():
            bak = LIVE + ".bak_%d" % int(now)
            with open(bak, "w", encoding="utf-8") as f:
                f.write(old)
    except Exception:                                                             # noqa: BLE001
        pass
    tmp = "%s.tmp.%d" % (LIVE, os.getpid())   # 每进程唯一: 两个写者用同名 tmp 会 os.replace 抢到不存在文件
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, LIVE)
    back = _j(LIVE, {}) or {}
    ok = isinstance(back.get("s"), dict) and all(k in back["s"] for k in signals if isinstance(signals.get(k), (int, float)))
    out = {"ok": bool(ok), "file": LIVE, "n": len(doc["s"]), "ts": doc["ts"]}
    if not ok:
        out["err"] = "回读校验失败: 写入 %d 键, 回读 %d 键" % (len(signals), len(back.get("s") or {}))
    if not quiet:
        print(json.dumps(out, ensure_ascii=False))
    return out


def write_registry():
    """把注册表落成唯一依据 JSON (signal → 组/单位/唯一依据/keys 全表)。

    台账里的点位是活的 (示教点/空间点会增删) ⇒ 除了 SPEC 里的核心信号, 再把**当前台账**
    真实存在的点位键一并登记 (按 group_of 归组) —— 注册表因此与现场一致, 又不靠手填。
    """
    os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
    groups = {}
    for k, g, u, s in SPEC:
        groups.setdefault(g, []).append({"key": k, "unit": u, "src": s})
    for src_name, reader in (("reports/aoi_points/*.json (示教台账)", _teach_points),
                             ("data/skills/l2_atomic/space_points.json (空间点 1~7)", _space_points)):
        try:
            got = reader()
            keys = (got[0] if isinstance(got, tuple) else got) or {}
        except Exception:                                                        # noqa: BLE001
            continue
        for k in keys:
            if any(it["key"] == k for it in groups.get(group_of(k), [])):
                continue
            groups.setdefault(group_of(k), []).append({"key": k, "unit": unit_of(k), "src": src_name})
    doc = {"schema": "zmax-ar-aoi-signals/1.0",
           "note": "AR 场景空间点位 + AOI 话题注册表 (ar_aoi_bus.py 生成; 信号分析页来源前缀 ar.)",
           "prefix": "ar.", "live": os.path.relpath(LIVE, ROOT),
           "producers": {"AR 服务 8797": "相机系位姿/曝光/帧龄 (tcp_ar_server.py)",
                         "状态空间节点 🔍 光学质量检测": "quality_check.py AOIQualityChecker (library.py node_ss_aoi)",
                         "工控机 AOI 10082/10083": "工控机 AOI 程序判决 (tools/aoi_link.py 客户端)",
                         "示教/空间点台账": "reports/aoi_points/*.json · data/skills/l2_atomic/space_points.json",
                         "TCP 真值": "zmax_data/rokae_sdk/tcp_out/latest.json"},
           "counts": {"signals": len(SPEC), "groups": len(groups)},
           "groups": groups}
    old = None
    try:
        with open(REGISTRY, encoding="utf-8") as f:
            old = f.read()
    except Exception:                                                             # noqa: BLE001
        pass
    new = json.dumps(doc, ensure_ascii=False, indent=1)
    if old != new:
        tmp = REGISTRY + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, REGISTRY)
    return {"ok": True, "file": REGISTRY, "signals": len(SPEC), "groups": len(groups),
            "changed": old != new, "keys": [g for g in groups]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["spec", "pull", "watch", "show", "publish"])
    ap.add_argument("-i", "--interval", type=float, default=2.0)
    ap.add_argument("--json", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.cmd == "spec":
        print(json.dumps(write_registry(), ensure_ascii=False, indent=1))
        for g, items in (json.load(open(REGISTRY, encoding="utf-8"))["groups"] or {}).items():
            print("·", g, "(%d)" % len(items))
            for it in items:
                print("   %-28s %-8s %s" % (it["key"], it["unit"], it["src"][:70]))
    elif a.cmd == "pull":
        write_registry()
        print(json.dumps(pull(quiet=a.quiet), ensure_ascii=False, indent=1))
    elif a.cmd == "watch":
        write_registry()
        print("▶ AR/AOI 信号总线常驻: 每 %.1fs 抓一轮 → %s" % (a.interval, LIVE))
        while True:
            try:
                r = pull(quiet=True)
                print("[%s] n=%d 点位=%d ok=%s" % (time.strftime("%H:%M:%S"), r.get("n", -1),
                                                   r.get("n_points", -1), r.get("ok")), flush=True)
            except Exception as e:                                                # noqa: BLE001
                print("[%s] 抓取失败: %s: %s" % (time.strftime("%H:%M:%S"), type(e).__name__, e), flush=True)
            time.sleep(max(0.05, a.interval))   # 2026-10-20 老倪「不要自己刷新, 保持信号连续」: 下限 0.5s→0.05s, 否则最快 2Hz, 波形必然断成点
    elif a.cmd == "show":
        d = _j(LIVE, {}) or {}
        s = d.get("s") or {}
        print("文件: %s\n时刻: %s  (帧龄 %.1fs)" % (LIVE, d.get("t"),
                                                  time.time() - float(d.get("ts") or 0)))
        cur = None
        for k in sorted(s, key=lambda x: (group_of(x), x)):
            g = group_of(k)
            if g != cur:
                print("·", g)
                cur = g
            print("   %-30s %s" % (k, s[k]))
        if d.get("meta"):
            print("meta:", json.dumps(d["meta"], ensure_ascii=False)[:400])
    else:
        sig = json.loads(a.json or "{}")
        print(json.dumps(publish(sig, meta={"by": "CLI publish"}), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
