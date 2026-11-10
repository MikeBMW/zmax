# -*- coding: utf-8 -*-
"""camera_scheduler — 位姿驱动的分布式感知调度 (算法层, 不依赖中间件)。

老倪 2026-11-10: 「AR 场景已经有路径了, 你来根据 AR 场景的具体点位, 规划到位置区域,
就开启相应的感知能力」

做什么
  输入: 机器人 TCP 在 base 系的位置 (米, 来自 tcp_out/latest.json 真值)
  输出: 该位置该启用哪几台相机、各担什么角色、该相机能不能出 3D 引导
  依据: 两个唯一真源, 不在本文件里抄数值
    ① 区域定义  zmax_data/env_model.json :: zones[].bbox   (工程配置, 5 个区)
    ② 相机能力  config/calib/camera_registry.json           (实测 7 台, 含内/外参状态)

三条硬规矩
  1. 只有 extrinsic.mode ∈ {tcp_compose, fixed_matrix} 的相机才准出 3D;
     其余 (uncalibrated) 一律降级 L0 只出 2D —— 不许拿"差不多"的外参算毫米。
  2. role=guide 且 level=L0 的相机 ⇒ 标 blocked 并写明缺什么, 不静默启用。
  3. 区域边界带 20mm 滞回: 只在穿越滞回带时才切换, 防止 TCP 抖动导致相机反复开关。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))  # .../zmax (perception→policies→lerobot→src→zmax)

ENV_MODEL = os.path.join(REPO, "zmax_data", "env_model.json")
REGISTRY = os.path.join(REPO, "config", "calib", "camera_registry.json")
TRAJ_ZONES = os.path.join(REPO, "config", "calib", "traj_zones.json")

DEFAULT_HYSTERESIS_MM = 20.0


# ────────────────────────────── 真源加载 ──────────────────────────────
def load_zones(path: str = ENV_MODEL, traj_path: str = TRAJ_ZONES) -> Dict[str, Dict[str, Any]]:
    """区域定义 (米)。两层合并, 工程真源优先:

      ① zmax_data/env_model.json :: zones   ← 工程配置, 权威
      ② config/calib/traj_zones.json        ← AR 轨迹派生 (tools/gen_traj_zones.py)
                                             同名时 ① 胜出 (派生层不许覆盖真源)
    """
    with open(path, encoding="utf-8") as f:
        zones = dict(json.load(f).get("zones") or {})
    if os.path.exists(traj_path):
        try:
            with open(traj_path, encoding="utf-8") as f:
                derived = json.load(f).get("zones") or {}
            for k, v in derived.items():
                zones.setdefault(k, v)          # setdefault ⇒ 真源优先
        except Exception:  # noqa: BLE001
            pass
    return zones


def load_registry(path: str = REGISTRY) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ────────────────────────────── 区域判定 ──────────────────────────────
def _in_box(p: Tuple[float, float, float], bbox: Dict[str, List[float]],
            pad: float = 0.0) -> bool:
    x, y, z = p
    for i, ax in enumerate("xyz"):
        lo, hi = bbox[ax]
        if not (lo - pad <= p[i] <= hi + pad):
            return False
    return True


def _box_center(bbox: Dict[str, List[float]]) -> Tuple[float, float, float]:
    return tuple((bbox[ax][0] + bbox[ax][1]) / 2.0 for ax in "xyz")  # type: ignore


def _dist(a, b) -> float:
    return sum((ai - bi) ** 2 for ai, bi in zip(a, b)) ** 0.5


def zone_of(p: Tuple[float, float, float], zones: Dict[str, Dict[str, Any]],
            prev: Optional[str] = None, hysteresis_mm: float = DEFAULT_HYSTERESIS_MM
            ) -> Tuple[str, str]:
    """TCP 位置 → 区域名。返回 (zone, how)。

    优先级: ① 落在某区 bbox 内 → 该区 (多区重叠取中心最近)
            ② 没落区内但距上次区域 < 滞回带 → 保持上次 (防抖)
            ③ 都不中 → '包络外' 或 '未分区'
    """
    hits = [z for z, v in zones.items() if _in_box(p, v["bbox"])]
    how = "in_bbox"
    if hits:
        if len(hits) > 1:
            # 「其它」是兜底区, 不许抢具体区 —— 具体区里取中心最近
            concrete = [z for z in hits if z not in ("其它", "包络外")]
            pool = concrete or hits
            pool.sort(key=lambda z: _dist(p, _box_center(zones[z]["bbox"])))
            how = "in_bbox(重叠 %d 区, 取最近 %s)" % (len(hits), pool[0])
            return pool[0], how
        return hits[0], how
    if prev and prev in zones:
        c = _box_center(zones[prev]["bbox"])
        b = zones[prev]["bbox"]
        # 到该区 bbox 的面距离 (盒外最近距离)
        dx = max(b["x"][0] - p[0], 0.0, p[0] - b["x"][1])
        dy = max(b["y"][0] - p[1], 0.0, p[1] - b["y"][1])
        dz = max(b["z"][0] - p[2], 0.0, p[2] - b["z"][1])
        face_mm = (dx * dx + dy * dy + dz * dz) ** 0.5 * 1000.0
        if face_mm <= hysteresis_mm:
            return prev, "滞回保持(距 %s 面 %.1fmm ≤ %.0fmm)" % (prev, face_mm, hysteresis_mm)
    # 包络检查
    env = None
    try:
        with open(ENV_MODEL, encoding="utf-8") as f:
            env = json.load(f).get("envelope")
    except Exception:  # noqa: BLE001
        pass
    if env and _in_box(p, env):
        return "其它", "在包络内但不在任何命名区"
    return "包络外", "超出工程包络"


# ────────────────────────────── 3D 闸门 ──────────────────────────────
def can_guide_3d(cam: Dict[str, Any]) -> Tuple[bool, str]:
    """该相机能否出 3D 引导。返回 (ok, why)。"""
    ex = (cam.get("extrinsic") or {})
    mode = ex.get("mode")
    if mode in ("tcp_compose", "fixed_matrix"):
        return True, "外参可用(%s, 残差 %s mm rms)" % (
            mode, ex.get("resid_mm_rms", "?"))
    return False, "外参未标(%s) ⇒ 只出 2D" % (ex.get("_reason") or mode or "缺")


# ────────────────────────────── 主调度 ──────────────────────────────
def perceive_plan(p_m: Tuple[float, float, float],
                  scene: Optional[str] = None,
                  prev_zone: Optional[str] = None,
                  hysteresis_mm: float = DEFAULT_HYSTERESIS_MM,
                  zone_override: Optional[str] = None) -> Dict[str, Any]:
    """TCP 位置 → 该位置的感知计划。

    返回:
      zone      判定到的区域
      cams      启用清单 [{id, role, level, label, enable, why}]
      guide     唯一主引导相机 (None = 本区域给不了 3D 引导)
      blocked   想用但缺标定的相机 + 缺什么
    """
    zones = load_zones()
    reg = load_registry()
    cams = reg["cams"]
    if zone_override:
        zone, how = zone_override, "override(ALERT 预热即将进入的区)"
    else:
        zone, how = zone_of(p_m, zones, prev=prev_zone, hysteresis_mm=hysteresis_mm)

    # 区域自带的感知绑定 (派生区: {"cam_id": "role"}) —— 优先于注册表的 coverage
    bind: Dict[str, str] = (zones.get(zone) or {}).get("cams") or {}

    on, blocked = [], []
    for cid, cam in cams.items():
        cov = cam.get("coverage") or {}
        roles = list(cam.get("role") or [])
        if bind:
            if cid not in bind:
                continue
            role_override = bind[cid]
            if role_override not in roles:
                roles = [role_override] + roles
        elif zone not in (cov.get("zones") or []):
            continue
        ok3d, why3d = can_guide_3d(cam)
        item = {"id": cid, "label": cam.get("label"), "role": roles,
                "level": cam.get("level"), "enable": True, "why": why3d}
        if "guide" in roles and not ok3d:
            item["enable"] = False
            item["level"] = "L0"
            blocked.append({"id": cid, "label": cam.get("label"), "why": why3d})
        on.append(item)

    # 主引导相机: 能出最高 level 的那台 (L2 > L1 > L0)
    order = {"L2": 3, "L1": 2, "L0": 1}
    guides = [c for c in on if c["enable"] and "guide" in c["role"]]
    guide = max(guides, key=lambda c: order.get(c["level"], 0))["id"] if guides else None

    return {"p_m": [round(v, 4) for v in p_m], "zone": zone, "zone_how": how,
            "scene": scene, "cams": on, "guide": guide, "blocked": blocked,
            "scene_note": "场景档位只影响主次优先级; 区域判定永远以 TCP 真值为准"
            if scene else None}


# ────────────────────────────── 轨迹扫描 ──────────────────────────────
def perceive_state(p_m: Tuple[float, float, float],
                   prev_state: str = "WATCH",
                   prev_zone: Optional[str] = None,
                   alert_band_mm: float = 100.0,
                   hysteresis_mm: float = DEFAULT_HYSTERESIS_MM) -> Dict[str, Any]:
    """四态感知门控 —— 对应大脑「周边监视 → 眼跳 → 中央凹采样 → 退出」的连续增益调节。

    不是二值开关 (开/关), 而是**精度权重 gain 连续变化**:
      WATCH    不在命名区        gain 0.2  只开 overview (顶摄低帧率跟拍 = 周边视觉)
      ALERT    进入区但贴边 <100mm gain 0.6  目标相机预热, 还不采信 (接近警觉)
      FOVEATE  深入区内 >100mm   gain 1.0  全开, 出 3D 引导 (= 中央凹对准)
      RELEASE  从区内退出        gain 0.2  回落 WATCH (不要瞬间断电, 保留余像)

    gain 的用途: 下游按它决定采样帧率/是否采信本次定位 —— 这正是大脑做的
    「按预期提高该感觉通道的精度权重」(predictive coding 的 precision weighting)。
    """
    zones = load_zones()
    zone, how = zone_of(p_m, zones, prev=prev_zone, hysteresis_mm=hysteresis_mm)
    named = zone not in ("其它", "包络外")

    # ALERT 的正确判据: 「逼近某个区」= 在区外但离区面 alert_band 内。
    # 不能用「离区内边界的深度」—— 插入工位区 z 只有 11mm 厚, 工件贴在区底时深度恒≈0,
    # 那样永远进不了高精度态 (实测 depth=0.5mm)。到达目标区就该全力看, 这是大脑的口径。
    near_mm, near_zone = 1e9, None
    if not named:
        for z, v in zones.items():
            if z in ("其它", "包络外"):
                continue
            b = v["bbox"]
            dx = max(b["x"][0] - p_m[0], 0.0, p_m[0] - b["x"][1])
            dy = max(b["y"][0] - p_m[1], 0.0, p_m[1] - b["y"][1])
            dz = max(b["z"][0] - p_m[2], 0.0, p_m[2] - b["z"][1])
            d = (dx * dx + dy * dy + dz * dz) ** 0.5 * 1000.0
            if d < near_mm:
                near_mm, near_zone = d, z

    if named:
        state = "FOVEATE"
    elif near_mm <= alert_band_mm:
        state = "ALERT"
    elif prev_state in ("FOVEATE", "ALERT"):
        state = "RELEASE"
    else:
        state = "WATCH"

    gain = {"WATCH": 0.2, "RELEASE": 0.2, "ALERT": 0.6, "FOVEATE": 1.0}[state]
    # ALERT 时预热"即将进入"那个区的相机 (大脑的 priming); 区内/其余用真实判定
    plan = perceive_plan(p_m, prev_zone=prev_zone, hysteresis_mm=hysteresis_mm,
                         zone_override=(near_zone if (state == "ALERT" and near_zone) else None))

    # 按 gain 决定每台相机的采样档 (大脑的双通道: 周边低带宽 / 中央凹高带宽)
    for c in plan["cams"]:
        if "overview" in c["role"]:
            c["sampling"] = "low_rate(2Hz)"          # 周边视觉: 一直在看, 但低带宽
        elif "quality" in c["role"]:
            c["sampling"] = "on_demand"              # 质量相机: 到位才抓一帧
        else:
            c["sampling"] = "high_rate(10Hz)" if gain >= 1.0 else "prewarm(1Hz)"

    return {"p_m": [round(v, 4) for v in p_m], "zone": zone, "zone_how": how,
            "state": state, "gain": gain, "zone_depth_mm": round(alert_band_mm - near_mm, 1) if not named else 0.0,
            "cams": plan["cams"], "guide": plan["guide"], "blocked": plan["blocked"],
            "_neuro": {"WATCH": "周边视觉低带宽监视", "ALERT": "接近警觉·预热",
                       "FOVEATE": "中央凹对准·高精度采样", "RELEASE": "退出·保留余像"}[state]}


def scan_traj(pts_m: List[Tuple[float, float, float]],
              label: str = "", hysteresis_mm: float = DEFAULT_HYSTERESIS_MM
              ) -> Dict[str, Any]:
    """把一条轨迹逐点过一遍调度, 输出区域切换序列 (即"到哪开哪台相机")。"""
    segs: List[Dict[str, Any]] = []
    prev_zone = None
    for i, p in enumerate(pts_m):
        plan = perceive_plan(p, prev_zone=prev_zone, hysteresis_mm=hysteresis_mm)
        z = plan["zone"]
        if not segs or segs[-1]["zone"] != z:
            segs.append({"zone": z, "from_i": i, "to_i": i, "guide": plan["guide"],
                         "n_pts": 1, "p_start": plan["p_m"], "p_end": plan["p_m"]})
        else:
            segs[-1]["to_i"] = i
            segs[-1]["n_pts"] += 1
            segs[-1]["p_end"] = plan["p_m"]
        prev_zone = z
    return {"label": label, "n_pts": len(pts_m), "segments": segs}
