#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_dispatch.py —— 质量检测调度（由「万有引力」节点每拍调用）

老倪 2026-11-23:「运行到 金手指 和 表面检测 的点的时候, 状态空间 光学质量检测, 要触发 AOI 检测…
               由 万有引力 节点调度 质量检测程序」

口径（三条硬约束, 前两条是技能里踩过的坑）:
  ① **调度归万有引力, 不许各模块自己发**: 到位判据只有一处——本模块读 `ss_live/traj_flow.json`
     的 `cursor/rounds`, 由 ss_grav_h 每拍调用 `tick()`; 其它地方（如 real_traj_flow）只能
     `request()`, 不自己发 HTTP。
  ② **非阻塞**: POST /capture_detect 只排队(实测 0.2~0.8s), 但 10Hz 循环不能等 ⇒ 入队 + 工作线程执行,
     `tick()` 只做「算 key / 入队 / 读缓存」, 实测 <1ms。
  ③ **不造数**: 服务不通 / 未出判决 ⇒ `pass=None + verdict="unavailable"`, 绝不填 0 冒充 OK。

点位真源（real_traj_flow.py 2026-11-15 对账结果, 不在这里另立一套）:
  156 → 金手指检测位 (z≈650) → 10082
  172 → 表面检测位 (侧面点0 最近轨迹点) → 10083
点名声 → 端口（段表/技能按名字触发时用）:
  含「金手指」→ 10082; 含「表面」→ 10083
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.request

ROOT_DEFAULT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
AOI_HOST = os.environ.get("ZMAX_AOI_HOST", "192.168.23.23")
COOLDOWN_S = float(os.environ.get("ZMAX_AOI_COOLDOWN_S") or 2.0)
POST_TMO = float(os.environ.get("ZMAX_AOI_POST_TMO") or 2.0)
GET_TMO = float(os.environ.get("ZMAX_AOI_GET_TMO") or 3.0)
PORTS = {"gold": 10082, "surface": 10083}
#: 轨迹流文件"活"的判定: 超过这个时长没更新 ⇒ 认为不在跑, 不按旧 cursor 发检测
FLOW_MAX_AGE_S = float(os.environ.get("ZMAX_AOI_FLOW_MAX_AGE") or 5.0)
#: 到位窗口: cursor 落在 point±1 都算到位（flow 按 chunk 推进, 不一定正好停在点上）
ARRIVE_WIN = int(os.environ.get("ZMAX_AOI_ARRIVE_WIN") or 1)

#: 轨迹点 → 检测项（真源注释见 real_traj_flow.AOI_ON_ARRIVE）
POINTS_BY_INDEX = {156: ("gold",), 172: ("surface",)}
#: 点名/段名 → 检测项（模糊包含即可, 段表名字如「金手指检测点1/2」「表面检测点」）
POINTS_BY_NAME = (("金手指", "gold"), ("表面", "surface"))


def resolve(idx=None, name=None):
    """到位点 → [(kind, port)]；两个来源都受理, 名字优先（段表更权威）。"""
    out = []
    if name:
        for kw, kind in POINTS_BY_NAME:
            if kw in str(name) and kind not in [k for k, _ in out]:
                out.append((kind, PORTS[kind]))
    if not out and idx is not None:
        i = int(idx)
        for p, kinds in POINTS_BY_INDEX.items():
            if abs(i - p) <= ARRIVE_WIN:                # 到位窗口 ±1
                for kind in kinds:
                    out.append((kind, PORTS[kind]))
    return out


class _Dispatcher:
    def __init__(self):
        self.q = queue.Queue(maxsize=32)
        self.lock = threading.Lock()
        self.pass_seen = {}          # (rounds, idx, kind) -> ts  去重（同一轮同一点只发一次）
        self.last_fire = {}          # kind -> ts  限频
        self.jobs = []               # 最近 50 次派发记录
        self.results = {}            # kind -> {pass, verdict, ok, age_s, ...}
        self._th = None
        self.stats = {"queued": 0, "done": 0, "fail": 0, "dropped": 0, "max_tick_ms": 0.0}

    # ---- 工作线程 ----
    def _ensure(self):
        if self._th is None:
            self._th = threading.Thread(target=self._worker, name="aoi-dispatch", daemon=True)
            self._th.start()

    def _worker(self):
        while True:
            job = self.q.get()
            if job is None:
                continue
            kind, port, meta = job["kind"], job["port"], job
            t0 = time.monotonic()
            rec = {"kind": kind, "port": port, "idx": meta.get("idx"), "rounds": meta.get("rounds"),
                   "t_fire": round(time.time(), 3), "ok": False, "verdict": "unavailable",
                   "post_ms": None, "result": None, "err": ""}
            try:
                req = urllib.request.Request("http://%s:%d/capture_detect" % (AOI_HOST, port), method="POST")
                with urllib.request.urlopen(req, timeout=POST_TMO) as resp:
                    body = resp.read().decode("utf-8", "replace")
                rec["post_ms"] = int((time.monotonic() - t0) * 1000)
                rec["ok"] = True
                try:
                    rec["ack"] = json.loads(body)
                except Exception:                                        # noqa: BLE001
                    rec["ack"] = body[:160]
            except Exception as e:                                       # noqa: BLE001
                rec["err"] = "%s: %s" % (type(e).__name__, e)
                self.stats["fail"] += 1
            # 判决: 立刻回读一次 /last_result（拿不到就如实 unavailable, 不造 0）
            try:
                with urllib.request.urlopen("http://%s:%d/last_result" % (AOI_HOST, port),
                                            timeout=GET_TMO) as r2:
                    d = json.loads(r2.read().decode("utf-8", "replace"))
                rec["result"] = {k: d.get(k) for k in ("verdict", "pass", "ok", "ts", "defects", "n")
                                 if k in (d or {})}
                if d:
                    rec["verdict"] = str(d.get("verdict") or ("ok" if d.get("pass") else "unknown"))
            except Exception as e:                                       # noqa: BLE001
                rec["verdict"] = "unavailable"
                rec["err"] = (rec["err"] + " | " if rec["err"] else "") + "last_result: %s" % type(e).__name__
            rec["done_ms"] = int((time.monotonic() - t0) * 1000)
            with self.lock:
                self.results[kind] = {"pass_id": meta.get("pass_id"), "idx": meta.get("idx"),
                                      "rounds": meta.get("rounds"), "verdict": rec["verdict"],
                                      "ok": rec["ok"], "ts": rec["t_fire"],
                                      "age_s": 0.0, "result": rec["result"], "err": rec["err"]}
                self.jobs.append(rec)
                self.jobs = self.jobs[-50:]
                self.stats["done"] += 1
                self._write_status()
            self._append_event(rec)

    # ---- 落盘 ----
    def _paths(self, root):
        live = os.path.join(root, "zmax_data", "ss_live")
        os.makedirs(live, exist_ok=True)
        return (os.path.join(live, "aoi_dispatch.json"),
                os.path.join(live, "aoi_dispatch_events.jsonl"))

    def _write_status(self, root=None):
        root = root or ROOT_DEFAULT
        try:
            p, _ = self._paths(root)
            now = time.time()
            doc = {"ts": round(now, 3), "host": AOI_HOST, "ports": PORTS,
                   "cooldown_s": COOLDOWN_S, "stats": dict(self.stats),
                   "results": {k: dict(v, age_s=round(now - v["ts"], 2)) for k, v in self.results.items()},
                   "recent": self.jobs[-8:],
                   "src": "src/lerobot/manifold/aoi_dispatch.py (由 ss_grav_h 每拍调用)"}
            t = p + ".tmp"
            with open(t, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=1, default=str)
            os.replace(t, p)
        except Exception:                                                # noqa: BLE001
            pass

    def _append_event(self, rec):
        try:
            _, ev = self._paths(ROOT_DEFAULT)
            with open(ev, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        except Exception:                                                # noqa: BLE001
            pass

    # ---- 对外 ----
    def request(self, kind, idx=None, rounds=None, reason=""):
        """入队一次检测（非阻塞）。同一轮同一点、或冷却窗口内 ⇒ 不重复发。"""
        if os.environ.get("ZMAX_AOI_ON_ARRIVE") == "0":
            return {"fired": False, "why": "ZMAX_AOI_ON_ARRIVE=0"}
        port = PORTS.get(kind)
        if port is None:
            return {"fired": False, "why": "未知检测项 %r" % (kind,)}
        now = time.monotonic()
        key = (rounds, idx, kind)
        with self.lock:
            if self.last_fire.get(kind) and now - self.last_fire[kind] < COOLDOWN_S:
                self.stats["dropped"] += 1
                return {"fired": False, "why": "冷却中 (%.1fs)" % COOLDOWN_S}
            if key in self.pass_seen:
                self.stats["dropped"] += 1
                return {"fired": False, "why": "本轮该点已发过"}
            if self.q.full():
                self.stats["dropped"] += 1
                return {"fired": False, "why": "队列满"}
            self.pass_seen[key] = time.time()
            if len(self.pass_seen) > 512:
                self.pass_seen = dict(list(self.pass_seen.items())[-256:])
            self.last_fire[kind] = now
            self._ensure()
            self.q.put_nowait({"kind": kind, "port": port, "idx": idx, "rounds": rounds,
                               "pass_id": "P%s_%s" % (rounds, idx), "reason": reason})
            self.stats["queued"] += 1
        return {"fired": True, "kind": kind, "port": port, "reason": reason}

    def tick(self, idx=None, name=None, rounds=None, root=None):
        """万有引力每拍调用：算方位 → 入队 → 返回缓存快照（不阻塞）。"""
        t0 = time.monotonic()
        flow = {}
        if idx is None:
            try:
                flow = json.load(open(os.path.join(root or ROOT_DEFAULT, "zmax_data/ss_live/traj_flow.json"),
                                      encoding="utf-8")) or {}
            except Exception:                                            # noqa: BLE001
                flow = {}
            idx = flow.get("cursor")
            rounds = flow.get("rounds") if rounds is None else rounds
            age = abs(time.time() - float(flow.get("ts") or 0))
            if str(flow.get("phase") or "").upper() != "RUN" or age > FLOW_MAX_AGE_S:
                return {"ts": round(time.time(), 3), "cursor": idx, "fired": [],
                        "skipped": "flow 未在跑 (phase=%s, 陈旧 %.1fs)" % (flow.get("phase"), age),
                        "flow_max_age_s": FLOW_MAX_AGE_S, "host": AOI_HOST}
        fired = []
        for kind, port in resolve(idx, name):
            # 去重键用点位号（不是 cursor）: 窗口内 cursor 抖动不会重复发
            _pt = [p for p, ks in POINTS_BY_INDEX.items() if kind in ks and idx is not None
                   and abs(int(idx) - p) <= ARRIVE_WIN]
            r = self.request(kind, idx=(_pt[0] if _pt else idx), rounds=rounds,
                             reason=("点名:%s" % name) if name else ("轨迹点:%s" % idx))
            if r.get("fired"):
                fired.append(r)
        with self.lock:
            snap = {"ts": round(time.time(), 3), "cursor": idx, "rounds": rounds,
                    "fired": fired, "queued": self.stats["queued"], "done": self.stats["done"],
                    "fail": self.stats["fail"], "dropped": self.stats["dropped"],
                    "results": {k: dict(v, age_s=round(time.time() - v["ts"], 2))
                                for k, v in self.results.items()},
                    "host": AOI_HOST, "cooldown_s": COOLDOWN_S}
        ms = (time.monotonic() - t0) * 1000.0
        with self.lock:
            self.stats["max_tick_ms"] = max(self.stats["max_tick_ms"], round(ms, 2))
        snap["tick_ms"] = round(ms, 2)
        if fired:
            self._write_status(root)
        return snap


_D = _Dispatcher()


def request(kind, idx=None, rounds=None, reason=""):
    return _D.request(kind, idx=idx, rounds=rounds, reason=reason)


def tick(idx=None, name=None, rounds=None, root=None):
    return _D.tick(idx=idx, name=name, rounds=rounds, root=root)


def snapshot():
    with _D.lock:
        return {"stats": dict(_D.stats),
                "results": {k: dict(v, age_s=round(time.time() - v["ts"], 2))
                            for k, v in _D.results.items()}}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--idx", type=int, default=None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--wait", type=float, default=3.0)
    a = ap.parse_args()
    print(json.dumps(tick(idx=a.idx, name=a.name, rounds=a.rounds), ensure_ascii=False)[:400])
    time.sleep(a.wait)
    print(json.dumps(snapshot(), ensure_ascii=False)[:600])
