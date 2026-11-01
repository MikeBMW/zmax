# -*- coding: utf-8 -*-
"""执行契约 (Execution Contract) — 真机动作的**唯一口径**, 归状态空间工程管。

老倪 2026-11-01: 「l2_daemon 不能脱离状态空间工程, 是不是放在机器人执行器节点比较合理?」
  ⇒ 结论: **契约归节点/工程, 进程仍旧独立 (systemd)**。为什么不把常驻进程塞进节点函数:
     · 画布节点是每拍调用的纯函数 (loop 220~310ms/拍, 有预算), 而 daemon 是 10Hz 常驻 + FIFO + 断线重连;
     · 节点被禁用/断点/未连线 ⇒ 动作无人发, 且**没有日志、没有回执** (最危险的静默失效);
     · 授权闸必须 fail-closed 且不依赖 GUI 存活 (画布崩了臂也必须立刻停手)。
  ⇒ 落法: 段表 schema / 闸序 / 回执字段 定义在这里 (进 git, 随工程迁移);
          「机器人执行器」节点 import 本模块 = 执行入口与回执口径的唯一声明;
          真正下发仍由 src/lerobot/engineering/exec/daemon.py 这个常驻进程承担。

迁移 550C: 代码 (本文件 + daemon.py) 随工程走; 运行态走数据盘
  ZMAX_REPO (仓库根) / ZMAX_DATA (zmax_data) / ZMAX_L2_FIFO (命令管道)
"""
from __future__ import annotations

import json
import os
import time

# ── ① 段表 schema (一行 = 一段; 缺字段等于没下这条) ───────────────────────────
SEG_REQUIRED = ("ros", "speed_mm_s")
SEG_OPTIONAL = ("axis", "d_mm", "abs_mm", "target", "note", "skill", "stage")
SEG_SCHEMA = {
    "ros": "动作类型: line_rel | line_abs | insert | pull | gripper",
    "axis": "line_rel 的轴: x_pos/y_pos/z_pos/x_neg/y_neg/z_neg",
    "d_mm": "相对位移 [dx,dy,dz] mm (line_rel 用)",
    "abs_mm": "段终点绝对坐标 [x,y,z] mm (防单段失败后整体漂移, 强烈建议带)",
    "speed_mm_s": "真实速度 mm/s (页面档位 5/10/50 透传)",
    "note": "人看的备注, 同时进日志",
}

# ── ② 闸序 (顺序不可换: 越靠前越必须 fail-closed) ────────────────────────────
GATE_ORDER = [
    ("auth", "真动授权 (zmax_data/ctl_auth.json 当下有效, 撤权即失效)"),
    ("stage", "阶段判定 (段属于哪个原子技能阶段)"),
    ("physics", "原子技能约束复核 (min(V_CAP, S_STEP/DT_S), 超限降速)"),
    ("vl", "视觉安全闸 (VL 快层反射, fail-closed)"),
    ("dispatch", "下发 (执行腿 bridge → Orin SDK 桥)"),
    ("arrive", "到位判据 (看真位姿残差, 不是'发了就算')"),
]

# ── ③ 回执字段 (动作执行器节点报给你的就是这些) ──────────────────────────────
RECEIPT_FIELDS = {
    "phase": "idle/moving/arrived/blocked/done",
    "seg": "当前第几段", "n_seg": "共几段",
    "skill": "当前技能", "target": "目标 [x,y,z] mm", "pos": "实际 [x,y,z] mm",
    "residual_mm": "离目标还差多少 mm (实测)",
    "speed_mm_s": "本段速度", "transport": "ros/sdk/bridge",
    "blocked_by": "被谁拦 (授权/位姿陈旧/安全闸/VL)",
    "auth_epoch": "被哪一次授权放行", "age_s": "状态多旧",
    "last_events": "最近三条原始事件 (含拒绝理由)",
}


def _find_repo():
    """仓库根: ZMAX_REPO > 向上找 .git (不能靠"上四级", 本文件在 src/lerobot/engineering/exec/)。"""
    e = os.environ.get("ZMAX_REPO") or ""
    if e and os.path.isdir(e):
        return os.path.abspath(e)
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        n = os.path.dirname(d)
        if n == d:
            break
        d = n
    return os.path.dirname(os.path.abspath(__file__))


def paths():
    repo = _find_repo()
    data = os.environ.get("ZMAX_DATA") or os.path.join(repo, "zmax_data")
    return {"repo": repo, "data": data,
            "fifo": os.environ.get("ZMAX_L2_FIFO") or os.path.join(data, "l2_cmd.fifo"),
            "auth": os.path.join(data, "ctl_auth.json"),
            "exec_state": os.path.join(data, "ss_live", "exec_state.json"),
            "exec_events": os.path.join(data, "ss_live", "exec_events.jsonl"),
            "daemon": os.path.join(repo, "src", "lerobot", "engineering", "exec", "daemon.py")}


def auth_ok():
    """真动授权口径 — 与 tools/traj_exec.py、daemon._auth_guard 同一份数据。"""
    p = paths()["auth"]
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:                                                   # noqa: BLE001
        return False, 0, "授权文件读不到(%s)" % str(e)[:60]
    if float(d.get("revoked_at") or 0) > 0:
        return False, int(d.get("epoch") or 0), "授权已被撤销"
    until = float(d.get("until") or 0)
    if until <= time.time():
        return False, int(d.get("epoch") or 0), "授权窗已过期 (先在 8793 页面做现场授权)"
    return True, int(d.get("epoch") or 0), "剩余 %.0fs" % (until - time.time())


def validate_seg(seg):
    """段表校验 ⇒ (ok, why)。缺 speed/ros 直接判废, 不许"看起来能发"。"""
    if not isinstance(seg, dict):
        return False, "段不是 dict"
    miss = [k for k in SEG_REQUIRED if seg.get(k) in (None, "", [])]
    if miss:
        return False, "缺字段 %s" % ",".join(miss)
    ros = str(seg.get("ros"))
    if ros == "line_rel" and not seg.get("abs_mm"):
        return True, "无 abs_mm (相对走, 单段失败会漂移)"
    return True, "ok"


def receipt():
    """读回执 (只读) — 动作执行器节点的口径就是这里。"""
    p = paths()
    out = {"node": "exec_contract", "ok": False}
    try:
        st = json.load(open(p["exec_state"], encoding="utf-8"))
        age = time.time() - float(st.get("t_pub") or st.get("t") or 0.0)
        out.update({k: st.get(k) for k in RECEIPT_FIELDS if k not in ("last_events", "age_s")})
        out["age_s"] = round(age, 2)
        out["ok"] = True
    except Exception as e:                                                   # noqa: BLE001
        out["state_error"] = "%s: %s" % (type(e).__name__, str(e)[:80])
    try:
        with open(p["exec_events"], "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            ev = []
            for ln in f.read().decode("utf-8", "ignore").splitlines()[-3:]:
                try:
                    ev.append(json.loads(ln))
                except Exception:                                            # noqa: BLE001
                    pass
            out["last_events"] = ev
    except Exception:                                                        # noqa: BLE001
        pass
    return out


def dispatch(segs, speed_mm_s=None, dry=False, stage=None):
    """把段表交给执行器 (写命令管道)。**唯一入口**, 授权不过就 fail-closed 一条不发。

    注意: 本函数不会在画布每拍自动调用 —— 只给显式入口 (8793 按钮 / 脚本) 用;
          画布节点只读回执, 避免"节点被禁用 ⇒ 动作静默消失"。
    """
    p = paths()
    ok, epoch, why = auth_ok()
    if not ok:
        return {"ok": False, "sent": 0, "blocked_by": "授权: " + why, "epoch": epoch}
    bad = []
    for i, s in enumerate(segs or []):
        v, w = validate_seg(s)
        if not v:
            bad.append({"i": i + 1, "why": w})
    if bad:
        return {"ok": False, "sent": 0, "blocked_by": "段表不合规", "bad": bad[:5]}
    if dry:
        return {"ok": True, "sent": 0, "dry": True, "n": len(segs), "epoch": epoch}
    # 新一轮下发 ⇒ 清执行器的变化率账 (否则第一拍拿上一次运行末拍做差分, 必误报)
    try:
        import importlib as _il
        _ex = _il.import_module("lerobot.policies.left_right.state_space.execution")
        _ex.RobotExecutor.reset("contract.dispatch 新下发")
    except Exception:                                                    # noqa: BLE001
        pass
    sent = 0
    try:
        with open(p["fifo"], "w", encoding="utf-8") as f:
            for s in segs:
                cmd = {k: s[k] for k in SEG_REQUIRED + SEG_OPTIONAL if k in s}
                if speed_mm_s:
                    cmd["speed_mm_s"] = float(speed_mm_s)
                if stage:
                    cmd["stage"] = stage
                cmd.setdefault("note", "exec_contract #%d" % (sent + 1))
                f.write(json.dumps(cmd, ensure_ascii=False) + "\n")
                f.flush()
                sent += 1
                time.sleep(0.12)                    # 与 traj_exec 同节奏, 别一次灌满
    except Exception as e:                                                   # noqa: BLE001
        return {"ok": False, "sent": sent, "blocked_by": "%s: %s" % (type(e).__name__, str(e)[:60])}
    return {"ok": True, "sent": sent, "n": len(segs), "epoch": epoch, "fifo": p["fifo"]}
