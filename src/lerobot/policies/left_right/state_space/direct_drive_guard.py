"""🚦 闭环直驱护栏 — 阶段一(影子模式): 只记录、零接管

老倪 2026-11-14 原话:
    「闭环直驱 改造, 但是要一步一步来, 首先要确保, 当前的215点能稳定运行,
      如果u发错了, 就还是按照215点执行」

铁律(顺序不能反):
    ① ZMAX_DD_MODE 未设/off  ⇒ **完全不介入**, 不写文件、不改 u、不改 tag
    ② shadow                 ⇒ 每拍把 u 与"实测运动"比对, 只写 dd_guard.json
                                 ★绝不修改 u, 绝不接管, 215 点照常走
    ③ armed                  ⇒ 连续 N 拍 verdict=allow 才把 allow=True 报给上层
                                 (本阶段只翻标志; 真正的速度下发接口另行落地,
                                  因为 daemon 的 /move_pose 是位姿不是速度)
    ④ 任何 NaN/超限/方向反了 ⇒ 立即 deny + ok_ticks 清零, 上层必须回退 215 点

比对用什么做参考: **实测速度**(tcp_out/latest.json 相邻两帧差分), 不用 FK 逆解 ——
真值就在手边, 而且闭环要求本来就是"指令与实际运动一致"。
"""
from __future__ import annotations

import json
import math
import os
import threading
import time

# ── 阈值(全部可用 env 覆盖, 便于现场调) ───────────────────────────────
V_CAP_MAX = float(os.environ.get("ZMAX_DD_VMAX", "0.35"))     # m/s, 单轴指令幅值上限
MAX_ANGLE_DEG = float(os.environ.get("ZMAX_DD_ANGLE", "25"))  # 指令与实测方向最大夹角
RATIO_MIN = float(os.environ.get("ZMAX_DD_RMIN", "0.2"))      # 指令/实测 速度比下限
RATIO_MAX = float(os.environ.get("ZMAX_DD_RMAX", "5.0"))      # 上限
OK_TICKS_NEEDED = int(os.environ.get("ZMAX_DD_OK_TICKS", "30"))  # 连续多少拍才 allow
VMIN_MEAS = 0.005            # m/s, 实测速度低于此视为静止 ⇒ 不判方向
UMIN = 0.01                  # m/s, 指令幅值低于此视为停车指令
STALE_S = 1.0                # latest.json 超过这么久 ⇒ 参考不可信

def _repo_root() -> str:
    """从本文件往上找含 zmax_data/ 的目录(别数 dirname 层数, 数错过一次)。"""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        # 必须是仓库根: 同时有 src/lerobot 和 zmax_data (src/zmax_data 是历史误建的诱饵目录)
        if (os.path.isdir(os.path.join(d, "zmax_data"))
                and os.path.isdir(os.path.join(d, "src", "lerobot"))):
            return d
        d = os.path.dirname(d)
    return "/home/ubuntu/zmax"


_ROOT = _repo_root()
_LATEST = os.path.join(_ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
_OUT = os.path.join(_ROOT, "zmax_data", "ss_live", "dd_guard.json")


def _mode() -> str:
    m = (os.environ.get("ZMAX_DD_MODE") or "off").strip().lower()
    return m if m in ("off", "shadow", "armed") else "off"


def _load_pose():
    try:
        if time.time() - os.path.getmtime(_LATEST) > STALE_S:
            return None, None
        d = json.load(open(_LATEST, encoding="utf-8"))
        p = (float(d.get("x", 0.0)), float(d.get("y", 0.0)), float(d.get("z", 0.0)))
        if p == (0.0, 0.0, 0.0):
            return None, None                      # 全 0 = 陈旧
        return p, os.path.getmtime(_LATEST)
    except Exception:                              # noqa: BLE001
        return None, None


class DirectDriveGuard:
    def __init__(self):
        self.lock = threading.Lock()
        self.prev_p = None
        self.prev_t = 0.0
        self.ok_ticks = 0
        self.n_check = 0
        self.n_allow = 0
        self.n_deny = 0
        self.deny_why = {}
        self.last_angle = None
        self.last_ratio = None
        self._last_write = 0.0

    # ── 核心: 每拍一次 ────────────────────────────────────────────
    def check(self, u, stage=None, note=None) -> dict:
        m = _mode()
        if m == "off":
            return {"mode": "off", "allow": False}

        u = [float(x) for x in (u if hasattr(u, "__len__") else [u])]
        u3 = u[:3]
        un = float(math.sqrt(sum(x * x for x in u3)))

        why = []
        # ① 指令合法性
        if any(not math.isfinite(x) for x in u):
            why.append("指令含 NaN/Inf")
        if un > V_CAP_MAX * 1.0001:
            why.append("幅值 %.3f > 上限 %.2f m/s" % (un, V_CAP_MAX))
        if max((abs(x) for x in u3), default=0.0) > V_CAP_MAX:
            why.append("单轴超上限 %.2f m/s" % V_CAP_MAX)

        # ② 与实测速度比对(只在臂真的在动时判方向)
        p, t = _load_pose()
        v_meas = None
        angle = None
        ratio = None
        if p is not None and self.prev_p is not None and t and self.prev_t:
            dt = t - self.prev_t
            if dt > 1e-4:
                v = [(p[i] - self.prev_p[i]) / dt for i in range(3)]
                vn = float(math.sqrt(sum(x * x for x in v)))
                v_meas = vn
                if vn >= VMIN_MEAS and un >= UMIN:
                    cos = sum(u3[i] * v[i] for i in range(3)) / (un * vn)
                    angle = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
                    ratio = un / vn
                    if angle > MAX_ANGLE_DEG:
                        why.append("方向偏 %.0f° > %.0f°" % (angle, MAX_ANGLE_DEG))
                    if not (RATIO_MIN <= ratio <= RATIO_MAX):
                        why.append("幅值比 %.2f 越界[%.1f,%.1f]"
                                   % (ratio, RATIO_MIN, RATIO_MAX))
        if p is not None:
            self.prev_p, self.prev_t = p, t

        ok = not why
        with self.lock:
            self.n_check += 1
            if ok:
                self.ok_ticks += 1
                self.n_allow += 1
            else:
                self.ok_ticks = 0
                self.n_deny += 1
                for w in why:
                    k = w.split(" ")[0]
                    self.deny_why[k] = self.deny_why.get(k, 0) + 1
            self.last_angle = angle
            self.last_ratio = ratio
            allow = (m == "armed" and not why and self.ok_ticks >= OK_TICKS_NEEDED)
            snap = {
                "mode": m, "allow": allow, "ok_ticks": self.ok_ticks,
                "need": OK_TICKS_NEEDED, "stage": stage, "u": [round(x, 6) for x in u],
                "u_norm": round(un, 6),
                "v_meas_mm_s": (None if v_meas is None else round(v_meas * 1000, 2)),
                "angle_deg": (None if angle is None else round(angle, 1)),
                "ratio": (None if ratio is None else round(ratio, 3)),
                "why": why, "note": str(note or "")[:80],
                "score": round(self.ok_ticks / float(max(1, OK_TICKS_NEEDED)), 3),
                "t": time.time(),
            }
            # 统计块(每 0.5s 落盘一次, 不拖慢 10Hz 主循环)
            if time.time() - self._last_write >= 0.5:
                self._last_write = time.time()
                snap["stat"] = {
                    "n_check": self.n_check, "n_ok": self.n_allow, "n_deny": self.n_deny,
                    "deny_why": dict(self.deny_why),
                    "allow_ratio": round(self.n_allow / max(1, self.n_check), 3),
                }
                try:
                    tmp = _OUT + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(snap, f, ensure_ascii=False)
                    os.replace(tmp, _OUT)
                except Exception:               # noqa: BLE001
                    pass
            self.last_snap = snap
        return snap


_G = DirectDriveGuard()


def check(u, stage=None, note=None) -> dict:
    """给 cognition.decide 用的入口: 永不抛异常(护栏自己不许把主链搞挂)。"""
    try:
        return _G.check(u, stage=stage, note=note)
    except Exception:                                # noqa: BLE001
        return {"mode": "off", "allow": False}


def last() -> dict:
    """最近一拍的护栏结论(ssact 用它决定 action.src)。"""
    try:
        return dict(getattr(_G, "last_snap", None) or {})
    except Exception:                                # noqa: BLE001
        return {}


def stats() -> dict:
    try:
        return {"n_check": _G.n_check, "n_ok": _G.n_allow, "n_deny": _G.n_deny,
                "ok_ticks": _G.ok_ticks, "deny_why": dict(_G.deny_why)}
    except Exception:                                # noqa: BLE001
        return {}
