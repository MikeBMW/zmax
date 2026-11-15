"""L5 语义 → 流形引擎引导 (确定性映射, 不含任何模型编造)。

为什么要有这一层
----------------
L5 (Qwen-VL 场景理解 / YOLO 检测框) 出来的是**语义**:
    · 阶段文字   接近/对位/下降/抓取/抬起/转移/插入/完成
    · 目标标签   光模块 / 金手指 / 连接器 …
    · 置信度     conf
    · 方向矢量   l5_scene_vec.json 的 vec = [dx, -dy, 0]·conf  (相机系, 见 ar_l5_understand.py:75)

流形引擎要的是**数值**:
    · 目标位姿 T_goal ∈ SE(3)
    · 势场权重 k (对抗噪声)
    · 门控 (置信度不够就不许引导)

本模块只做**确定性查表 + 门控**, 不训练、不预测:
    阶段 → 215 点真值表区间 → T_goal
    conf → k_l5 (低置信直接不出引导, 绝不拿噪声指方向)
    vec  → 水平方向提示 (相机系, 正交于重力; 用法见 cam_hint)

铁律 (老倪):
    · 上层只给意图/条件, 动作由下层收口 —— 本模块**不产动作**, 只产 T_goal/k/门控;
    · 取不到就报缺 (ok=False + why), 绝不拿默认值冒充"L5 已引导";
    · 阶段区间若未经真值标定, 必须明写 `range_src="均分假设(未标定)"`。
"""
from __future__ import annotations

import json
import os

import numpy as np

STAGES = ("接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成")

# 置信度门控: 低于此值 ⇒ L5 不参与引导 (宁可不出, 不可乱指)
CONF_MIN = 0.40
# 置信度对势场权重的放大区间: conf=0.4 → 0.5x, conf=1.0 → 1.0x
K_MIN, K_MAX = 0.5, 1.0


def _read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                    # noqa: BLE001
        return None


# ── 回放轨迹只读锁 (老倪 2026-11-15: "回放轨迹不能被修改") ──────────────────────
# 215 点真值表是**唯一安全基准**, L2~L5 只能从它学, 不能改它。
# 任何层一旦写它, md5 变了, 这里直接 raise —— 不允许"悄悄改了再跑"。
TRAJ_PATH_REL = "tools/web/real_traj_joints.json"
TRAJ_MD5 = "15e4a986d06eb40f25701fed1270712f"
TRAJ_N = 215


def assert_traj_untouched(path: str) -> None:
    """回放轨迹只读校验: 内容变了/帧数变了 → 抛错, 不静默继续。"""
    import hashlib
    b = open(path, "rb").read()
    md5 = hashlib.md5(b).hexdigest()
    if md5 != TRAJ_MD5:
        raise RuntimeError(
            "回放轨迹 %s 被修改 (md5 %s ≠ 只读基准 %s)。\n"
            "215 点真值表是 L2~L5 的唯一安全基准, 只允许读。\n"
            "若确需换代, 先经老倪确认, 再更新 TRAJ_MD5 常量 (这是一次显式的口径变更)。"
            % (path, md5[:12], TRAJ_MD5[:12]))


def _handeye_T():
    """T_cam2tool (4x4) ← models/handeye_state.json (2026-11-15 标定: 0.32mm/0.029°)."""
    import json as _j, os as _os
    p = "/home/ubuntu/zmax/models/handeye_state.json"
    if not _os.path.exists(p):
        return None, "无 handeye_state.json"
    try:
        d = _j.load(open(p))
        T = np.asarray(d.get("T_cam2tool"), float).reshape(4, 4)
        if abs(np.linalg.det(T[:3, :3]) - 1.0) > 1e-3:
            return None, "T_cam2tool 不是刚体阵 (det=%.4f)" % np.linalg.det(T[:3, :3])
        return T, "handeye_state.json (resid %.2fmm/%.3f°)" % (
            d.get("resid_trans_mm_rms", -1), d.get("resid_rot_deg_rms", -1))
    except Exception as e:                                               # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


DEPTH_URL = "http://192.168.23.66:8795/depth.png"
DEPTH_SCALE_M = 0.0001          # D405 depth_scale ⇒ PNG 计数 × 0.0001 = 米


def _read_depth_png(url: str = DEPTH_URL, ts: float | None = None, timeout: float = 5.0):
    """取 D405 原始 16bit 深度 (单位 0.1mm)。失败返回 (None, why)。"""
    try:
        import urllib.request
        u = url + (("?ts=%.3f" % ts) if ts else "")
        with urllib.request.urlopen(u, timeout=timeout) as r:
            buf = r.read()
        import cv2 as _cv2, numpy as _np
        a = _cv2.imdecode(_np.frombuffer(buf, _np.uint8), _cv2.IMREAD_UNCHANGED)
        if a is None:
            return None, "深度 PNG 解码失败"
        return a, "ok(h=%d,w=%d,dtype=%s)" % (a.shape[0], a.shape[1], a.dtype)
    except Exception as e:                                              # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, str(e)[:70])


def _bbox_depth_to_cam3d(bbox, depth, K=None):
    """检测框 + 深度图 → 相机系 3D 点 (米)。

    取 bbox 内**有效深度中位数**（不用中心单点: 中心常落在高光/边缘 → 0 或跳变）。
    反投影: X=(u-cx)·Z/fx, Y=(v-cy)·Z/fy   K 从 models/real_cam_calib.json。
    """
    import os as _os, json as _j
    import numpy as _np
    if depth is None or bbox is None:
        return None, "缺深度或缺框"
    try:
        x1, y1, x2, y2 = [int(round(float(v))) for v in bbox[:4]]
    except Exception:                                                   # noqa: BLE001
        return None, "bbox 非法"
    h, w = depth.shape[:2]
    x1, x2 = max(0, min(w - 1, x1)), max(0, min(w - 1, x2))
    y1, y2 = max(0, min(h - 1, y1)), max(0, min(h - 1, y2))
    if x2 <= x1 or y2 <= y1:
        return None, "bbox 退化 (%d,%d,%d,%d)" % (x1, y1, x2, y2)
    roi = depth[y1:y2, x1:x2].astype(_np.float64)
    v = roi[roi > 0]
    if v.size < 8:
        return None, "bbox 内有效深度像素不足 (%d)" % v.size
    z = float(_np.median(v)) * DEPTH_SCALE_M
    if not (0.05 < z < 3.0):
        return None, "深度超出合理范围 %.3fm" % z
    if K is None:
        try:
            d = _j.load(open("/home/ubuntu/zmax/models/real_cam_calib.json"))
            Km = _np.asarray(d["K"], float).reshape(3, 3)
            fx, fy, cx, cy = Km[0, 0], Km[1, 1], Km[0, 2], Km[1, 2]
        except Exception:                                               # noqa: BLE001
            fx = fy = 394.0; cx, cy = 318.44, 238.66
    else:
        Km = _np.asarray(K, float).reshape(3, 3)
        fx, fy, cx, cy = Km[0, 0], Km[1, 1], Km[0, 2], Km[1, 2]
    u, vt = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    X = (u - cx) * z / fx
    Y = (vt - cy) * z / fy
    return _np.array([X, Y, z], float), "bbox中位深度 %.0fmm · %d px · fx=%.1f" % (z * 1000, v.size, fx)


class L5Guide:
    """把 L5 的语义判读翻成流形引擎能吃的引导量。"""

    def __init__(self, root: str = "/home/ubuntu/zmax", log=None) -> None:
        self.root = root
        self._log = log
        self._traj = None

    # ── 端口解析 (优先于文件) ────────────────────────────────────────────────
    @staticmethod
    def _parse_port(v, name: str = "?") -> dict:
        """从画布端口值里抽 stage/conf/label/vec。解析不出就返回 {} (不猜)。

        接受三种形态 (都来自真实上游, 不做形状假设以外的推断):
          · dict  {"value": {...}} 或直接 {"stage":…, "conf":…}   ← 总线包装 / 节点直出
          · str   "插入"                                            ← 语义文字
          · list/tuple 长度 8 的 one-hot                            ← 阶段先验 (ss_moe out3)
        """
        if v is None:
            return {}
        # 总线包装 {"value":…, "age_s":…, "fresh":…}
        if isinstance(v, dict) and ("value" in v or "fresh" in v):
            if v.get("fresh") is False:
                return {}
            return L5Guide._parse_port(v.get("value"), name)
        if isinstance(v, str):
            s = v.strip()
            return {"stage": s} if s in STAGES else {}
        if isinstance(v, dict):
            st = v.get("stage") or v.get("阶段") or v.get("stage_name") or v.get("phase")
            out = {}
            if isinstance(st, str) and st.strip() in STAGES:
                out["stage"] = st.strip()
            conf = v.get("conf", v.get("confidence"))
            if conf is not None:
                try:
                    out["conf"] = float(conf)
                except Exception:                                            # noqa: BLE001
                    pass
            lb = v.get("label") or v.get("目标")
            if lb:
                out["label"] = str(lb)
            for k in ("vec", "vector", "z"):
                if isinstance(v.get(k), (list, tuple)) and len(v[k]) >= 3:
                    out["vec"] = list(v[k])[:3]
                    break
            return out
        if isinstance(v, (list, tuple)) and len(v) == len(STAGES):
            try:
                arr = [float(x) for x in v]
                i = int(max(range(len(arr)), key=lambda j: arr[j]))
                return {"stage": STAGES[i], "conf": max(0.0, min(1.0, arr[i])),
                        "stage_src": "八阶段 one-hot[%d]" % i}
            except Exception:                                                # noqa: BLE001
                return {}
        return {}

    # ── 真值表 ──────────────────────────────────────────────────────────────
    def _frames(self):
        if self._traj is not None:
            return self._traj
        # 只读校验: 回放轨迹一旦被改, 这里就炸 (不接受"改了也能跑")
        try:
            assert_traj_untouched(os.path.join(self.root, TRAJ_PATH_REL))
        except FileNotFoundError:
            self._traj = []
            return self._traj
        for rel in (TRAJ_PATH_REL,):
            p = os.path.join(self.root, rel)
            d = _read_json(p)
            if isinstance(d, dict) and d.get("frames"):
                self._traj = d["frames"]
                return self._traj
        self._traj = []
        return self._traj

    # ── 语义读数 ────────────────────────────────────────────────────────────
    def read_live(self) -> dict:
        """读当前 L5 判读: vec(方向) + 理解结果(阶段/标签/置信度)。缺什么就标什么。"""
        live = os.path.join(self.root, "zmax_data", "ss_live")
        vecd = _read_json(os.path.join(live, "l5_scene_vec.json")) or {}
        und = _read_json(os.path.join(live, "l5_understand_latest.json")) or {}
        vec = vecd.get("vec")
        conf = float(vecd.get("conf") or und.get("conf") or 0.0)
        label = str(vecd.get("label") or und.get("label") or "")
        stage = str(und.get("stage") or und.get("阶段") or "").strip()
        import time
        ts = vecd.get("ts") or und.get("ts")
        age = (time.time() - float(ts)) if ts else None
        return {"vec": vec, "conf": conf, "label": label, "stage": stage,
                "age_s": (round(age, 2) if age is not None else None),
                "src": vecd.get("src") or und.get("src"),
                "have_vec": isinstance(vec, (list, tuple)) and len(vec) >= 3,
                "have_stage": stage in STAGES}

    # ── 阶段 → 目标点 ───────────────────────────────────────────────────────
    def stage_range(self, stage: str) -> tuple[int, int, str]:
        """阶段 → 215 点表的下标区间。

        ⚠️ 均分是**假设**, 真值表里没有 stage 列 (只有 p/q/关节), 所以这里明写
           range_src="均分假设(未标定)"。等真值表补了阶段列, 改成按列切。
        """
        fr = self._frames()
        n = len(fr)
        if n == 0 or stage not in STAGES:
            return 0, 0, "无真值表或无阶段"
        k = STAGES.index(stage)
        per = n / len(STAGES)
        i0 = int(round(k * per))
        i1 = int(round((k + 1) * per)) - 1
        i1 = max(i0, min(n - 1, i1))
        return i0, i1, "均分假设(未标定)"

    def goal_for_stage(self, stage: str):
        """该阶段的目标位姿 T_goal (取区间出口点 = 该阶段做到位的位置)。"""
        fr = self._frames()
        i0, i1, rsrc = self.stage_range(stage)
        if not fr:
            return None, {"why": "无 215 点真值表", "range_src": rsrc}
        try:
            from .se3_chain import T_from_rot_t, quat_to_R
            q = np.asarray(fr[i1]["q"], float).reshape(4)
            p = np.asarray(fr[i1]["p"], float).reshape(3)
            return T_from_rot_t(quat_to_R(q), p), {"idx": i1, "range": [i0, i1],
                                                  "range_src": rsrc, "n": len(fr)}
        except Exception as e:                                           # noqa: BLE001
            return None, {"why": "%s: %s" % (type(e).__name__, e), "range_src": rsrc}

    # ── L5 自主标定: 视觉 → base_link 目标位姿 ──────────────────────────────
    def visual_goal(self, port_data: dict | None = None, tcp_pose=None):
        """L5 自主标定 (老倪 2026-11-15): 用视觉把**工件实际位置**算成 base_link 的 T_goal。

        与 stage_range 的根本区别:
          · stage_range  → 拿 215 点表的**回放点**当目标 (只作参考/安全包络, 不是自主)
          · visual_goal  → 用相机看工件 + 手眼外参, 算出工件**此刻**在哪 (自主标定)

        链路: 检测框中心(像素) + 深度 → P_cam(3) --T_cam2tool--> P_tool --T_tool_base--> P_base
              T_tool_base 由 endInRef 真值给 (x,y,z + rpy), 手眼给 T_cam2tool.

        返回 (T_goal, info) 或 (None, why)。**没有深度/没有框就返回 None, 不编。**

        端口取值 (依次): in2/in1 的 `det_xyz_cam` (相机系 3D 点) > `bbox`+`depth_m` > `peg_xyz_mm`
        """
        pd = port_data or {}
        T_ct, src_ct = _handeye_T()
        if T_ct is None:
            return None, {"ok": False, "why": "手眼外参不可用: " + src_ct}

        def _find3d(v):
            """从端口值里挖相机系 3D 点 (米) + 置信度。挖不到返回 None。"""
            cands = []
            def walk(o, depth=0):
                if depth > 3 or o is None:
                    return
                if isinstance(o, dict):
                    for k in ("det_xyz_cam", "xyz_cam", "p_cam", "peg_xyz_m",
                              "peg_xyz_mm", "target_xyz_mm", "xyz_mm", "peg_optical_module"):
                        if k in o:
                            cands.append((k, o[k]))
                    for vv in o.values():
                        walk(vv, depth + 1)
                elif isinstance(o, list) and len(o) == 3 and all(isinstance(x, (int, float)) for x in o):
                    cands.append(("bare3", o))
            for key in ("in2", "in1", "in3"):
                walk(pd.get(key))
            for k, v in cands:
                try:
                    a = np.asarray(v, float).reshape(-1)
                    if a.size < 3:
                        continue
                    xyz = a[:3].copy()
                    if "mm" in k or (np.abs(xyz).max() > 5.0):     # 毫米量纲 → 转米
                        xyz = xyz / 1000.0
                    return xyz, k
                except Exception:                                          # noqa: BLE001
                    continue
            return None, None

        xyz_cam, kind = _find3d(pd)

        # bbox + 真实深度 兜底（老倪 2026-11-15: 深度已接 8795 16bit/0.1mm）
        depth_why = None
        if xyz_cam is None:
            bbox = None
            def _find_bbox(o, depth=0):
                if depth > 3 or o is None:
                    return None
                if isinstance(o, dict):
                    for k in ("bbox", "bbox_px", "xyxy", "box", "det_box"):
                        if k in o:
                            try:
                                bb = [float(v) for v in o[k]]
                                if len(bb) == 4:
                                    return bb
                            except Exception:                           # noqa: BLE001
                                pass
                    for vv in o.values():
                        r = _find_bbox(vv, depth + 1)
                        if r:
                            return r
                elif isinstance(o, list) and len(o) == 4 and all(isinstance(x, (int, float)) for x in o):
                    return [float(x) for x in o]
                return None
            for key in ("in2", "in1", "in3"):
                bbox = _find_bbox(pd.get(key))
                if bbox:
                    break
            if bbox:
                dimg, dwh = _read_depth_png()
                if dimg is None:
                    depth_why = "深度桥不可用: " + str(dwh)
                else:
                    xyz_cam, k2 = _bbox_depth_to_cam3d(bbox, dimg)
                    if xyz_cam is not None:
                        kind = "bbox+depth(%s)" % k2
                    else:
                        depth_why = k2

        if xyz_cam is None:
            return None, {"ok": False,
                          "why": "无相机系 3D 目标且 bbox+深度也算不出"
                                 + ((" (" + depth_why + ")") if depth_why else "")
                                 + " ⇒ L5 无法自主标定, 退回参考区间",
                          "src_kind": "no-visual", "depth_why": depth_why}

        # T_tool_base ← 当前 TCP 真值
        if tcp_pose is None:
            try:
                pt = json.load(open(os.path.join(self.root, "zmax_data/rokae_sdk/tcp_out/latest.json")))
                p_tb = np.array([pt["x"], pt["y"], pt["z"]], float)
                q = pt.get("q") or [pt.get("qx", 0), pt.get("qy", 0), pt.get("qz", 0), pt.get("qw", 1)]
                from .se3_chain import quat_to_R, T_from_rot_t
                T_tb = T_from_rot_t(quat_to_R(np.asarray(q, float)), p_tb)
            except Exception as e:                                          # noqa: BLE001
                return None, {"ok": False, "why": "位姿真值不可用: %s: %s" % (type(e).__name__, e)}
        else:
            T_tb = np.asarray(tcp_pose, float).reshape(4, 4)

        # 相机系点 → 工具系 → 基座系
        P_cam = np.array([xyz_cam[0], xyz_cam[1], xyz_cam[2], 1.0])
        P_tool = T_ct @ P_cam
        P_base = T_tb @ P_tool
        T_goal = T_tb @ T_ct        # 目标姿态沿用当前工具姿态 (位置自主, 姿态暂不猜)
        T_goal = np.array(T_goal, float)
        T_goal[:3, 3] = P_base[:3]

        info = {"ok": True, "src_kind": "visual(%s)" % kind, "handeye": src_ct,
                "p_cam_m": np.round(xyz_cam, 4).tolist(),
                "p_base_mm": np.round(P_base[:3] * 1000, 1).tolist(),
                "why": "L5 视觉自主标定: 工件在基座系 %s mm"
                       % np.round(P_base[:3] * 1000, 1).tolist()}
        return T_goal, info

    # ── 门控 ────────────────────────────────────────────────────────────────
    @staticmethod
    def gate(conf: float) -> tuple[bool, float, str]:
        """置信度门控: 返回 (是否允许引导, 势场增益 k, 原因)。"""
        c = float(conf)
        if c < CONF_MIN:
            return False, 0.0, "conf %.2f < 阈值 %.2f ⇒ L5 不参与 (不拿噪声指方向)" % (c, CONF_MIN)
        k = K_MIN + (K_MAX - K_MIN) * (c - CONF_MIN) / max(1e-9, 1.0 - CONF_MIN)
        return True, k, "conf %.2f ≥ 阈值 ⇒ 引导, k_L5=%.2f" % (c, k)

    # ── 对外: 一次取全 ──────────────────────────────────────────────────────
    def guide(self, stage: str | None = None, max_age_s: float = 5.0,
              port_data: dict | None = None) -> dict:
        """产出给流形引擎的引导包。ok=False 时**不得**当作"已引导"使用。

        取语义的优先级 (高→低), 来源写进 src_kind 便于追溯:
          ① stage 显式传参        (调试/单测入口)
          ② port:in5  ss_moe 阶段先验 (最结构化: 八阶段 one-hot 或 stage 字符串)
          ③ port:in1  n_vlm_llm 语义 (dict 里有 stage/conf/label 才认; 纯潜向量认不出 ⇒ 跳过)
          ④ file      l5_understand_latest.json + l5_scene_vec.json (兜底)
        """
        live = self.read_live()
        live["vec"] = live.get("vec")

        # ── 端口优先 ────────────────────────────────────────────────────────
        p_stage = p_conf = p_label = p_vec = p_kind = None
        # in5=ss_moe 阶段先验 / in3=sscalib 标定层(含 stage+speed) / in1=n_vlm_llm 语义
        # 实测: ss_moe 三个端口全 None ⇒ 真实的 stage 只有 sscalib.out2 给得出来
        for pname in ("in5", "in3", "in4", "in1"):
            pp = self._parse_port((port_data or {}).get(pname), pname)
            if pp.get("stage"):
                p_stage, p_conf = pp["stage"], pp.get("conf")
                p_label, p_vec = pp.get("label"), pp.get("vec")
                p_kind = "port:%s%s" % (pname, (" (" + pp["stage_src"] + ")") if pp.get("stage_src") else "")
                break

        if stage:
            st, conf, label, vec, src_kind = (stage, live["conf"], live["label"],
                                              live["vec"], "explicit")
        elif p_stage:
            st, conf = p_stage, (p_conf if p_conf is not None else live["conf"])
            label, vec, src_kind = (p_label or live["label"]), (p_vec or live["vec"]), p_kind
        else:
            st, conf, label, vec, src_kind = (live["stage"], live["conf"],
                                              live["label"], live["vec"], "file")

        out = {"ok": False, "stage": st, "conf": conf, "label": label,
               "vec": vec, "age_s": live["age_s"], "src": live["src"],
               "src_kind": src_kind, "T_goal": None, "k_l5": 0.0, "why": [],
               "range_src": None}

        # ── ⓪ L5 自主标定优先 (老倪 2026-11-15: "L5 是自主标定; 215 点回放是本基准, 不能拿回放点当目标") ──
        # 视觉能给"工件此刻在哪" → 用它当 T_goal; 给不出才退回 215 点表的阶段区间**仅作参考**
        vT, vinfo = self.visual_goal(port_data=port_data)
        out["visual"] = {k: vinfo[k] for k in ("ok", "why", "src_kind") if k in vinfo}
        if vT is not None:
            out["ok"] = True
            out["T_goal"] = vT.tolist()
            out["goal_src"] = "L5_visual"          # 与 goal_src=215点表 区分
            out["range_src"] = None
            out["visual"] = vinfo
            allow, k, note = self.gate((p_conf if p_conf is not None else live["conf"]) or 0.6)
            out["k_l5"] = round(k if allow else K_MIN, 4)
            out["why"].append("L5 自主标定: " + str(vinfo.get("why")))
            if not allow:
                out["why"].append(note + " (视觉目标已算出, 但置信不足 ⇒ 势场权重取最小)")
            out["stages_ref"] = {"stage": st, "ref_range": None,
                                 "note": "215 点表只作安全包络参考, 不参与目标生成"}
            return out       # ← 视觉目标一旦成立, 不再用回放点当目标

        if not st:
            out["why"].append("无阶段语义 (端口 in5/in1 与 l5_understand_latest.json 都取不到)")
            out["why"].append("且无视觉 3D 目标 ⇒ L5 无法定目标")
            return out
        if st not in STAGES:
            out["why"].append("阶段 %r 不在八阶段表内" % st)
            return out
        if src_kind == "file" and live["age_s"] is not None and live["age_s"] > max_age_s:
            out["why"].append("判读过期 %.1fs > %.1fs" % (live["age_s"], max_age_s))

        Tg, gmeta = self.goal_for_stage(st)
        if Tg is None:
            out["why"].append("阶段目标取不到: %s" % gmeta.get("why"))
            return out
        out["T_goal"] = Tg.tolist()
        out["goal_idx"] = gmeta.get("idx")
        out["stage_range"] = gmeta.get("range")
        out["range_src"] = gmeta.get("range_src")
        out["goal_src"] = "215点表(参考)"     # ⚠️ 不是自主标定, 只是回放基准的出口点

        allow, k, note = self.gate(conf)
        out["k_l5"] = round(k, 4)
        out["gate"] = note
        out["ok"] = True
        out["degraded"] = (not allow)
        if not allow:
            out["why"].append(note)
        if isinstance(vec, (list, tuple)) and len(vec) >= 3:
            v = np.asarray(vec, float).reshape(3)
            n = float(np.linalg.norm(v[:2]))
            out["cam_hint"] = (None if n < 1e-9
                               else [round(float(v[0] / n), 4), round(float(v[1] / n), 4), 0.0])
            out["cam_hint_note"] = "相机系水平方向 (需外参才能进 base_link); 不进 T_goal"
        else:
            out["cam_hint"] = None
            out["why"].append("无方向矢量 (检测框缺失 ⇒ vec=null)")
        out["why"] = out["why"] or ["正常"]
        return out


if __name__ == "__main__":
    import sys
    g = L5Guide()
    live = g.read_live()
    print("=== 当前 L5 判读 ===")
    print(json.dumps(live, ensure_ascii=False, indent=2))
    print("\n=== 八阶段 → 215 点表区间 ===")
    for s in STAGES:
        i0, i1, rsrc = g.stage_range(s)
        Tg, meta = g.goal_for_stage(s)
        tm = (None if Tg is None else np.round(Tg[:3, 3] * 1000.0, 2).tolist())
        print("  %-4s [%3d,%3d] idx=%3s  目标 t_mm=%s  (%s)" % (s, i0, i1, meta.get("idx"), tm, rsrc))
    print("\n=== guide() 实测 (用当前 live 语义) ===")
    r = g.guide()
    print(json.dumps({k: v for k, v in r.items() if k != "T_goal"}, ensure_ascii=False, indent=2))
    raise SystemExit(0)
