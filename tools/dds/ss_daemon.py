#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zmax_dds_ss_daemon.py — 📡 全局数据空间发布守护 (状态空间真实数据源 → DDS, 受模式控制)

老倪 2026-09-25/26:
  「topic 用于测试, 标定, 诊断, 量产时不用」+「写全局数据空间发布守护 (把所有真实数据源接上 DDS, 受模式控制)」

════════════════════ 设计 (与 docs/DDS-TELEMETRY-ARCHITECTURE.md 同口径) ════════════════════
① **受模式控制**: 模式 = env `ZMAX_TELEMETRY` > 运行时 > 文件 `~/.zmax_telemetry_mode` > prod
   · prod: **根本不 import cyclonedds**、不建参与者、不开线程 → 量产零开销 (只空转等模式变化)
   · diag/calib/test: 只发该档允许的话题 (见 zmax_telemetry.MODE_TOPICS)
② **只读真实数据源** (不触发任何动作, 不写任何业务文件):
   ss_state  ← 真机 tap `~/zmax/zmax_data/ss_live/state_*.jsonl` 最新行 (tcp / jpos / gripper / prod_stage / pubs)
   ss_action ← 真机 tap `~/zmax/zmax_data/ss_live/proposal_*.jsonl` 最新行 (action 6 维 / yaw / model_ms)
   ss_infer  ← 本机推理服务 `http://127.0.0.1:8790/health` (models / infer_count / last_ms / device)
   ss_calib  ← 标定真源文件 (手眼 / 相机外参 / 对齐图 / 质量门) —— 有则实发, 无则 valid=0
   ss_diag   ← 诊断: 各话题发布计数 / 源帧龄 / 推理延时 / 服务健康度 (systemctl 每 10s)
   ss_test   ← 最近一次取证结果 (reports/verify_*.json · sim2real_preflight · web agent 27/27)
③ **未测量 = -1.0** (不用 0 冒充) · 每条消息带 ts + 每话题 seq · 源帧过期 (>5s) 只发 diag 告警不发状态
④ 通道分离: 本守护只做 **通道 A (内网遥测)**; APP 硬件上报 (hw_state) 属通道 B, 由 zmax-dds-pub 独立跑

用法:
  python3 zmax_dds_ss_daemon.py --status          # 看模式 + 允许话题 + 各源可用性
  python3 zmax_dds_ss_daemon.py --once            # 发一轮(按当前模式) 后退出 (取证/自检用)
  python3 zmax_dds_ss_daemon.py --seconds 30      # 跑 30 秒
  python3 zmax_dds_ss_daemon.py                   # 常驻 (systemd 用)
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import subprocess
import sys
import threading
import time

# 🐛 2026-10-14 实测: 节拍线程 (ss_cfg_names / ss_engine) 与 DDS 建链是并发的, 线程可能先跑一轮
#   ⇒ 日志出现「⚠️ ss_engine 发布失败: ModuleNotFoundError: No module named 'ss_types'」(首轮丢一帧)。
#   ss_types.py / zmax_types.py / dds_link_bus.py 就在本文件同目录 ⇒ 模块级先注入一次 (幂等, 与
#   ensure_node() 里的 DDS_DIR 注入是同一件事)。
_DDS_SELF = os.path.dirname(os.path.abspath(__file__))
if _DDS_SELF not in sys.path:
    sys.path.insert(0, _DDS_SELF)

HOME = os.path.expanduser("~")
# ⚠️ 2026-10-07 修正: 默认原来是 ~/zmax_ss_remote, 但**真实 tap 一直在工程根的 zmax_data/ss_live**
#    (state_*/proposal_*/energy_* 都写那里) ⇒ 旧默认等于守护一个空目录(状态/动作/能量话题全静默)。
#    现在: 显式 env > 规范路径(存在就用) > 旧默认 (保持向后兼容)。
_TAP_CANON = os.path.join(os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax"), "zmax_data", "ss_live")
_TAP_LEGACY = os.path.join(HOME, "zmax_ss_remote")
SS_REMOTE = os.environ.get("SS_REMOTE_DIR") or (_TAP_CANON if os.path.isdir(_TAP_CANON) else _TAP_LEGACY)
# 🧭 MoveIt plan-only 的 DDS 镜像 tap (老倪 2026-09-29「把 /plan_kinematic_path 返回的关节轨迹
#    也镜像成 DDS 一条 ss_plan」): 容器 zmax-moveit 里 moveit_plan_live.py 逐轮规划追加一行,
#    本守护读最新一行 → 发 ss_plan。只规划不执行(容器 allow_trajectory_execution=False)。
PLAN_DIR = os.environ.get("SS_PLAN_DIR", os.path.join(HOME, "zmax_moveit_plan"))
PLAN_FILE = os.path.join(PLAN_DIR, "live_plan.jsonl")
REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")   # ★ 单一工程根(2026-09-29 整治: 原来错指 mac-hw 共享检出)
MODELS = os.path.join(REPO, "models")
REPORTS = os.path.join(REPO, "reports")
REPORTS_CANDS = [os.path.join(REPO, "reports"), REPORTS]
INFER = "http://127.0.0.1:8790/health"
MODE_FILE = os.path.join(HOME, ".zmax_telemetry_mode")
DDS_DIR = os.path.join(REPO, "dds")
LOG = os.path.join("/tmp", "zmax_dds_ss.log")
STALE_S = 5.0                     # 源帧龄超过它就只发 diag, 不发状态/动作 (老倪: 负帧龄拒用)
# 能量层是**每轮聚合量**(跑一次 pipeline 迭代出一份), 不是 10Hz 流 ⇒ 单独的帧龄预算:
#   900s 内算"本轮有效"; 超过就当没有 (宁可不发, 也不把上上轮的数当现在).
STALE_ENERGY_S = float(os.environ.get("ZMAX_ENERGY_STALE_S", "900"))
# 🔧 驱动扭矩是**逐帧高频信号** (10Hz 实测数据通道) ⇒ 用紧的帧龄预算: 3s 内算现在, 超过就发 -1 并说明
STALE_TORQUE_S = float(os.environ.get("ZMAX_TORQUE_STALE_S", "3.0"))
# 🧮 配置名称清单: 它只在**主参数节点执行**时才刷新 (不是流) ⇒ 帧龄预算给宽: 10 分钟内算"现在",
#    超过就在 note 里明说"节点记录陈旧"(真源纪律: 不拿旧记录当现状), 但名称照发(名称本身没变过就不算错)。
STALE_CFG_S = float(os.environ.get("ZMAX_CFG_STALE_S", "600"))
# 🧮 流形引擎常驻回路 (老倪 2026-10-14): tap 由 tools/ss_engine_loop.py 每周期写, 这里读它发 DDS。
#    与扭矩同口径: 帧龄超 STALE_ENGINE_S 只发告警, **不把旧帧当现在**。
STALE_ENGINE_S = float(os.environ.get("ZMAX_SS_ENGINE_STALE_S", "3.0"))
ENGINE_TAP_DIR = os.environ.get("ZMAX_SS_ENGINE_TAP_DIR") or "/dev/shm/zmax_ss_engine"
_EN_LOGGED = {"dir": "", "none": 0.0}
# 🎛 八阶段状态机 (老倪 2026-10-15「八个状态, 是哪个 topic 发出来的?」): 阶段快照帧龄阈值 +
#    停发日志节流 (与 ss_engine 同款口径 —— 源不新鲜就明说停发, 不拿旧阶段当现在)
STAGE_STALE_S = float(os.environ.get("ZMAX_SS_STAGE_STALE_S", "5.0"))
_ST_LOGGED = {"none": 0.0, "stale": 0.0}
# 🧮 主参数节点已加载配置名称的真源: 画布真源里该节点的 params (cfg_entries/cfg_loaded_at)
CFG_CANDS = [os.path.join(REPO, "data", "database", "zmax", "sources", "canvas", "state_space_obs.json"),
             os.path.join(REPO, "flows", "state_space_obs.json"),
             os.path.join(HOME, "lerobot-smolvla-lew", "flows", "state_space_obs.json")]

# 模式 → 允许话题 (与 tools/gui/zmax_telemetry.py::MODE_TOPICS 同口径)
CHUNK_STALE_S = float(os.environ.get("ZMAX_CHUNK_STALE_S", "30"))
META_PRED_STALE_S = 180.0        # 元任务预测帧龄阈值 (超过 ⇒ note 里明说陈旧, 不拿旧预测冒充现在)

# ⚖ 原子技能话题 (SK01..SK08) —— 与 src/lerobot/dataspace/topics.py::SKILL_TOPICS 同口径
SKILL_TOPICS = ["skill_%s" % c for c in
                ("sk01", "sk02", "sk03", "sk04", "sk05", "sk06", "sk07", "sk08")]
SKILL_PHYS = os.path.join(_TAP_CANON, "skill_phys.json")   # 数值真源 (技能派发循环服务 60Hz 写)
POSE_STALE_S = float(os.environ.get("ZMAX_SKILL_POSE_STALE_S", "5.0"))   # 位姿停更 ⇒ 位置/角度发 -1

MODE_TOPICS = {
    "prod": [],
    "diag": ["hw_state", "heartbeat", "ss_infer", "train_prog", "ss_diag", "ss_energy", "ss_torque",
             "ss_cfg_names", "ss_engine", "ss_meta_task", "ss_meta_pred", "ss_stage", "ss_action_chunk"]
             + SKILL_TOPICS,
    "calib": ["ss_state", "ss_action", "link_value", "hw_state", "heartbeat", "ss_calib", "ss_diag",
              "ss_plan", "ss_energy", "ss_torque", "ss_cfg_names", "ss_engine", "ss_meta_task",
              "ss_meta_pred", "ss_stage", "ss_action_chunk"] + SKILL_TOPICS,
    "test": ["hw_state", "heartbeat", "train_prog", "deploy_cmd", "link_value", "ss_state", "ss_action",
             "ss_infer", "ss_canvas", "ss_macro", "ss_nodes", "ss_calib", "ss_diag", "ss_test",
             "ss_plan", "ss_energy", "ss_torque", "ss_cfg_names", "ss_engine", "ss_meta_task",
             "ss_meta_pred", "ss_stage", "ss_action_chunk"] + SKILL_TOPICS,
}
MODE_TOPICS["dev"] = MODE_TOPICS["test"]


def log(m):
    line = "%s %s" % (time.strftime("%F %T"), m)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:                                                        # noqa: BLE001
        pass


# ───────────────────────── 模式 (单一真源优先, 读不到则按同口径兜底) ─────────────────────────
def mode():
    env = (os.environ.get("ZMAX_TELEMETRY") or "").strip().lower()
    if env in MODE_TOPICS:
        return env
    for p in (os.path.join(REPO, "tools", "gui"),):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    try:
        import zmax_telemetry as zt                                  # noqa: PLC0415
        return zt.mode()
    except Exception:                                                # noqa: BLE001
        pass
    try:
        m = open(MODE_FILE, encoding="utf-8").read().strip().lower()
        if m in MODE_TOPICS:
            return m
    except Exception:                                                # noqa: BLE001
        pass
    return "prod"


def allowed(topic):
    _m = MODE_TOPICS.get(mode(), [])
    if topic not in _m:
        return False
    # 🧭 2026-10-15 老倪三产品分工(以后同步开发 A/B/C): 产品档位**再收一道**, 且只能收窄不能放宽 ——
    #   C 档(量产) topics=none ⇒ 不发任何序列化 topic (信号只走共享内存 /dev/shm/zmax_ss_engine 直传);
    #   A 档(开发) topics=core ⇒ 只发核心集; B 档(调试) topics=all ⇒ 全开。真源 tools/zmax_profile.py。
    try:
        _tp = os.path.join(REPO, "tools")
        if os.path.isdir(_tp) and _tp not in sys.path:
            sys.path.insert(0, _tp)
        import zmax_profile as _zp                                          # noqa: PLC0415
        if _zp.topics_mode() == "none":
            return False
        return topic in set(_zp.dds_topics_allowed(_m))
    except Exception as _e:                                                 # noqa: BLE001
        log("⚠️ 产品档位读取失败, 按运行模式原样放行: %s" % str(_e)[:80])
        return True


# ───────────────────────── 真实数据源读取 (全只读) ─────────────────────────
def _newest(pattern):
    c = glob.glob(pattern)
    return max(c, key=os.path.getmtime) if c else None


def _last_line(path, max_bytes=262144):
    """只读文件尾 (不整文件读入 — state_*.jsonl 已 500MB+)"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            chunk = f.read().decode("utf-8", "ignore").strip().splitlines()
        for ln in reversed(chunk):
            if ln.strip().startswith("{"):
                try:
                    return json.loads(ln)
                except Exception:                                    # noqa: BLE001
                    continue
    except Exception:                                                # noqa: BLE001
        pass
    return None


def _quat_angle_deg(q):
    """四元数 → 末端姿态的旋转角 (deg) = 2·acos(|w|); 读不到 ⇒ -1 (不用 0 冒充)"""
    try:
        w = abs(float(q[3] if len(q) >= 4 else q[0]))
        w = max(-1.0, min(1.0, w))
        return round(2.0 * math.degrees(math.acos(w)), 3)
    except Exception:                                                    # noqa: BLE001
        return -1.0


def read_state():
    """真机 tap 状态帧 (tcp/jpos/gripper/prod_stage)"""
    p = _newest(os.path.join(SS_REMOTE, "state_*.jsonl"))
    if not p:
        return None, None
    d = _last_line(p)
    return d, (os.path.getmtime(p) if p else None)


def read_proposal():
    """推理服务对真机帧的输出 (action 6 / yaw / model_ms)"""
    p = _newest(os.path.join(SS_REMOTE, "proposal_*.jsonl"))
    if not p:
        return None, None
    d = _last_line(p)
    return d, (os.path.getmtime(p) if p else None)


def read_plan():
    """MoveIt plan-only 最新一条规划 (含同源闸判据)"""
    p = PLAN_FILE if os.path.isfile(PLAN_FILE) else None
    if not p:
        return None, None
    d = _last_line(p)
    return d, (os.path.getmtime(p) if p else None)


def read_energy():
    """流形引擎能量层 tap (tools/manifold_energy_probe.py 真跑一轮 pipeline 迭代写出)"""
    p = _newest(os.path.join(SS_REMOTE, "energy_*.jsonl"))
    if not p:
        return None, None
    return _last_line(p), os.path.getmtime(p)


# 🔴 2026-10-14 修 (与 2026-10-07 那次同类坑, 换了个形式): 扭矩 tap 在 2026-10-13 已改为写**内存盘**
#    /dev/shm/zmax_torque (10Hz 逐帧 ≈2GB/天, 不再落盘), 但本守护仍按 SS_REMOTE(=工程根 zmax_data/ss_live)
#    找 torque_*.jsonl ⇒ 永远找不到 ⇒ pub_torque 静默返回 False ⇒ **话题 zmax/ss_torque 全静默**
#    (现场表现: "流形引擎在跑, 数据空间这条话题一条都看不到")。口径与发布器同源:
#    显式 env ZMAX_TORQUE_TAP_DIR > 内存盘规范路径(存在就用) > SS_REMOTE(向后兼容)。
_TQ_CANON = os.environ.get("ZMAX_TORQUE_TAP_DIR") or "/dev/shm/zmax_torque"
TORQUE_TAP_DIR = _TQ_CANON if os.path.isdir(_TQ_CANON) else SS_REMOTE
_TQ_LOGGED = {"dir": "", "none": 0.0}


def read_torque():
    """驱动扭矩 tap (tools/tdrive_bus.py 逐帧算 T_drive = M·(−∇Φ) 写出; 最后一行才是 payload)"""
    if TORQUE_TAP_DIR != _TQ_LOGGED["dir"]:
        log("🛞 扭矩 tap 目录 = %s (发布器同源口径; 找不到就明说, 不许静默)" % TORQUE_TAP_DIR)
        _TQ_LOGGED["dir"] = TORQUE_TAP_DIR
    p = _newest(os.path.join(TORQUE_TAP_DIR, "torque_*.jsonl"))
    if not p:
        if time.time() - _TQ_LOGGED["none"] > 60:      # 静默 60s 报一次, 不刷屏
            log("⏸ 扭矩 tap 目录里没有 torque_*.jsonl (%s) → ss_torque 不发 (跑 tools/tdrive_bus.py run)"
                % TORQUE_TAP_DIR)
            _TQ_LOGGED["none"] = time.time()
        return None, None
    return _last_line(p), os.path.getmtime(p)


def read_engine():
    """流形引擎常驻回路 tap (tools/ss_engine_loop.py 每周期一行; **最后一行才是 payload**)"""
    if ENGINE_TAP_DIR != _EN_LOGGED["dir"]:
        log("🧮 流形引擎 tap 目录 = %s (发布器同源口径; 找不到就明说, 不许静默)" % ENGINE_TAP_DIR)
        _EN_LOGGED["dir"] = ENGINE_TAP_DIR
    p = _newest(os.path.join(ENGINE_TAP_DIR, "engine_*.jsonl"))
    if not p:
        if time.time() - _EN_LOGGED["none"] > 60:
            log("⏸ 流形引擎 tap 目录里没有 engine_*.jsonl (%s) → ss_engine 不发 (跑 tools/ss_engine_loop.py run)"
                % ENGINE_TAP_DIR)
            _EN_LOGGED["none"] = time.time()
        return None, None
    return _last_line(p), os.path.getmtime(p)


def read_trace_stage():
    """🎛 动作调制器八阶段状态机 —— 真源 = 3D 面板快照 trace_live.json 的阶段字段。

    老倪 2026-10-15: 「八个状态, 是哪个 topic 发出来的? 你要放到信号分析的窗口里显示」
    在这之前**没有任何话题**发这八个状态: 阶段只是 trace_live.json 里的一个**字符串**
    ("阶段": "抓取") ⇒ 信号分析页只收数值 ⇒ 看不到状态机。这里读三件事:
      阶段(名) / 阶段序号(0..12) / 八阶段序号(0..7) / 阶段限速_mps —— 后三项由 3D 面板发的数值通道给。
    返回 (dict, mtime) —— 缺字段就返回 None(不猜), 由 pub_stage 决定发不发。
    """
    p = os.path.join(_TAP_CANON, "trace_live.json")
    if not os.path.isfile(p):
        return None, None
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:                                                        # noqa: BLE001
        return None, None
    if not isinstance(d, dict) or "阶段" not in d:
        return None, None
    return d, os.path.getmtime(p)


def read_infer():
    try:
        import urllib.request
        with urllib.request.urlopen(INFER, timeout=3) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception:                                                # noqa: BLE001
        return {}


def read_calibs():
    """标定真源 (存在才发, 不发假值)

    ⚠️ 2026-09-26: 标定文件在 **main 线检出** (worktree /home/ubuntu/zmax/models) ——
    共享目录 /home/ubuntu/zmax 被切到别的分支后这些文件会"消失"
    → 必须在多候选目录里找, 否则标定通道静默空转。
    """
    out = []
    trees = [os.path.join(REPO, "models"),
             MODELS,
             os.path.join(HOME, "zmax_data", "calib")]
    seen = set()
    cands = []
    for t in trees:
        for fn, kind in (("handeye_state.json", "handeye"), ("real_cam_calib.json", "extrinsic"),
                         ("l4_align_map.json", "align"), ("lie_quality_gate.json", "gate")):
            p = os.path.join(t, fn)
            if p in seen:
                continue
            seen.add(p)
            cands.append((p, kind))
    for p, kind in cands:
        if os.path.isfile(p):
            try:
                out.append((kind, json.load(open(p, encoding="utf-8"))))
            except Exception:                                        # noqa: BLE001
                out.append((kind, {}))
    return out


def _age_of_stamp(s):
    """'%F %T' 时刻 → 距今秒数 (解析失败返回 None, 不猜)"""
    try:
        return max(0.0, time.time() - time.mktime(time.strptime(str(s).strip(), "%Y-%m-%d %H:%M:%S")))
    except Exception:                                                    # noqa: BLE001
        return None


def read_cfg_names():
    """🧮 主参数节点 (n_calib_mani) **已加载的配置名称** (只读画布节点参数, 不猜不编)

    老倪 2026-10-14: 「主参数节点, 需要发出 加载的配置名称的 topic, 字符串就可以, 周期 5 秒」
    返回 {names[list], loaded_at, source, note} —— names 取 params.cfg_entries 的**键**
    (节点加载时逐个写进这份清单, 键就是配置名称; 路径/哈希在值里, 不要)。
    """
    out = {"names": [], "loaded_at": "", "source": "", "note": ""}
    for c in CFG_CANDS:
        if not os.path.isfile(c):
            continue
        try:
            d = json.load(open(c, encoding="utf-8"))
        except Exception as e:                                           # noqa: BLE001
            out["note"] = "画布真源解析失败: %s" % type(e).__name__
            continue
        for n in (d.get("nodes") or []):
            pr = n.get("params") or {}
            if not (n.get("id") == "n_calib_mani" or pr.get("manifold_calib")
                    or "标定诊断测量" in str(n.get("name", ""))):
                continue
            ent = pr.get("cfg_entries")
            if isinstance(ent, dict):
                out["names"] = [str(k) for k in ent.keys()]
            elif isinstance(ent, list):
                out["names"] = [str(x.get("name") if isinstance(x, dict) else x) for x in ent]
            out["loaded_at"] = str(pr.get("cfg_loaded_at") or "")
            out["source"] = "%s · 节点 %s" % (os.path.relpath(c, REPO), n.get("id"))
            if not out["names"]:
                out["note"] = "主参数节点还没加载过配置 (无 cfg_entries)"
            return out
        out["note"] = "画布上没有主参数节点"
        return out
    out["note"] = "画布真源找不到 (%s)" % os.path.basename(CFG_CANDS[0])
    return out


def read_canvas_nodes():
    """画布真源 (state_space_obs.json) → 节点清单 [{id,name,layer,type}]

    层判定与画布一致: 按 y 行带读 params.layer / 行背景名; 取不到就留空 (不猜)。
    """
    cands = [os.path.join(REPO, "flows", "state_space_obs.json"),
             os.path.join(REPO, "flows", "state_space_obs.json"),
             os.path.join(HOME, "lerobot-smolvla-lew", "flows", "state_space_obs.json")]
    for c in cands:
        if not os.path.isfile(c):
            continue
        try:
            d = json.load(open(c, encoding="utf-8"))
        except Exception:                                                # noqa: BLE001
            continue
        rows = {}                       # y → 行名 (来自 row_bg 背景节点)
        for n in d.get("nodes", []):
            pr = n.get("params") or {}
            if pr.get("bg") or pr.get("row_bg"):
                rows[int(n.get("y", 0))] = str(n.get("name", ""))
        out = []
        for n in d.get("nodes", []):
            pr = n.get("params") or {}
            if pr.get("bg") or pr.get("row_bg"):
                continue
            y = int(n.get("y", 0))
            out.append({"id": str(n.get("id", "")), "name": str(n.get("name", "")),
                        "layer": str(pr.get("layer") or rows.get(y, "") or ""),
                        "type": str(n.get("type", "")), "file": os.path.basename(c)})
        if out:
            return out, c
    return [], ""


def read_memory_layers():
    """五层记忆真源 (data/memory/memory_layers.json)"""
    for c in (os.path.join(REPO, "data", "memory", "memory_layers.json"),
              os.path.join(REPO, "data", "memory", "memory_layers.json"),
              os.path.join(HOME, "lerobot-smolvla-lew", "data", "memory", "memory_layers.json")):
        if not os.path.isfile(c):
            continue
        try:
            return json.load(open(c, encoding="utf-8")), c
        except Exception:                                                # noqa: BLE001
            continue
    return {}, ""


def read_dds_services():
    """在役 DDS 相关服务 (systemctl, 10s 缓存)"""
    out = {}
    for s2 in ("zmax-dds-pub", "zmax-dds-agg", "zmax-dds-ss"):
        try:
            r = subprocess.run(["systemctl", "is-active", s2], capture_output=True, text=True, timeout=5)
            out[s2] = (r.stdout or "").strip() or "unknown"
        except Exception:                                                # noqa: BLE001
            out[s2] = "?"
    return out


def read_test_result():
    """最近一次取证结果 (passed/total 若有)"""
    pats = ["verify_*.json", "*preflight_*.json", "intact_v4_*.json", "l4_intact_ab_*.json"]
    best = None
    for pat in pats:
        for rd in REPORTS_CANDS:
            for p in glob.glob(os.path.join(rd, pat)):
                if best is None or os.path.getmtime(p) > best[1]:
                    best = (p, os.path.getmtime(p))
    if not best:
        return None
    p, mt = best
    passed = failed = total = None
    detail = os.path.basename(p)
    try:
        d = json.load(open(p, encoding="utf-8"))
        if isinstance(d, dict):
            for k in ("passed", "ok_count", "judge_passed", "n_pass"):
                if isinstance(d.get(k), int):
                    passed = d[k]
                    break
            for k in ("failed", "ng_count", "n_fail"):
                if isinstance(d.get(k), int):
                    failed = d[k]
                    break
            for k in ("total", "n", "judge_total", "n_total"):
                if isinstance(d.get(k), int):
                    total = d[k]
                    break
            detail = "%s %s" % (detail, json.dumps({k: d[k] for k in list(d)[:3]}, ensure_ascii=False)[:120])
    except Exception:                                                # noqa: BLE001
        pass
    return {"path": p, "suite": pat.split("*")[0].strip("_") or "verify",
            "passed": passed, "failed": failed, "total": total, "detail": detail, "ts": mt}


def services_health():
    out = {}
    for s in ("ss-local-infer", "ss-bypass", "ss-remote-tap", "ss-yolo-bypass",
              "zmax-dds-pub", "zmax-dds-agg"):
        try:
            r = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True, timeout=5)
            out[s] = (r.stdout or "").strip() or "unknown"
        except Exception:                                            # noqa: BLE001
            out[s] = "?"
    return out


# ───────────────────────── 发布守护 ─────────────────────────
class SSDaemon:
    def __init__(self):
        self.node = None
        self.seq = {}
        self.sent = {}
        self.errs = 0
        self.t0 = time.time()
        self._svc = {}
        self._svc_t = 0.0
        self._mode = None
        self._canvas_i = 0          # ss_canvas 轮转游标
        self._t_cfg = 0.0           # 🧮 ss_cfg_names 上次发布时刻 (专用线程用)
        self._stop = threading.Event()   # 🧮 线程退出信号 (run 退出时置位)
        self._svc_nodes = {}
        self._svc_nodes_t = 0.0
        self._pending = {}      # topic → 等配对是否成功 (只提示一次)

    def ensure_node(self):
        if self.node is not None:
            return True
        if DDS_DIR not in sys.path:
            sys.path.insert(0, DDS_DIR)
        try:
            from zmax_node import Node                              # noqa: PLC0415
            # ⚠ 2026-09-29 实测坑: 原来写 `cfg if os.path.getsize(cfg) else None` —— 文件**不存在**时
            #   os.path.getsize 直接抛 FileNotFoundError ⇒ 整个 DDS 参与者建不起来 ⇒ 所有话题静默
            #   (表现: 状态灯全黑, 日志刷 "DDS 不可用: No such file")。缺文件/空文件都应视为"没配, 走默认发现"。
            cfg = os.path.join(DDS_DIR, "cyclonedds_unicast.xml")
            if not os.path.isfile(cfg) or os.path.getsize(cfg) == 0:
                cfg = None                                          # 默认多播发现(=当前实测可用状态)
                log("ℹ️ 未配单播配置文件(或为空) → 用默认发现; 跨机单播见 dds/cyclonedds_unicast.template.xml")
            self.node = Node("ss_daemon", domain=0, config_xml=cfg)
            log("📡 DDS 参与者已建立 (mode=%s, 允许话题 %d 个)" % (mode(), len(MODE_TOPICS.get(mode(), []))))
            return True
        except Exception as e:                                        # noqa: BLE001
            self.errs += 1
            log("⚠️ DDS 不可用: %s" % str(e)[:140])
            self.node = None
            return False

    def drop_node(self):
        self.node = None
        log("🔴 切到 prod: DDS 参与者已释放 (量产零开销)")

    def publish(self, topic, msg):
        """按模式发一条 (带 ts/seq)"""
        if not allowed(topic):
            return False
        if not self.ensure_node():
            return False
        self.seq[topic] = self.seq.get(topic, 0) + 1
        if topic not in self._pending and self.node.wait_for_match(topic, 1, 1.5):
            self._pending[topic] = True
        try:
            self.node.send(topic, msg)
            self.sent[topic] = self.sent.get(topic, 0) + 1
            return True
        except Exception as e:                                        # noqa: BLE001
            self.errs += 1
            log("⚠️ 发 %s 失败: %s" % (topic, str(e)[:110]))
            return False

    # ── 各真实源 → DDS 消息 ──
    def pub_energy(self):
        """流形引擎能量层 → zmax/ss_energy (功率/转速/扭矩/能量/效率/能级壳层)"""
        from ss_types import SSEnergy, SSEnergyLayer                 # noqa: PLC0415

        def _f(v, dv=-1.0):
            try:
                return float(v)
            except (TypeError, ValueError):
                return float(dv)

        def _i(v, dv=-1):
            try:
                return int(v)
            except (TypeError, ValueError):
                return int(dv)

        d, mt = read_energy()
        age = (time.time() - mt) if mt else -1.0
        if not d:
            return False
        if age > STALE_ENERGY_S:
            log("⏸ 能量 tap 过期 %.0fs (>%.0fs) — 不伪装成在工作 (跑 tools/manifold_energy_probe.py run)" % (age, STALE_ENERGY_S))
            return False
        shells = [SSEnergyLayer(
            layer=str(s.get("layer") or ""), shell_n=_i(s.get("shell_n"), 0),
            e_layer_cj=_f(s.get("e_layer_cj"), 0.0), e_cum_cj=_f(s.get("e_cum_cj"), 0.0),
            e_work_cj=_f(s.get("e_work_cj"), 0.0), e_standing_cj=_f(s.get("e_standing_cj"), 0.0),
            level_c=_f(s.get("level_c")), tau_cj=_f(s.get("tau_cj"), 0.0), omega_hz=_f(s.get("omega_hz")),
            p_out_cjs=_f(s.get("p_out_cjs")), eta_cjj=_f(s.get("eta_cjj")),
            feasible_r=_f(s.get("feasible_r")), lora_r=_i(s.get("lora_r")),
            lora_boost_cj=_f(s.get("lora_boost_cj"), 0.0), share=_f(s.get("share")),
            note=str(s.get("note") or "")[:180]) for s in (d.get("shells") or [])]
        self.publish("ss_energy", SSEnergy(
            ts=float(d.get("ts") or time.time()), node=str(d.get("node") or "流形引擎"),
            state=str(d.get("state") or ""), e_total_cj=_f(d.get("e_total_cj"), 0.0),
            e_base_cj=_f(d.get("e_base_cj"), 0.0), e_boost_cj=_f(d.get("e_boost_cj"), 0.0),
            e_worksum_cj=_f(d.get("e_worksum_cj"), 0.0), e_standsum_cj=_f(d.get("e_standsum_cj"), 0.0),
            p_in_w=_f(d.get("p_in_w")), w_in_j=_f(d.get("w_in_j")), eta_total_cjj=_f(d.get("eta_total_cjj")),
            n_levels_active=_i(d.get("n_levels_active")), shells=shells,
            shell_monotonic_ok=_i(bool(d.get("shell_monotonic_ok")), -1),
            feasible_narrowing_ok=_i(bool(d.get("feasible_narrowing_ok")), -1),
            sum_ok=_i(bool(d.get("sum_ok")), -1),
            criterion=str(d.get("criterion") or ""), source=str(d.get("source") or ""),
            note="frame_age=%.1fs tap=%s" % (age, os.path.basename(_newest(
                os.path.join(SS_REMOTE, "energy_*.jsonl")) or ""))))
        return True

    def pub_torque(self):
        """驱动扭矩 T_drive = M·(−∇Φ) → zmax/ss_torque (6D 扭矩 / 主参数 M / 势场负梯度 / 健康度)"""
        from ss_types import SSDrivingTorque                              # noqa: PLC0415

        def _f(v, dv=-1.0):
            try:
                return float(v)
            except (TypeError, ValueError):
                return float(dv)

        def _vec(v, n=0):
            try:
                out = [float(x) for x in (v or [])]
            except TypeError:
                return []
            if n and len(out) != n:
                return []
            return out

        d, mt = read_torque()
        age = (time.time() - mt) if mt else -1.0
        if not d:
            return False
        if age > STALE_TORQUE_S:
            log("⏸ 驱动扭矩 tap 过期 %.1fs (>%.1fs) — 不把旧的当现在 (跑 tools/tdrive_bus.py run)" % (age, STALE_TORQUE_S))
            return False
        self.publish("ss_torque", SSDrivingTorque(
            ts=float(d.get("ts") or time.time()), node=str(d.get("node") or "流形引擎"),
            scene=str(d.get("scene") or ""), stage=str(d.get("stage") or ""), skill=str(d.get("skill") or ""),
            torque=_vec(d.get("torque"), 6), torque_norm=_f(d.get("torque_norm"), 0.0),
            torque_inv=_vec(d.get("torque_inv"), 6), unit=str(d.get("unit") or "N·m"),
            metric_tensor=_vec(d.get("metric_tensor")), metric_dim=int(d.get("metric_dim") or 0),
            potential_gradient=_vec(d.get("potential_gradient"), 6), neg_gradient=_vec(d.get("neg_gradient"), 6),
            phi=_f(d.get("phi"), 0.0), health=_f(d.get("health")), status=str(d.get("status") or ""),
            gain=_f(d.get("gain"), 1.0), x=_vec(d.get("x"), 3), gates=str(d.get("gates") or ""),
            source=str(d.get("source") or ""), unit_note=str(d.get("unit_note") or "")[:200],
            task_id=str((d.get("identity") or {}).get("task_id") or ""),
            task_name=str((d.get("identity") or {}).get("task_name") or "")[:80],
            product=str((d.get("identity") or {}).get("product_name") or "")[:80],
            product_prime=int((d.get("identity") or {}).get("product_prime") or 0),
            m_scale=float(((d.get("identity") or {}).get("main_params") or {}).get("metric_M") or -1.0),
            identity_json=json.dumps(d.get("identity") or {}, ensure_ascii=False)[:4000],
            note="frame_age=%.2fs tap=%s" % (age, os.path.basename(_newest(
                os.path.join(SS_REMOTE, "torque_*.jsonl")) or ""))))
        return True

    def pub_state(self):
        from ss_types import SSState                                 # noqa: PLC0415
        d, mt = read_state()
        age = (time.time() - mt) if mt else -1.0
        if not d or age > STALE_S:
            return False
        tcp = d.get("tcp") or []
        jpos = d.get("jpos") or []
        vec = [float(x) for x in (jpos + ([float(d["gripper"])] if isinstance(d.get("gripper"), (int, float)) else []))]
        self.publish("ss_state", SSState(
            ts=time.time(), layer="L2", stage=str(d.get("prod_stage", "") or ""),
            vec=vec, dim=len(vec),
            pos_x=float(tcp[0]) if len(tcp) > 0 else -1.0,
            pos_y=float(tcp[1]) if len(tcp) > 1 else -1.0,
            pos_z=float(tcp[2]) if len(tcp) > 2 else -1.0,
            source="real(tap)", note="frame_age=%.2fs tcp_frame=%s" % (age, d.get("tcp_frame", ""))))
        return True

    def pub_action(self):
        from ss_types import SSAction                                # noqa: PLC0415
        d, mt = read_proposal()
        age = (time.time() - mt) if mt else -1.0
        if not d or age > STALE_S:
            return False
        act = d.get("action") or []
        yaw = d.get("yaw") or {}
        self.publish("ss_action", SSAction(
            ts=time.time(), kind="joint", joints=[float(x) for x in act][:6],
            source="infer-8790(%s)" % d.get("input_map", ""),
            gate_reason="model_ms=%s yaw_ok=%s" % (d.get("model_ms"),
                                                  (yaw.get("ok") if isinstance(yaw, dict) else yaw))))
        return True

    def pub_plan(self):
        """🧭 MoveIt plan-only 轨迹 → DDS ss_plan (只规划不执行; 带同源闸)"""
        from ss_types import SSPlan                                 # noqa: PLC0415
        d, mt = read_plan()
        age = (time.time() - mt) if mt else -1.0
        if not d or age > max(STALE_S, 30.0):      # 规划比状态慢, 给到 30s 帧龄
            return False
        jp = [float(x) for x in (d.get("joints_path") or [])]
        tp = [float(x) for x in (d.get("tcp_path") or [])]
        n = int(d.get("n_points") or (len(jp) // 6) or -1)
        fk_err = float(d.get("fk_start_pos_err_mm", -1.0))
        # 同源闸: FK(真关节) 与真机 TCP 的位置差 ≤5mm 才算同源(可贴真机画面)
        if fk_err is None or fk_err < 0:
            gate, why = -1, "未判(缺 FK 起点误差)"
        elif fk_err <= 5.0:
            gate, why = 1, "同源: FK(真关节) 与真机 TCP 差 %.2fmm (≤5mm)" % fk_err
        else:
            gate, why = 0, ("不同源: FK(真关节) 与真机 TCP 差 %.1fmm (>5mm) —— 关节零位/符号口径不同, "
                            "只可当设计态轨迹看, 不许冒充真机" % fk_err)
        if d.get("gate_reason"):
            why = str(d["gate_reason"])[:200]
        self.publish("ss_plan", SSPlan(
            ts=time.time(), source=str(d.get("source", "moveit_plan_only")),
            group=str(d.get("group", "")), base_frame=str(d.get("base_frame") or d.get("base") or ""),
            plan_code=int(d.get("plan_code", -1)), n_points=n,
            plan_time_s=float(d.get("plan_time_s", -1.0)),
            joints_path=jp, tcp_path=tp,
            start_joints=[float(x) for x in (d.get("start_joints") or [])][:6],
            goal_xyz=[float(x) for x in (d.get("goal_xyz") or [])][:3],
            end_err_mm=float(d.get("end_err_mm", -1.0)), fk_start_pos_err_mm=fk_err,
            gate_same_source=gate, gate_reason=why,
            frame_age_s=float(d.get("frame_age_s", -1.0)),
            note=str(d.get("note", ""))[:200]))
        return True

    def pub_infer(self):
        from ss_types import SSInfer                                 # noqa: PLC0415
        h = read_infer()
        if not h:
            return False
        self.publish("ss_infer", SSInfer(
            ts=time.time(), model="+".join(h.get("models") or [])[:120], layer="L4",
            latency_ms=float(h.get("last_ms") if h.get("last_ms") is not None else -1.0),
            device=str(h.get("device", "")),
            ok=1 if h.get("online") else 0,
            note="infer_count=%s load_ms=%s port=%s" % (h.get("infer_count"), h.get("load_ms"), h.get("port"))))
        return True

    def pub_calib(self):
        from ss_types import SSCalib                                 # noqa: PLC0415
        n = 0
        for kind, d in read_calibs():
            T = []
            for k in ("T", "T_base_cam", "handeye", "transform"):
                v = d.get(k) if isinstance(d, dict) else None
                if isinstance(v, list) and len(v) == 16:
                    T = [float(x) for x in v]
                    break
            def g(*ks):
                for k in ks:
                    if isinstance(d, dict) and isinstance(d.get(k), (int, float)):
                        return float(d[k])
                return -1.0
            self.publish("ss_calib", SSCalib(
                ts=time.time(), kind=kind,
                src_frame=str((d or {}).get("src_frame", (d or {}).get("parent", "")) if isinstance(d, dict) else ""),
                dst_frame=str((d or {}).get("dst_frame", (d or {}).get("child", "")) if isinstance(d, dict) else ""),
                T=T, plane_z_mm=g("plane_z_mm", "plane_z", "z_mm"),
                tx=g("tx", "x"), ty=g("ty", "y"), tz=g("tz", "z"),
                rx_deg=g("rx_deg", "rx"), ry_deg=g("ry_deg", "ry"), rz_deg=g("rz_deg", "rz"),
                rms_mm=g("rms_mm", "residual_mm", "rmse_mm"), samples=int(g("samples", "n")),
                valid=1 if T or g("rms_mm") >= 0 else 0,
                note="file=%s" % kind))
            n += 1
        return n > 0

    def pub_meta_task(self):
        """🧾 任务 → 元任务清单 → zmax/ss_meta_task (老倪 2026-10-14)

        与「已加载配置名」同一个 5s 节拍、同一个出口 (主参数节点 n_calib_mani): 元任务是**配置的
        派生件**, 内容由 tools/ss_meta_task.py 真源现算 (复用 export_meta_doc.build_meta_tasks,
        与文档同一条映射链)。意图不参与内容, 只决定选哪一批 (任务ID)。
        """
        from ss_types import SSMetaTask                                  # noqa: PLC0415
        _t = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if _t not in sys.path:
            sys.path.insert(0, _t)
        import ss_meta_task as SM                                        # noqa: PLC0415
        d = SM.build(write=True)
        self.publish("ss_meta_task", SSMetaTask(
            ts=time.time(), task_id=str(d.get("task_id") or ""),
            task_name=str(d.get("task_name") or ""), n=int(d.get("n") or 0),
            n_all=int(d.get("n_all") or 0),
            layers=" · ".join("%s=%d" % kv for kv in (d.get("by_layer") or {}).items()),
            prio=" · ".join("%s=%d" % kv for kv in (d.get("by_prio") or {}).items()),
            fn_ids=", ".join((m.get("fn_id") or "") for m in (d.get("items") or [])[:12]),
            src="meta:%s bind:%s canvas:%s" % (
                (d.get("sources") or {}).get("config_meta.json"),
                (d.get("sources") or {}).get("ss_task_binding.json"),
                (d.get("sources") or {}).get("state_space_obs.json")),
            note=str(d.get("note") or "")))

    def pub_action_chunk(self):
        """🧩 **动作块** → zmax/ss_action_chunk (老倪 2026-10-15)。

        真源 = 常驻回路经 tools/ss_chunk_pipeline.py 落的 zmax_data/ss_live/chunk_latest.json。
        纪律: 帧龄 > CHUNK_STALE_S 就明说陈旧; 块不 ok (引擎无目标点等) 就发空块 + note 写原因, 不编块。
        """
        from ss_types import SSActionChunk                                    # noqa: PLC0415
        _root = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
        p = os.path.join(_root, "zmax_data", "ss_live", "chunk_latest.json")
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:                                               # noqa: BLE001
            self.publish("ss_action_chunk", SSActionChunk(ts=time.time(),
                                                          note="读不到块真源 %s (%s)" % (os.path.basename(p),
                                                                                          type(e).__name__)))
            return False
        age = time.time() - float(d.get("ts") or 0.0)
        note = ""
        if not d.get("ok"):
            note = "块未产出: %s" % str(d.get("reason") or "")[:80]
        elif age > CHUNK_STALE_S:
            note = "⚠️ 块陈旧 %.1fs (> %.0fs): 这不是现在的块" % (age, CHUNK_STALE_S)
        ch, ff, uu = (d.get("chunk") or []), (d.get("ff") or []), (d.get("u") or [])
        sk = d.get("skills") or {}
        # 技能派发帧龄 (由技能循环服务刷新的 skill_dispatch.json)
        _dage = -1.0
        try:
            with open(os.path.join(_root, "zmax_data", "ss_live", "skill_dispatch.json"), encoding="utf-8") as f:
                _dage = time.time() - float((json.load(f) or {}).get("ts") or 0.0)
        except Exception:                                                    # noqa: BLE001
            pass
        self.publish("ss_action_chunk", SSActionChunk(
            ts=time.time(), cycle=int(d.get("cycle") or 0), h=int(d.get("h") or 0),
            stage=str(d.get("stage") or ""), stage_idx=int(d.get("stage_idx") or -1),
            chunk_src=str(d.get("chunk_src") or "")[:120], ff_mode=str(d.get("ff_mode") or "")[:80],
            chunk=[float(x) for row in ch for x in (row or [])],
            ff=[float(x) for row in ff for x in (row or [])],
            u=[float(x) for row in uu for x in (row or [])],
            lam=[float(x) for x in (d.get("lam") or [])],
            # ⚠️ 数值字段不能用 `or -1.0` 兜底: 0.0 是**合法值** (块退化时转角=0), 会被误判成"没值"
            turn_max_deg=(-1.0 if d.get("turn_max_deg") is None else float(d["turn_max_deg"])),
            turn_mean_deg=(-1.0 if d.get("turn_mean_deg") is None else float(d["turn_mean_deg"])),
            step_delta=(-1.0 if d.get("step_delta") is None else float(d["step_delta"])),
            jerk=(-1.0 if d.get("jerk") is None else float(d["jerk"])),
            u_norm0=(-1.0 if d.get("u_norm0") is None else float(d["u_norm0"])),
            skill_list=", ".join("%s:步%d" % (k, int(v.get("step") or 0)) for k, v in list(sk.items())[:8]),
            dispatch_age_s=round(_dage, 2),
            ms=float(d.get("ms") or -1.0), src=str(d.get("chunk_src") or "")[:120], note=note))
        return True

    def pub_meta_pred(self):
        """🧾 **元任务预测值** → zmax/ss_meta_pred (老倪 2026-10-14: 「将元任务预测的topic，放到信号分析」)

        输入 = 流形引擎驱动扭矩 (zmax/ss_torque) ⇒ 各元任务(功能)得分 + top-k。
        真源 = tools/ss_meta_predict.py 落的 zmax_data/ss_live/meta_pred.json。
        纪律: 帧龄超过 META_PRED_STALE_S 就**明说陈旧**(预报值不是现在的值), trained/frozen 原样转发,
              不把"未训练/恒定输入"的降级结果说成有预测力。
        """
        from ss_types import SSMetaPred                                    # noqa: PLC0415
        p = os.path.join(os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax"),      # 与 _TAP_CANON 同根
                         "zmax_data", "ss_live", "meta_pred.json")
        d = {}
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:                                             # noqa: BLE001
            note = "读不到预测真源 %s (%s)" % (os.path.basename(p), type(e).__name__)
            self.publish("ss_meta_pred", SSMetaPred(ts=time.time(), note=note))
            return False
        ip = d.get("input") or {}
        top = d.get("top") or []
        ids, scs = [], []
        for it in top[:8]:
            if isinstance(it, dict):
                # 🧾 2026-10-15 老倪「需要显示确切的元任务」: 功能号后面**带上元任务名**
                #   (真源 meta_pred.json 的 top[].name) ⇒ 话题本身就自解释, 下游不用再查表。
                _fid = str(it.get("fn_id") or it.get("id") or "")
                _nm = str(it.get("name") or "").strip()
                ids.append((_fid + " " + _nm).strip() if _nm else _fid)
                scs.append("%.4f" % float(it.get("score") or it.get("s") or 0.0))
            else:
                ids.append(str(it)[:24])
                scs.append("")
        ts_pred = float(d.get("ts") or 0.0)
        age = (time.time() - ts_pred) if ts_pred else -1.0
        note = ""
        if age < 0:
            note = "预测真源无时间戳"
        elif age > META_PRED_STALE_S:
            note = "预测陈旧: %.0f 分钟前生成 (跑一次 ss_meta_predict 即刷新)" % (age / 60.0)
        if not int(d.get("trained") or 0):
            note = (note + " · " if note else "") + "未训练头 ⇒ 得分仅供参考"
        if int(d.get("frozen") or 0):
            note = (note + " · " if note else "") + "恒定输入降级 (无区分度, 如实标)"
        self.publish("ss_meta_pred", SSMetaPred(
            ts=time.time(), ts_pred=ts_pred, scene=str(ip.get("scene") or d.get("scene") or ""),
            task_id=str(d.get("task_id") or ""), n_meta=int(d.get("n_meta") or 0),
            n_cand=len(d.get("scores") or []) or len(top),
            top_ids=", ".join(x for x in ids if x), top_scores=", ".join(scs),
            input_src=str(ip.get("src") or ""), input_ok=1 if ip.get("ok") else 0,
            input_age_s=float(ip.get("age_s") or -1.0), method=str(d.get("method") or "")[:80],
            trained=int(d.get("trained") or 0), frozen=int(d.get("frozen") or 0),
            src="zmax_data/ss_live/meta_pred.json (%s)" % d.get("schema", "?"), note=note[:200]))
        return True

    def pub_cfg_names(self):
        """🧮 主参数节点已加载的配置名称 → zmax/ss_cfg_names (老倪 2026-10-14: 字符串型, 5s 周期)

        载荷只放**名称串** (+ loaded_at 供判帧龄); 节点记录陈旧时 note 里写明, 不假装是最新。
        """
        from ss_types import SSConfigNames                               # noqa: PLC0415
        r = read_cfg_names()
        names = " · ".join(r["names"])
        note = r["note"]
        if names and not note:
            age = _age_of_stamp(r["loaded_at"])
            if age is not None and age > STALE_CFG_S:
                note = "主参数节点记录陈旧: %.0f 分钟前加载 (跑一次该节点即刷新)" % (age / 60.0)
        self.publish("ss_cfg_names", SSConfigNames(
            ts=time.time(), names=names, loaded_at=r["loaded_at"],
            source=r["source"], note=note[:160]))
        return bool(names)

    def pub_engine(self):
        """🧮 流形引擎每周期输出 → zmax/ss_engine (常驻回路; 真调 ManifoldEngine.step 的结果)

        口径: 只转发 **新鲜** 帧 (帧龄 > STALE_ENGINE_S 就明说停发, 不拿旧帧冒充在跑);
        cycle 单调递增 ⇒ 订阅侧一看 cycle 就知道回路是不是真在按周期跑。
        """
        from ss_types import SSManifoldStep                               # noqa: PLC0415

        def _f(v, dv=-1.0):
            try:
                return float(v)
            except (TypeError, ValueError):
                return float(dv)

        def _i(v, dv=0):
            try:
                return int(v)
            except (TypeError, ValueError):
                return int(dv)

        def _vec(v, n=0):
            try:
                out = [float(x) for x in (v or [])]
            except TypeError:
                return []
            return out if (not n or len(out) == n) else []

        d, mt = read_engine()
        age = (time.time() - mt) if mt else -1.0
        if not d:
            return False
        if age > STALE_ENGINE_S:
            if time.time() - _EN_LOGGED.get("stale", 0.0) > 60:
                log("⏸ 流形引擎 tap 过期 %.1fs (>%.1fs) — 不把旧的当现在 (跑 tools/ss_engine_loop.py run)"
                    % (age, STALE_ENGINE_S))
                _EN_LOGGED["stale"] = time.time()
            return False
        p = _vec(d.get("p"))
        a = _vec(d.get("action"))
        self.publish("ss_engine", SSManifoldStep(
            ts=_f(d.get("ts"), time.time()), cycle=_i(d.get("cycle")), hz=_f(d.get("hz")),
            step_ms=_f(d.get("ms")), provider=str(d.get("provider") or ""),
            source=str(d.get("source") or "")[:160], traj_at=str(d.get("traj_at") or ""),
            traj_idx=_i(d.get("idx"), -1), traj_n=_i(d.get("traj_n")), replay=_i(bool(d.get("replay"))),
            project=str(d.get("project") or ""), task_id=str(d.get("task_id") or ""),
            task_name=str(d.get("task_name") or ""), scene=str(d.get("scene") or ""),
            M=_f(d.get("M")), inertia=_i(bool(d.get("inertia"))), calib=str(d.get("calib") or "")[:120],
            decode_src=str(d.get("decode_src") or "")[:120], p=p,
            # 不引 numpy (本守护只做转发): 纯 python 求模, 0 依赖
            p_norm=float(sum(x * x for x in p) ** 0.5) if p else 0.0, phi=_f(d.get("phi")),
            grad_norm=_f(d.get("grad_norm")), action=a,
            action_norm=float(sum(x * x for x in a) ** 0.5) if a else 0.0,
            confidence=_f(d.get("confidence")), anomaly=_f(d.get("anomaly")),
            residual=_f(d.get("residual")),
            momentum=_f(d.get("momentum"), -1.0) if d.get("momentum") is not None else -1.0,
            hom_enabled=_i(bool(d.get("hom_enabled"))), hom_mode=str(d.get("hom_mode") or ""),
            hom_vitality=_f(d.get("hom_vitality")), hom_gain=_f(d.get("hom_gain"), 1.0),
            hom_dominant=str(d.get("hom_dominant") or ""), hom_urgency=_f(d.get("hom_urgency")),
            hom_veto=_i(bool(d.get("hom_veto"))),
            t_encode_ms=_f(d.get("t_encode_ms")), t_project_ms=_f(d.get("t_project_ms")),
            t_grad_ms=_f(d.get("t_grad_ms")),
            note=("帧龄 %.2fs" % age) if age >= 0 else ""))
        return True

    def pub_stage(self):
        """🎛 动作调制器八阶段状态机 → zmax/ss_stage (老倪 2026-10-15: 「八个状态, 是哪个 topic 发出来的?」)

        口径: 只发**新鲜**快照 (帧龄 > STAGE_STALE_S 就明说停发 —— 3D 面板没在跑时这份快照就是旧的,
        不拿旧阶段当现在)。idx8 = 插拔链八阶段序号 0..7; v_cap = 本阶段限速 m/s (调制器限幅表)。
        """
        from ss_types import SSStage                                    # noqa: PLC0415

        def _f(v, dv=-1.0):
            try:
                return float(v)
            except (TypeError, ValueError):
                return float(dv)

        def _i(v, dv=-1):
            try:
                return int(v)
            except (TypeError, ValueError):
                return int(dv)

        d, mt = read_trace_stage()
        if not d:
            if time.time() - _ST_LOGGED["none"] > 60:
                log("⏸ 没有阶段源 zmax_data/ss_live/trace_live.json (3D 面板没跑) → ss_stage 不发")
                _ST_LOGGED["none"] = time.time()
            return False
        age = (time.time() - mt) if mt else -1.0
        if age > STAGE_STALE_S:
            if time.time() - _ST_LOGGED["stale"] > 60:
                log("⏸ 阶段快照过期 %.1fs (>%.1fs) — 不把旧阶段当现在 (3D 面板没在跑)" % (age, STAGE_STALE_S))
                _ST_LOGGED["stale"] = time.time()
            return False
        name = str(d.get("阶段") or "")
        # ⚠️ 阶段名有时带后缀 ("转移 · 接触") ⇒ 剥掉再发, 免得消费侧按名对表对不上
        name = name.split(" ·")[0].split("·")[0].strip()
        idx = _i(d.get("阶段序号"), -1)
        idx8 = _i(d.get("八阶段序号"), -1)
        self.publish("ss_stage", SSStage(
            ts=time.time(), idx=int(idx), idx8=int(idx8), name=name[:32],
            v_cap=_f(d.get("阶段限速_mps"), -1.0), done=1 if name == "完成" else 0,
            age_s=float(age), source="zmax_data/ss_live/trace_live.json (3D 面板快照)",
            note="真源 ActionModulator.STAGES (cognition.py:31) · 十三段 idx=%d · 插拔八段 idx8=%d"
                 % (idx, idx8)))
        return True

    # ══════════════════ ⚖ 原子技能物理量 (老倪 2026-10-15) ══════════════════
    def pub_skills(self):
        """⚖ 每个原子技能一条话题: zmax/skill_sk01 … zmax/skill_sk08

        「所有的原子技能, 例如接近、对位, 都要有 topic 输出, 且在实时监控信号分析窗口都有对应的信号;
          我要在信号分析窗口看到实际的物理模型, x y z v a 等距离、速度、角度等物理值; 要实际发出来。」

        每技能一条消息 = **实测值** + **物理模型包络**:
          实测  x/y/z 位置 mm · v 速度 mm/s · a 加速度 mm/s² · s 本段累计行程 mm · angle 姿态角 deg
                err 物理闸削出的偏差 mm/s · big 大偏差标志 · step 块内第几拍 · in_service 是否在职
          包络  v_cap 限速 m/s · a_max 加速度上限 m/s² · jerk_max · s_step 单拍位移上限 m · s_max 段行程上限
                m_kg 运动质量 · f_max 力上限  ⇒ 信号分析里"实测曲线 vs 物理上限"可以同图叠出来

        真源 (全链可追, 一个数都不在这里算):
          zmax_data/ss_live/skill_phys.json   ← 技能派发循环服务 tools/ss_skill_dispatch.py 每拍过物理闸写出
          src/lerobot/policies/left_right/state_space/physics_constraints.py  (InertiaLimiter, 五条约束)
          config/calib/zmax_skill_physics.json (标定上下限, tools/skill_physics_calib.py)
          zmax_data/ss_live/state_*.jsonl      (真机 tap 位姿; 停更 ⇒ x/y/z/angle 发 -1)
        未测 = -1 (不用 0 冒充); 不在职 ⇒ in_service=0 且实测值 -1, 包络照发。
        """
        from ss_types import SSSkillPhys                                 # noqa: PLC0415
        try:
            d = json.load(open(SKILL_PHYS, encoding="utf-8"))
        except Exception:                                                # noqa: BLE001
            return False
        mt = os.path.getmtime(SKILL_PHYS) if os.path.isfile(SKILL_PHYS) else None
        age_src = (time.time() - mt) if mt else -1.0
        # 位姿 (x/y/z/angle): **由技能派发循环服务读真机 tap 后写进 skill_phys.json**, 这里只转发 ——
        #   一个 tap 只允许一个读者(否则两处各读一份、各算一次新鲜度, 迟早出现"一条通道的位置是新的、
        #   另一条是旧的"这种自打脸)。帧龄超阈时那边已经写成 -1, 这里照发, 不拿旧位姿当现在。
        n_ok = 0
        for code, r in sorted((d.get("skills") or {}).items()):
            if not code.startswith("SK"):
                continue
            k = "skill_" + code.lower()
            if not allowed(k):
                continue
            ins = 1 if int(r.get("在职") or 0) else 0
            _pose_ok = float(r.get("x", -1.0)) != -1.0
            note = ("在职: 数值=派发循环服务该技能最新一拍(过物理闸后); 位置/角度=%s"
                    % ("真机 tap 当前位姿 (帧龄 %.2fs)" % float(r.get("pose_age_s", -1.0))
                       if _pose_ok else "位姿停更/无位姿 ⇒ -1")) if ins else \
                   "不在职: 该技能当前没有块认领 ⇒ 实测值 -1 (包络照发)"
            msg = SSSkillPhys(
                ts=time.time(), skill=code[:8], stage=str(r.get("stage") or "")[:16],
                in_service=ins, step=int(r.get("step") if r.get("step") is not None else -1),
                x=float(r.get("x", -1.0)), y=float(r.get("y", -1.0)), z=float(r.get("z", -1.0)),
                v=float(r.get("v_mms") if r.get("v_mms") is not None else -1.0),
                a=float(r.get("a_mms2") if r.get("a_mms2") is not None else -1.0),
                s=float(r.get("s_mm") if r.get("s_mm") is not None else -1.0),
                angle=float(r.get("angle", -1.0)),
                err=float(r.get("err_mms") if r.get("err_mms") is not None else -1.0),
                big=int(r.get("big") or 0),
                v_cap=float(r.get("v_cap", -1.0)), a_max=float(r.get("a_max", -1.0)),
                jerk_max=float(r.get("jerk_max", -1.0)), s_step=float(r.get("s_step", -1.0)),
                s_max=float(r.get("s_max", -1.0)), m_kg=float(r.get("m_kg", -1.0)),
                f_max=float(r.get("f_max", -1.0)), frame_age_s=float(age_src),
                source="zmax_data/ss_live/skill_phys.json (技能派发循环服务 60Hz 过物理闸写)",
                why=str(r.get("why") or "")[:48], note=note)
            if self.publish(k, msg):
                n_ok += 1
        return n_ok > 0


    def pub_diag(self):
        from ss_types import SSDiag                                  # noqa: PLC0415
        now = time.time()
        _, st_mt = read_state()
        _, pr_mt = read_proposal()
        h = read_infer()
        if now - self._svc_t > 10:
            self._svc = services_health()
            self._svc_t = now
        self.publish("ss_diag", SSDiag(
            ts=now, node="ss_daemon", kind="frame_age",
            frame_age_s=round(now - st_mt, 3) if st_mt else -1.0,
            hz=-1.0, dropped=self.errs, health=1.0 if (st_mt and now - st_mt < STALE_S) else 0.0,
            level="ok" if (st_mt and now - st_mt < STALE_S) else "warn",
            msg="state=%s proposal=%s" % (round(now - st_mt, 2) if st_mt else "无",
                                          round(now - pr_mt, 2) if pr_mt else "无")))
        self.publish("ss_diag", SSDiag(
            ts=now, node="ss-local-infer", kind="latency",
            latency_ms=float(h.get("last_ms")) if isinstance(h.get("last_ms"), (int, float)) else -1.0,
            count=int(h.get("infer_count") or -1), health=1.0 if h.get("online") else 0.0,
            level="ok" if h.get("online") else "error",
            msg="models=%s" % ",".join((h.get("models") or [])[:2])))
        okn = sum(1 for v in self._svc.values() if v == "active")
        self.publish("ss_diag", SSDiag(
            ts=now, node="services", kind="health", count=okn,
            health=round(okn / max(1, len(self._svc)), 3), level="ok" if okn == len(self._svc) else "warn",
            msg=json.dumps(self._svc, ensure_ascii=False)[:180]))
        # 🔒 2026-10-14: 节拍线程 (ss_cfg_names/ss_engine) 会在 publish() 里写 self.sent, 主 tick 在这里
        #    迭代同一个 dict ⇒ 实测「tick 异常: dictionary changed size during iteration」。取快照。
        for t, c in list(self.sent.items()):
            self.publish("ss_diag", SSDiag(ts=now, node="ss_daemon", kind="throughput",
                                           count=c, hz=round(c / max(1.0, now - self.t0), 3),
                                           queue=self.seq.get(t, 0) - c, level="ok", msg="topic=" + t))
        return True

    def pub_canvas(self):
        """ss_canvas ← 画布真源节点清单 (轮转发布: 每轮 5 个, 87 节点约 35s 扫完一遍)

        status/fps/counter 本机无真实计数源 → 一律 idle / -1.0 / -1 (诚实: 未测量不冒充 0)
        """
        from ss_types import SSCanvasNode                               # noqa: PLC0415
        nodes, src = read_canvas_nodes()
        if not nodes:
            return False
        n = len(nodes)
        start = self._canvas_i % n
        batch = [nodes[(start + k) % n] for k in range(min(5, n))]
        self._canvas_i = (start + len(batch)) % n
        for nd in batch:
            self.publish("ss_canvas", SSCanvasNode(
                ts=time.time(), node_id=nd["id"], name=nd["name"], layer=nd["layer"],
                status="idle", fps=-1.0, last_ms=-1.0, counter=-1,
                note="source=%s · 画布 %d 节点 · 本机无计数源(未测量=-1)" % (nd["file"], n)))
        return True

    def pub_macro(self):
        """ss_macro ← 五层记忆真源 (data/memory/memory_layers.json): 每层一条"""
        from ss_types import SSMacro                                    # noqa: PLC0415
        d, src = read_memory_layers()
        if not d:
            return False
        n = 0
        for lname, v in d.items():
            if lname in ("updated", "ts") or not isinstance(v, dict):
                continue
            items = v.get("items") or []
            links = []
            for it in items[:3]:
                if isinstance(it, dict):
                    links.extend([str(x) for x in (it.get("links") or [])][:1])
            self.publish("ss_macro", SSMacro(
                ts=time.time(), layer_name=str(lname),
                intent=str(v.get("intent") or v.get("desc") or "")[:120],
                plan=",".join(links)[:180], progress=-1.0,
                recalled=int(v.get("count", len(items))),
                note="source=%s updated=%s" % (os.path.basename(src), d.get("updated", ""))))
            n += 1
        return n > 0

    def pub_nodes(self):
        """ss_nodes ← 本守护自描述: 已发布话题 + **实测**频率 + 在役 DDS 服务"""
        from ss_types import SSNodes                                    # noqa: PLC0415
        now = time.time()
        el = max(1.0, now - self.t0)
        svc = self.nodes_svc_cache()
        topics = sorted(list(self.sent.keys()))
        self.publish("ss_nodes", SSNodes(
            ts=now,
            nodes=["ss_daemon(本守护)"] + ["%s:%s" % (k, v) for k, v in svc.items()],
            topics=topics,
            publish_hz=[round(self.sent.get(t, 0) / el, 3) for t in topics]))
        return True

    def nodes_svc_cache(self):
        now = time.time()
        if now - getattr(self, "_svc_nodes_t", 0) > 10:
            self._svc_nodes = read_dds_services()
            self._svc_nodes_t = now
        return getattr(self, "_svc_nodes", {})

    def pub_test(self):
        from ss_types import SSTest                                  # noqa: PLC0415
        r = read_test_result()
        if not r:
            return False
        n = 0
        for key, val in (("passed", r["passed"]), ("failed", r["failed"]), ("total", r["total"])):
            if isinstance(val, int):
                self.publish("ss_test", SSTest(
                    ts=time.time(), suite=r["suite"], case=key,
                    passed=1 if (key == "passed" and val > 0) else (0 if key == "failed" and val > 0 else -1),
                    total=r["total"] if isinstance(r["total"], int) else -1,
                    failed=r["failed"] if isinstance(r["failed"], int) else -1,
                    detail=r["detail"][:200]))
                n += 1
        if n == 0:
            self.publish("ss_test", SSTest(ts=time.time(), suite=r["suite"], case="artifact",
                                           passed=-1, total=-1, detail=r["detail"][:200]))
            n = 1
        return n > 0

    def tick(self, fast=True):
        m = mode()
        if m != self._mode:
            log("🔀 遥测模式 → %s (允许 %d 个话题)" % (m, len(MODE_TOPICS.get(m, []))))
            self._mode = m
        if m == "prod":
            if self.node is not None:
                self.drop_node()
            return
        if not self.ensure_node():
            return
        # ⚠️ 每个允许话题**每轮都发**: DDS 发现是异步的, 只发一次会丢给"还没发现"的读者
        #    (实测: diag 首发命中, 低频的 infer/calib/test 首发丢失 → 取证假失败)
        #    文件类源 (calib/test) 用 mtime 缓存解析结果, 保持每轮发但不重复读盘。
        if allowed("ss_state"):
            self.pub_state()
        if allowed("ss_action"):
            self.pub_action()
        if any(allowed(k) for k in SKILL_TOPICS):     # ⚖ 原子技能物理量: 每技能一条话题 (老倪 2026-10-15)
            self.pub_skills()
        if allowed("ss_diag"):
            self.pub_diag()
        if allowed("ss_infer"):
            self.pub_infer()
        if allowed("ss_calib"):
            self.pub_calib()
        if allowed("ss_test"):
            self.pub_test()
        if allowed("ss_canvas"):
            self.pub_canvas()
        if allowed("ss_macro"):
            self.pub_macro()
        if allowed("ss_nodes"):
            self.pub_nodes()
        if allowed("ss_plan"):
            self.pub_plan()
        if allowed("ss_energy"):
            self.pub_energy()
        if allowed("ss_torque"):
            self.pub_torque()
        # 🧮 主参数节点已加载的配置名称 (老倪 2026-10-14 规格「字符串就可以, 周期5秒」)：
        #    ⚠ 实测: 主 tick 一次要 17~26s (远端读取 + 服务健康检查都在里面), 挂在 tick 里做 5s 门控
        #    会退化 ≈20s (实测相邻两条 21.0s) ⇒ 改由 `_cfg_thread()` 专用节拍线程发, 这里不再发。

    def _cfg_thread(self, period=5.0):
        """🧮 主参数节点已加载配置名称的**专用 5s 节拍线程** (老倪 2026-10-14 规格: 周期 5 秒)

        为什么不挂在主 tick 上: 实测主循环一次 tick 17~26s (read_state/read_calibs/services_health
        都在 tick 里, 远端读慢), 5s 门控会退化成 ~20s。本线程只做一件事: 每 5s 把
        **节点记录里的配置名称**发一条 zmax/ss_cfg_names — 只读真源, 不触发任何动作。
        """
        for _ in range(100):                      # 同上: 等 DDS 参与者就绪, 避免首轮半成品模块
            if self.node is not None or self._stop.is_set():
                break
            self._stop.wait(0.1)
        while not self._stop.is_set():
            t0 = time.time()
            try:
                if allowed("ss_cfg_names"):
                    self.pub_cfg_names()
                if allowed("ss_meta_task"):          # 🧾 元任务: 与配置名同一节拍/同一出口 (主参数节点)
                    self.pub_meta_task()
                if allowed("ss_meta_pred"):          # 🧾 元任务预测值 (输入=驱动扭矩) → 信号分析可见
                    self.pub_meta_pred()
                if allowed("ss_action_chunk"):       # 🧩 动作块 (块/前馈序列/加权调制后序列) → 信号分析可见
                    self.pub_action_chunk()
            except Exception as e:                                       # noqa: BLE001
                log("⚠️ ss_cfg_names / ss_meta_task 发布失败: %s: %s" % (type(e).__name__, str(e)[:100]))
            self._stop.wait(max(0.05, period - (time.time() - t0)))

    def _engine_thread(self, period=0.2):
        """🧮 流形引擎常驻回路的**专用节拍线程** (主 tick 实测 17~26s, 挂主 tick 会把 10Hz 压成 0.05Hz)。

        只做一件事: 读 tap 最后一帧 → 发 zmax/ss_engine。只读真源, 不触发任何动作。
        """
        # ⏳ 首轮前等 DDS 参与者建好: 实测并发的首个 tick 会撞上 `import ss_types` / `import cyclonedds`
        #    的半成品模块 (ModuleNotFoundError: ss_types / KeyError: 'cyclonedds') ⇒ 白丢一帧 + 刷告警。
        for _ in range(100):
            if self.node is not None or self._stop.is_set():
                break
            self._stop.wait(0.1)
        while not self._stop.is_set():
            t0 = time.time()
            try:
                if allowed("ss_engine"):
                    self.pub_engine()
            except Exception as e:                                       # noqa: BLE001
                log("⚠️ ss_engine 发布失败: %s: %s" % (type(e).__name__, str(e)[:100]))
            try:
                # 🎛 八阶段状态机 (老倪 2026-10-15: 「八个状态, 是哪个 topic 发出来的?」)
                if allowed("ss_stage"):
                    self.pub_stage()
            except Exception as e:                                       # noqa: BLE001
                log("⚠️ ss_stage 发布失败: %s: %s" % (type(e).__name__, str(e)[:100]))
            self._stop.wait(max(0.02, period - (time.time() - t0)))

    def run(self, seconds=0.0, once=False):
        t0 = time.time()
        n = 0
        if once:
            # 单轮取证: 直接把这一条也发掉 (线程不启, 免得等 5s)
            try:
                if allowed("ss_cfg_names"):
                    self.pub_cfg_names()
                if allowed("ss_meta_task"):
                    self.pub_meta_task()
                if allowed("ss_meta_pred"):
                    self.pub_meta_pred()
            except Exception as e:                                       # noqa: BLE001
                log("⚠️ ss_cfg_names / ss_meta_task 一次性发布失败: %s" % type(e).__name__)
        else:
            th = threading.Thread(target=self._cfg_thread, name="ss_cfg_names", daemon=True)
            th.start()
            log("🧮 配置名称 5s 节拍线程已启动 (话题 zmax/ss_cfg_names)")
            th2 = threading.Thread(target=self._engine_thread, name="ss_engine", daemon=True)
            th2.start()
            log("🧮 流形引擎常驻回路 5Hz 转发线程已启动 (话题 zmax/ss_engine ← tap %s)" % ENGINE_TAP_DIR)
        while True:
            try:
                fast = (n % 5 == 0)
                self.tick(fast=fast)
            except Exception as e:                                    # noqa: BLE001
                self.errs += 1
                log("⚠️ tick 异常: %s" % str(e)[:140])
            n += 1
            if once:
                return
            if seconds and time.time() - t0 >= seconds:
                log("⏹ 到时长退出 (sent=%s)" % json.dumps(self.sent, ensure_ascii=False))
                return
            time.sleep(float(os.environ.get("ZMAX_SS_TICK_S", "0.1")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="发一轮后退出")
    ap.add_argument("--seconds", type=float, default=0.0, help="跑多久 (0=常驻)")
    ap.add_argument("--status", action="store_true", help="只看模式与源可用性")
    a = ap.parse_args()
    m = mode()
    if a.status:
        st, smt = read_state()
        pr, pmt = read_proposal()
        h = read_infer()
        print(json.dumps({"mode": m, "allowed_topics": MODE_TOPICS.get(m, []),
                          "state_src": {"file": _newest(os.path.join(SS_REMOTE, "state_*.jsonl")),
                                        "keys": list(st) if st else None},
                          "action_src": {"file": _newest(os.path.join(SS_REMOTE, "proposal_*.jsonl")),
                                         "keys": list(pr) if pr else None},
                          "infer": {"online": h.get("online"), "infer_count": h.get("infer_count")},
                          "calib_files": [k for k, _ in read_calibs()],
                          "test_src": (read_test_result() or {}).get("path"),
                          "canvas_src": {"file": read_canvas_nodes()[1],
                                         "nodes": len(read_canvas_nodes()[0])},
                          "macro_src": {"file": read_memory_layers()[1],
                                        "layers": [k for k in read_memory_layers()[0] if k != "updated"]},
                          "energy_src": {"file": read_energy()[1],
                                        "e_total_cj": (read_energy()[0] or {}).get("e_total_cj"),
                                        "n_levels": len((read_energy()[0] or {}).get("shells") or [])},
                          "dds_services": read_dds_services()},
                         ensure_ascii=False, indent=1))
        return 0
    d = SSDaemon()
    log("📡 全局数据空间发布守护启动 (模式=%s · 允许=%d 话题 · prod 时不 import cyclonedds)"
        % (m, len(MODE_TOPICS.get(m, []))))
    d.run(seconds=a.seconds, once=a.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
