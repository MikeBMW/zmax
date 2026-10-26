#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🕹 550C 动作下发方: 收 ss_plan → 逐段下发 Orin SDK 桥 → 真值对账 → 落台账

部署位置: 550C (Nodka-PTL-Demo, 192.168.23.70) · /home/intel/zmax_550c/tools/plan_exec_550c.py

为什么 (老倪 2026-10-25): 「让 550C 成为下发方」
  550B 只发布意图(段表绝对目标), 下发与到位判据在 550C。550C 到 Orin 是**产线局域网直连**
  (192.168.23.66:39061), 不经过 ECS 跳板 ⇒ 不会像 550B 直连那样断。

闸门 (任一不过 ⇒ 拒发并留痕, 绝不发半条):
  ① 载荷解析: plan_id / n_seg 1..8 / abs_mm 每点 3 个数
  ② 授权: note.auth_remaining_s 是**发布时的剩余秒数**, 用**本机收到时刻**+它算过期
     —— 不对时, 不信任任何远端时钟; remaining ≤ 0 直接拒
  ③ 幂等: 同一 plan_id 只执行一次(默认 10 分钟窗口), 防 ws 重发导致重复动作
  ④ 起点一致性: 当前 TCP 与段表起点 ≤20mm, 否则拒(不在未知位置起步)
  ⑤ 每段真值对账: |TCP-目标| ≤2mm 且 max|jointVel|<0.05 才算到位; 失败立即 /stop 并中止余段

输出: 
  · 台账   zmax_data/runtime/plan/plan_exec_550c.jsonl (逐段 Δ/残差/耗时)
  · 状态   zmax_data/runtime/plan/plan_exec_state.json (phase/seg/plan_id/ts, 供 550B ssh 读取)
"""
import json
import math
import os
import sys
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
for _p in (os.path.join(ROOT, "dds"), os.path.join(ROOT, "tools", "dds")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from zmax_node import Node  # noqa: E402

BRIDGE = os.environ.get("ZMAX_BRIDGE_URL") or "http://192.168.23.66:39061"
OUT_DIR = os.environ.get("ZMAX_PLAN_OUT") or os.path.join(ROOT, "zmax_data/runtime/plan")
LEDGER = os.path.join(OUT_DIR, "plan_exec_550c.jsonl")
STATE = os.path.join(OUT_DIR, "plan_exec_state.json")
SEEN = os.path.join(OUT_DIR, "plan_exec_seen.json")
TOL_MM = 2.0
TIME_LIMIT_S = 25.0
IDEMPOTENT_S = 600.0


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def bridge(path, body=None, timeout=25, method=None):
    data = None if body is None else json.dumps(body).encode()
    rq = urllib.request.Request(BRIDGE + path, data=data,
                                headers={"Content-Type": "application/json"},
                                method=method or ("POST" if data else "GET"))
    with urllib.request.urlopen(rq, timeout=timeout) as r:
        return json.loads(r.read().decode())


def tcp_mm(st):
    return [round(float(v) * 1000.0, 2) for v in (st.get("endInRef") or [])[:3]]


def vmax(st):
    out = []
    for e in (st.get("jointVel") or []):
        out.append(max(abs(x) for x in e) if isinstance(e, list) else abs(e))
    return max(out or [0.0])


def rpy_to_quat(rx, ry, rz):
    cx, sx = math.cos(rx / 2), math.sin(rx / 2)
    cy, sy = math.cos(ry / 2), math.sin(ry / 2)
    cz, sz = math.cos(rz / 2), math.sin(rz / 2)
    return [sx * cy * cz - cx * sy * sz, cx * sy * cz + sx * cy * sz,
            cx * cy * sz - sx * sy * cz, cx * cy * cz + sx * sy * sz]


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def ledger(rec):
    os.makedirs(OUT_DIR, exist_ok=True)
    rec = dict(rec, t=time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_seen():
    try:
        d = json.load(open(SEEN, encoding="utf-8"))
        return {k: float(v) for k, v in d.items() if time.time() - float(v) < IDEMPOTENT_S}
    except Exception:                                                      # noqa: BLE001
        return {}


def state(**kw):
    d = {"ts": time.time(), "t": time.strftime("%Y-%m-%d %H:%M:%S"), "host": "550C"}
    d.update(kw)
    write_json(STATE, d)


def execute(payload):
    """payload: {plan_id, n_seg, speed_mm_s, auth_remaining_s, abs_mm[], dirs[]}"""
    plan_id = payload["plan_id"]
    pts = payload["abs_mm"]
    sp = float(payload.get("speed_mm_s") or 200.0)
    h = bridge("/health", timeout=8)
    if not (h.get("ok") and h.get("sdk")):
        ledger({"ev": "reject", "plan_id": plan_id, "why": "Orin 桥不可用"})
        state(phase="blocked", plan_id=plan_id, why="Orin 桥不可用: %s" % str(h)[:80])
        return {"ok": False, "why": "Orin 桥不可用: %s" % h}
    st = bridge("/status", timeout=8)["status"]
    here = tcp_mm(st)
    q = rpy_to_quat(float(st["endInRef"][3]), float(st["endInRef"][4]), float(st["endInRef"][5]))
    # 起点 = 发布端给的 start_mm(规划起点), 兼容旧发布端(没有 start_mm 时退回 pts[0])
    _st0 = payload.get("start_mm") if isinstance(payload, dict) else None
    start = [round(float(v), 2) for v in (_st0 if _st0 else pts[0])]
    off = max(abs(here[i] - start[i]) for i in range(3))
    if off > 20.0:
        ledger({"ev": "reject", "plan_id": plan_id,
                "why": "起点不一致 %.1fmm >20mm" % off, "here_mm": here, "start_mm": start})
        state(phase="blocked", plan_id=plan_id, why="当前 TCP 距起点 %.1fmm >20mm" % off)
        return {"ok": False, "why": "当前 TCP %s 距段表起点 %s 差 %.1fmm >20mm ⇒ 不在未知位置起步" % (here, start, off)}

    state(phase="running", plan_id=plan_id, seg=0, n_seg=len(pts), start=here, speed=sp)
    results = []
    t_all = time.time()
    for i, tgt_mm in enumerate(pts, 1):
        tgt = [float(v) for v in tgt_mm]
        t0 = time.time()
        cur = tcp_mm(st)
        # 🔴 2026-10-26 实测复现: seg1 成功后立刻发 seg2 → 桥返回 moveStart 报错(ec 被吞),
        #   而 moveAppend 是 0 —— 典型的"上一条运动还没在内核里收尾就又 moveStart"。
        #   修法两条: ①下发前等到真静止(vmax 小 + 位置不再变, 最多等 3s); ②失败 0.3s 后重试一次。
        _t_wait = time.time()
        _prev = None
        while time.time() - _t_wait < 3.0:
            try:
                _s = bridge("/status", timeout=6)["status"]
                _p = tcp_mm(_s)
                if vmax(_s) < 0.05 and _prev is not None and max(abs(_p[k] - _prev[k]) for k in range(3)) < 0.1:
                    break
                _prev = _p
            except Exception:                                                # noqa: BLE001
                pass
            time.sleep(0.12)
        r = bridge("/move_pose", {"p": [v / 1000.0 for v in tgt], "q": q, "speed": sp, "dry": False})
        res = (r.get("result") or {})
        if not res.get("ok"):
            # 重试一次 (拿新位姿再发; 只重试一次, 不掩盖真故障)
            time.sleep(0.3)
            _s2 = bridge("/status", timeout=6)["status"]
            _e2 = _s2.get("endInRef") or []
            _q2 = rpy_to_quat(float(_e2[3]), float(_e2[4]), float(_e2[5])) if len(_e2) >= 6 else q
            r = bridge("/move_pose", {"p": [v / 1000.0 for v in tgt], "q": _q2, "speed": sp, "dry": False})
            res = (r.get("result") or {})
            if not res.get("ok"):
                res["why"] = "%s (已重试 1 次)" % (res.get("why") or "moveStart 报错")
        # 🔴 2026-10-26 现场「只走了两步就中断」复盘:
        #   ① 段下发被判失败 ⇒ 这里去调 /stop, 而 Orin 桥的 /stop 当时裸调 stopMove()/moveReset()
        #      少了 ec 参数 ⇒ 抛 TypeError ⇒ HTTP 500 ⇒ **未捕获异常把整个执行器进程打死**,
        #      systemd 重启后状态文件回到 idle ⇒ 页面看着"没报错就停了"。
        #   ② 失败原因也跟着丢了: ledger 写在 /stop 之后, 那句 seg_fail 永远没落盘。
        #   现在改成: 先落 ledger(带桥返回的完整 ec/why) → 再尽力 stop(任何异常都吞掉) → 不崩。
        if not res.get("ok"):
            _why = str(res.get("why") or (r.get("error") or "未知"))[:120]
            ledger({"ev": "seg_fail", "plan_id": plan_id, "seg": i, "why": _why,
                    "target_mm": tgt, "here_mm": cur,
                    "append_ec": (res.get("sent") or {}).get("moveAppend_ec"),
                    "start_ec": (res.get("sent") or {}).get("moveStart_ec")})
            _stop = {}
            try:
                _stop = bridge("/stop", {}, timeout=8)
            except Exception as _e:                                          # noqa: BLE001
                _stop = {"ok": False, "err": str(_e)[:120]}
            state(phase="aborted", plan_id=plan_id, seg=i, n_seg=len(pts),
                  why=_why, stop=_stop, target_mm=tgt, here_mm=cur)
            return {"ok": False, "why": "第 %d 段下发被拒: %s" % (i, _why), "segs": results, "stop": _stop}
        while time.time() - t0 < TIME_LIMIT_S:
            st = bridge("/status", timeout=6)["status"]
            cur = tcp_mm(st)
            if vmax(st) < 0.05 and max(abs(cur[k] - tgt[k]) for k in range(3)) <= TOL_MM:
                break
            time.sleep(0.15)
        err = max(abs(cur[k] - tgt[k]) for k in range(3))
        took = round(time.time() - t0, 2)
        ok = err <= TOL_MM and vmax(st) < 0.05
        results.append({"seg": i, "ok": ok, "took_s": took, "resid_mm": round(err, 2), "tcp_mm": cur})
        ledger({"ev": "seg_ok" if ok else "seg_bad", "plan_id": plan_id, "seg": i,
                "target_mm": tgt, "tcp_mm": cur, "resid_mm": round(err, 2), "took_s": took})
        state(phase="running", plan_id=plan_id, seg=i, n_seg=len(pts), last=cur,
              resid_mm=round(err, 2), took_s=took)
        if not ok:
            bridge("/stop", {}, timeout=8)
            state(phase="aborted", plan_id=plan_id, seg=i, resid_mm=round(err, 2))
            return {"ok": False, "why": "第 %d 段偏差 %.2fmm/未停稳" % (i, err), "segs": results}

    total = round(time.time() - t_all, 2)
    state(phase="done", plan_id=plan_id, seg=len(pts), n_seg=len(pts), total_s=total,
          end_tcp=results[-1]["tcp_mm"])
    ledger({"ev": "plan_done", "plan_id": plan_id, "n_seg": len(pts), "total_s": total,
            "end_tcp_mm": results[-1]["tcp_mm"], "speed_mm_s": sp})
    return {"ok": True, "total_s": total, "segs": results}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    n = Node("plan_exec_550c")
    n.sub("ss_plan")
    log("550C 下发方就绪 · 订阅 ss_plan · 桥=%s" % BRIDGE)
    log("配对=%s" % n.wait_for_match("ss_plan", 1, 10))
    state(phase="idle", seg=0)
    seen = load_seen() if os.path.exists(SEEN) else {}
    while True:
        for s in n.sub("ss_plan").take():
            try:
                note = json.loads(s.note or "{}")
            except Exception:                                              # noqa: BLE001
                continue
            pid = str(note.get("plan_id") or "").strip()
            if not pid:
                continue
            if pid in seen:
                continue
            pts = note.get("abs_mm") or []
            rem = float(note.get("auth_remaining_s") or 0.0)
            log("收到段表 plan_id=%s n_seg=%s 授权剩余 %.0fs" % (pid, note.get("n_seg"), rem))
            # 段数上限原来 8: 手工 4 段够用, 但覆盖扫描(建图轨迹3)一排一排走, 天然 12 段 ⇒
            # 改 24 (仍是"防呆上限", 不是安全闸; 安全靠起点/包络/授权/预检)。
            if not (1 <= len(pts) <= 24) or any(len(p) < 3 for p in pts):
                ledger({"ev": "reject", "plan_id": pid, "why": "abs_mm 不合法"})
                continue
            if rem <= 1.0:
                ledger({"ev": "reject", "plan_id": pid, "why": "授权剩余 %.0fs ≤1s" % rem})
                state(phase="blocked", plan_id=pid, why="授权已过期(剩 %.0fs)" % rem)
                log("🛑 拒: 授权剩余 %.0fs" % rem)
                seen[pid] = time.time()
                continue
            seen[pid] = time.time()
            write_json(SEEN, seen)
            # 🔴 2026-10-26: execute() 里任何没料到的异常都不许打死这个常驻进程
            #    (上一轮就是 /stop 的 HTTP 500 冒到这里, 进程崩、systemd 重启、状态回到 idle,
            #     现场看到的现象是"走两步就停了, 页面也没报错")。
            try:
                out = execute(note)
            except Exception as _e:                                        # noqa: BLE001
                import traceback
                _tb = traceback.format_exc()[-400:]
                ledger({"ev": "crash", "plan_id": pid, "err": str(_e)[:160], "tb": _tb})
                state(phase="error", plan_id=pid, why="执行器异常: %s" % str(_e)[:120])
                log("💥 执行器异常(已兜住, 不退出): %s" % str(_e)[:160])
                out = {"ok": False, "why": str(_e)[:120]}
            log("执行结果: ok=%s %s" % (out.get("ok"), out.get("why") or ""))
        time.sleep(0.2)


if __name__ == "__main__":
    main()
