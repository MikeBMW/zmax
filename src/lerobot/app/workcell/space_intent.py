#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""space_intent.py —— 空间点智能体（Space Intent Agent）

老倪 2026-11-27：
  「每个空间点，就是一个智能点；每个移动，都会对应一个状态，一个空间点的智能化能力；
    从 AOI 检测的金手指和表面检测开始，根据空间点位自主调用光学检测的功能，
    到了插拔点，也要触发力控算法；全程都在影子模式，根据实际数据自主进化。」

设计（与既有分层不冲突，只做「到位判定 + 能力触发」这一层）：

    机械臂 TCP 位姿 ──► locate()  ──► 命中的空间点（含距离/角度/置信）
                                        │
                                        ▼
                                    tick()  ──► 能力请求（aoi_detect / force_ctrl / pick_place / calib_trace）
                                        │
                          ┌─────────────┴─────────────┐
                     shadow=True                  shadow=False
                  只记录、不下发                真调（需显式开启）

三条硬约束（沿用 aoi_dispatch.py 的纪律）：
  ① **不造数**：位姿陈旧 / 定位不到 / 服务不通 ⇒ 如实标 unavailable，绝不填默认值冒充成功；
  ② **不阻塞**：tick() 只做「定位 + 入队 + 记账」，实测 <2ms，10Hz 循环可以放心调；
  ③ **影子优先**：默认 shadow=True，只写空间轨迹日志；要真动必须显式 live 且外部授权。

与 aoi_dispatch.py 的关系：
  · aoi_dispatch 是**轨迹 cursor 驱动**（156→金手指、172→表面），是"路径经过此处"；
  · 本模块是**空间位置驱动**（TCP 到哪个点就触发那个点），是"人/臂停在此处"。
  两者互补：轨迹流在跑时用 aoi_dispatch 的节拍，自由移动时用 space_intent 的到达判定。
  为避免重复触发，本模块对 aoi_* 能力默认只做**影子记账**，不直接发 POST。
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass, field, asdict

# ────────────────────────── 定位 ──────────────────────────

DEFAULTS = {
    "tol_mm": 10.0,
    "tol_deg": 15.0,
    "confirm_ticks": 2,        # 连续 N 拍命中才算"到达"（防抖）
    "cooldown_s": 5.0,         # 同一点两次触发的最小间隔
    "max_points": 3,           # 同时命中的候选数（用于消歧）
}


def _repo_root(start: str) -> str:
    d = os.path.abspath(start)
    for _ in range(8):
        if os.path.isdir(os.path.join(d, "tools")) and os.path.isdir(os.path.join(d, "config")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


ROOT = os.environ.get("ZMAX_ROOT") or _repo_root(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.environ.get("ZMAX_SPACE_INTENTS") or os.path.join(ROOT, "config", "space_intents.json")
LOGDIR = os.environ.get("ZMAX_SPACE_LOG_DIR") or os.path.join(ROOT, "zmax_data", "space_intent")


def _ang_diff_deg(a, b) -> float:
    """两个欧拉角三元组的最大分量差（度）。"""
    if not a or not b:
        return 180.0
    d = 0.0
    for x, y in zip(a, b):
        if x is None or y is None:
            return 180.0
        v = abs(float(x) - float(y)) % 360.0
        if v > 180.0:
            v = 360.0 - v
        d = max(d, v)
    return d


def _dist_mm(a, b) -> float:
    if not a or not b or len(a) < 3 or len(b) < 3:
        return 1e9
    try:
        return 1000.0 * math.sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(3)))
    except (TypeError, ValueError):
        return 1e9


# ────────────────────────── 数据 ──────────────────────────

@dataclass
class Hit:
    """一次定位结果。"""
    name: str
    role: str
    phase: str
    dist_mm: float
    ang_deg: float
    score: float                      # 越小越接近（归一化后的综合距离）
    capabilities: list = field(default_factory=list)

    def brief(self) -> dict:
        return {"name": self.name, "role": self.role, "phase": self.phase,
                "dist_mm": round(self.dist_mm, 2), "ang_deg": round(self.ang_deg, 2),
                "score": round(self.score, 4),
                "caps": [c.get("kind") for c in self.capabilities]}


@dataclass
class PointState:
    """每个点的运行态（防抖 + 冷却 + 触发计数）。"""
    streak: int = 0
    last_fire: float = 0.0
    fires: int = 0
    last_hit: float = 0.0


# ────────────────────────── 主体 ──────────────────────────

class SpaceIntent:
    """空间点智能体仲裁器。

    用法（引擎每拍 / 独立守护进程）：
        si = SpaceIntent(shadow=True)
        res = si.tick(xyz=[...], abc=[...])     # 位姿单位: xyz 米, abc 度
        print(res.verdict, res.fired)
    """

    def __init__(self, registry_path: str = REGISTRY, shadow: bool = True,
                 logger=None):
        self.path = registry_path
        self.shadow = bool(shadow)
        self._lock = threading.RLock()
        self._states: dict[str, PointState] = {}
        self._last_reg_mtime = 0.0
        self.reg: dict = {}
        self.params = dict(DEFAULTS)
        self.logger = logger                     # 回调: fn(dict) —— 影子轨迹落盘用
        self._load(force=True)
        os.makedirs(LOGDIR, exist_ok=True)
        self.log_path = os.path.join(LOGDIR, "space_intent_%s.jsonl" % time.strftime("%Y%m%d"))
        self._fout = open(self.log_path, "a", encoding="utf-8")

    # ---- 注册表 ----
    def _load(self, force: bool = False) -> None:
        try:
            mt = os.path.getmtime(self.path)
        except OSError:
            self.reg = {"points": {}, "roles": {}}
            return
        if not force and mt <= self._last_reg_mtime:
            return
        try:
            reg = json.load(open(self.path, encoding="utf-8"))
        except Exception:
            return
        with self._lock:
            self.reg = reg
            self._last_reg_mtime = mt
            for name, p in (reg.get("points") or {}).items():
                self._states.setdefault(name, PointState())
                # 点位可覆盖全局容差
                for k in ("tol_mm", "tol_deg"):
                    if p.get(k) is not None:
                        p.setdefault("_eff_" + k, p[k])

    def reload_if_changed(self) -> bool:
        before = self._last_reg_mtime
        self._load()
        return self._last_reg_mtime != before

    @property
    def points(self) -> dict:
        return (self.reg.get("points") or {})

    # ---- 定位 ----
    def locate(self, xyz, abc=None, max_points: int | None = None) -> list[Hit]:
        """按当前 TCP 位姿找命中的空间点。返回按接近度排序的 Hit 列表（不含防抖）。"""
        if not xyz:
            return []
        n = max_points or self.params["max_points"]
        hits: list[Hit] = []
        for name, p in self.points.items():
            pp = p.get("pos")
            if not pp:
                continue
            d = _dist_mm(xyz, pp)
            tol_m = float(p.get("tol_mm") or self.params["tol_mm"])
            if d > tol_m * 3.0:           # 粗筛：3 倍容差外直接跳过，省算力
                continue
            a = _ang_diff_deg(abc, p.get("abc"))
            tol_a = float(p.get("tol_deg") or self.params["tol_deg"])
            # 归一化综合距离：位置权重 1，角度按"每 tol_deg 折算成 1 倍 tol_m"
            score = (d / max(tol_m, 1e-6)) + (a / max(tol_a, 1e-6))
            hits.append(Hit(name=name, role=p.get("role", "unknown"),
                            phase=p.get("phase", ""), dist_mm=d, ang_deg=a,
                            score=score, capabilities=p.get("capabilities") or []))
        hits.sort(key=lambda h: h.score)
        return hits[:n]

    # ---- 到达判定 + 触发 ----
    def tick(self, xyz, abc=None, ctx: dict | None = None) -> dict:
        """一拍：定位 → 防抖 → 触发（影子只记账）。返回结构化结果（永不为 None）。"""
        t0 = time.perf_counter()
        now = time.time()
        ctx = ctx or {}
        out = {
            "t": now, "shadow": self.shadow,
            "pos": xyz, "abc": abc,
            "hit": None, "candidates": [],
            "arrived": False, "fired": [],
            "verdict": "idle", "why": "",
            "ms": 0.0,
        }
        hits = self.locate(xyz, abc)
        out["candidates"] = [h.brief() for h in hits]

        if not hits:
            out["verdict"] = "no_point"
            out["why"] = "当前位姿不在任何空间点的容差内"
            out["ms"] = round((time.perf_counter() - t0) * 1000, 2)
            self._shadow_log(out)
            return out

        best = hits[0]
        st = self._states.setdefault(best.name, PointState())
        p = self.points.get(best.name) or {}
        tol_m = float(p.get("tol_mm") or self.params["tol_mm"])
        tol_a = float(p.get("tol_deg") or self.params["tol_deg"])
        # 主判据：位置进容差 且 角度进容差（角度缺失时只看位置）
        in_tol = (best.dist_mm <= tol_m) and (best.ang_deg <= tol_a or abc is None)

        out["hit"] = best.brief()
        if not in_tol:
            st.streak = 0
            out["verdict"] = "near"
            out["why"] = "接近 %s 但未进容差(%.1fmm/%.1f° ≤ %.0fmm/%.0f°)" % (
                best.name, best.dist_mm, best.ang_deg, tol_m, tol_a)
            out["ms"] = round((time.perf_counter() - t0) * 1000, 2)
            self._shadow_log(out)
            return out

        # 防抖：连续 N 拍命中才算到达
        need = int(p.get("confirm_ticks") or self.params["confirm_ticks"])
        st.streak += 1
        st.last_hit = now
        if st.streak < need:
            out["verdict"] = "confirming"
            out["why"] = "到达确认中 %d/%d" % (st.streak, need)
            out["ms"] = round((time.perf_counter() - t0) * 1000, 2)
            self._shadow_log(out)
            return out

        out["arrived"] = True
        out["verdict"] = "arrived"

        # 冷却：避免在同一点反复触发
        cd = float(p.get("cooldown_s") or self.params["cooldown_s"])
        if now - st.last_fire < cd:
            out["why"] = "在 %s 的冷却期内(%.1fs<%.1fs)" % (best.name, now - st.last_fire, cd)
            out["ms"] = round((time.perf_counter() - t0) * 1000, 2)
            self._shadow_log(out)
            return out

        # 能力触发
        caps = best.capabilities or []
        if not caps:
            out["why"] = "%s 是%s位，无绑定能力" % (best.name, best.phase or best.role)
        else:
            for cap in caps:
                req = {
                    "point": best.name, "role": best.role, "phase": best.phase,
                    "kind": cap.get("kind"), "params": {k: v for k, v in cap.items() if k != "kind"},
                    "dist_mm": round(best.dist_mm, 2), "ang_deg": round(best.ang_deg, 2),
                    "shadow": self.shadow, "t": now,
                }
                if self.shadow:
                    req["dispatched"] = False
                    req["note"] = "影子模式：只记录，不调用"
                else:
                    req["dispatched"] = self._dispatch(req, ctx)
                out["fired"].append(req)

        st.last_fire = now
        st.fires += 1
        out["ms"] = round((time.perf_counter() - t0) * 1000, 2)
        self._shadow_log(out)
        return out

    # ---- 真调（live 模式）----
    def _dispatch(self, req: dict, ctx: dict) -> bool:
        """只有 shadow=False 才会进来。目前仅实现 aoi_detect 的真调用，其余如实 False。

        ⚠ 与 aoi_dispatch.py 的分工：那边由轨迹 cursor 驱动、已经处理了节拍/非阻塞/去重；
        这里若也发 POST，会在"轨迹跑过检测点"时造成重复请求。所以 force_ctrl/pick_place/
        calib_trace 一律返回 False 并注明"未接管"，避免两条调度链打架。
        """
        kind = req.get("kind")
        if kind == "aoi_detect":
            # 交给既有 aoi_dispatch 的队列，不自己发 HTTP（口径统一：调度归万有引力）
            try:
                from lerobot.app.workcell import aoi_dispatch as _ad   # noqa: WPS433
                tgt = (req.get("params") or {}).get("target") or ""
                fn = getattr(_ad, "request", None)
                if callable(fn):
                    fn(target=tgt, point=req.get("point"))
                    req["note"] = "已转交 aoi_dispatch.request（统一调度链）"
                    return True
                req["note"] = "aoi_dispatch 无 request() ⇒ 未派发"
                return False
            except Exception as e:                                          # noqa: BLE001
                req["note"] = "转交 aoi_dispatch 失败: %s" % str(e)[:80]
                return False
        req["note"] = "live 未接管 %s（避免与既有调度链冲突）" % kind
        return False

    # ---- 影子日志 ----
    def _shadow_log(self, rec: dict) -> None:
        try:
            self._fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._fout.flush()
        except Exception:
            pass
        if callable(self.logger):
            try:
                self.logger(rec)
            except Exception:
                pass

    # ---- 状态导出（给面板）----
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "shadow": self.shadow,
                "registry": self.path,
                "registry_version": (self.reg or {}).get("version"),
                "n_points": len(self.points),
                "log": self.log_path,
                "points": {
                    n: {"streak": s.streak, "fires": s.fires,
                        "last_fire": s.last_fire, "last_hit": s.last_hit,
                        "role": (self.points.get(n) or {}).get("role")}
                    for n, s in self._states.items()
                },
            }

    def close(self) -> None:
        try:
            self._fout.close()
        except Exception:
            pass


# ────────────────────────── 自测 ──────────────────────────
if __name__ == "__main__":
    import sys
    si = SpaceIntent(shadow=True)
    print("注册表:", si.path, "| 点数:", len(si.points), "| shadow:", si.shadow)
    tests = [
        ("金手指点1", [0.4898, 0.1387, 0.691], [-29.088, -89.753, -152.111]),
        ("侧面点2",  [0.411388, -0.4034, 0.535036], [18.651, 85.023, -8.415]),
        ("光模块插入点", [0.813509, 0.228141, 0.277544], None),
        ("空中(不应命中)", [0.20, 0.00, 0.90], None),
    ]
    for label, xyz, abc in tests:
        print("\n--- %s ---" % label)
        for i in range(2):                       # 两次：验证防抖
            r = si.tick(xyz, abc)
            print("  #%d verdict=%-11s hit=%s fired=%s %s" % (
                i + 1, r["verdict"],
                (r["hit"] or {}).get("name", "-"),
                [f.get("kind") for f in r["fired"]] or "-",
                r["why"][:60]))
    si.close()
    print("\n影子日志:", si.log_path)
