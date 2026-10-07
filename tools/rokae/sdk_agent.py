#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sdk_agent.py — 容器内**常驻**的本机 SDK 直连代理 (纯新增件, 不改任何既有代码/服务)

为什么常驻: 每条动作起一个 docker run 要 2s 桥接开销; 常驻后持一条 SDK 会话,
主机侧只往 FIFO 写一行 JSON, 动作延迟 = 纯运动时间。
Orin 零参与: 不读不写 Orin 任何文件/单元/服务, 也不依赖它的 ROS/DDS。

输入(FIFO, 每行一个 JSON):
  {"id":"..","cmd":"state"}                              → 只读状态
  {"id":"..","cmd":"pose"}                               → 只读位姿
  {"id":"..","cmd":"move-rel","dx":1.0,"dy":0,"dz":0,"speed":5.0,"cap_mm":5.0}
  {"id":"..","cmd":"move-abs","x":..,"y":..,"z":..,"speed":5.0}   (m; 姿态默认不变)
  {"id":"..","cmd":"stop"} / {"cmd":"reset"} / {"cmd":"ping"}
输出:
  /sdk/tcp_out/agent_result.json      最近一条命令的结果(含 verdict + 全量证据)
  /sdk/tcp_out/agent_heartbeat.json   每秒心跳(电源/状态/位姿/采样器龄) —— 页面状态条用
  /sdk/logs/agent_<date>.jsonl        逐条流水(含每次动作的逐帧真值)
守卫: 全部复用 sdk_ctl 里的同一套(前置自检 / 回读校验 / 越界立刻 stop / 证据 JSON / 收尾回 Idle)
"""
import json
import os
import select
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/repo")
import sdk_ctl as C  # noqa: E402

FIFO = os.environ.get("ZMAX_ARM_FIFO", "/sdk/cmd_arm.fifo")
RESULT = "/sdk/tcp_out/agent_result.json"
HEART = "/sdk/tcp_out/agent_heartbeat.json"
LOGDIR = "/sdk/logs"


def sdir(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def dump(p, obj):
    tmp = p + ".tmp"
    with open(sdir(tmp), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def alog(obj):
    os.makedirs(LOGDIR, exist_ok=True)
    with open(os.path.join(LOGDIR, "agent_%s.jsonl" % time.strftime("%Y%m%d")), "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def ns(**kw):
    return types.SimpleNamespace(**kw)


def handle(r, req):
    """执行一条命令 → (rc, out)。out 里带 verdict 与全量证据。"""
    cmd = req.get("cmd")
    rid = str(req.get("id") or "")
    t0 = time.time()
    if cmd == "ping":
        return 0, {"cmd": "ping", "pong": True}
    if cmd == "state":
        return 0, {"cmd": "state", "state": C.read_state(r), "alarms": C.alarms(),
                   "sampler": C.sampler_pose(), "pose": C.read_pose(r)}
    if cmd == "pose":
        return 0, {"cmd": "pose", "pose": C.read_pose(r), "sampler": C.sampler_pose()}
    if cmd == "stop":
        ec = {}
        r.stop(ec)
        return 0, {"cmd": "stop", "ec": dict(ec), "verdict": "STOPPED"}
    if cmd == "reset":
        ec = {}
        r.moveReset(ec)
        return 0, {"cmd": "reset", "ec": dict(ec), "verdict": "RESET"}
    if cmd in ("move-rel", "move-abs"):
        speed = min(float(req.get("speed") or 5.0), C.MAX_SPEED_MM_S)
        out = {"cmd": cmd, "id": rid, "speed_mm_s": speed, "host_time": C.host_ts()}
        bad = C.precheck(r, out)
        if bad:
            out["verdict"] = "ABORT 前置条件不满足: %s" % bad
            C.log("⛔ " + out["verdict"])
            return 3, out
        p0 = C.read_pose(r)
        if cmd == "move-rel":
            d = [float(req.get("dx") or 0.0), float(req.get("dy") or 0.0), float(req.get("dz") or 0.0)]
            cap = min(float(req.get("cap_mm") or C.DEFAULT_MAX_MM), C.HARD_MAX_MM)
            out["delta_req_mm"] = d
            out["cap_mm"] = cap
            if max(abs(v) for v in d) > cap:
                out["verdict"] = "ABORT 请求位移 %.2fmm > 上限 %.2fmm" % (max(abs(v) for v in d), cap)
                return 2, out
            tgt = [p0["tcp"][i] + d[i] / 1000.0 for i in range(3)]
            rpy = p0["rpy"]
        else:
            tgt = [float(req["x"]), float(req["y"]), float(req["z"])]
            rpy = p0["rpy"] if req.get("rx") is None else [float(req["rx"]), float(req["ry"]), float(req["rz"])]
            out["target_req"] = tgt
        out["pre_sampler"] = C.sampler_pose()
        _mv = str(req.get("motion") or "L").upper()
        rc, out = C.do_move(r, tgt, rpy, speed, out, 999.0, cmd, motion=_mv, guard_box=req.get("guard_box"))
        # 🧗 奇异点自愈 (2026-10-07 实测): 控制器对 MoveL 可能报 50102「轨迹前瞻过程中遇到奇异点」——
        #    特征是 moveStart ec=0 但臂**一动不动**, 20s 后残差=全量位移。控制器手册给的修法②就是
        #    "把笛卡尔运动指令改为关节空间运动指令" ⇒ 同一目标自动改用 MoveJ 再试一次(**只一次**)。
        if rc != 0 and _mv != "J" and bool(req.get("allow_movej_retry", False)):
            _first = {"rc": rc, "verdict": out.get("verdict"), "took_s": out.get("took_s"),
                      "resid_mm": out.get("max_dev_mm")}
            C.log("🧗 MoveL 被拒(rc=%s) ⇒ 按控制器手册修法②改用 MoveJ 重试一次" % rc)
            rc2, out2 = C.do_move(r, tgt, rpy, speed, {}, 999.0, cmd, motion="J", guard_box=req.get("guard_box"))
            out2["retry_after_moveL"] = _first
            rc, out = rc2, out2
        out["took_s"] = round(time.time() - t0, 2)
        return rc, out
    return 1, {"cmd": cmd, "verdict": "未知命令: %s" % cmd}


def main():
    r = C.x.xMateRobot()
    C.log("SDK 代理: 连接 %s ..." % C.IP)
    r.connectToRobot(C.IP)
    C.log("SDK 代理就绪 · FIFO=%s" % FIFO)
    dump(HEART, {"agent": "up", "t": time.strftime("%F %T"), "ip": C.IP})
    if os.path.exists(FIFO):
        os.unlink(FIFO)
    os.mkfifo(FIFO, 0o666)
    try:
        os.chmod(FIFO, 0o666)      # 2026-10-07 实测: 容器 root 造出的 FIFO 是 0644 ⇒ 宿主用户 PermissionError
    except Exception:                                                        # noqa: BLE001
        pass
    fd = os.open(FIFO, os.O_RDONLY | os.O_NONBLOCK)
    buf = b""
    last_heart = 0.0
    while True:
        rl, _, _ = select.select([fd], [], [], 1.0)
        if rl:
            try:
                chunk = os.read(fd, 65536)
            except Exception:                                                # noqa: BLE001
                chunk = b""
            if chunk == b"":        # 所有写端关闭 → 重开, 避免 select 空转
                os.close(fd)
                fd = os.open(FIFO, os.O_RDONLY | os.O_NONBLOCK)
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                t0 = time.time()
                try:
                    req = json.loads(line.decode("utf-8"))
                except Exception as e:                                       # noqa: BLE001
                    C.log("无效指令: %s (%s)" % (line[:80], e))
                    continue
                C.log("▶ %s %s" % (req.get("cmd"), req.get("id") or ""))
                try:
                    rc, out = handle(r, req)
                except Exception as e:                                       # noqa: BLE001
                    rc, out = 9, {"cmd": req.get("cmd"), "verdict": "执行异常: %s" % str(e)[:200]}
                    C.log("✖ %s" % out["verdict"])
                try:                       # 每条动作另存一份独立证据文件(便于单条引用/导出)
                    C.write_evid(out, req.get("cmd") or "cmd")
                except Exception:                                                # noqa: BLE001
                    pass
                res = {"id": req.get("id"), "cmd": req.get("cmd"), "rc": rc,
                       "t": time.strftime("%F %T"), "took_s": round(time.time() - t0, 2),
                       "verdict": out.get("verdict"), "out": out}
                dump(RESULT, res)
                alog(res)
                C.log("◀ %s rc=%s %s" % (req.get("cmd"), rc, out.get("verdict")))
        now = time.time()
        if now - last_heart >= 1.0:
            last_heart = now
            try:
                dump(HEART, {"agent": "up", "t": time.strftime("%F %T"), "container_t": time.time(),
                             "state": C.read_state(r), "pose": C.read_pose(r), "sampler": C.sampler_pose(),
                             "alarms": C.alarms()})
            except Exception as e:                                           # noqa: BLE001
                dump(HEART, {"agent": "up_but_read_fail", "err": str(e)[:150]})


if __name__ == "__main__":
    main()
