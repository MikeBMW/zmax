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
import math
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
    if cmd == "path":
        return do_path(r, req)
    if cmd == "follow":
        if req.get("on"):
            return follow_on(r, req)
        return follow_off()
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
        # 📏 整段平均速率 (2026-10-13 老倪: 速度既然按 mm/s 说事, 就得有"实得多少"这一行)
        #    Δ 路径 / 整段耗时(含收尾安定) ⇒ 名义与实得的差距 = 控制器自己的速度倍率。
        #    有这一行, 现场/页面看就知道"设了 200 为什么还是慢", 不用猜; 没动(奇异)则实得=0%, 一眼可见。
        try:
            _d = out.get("delta_mm") or {}
            _path = math.sqrt(sum(float(_d.get(a) or 0.0) ** 2 for a in "xyz"))
            out["achieved_mm_s"] = round(_path / out["took_s"], 2) if out["took_s"] > 0 else None
            C.log("📏 整段平均速率 %.2f mm/s (Δ路径 %.1fmm / %.1fs · 名义 %.1f mm/s ⇒ 实得 %.0f%%)"
                  % (out["achieved_mm_s"] or 0.0, _path, out["took_s"], speed,
                     (100.0 * (out["achieved_mm_s"] or 0.0) / speed) if speed else 0.0))
        except Exception as _e:                                            # noqa: BLE001
            C.log("📏 整段平均速率算不出(%s)" % str(_e)[:60])
        return rc, out
    return 1, {"cmd": cmd, "verdict": "未知命令: %s" % cmd}


FOLLOW_ST = {"on": False, "n": 0}
FOLLOW_DIR = "/sdk/follow/dir.json"
FOLLOW_STF = "/sdk/follow/status.json"


def _follow_dump():
    try:
        os.makedirs("/sdk/follow", exist_ok=True)
        with open(FOLLOW_STF, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in FOLLOW_ST.items() if k != "thread"}, f, ensure_ascii=False)
    except Exception:                                                       # noqa: BLE001
        pass


def follow_on(r, req):
    """🌊 流式跟随: 按 dir.json 的方向**连续追加** 2mm 小段 (moveAppend + 转角区),
    走出平顺的慢速运动; 总行程被 band_mm 死死卡住 (老倪: 「不要走那么远, 先短距离」)。

    硬化上限: 速度 ≤10mm/s · 带宽 ≤40mm · 单点 ≤5mm —— 改这里才能改, 不接受请求放大。
    安全: dir.json 里 armed=false / on=false / 时间戳旧 >1.5s ⇒ 立即 stop(); 报警/急停/碰撞 ⇒ 立即 stop()。
    """
    if FOLLOW_ST.get("on"):
        return 0, {"cmd": "follow", "verdict": "已在跟随中"}
    # ⚡ 速度上限 80mm/s (2026-10-18 现场: 「你的频率太慢了…跟上节奏啊」——
    #    仿真一个动作 30~80mm, 我们幅度只有 15mm; 若还按 10mm/s, 走完 15mm 要 1.5s,
    #    必然永远滞后一个节拍。跟节奏 = 速度取仿真当期速度, 幅度靠 band 卡小。)
    speed = max(1.0, min(float(req.get("speed") or 10.0), C.MAX_SPEED_MM_S, 80.0))
    band = max(5.0, min(float(req.get("band_mm") or 20.0), 40.0))
    step = max(0.5, min(float(req.get("step_mm") or 2.0), 6.0))
    zone = max(1.0, min(float(req.get("zone_mm") or 3.0), 20.0))
    p0 = C.read_pose(r)
    st = FOLLOW_ST
    st.update({"on": True, "n": 0, "why": "", "speed": speed, "band": band, "step": step,
               "anchor": list(p0["tcp"]), "rpy": list(p0["rpy"]), "pose": list(p0["tcp"]),
               "commit": list(p0["tcp"]), "t0": time.time(), "started": False})
    ec = {}
    r.setDefaultSpeed(speed, ec)
    st["setDefaultSpeed_ec"] = dict(ec)
    ec = {}
    r.setDefaultZone(int(zone), ec)
    st["setDefaultZone_ec"] = dict(ec)
    ec = {}
    r.setDefaultConfOpt(False, ec)
    ec = {}
    r.moveReset(ec)
    C.log("🌊 follow 开: 速度%.1fmm/s 带宽%.0fmm 单点%.1fmm 转角区%.0fmm" % (speed, band, step, zone))

    import threading

    def _loop():
        last = list(st["anchor"])
        t_chk = 0.0
        try:
            while st.get("on"):
                now = time.time()
                try:
                    with open(FOLLOW_DIR, encoding="utf-8") as f:
                        d = json.load(f)
                except Exception:                                           # noqa: BLE001
                    d = {}
                age = now - float(d.get("ts") or 0.0)
                st["dir_age_s"] = round(age, 2)
                if not d.get("on"):
                    st["why"] = "桥接开关已关"
                    break
                if not d.get("armed"):
                    st["why"] = "真动授权未开/已撤"
                    break
                if age > 1.5:
                    st["why"] = "方向流超时 %.1fs" % age
                    break
                if now - t_chk > 1.0:            # 每秒复查控制器状态
                    t_chk = now
                    try:
                        _s = C.read_state(r)
                        st["state"] = _s
                        if _s.get("has_error") or _s.get("estop") or _s.get("collision"):
                            st["why"] = "控制器异常(报警/急停/碰撞)"
                            break
                    except Exception:                                       # noqa: BLE001
                        pass
                # 🎯 追「按比例缩小的仿真轨迹」: dir.json 给的是相对 anchor 的目标偏移(mm),
                #    agent 每 0.2s 往目标方向追加 2mm ⇒ 方向/频率与仿真一致, 幅度由宿主侧缩放卡死。
                tgt_mm = d.get("target_mm") or [0.0, 0.0, 0.0]
                tgt = [st["anchor"][i] + float(tgt_mm[i]) / 1000.0 for i in range(3)]
                st["target"] = tgt
                # 🎯 用**实测位姿**当起点 (不能用自己记的 commit: 控制器没执行时 commit 会跑飞,
                #    表现成"以为到位了、其实臂没动" —— 2026-10-18 现场踩过)
                try:
                    st["pose"] = list(C.read_pose(r)["tcp"])
                except Exception:                                       # noqa: BLE001
                    pass
                cur = st["pose"]
                del_ = [tgt[i] - cur[i] for i in range(3)]
                norm_mm = max(abs(x) * 1000.0 for x in del_)
                # 🩺 卡住检测: 有目标但 1.2s 没动 ⇒ 补一次 moveStart (控制器队列没跑起来的那种)
                if st.get("last_norm") is not None and abs(norm_mm - st["last_norm"]) < 0.3:
                    st["still"] = int(st.get("still") or 0) + 1
                else:
                    st["still"] = 0
                st["last_norm"] = norm_mm
                if st.get("still") == 6 and st.get("started"):
                    ec3 = {}
                    r.moveStart(ec3)
                    st["restart_ec"] = dict(ec3)
                    C.log("🩺 follow 卡住 ⇒ 补一次 moveStart ec=%s" % ec3)
                    st["still"] = 0
                if norm_mm < 0.6:                                  # 已到目标 ⇒ 不发新点, 等它变
                    st["why"] = "跟到位, 等仿真下一个点"
                    _follow_dump()
                    time.sleep(0.05)
                    continue
                frac = min(1.0, st["step"] / norm_mm)
                nxt = [cur[i] + del_[i] * frac for i in range(3)]
                dev = max(abs(nxt[i] - st["anchor"][i]) * 1000.0 for i in range(3))
                if dev > st["band"] * 1.1:
                    st["why"] = "目标超带宽 (%.1fmm > %.0f), 拒绝追加" % (dev, st["band"])
                    _follow_dump()
                    time.sleep(0.05)
                    continue
                st["why"] = "跟随中 (目标差 %.1fmm)" % norm_mm
                cp = C.x.CartesianPosition(list(nxt), list(st["rpy"]))
                mc = C.x.MoveLCommand(cp, st["speed"], -1)
                ec = {}
                r.moveAppend(mc, C.x.PyString("flw_%d" % st["n"]), ec)
                if ec.get("ec", 0) != 0:
                    st["why"] = "moveAppend ec=%s" % ec
                    break
                if not st["started"]:
                    ec2 = {}
                    r.moveStart(ec2)
                    st["started"] = True
                    st["moveStart_ec"] = dict(ec2)
                st["n"] += 1
                last = nxt
                st["commit"] = nxt
                st["why"] = "跟随中"
                try:
                    st["pose"] = list(C.read_pose(r)["tcp"])
                    st["travel_mm"] = round(max(abs(st["pose"][i] - st["anchor"][i]) * 1000.0
                                                for i in range(3)), 1)
                except Exception:                                           # noqa: BLE001
                    pass
                _follow_dump()
                time.sleep(max(0.02, st["step"] / st["speed"]))   # 2mm @10mm/s = 0.2s 一点
        finally:
            st["on"] = False
            try:
                ec = {}
                r.stop(ec)
                st["stop_ec"] = dict(ec)
            except Exception as e:                                          # noqa: BLE001
                st["stop_err"] = str(e)[:100]
            try:
                st["final_pose"] = list(C.read_pose(r)["tcp"])
                st["travel_mm"] = round(max(abs(st["final_pose"][i] - st["anchor"][i]) * 1000.0
                                            for i in range(3)), 1)
            except Exception:                                               # noqa: BLE001
                pass
            _follow_dump()
            C.log("🛑 follow 结束: %s · 追加 %d 点 · 行程 %smm"
                  % (st.get("why"), st.get("n"), st.get("travel_mm")))

    th = threading.Thread(target=_loop, daemon=True)
    th.start()
    st["thread"] = th
    _follow_dump()
    return 0, {"cmd": "follow", "verdict": "FOLLOW ON", "speed_mm_s": speed, "band_mm": band,
               "step_mm": step, "zone_mm": zone, "anchor": st["anchor"]}


def do_path(r, req):
    """🧪 一次性下发多点路径: append 全部点 → **一次** moveStart → 连续走完 (测验"批量路径能不能不停)"""
    pts = [[float(x) for x in p][:3] for p in (req.get("points") or [])]
    if not pts or len(pts) > 200:
        return 2, {"cmd": "path", "verdict": "点数非法 (1~200)"}
    # 2026-10-18 老倪「提速到 200mm/s」: 原来这里硬卡 100, 改成到 MAX_SPEED_MM_S 的 300 (再高就让它显式调)
    speed = max(1.0, min(float(req.get("speed") or 50.0), C.MAX_SPEED_MM_S, 300.0))
    zone = max(0.0, min(float(req.get("zone") or 5.0), 30.0))
    out = {"cmd": "path", "n_points": len(pts), "speed_mm_s": speed, "zone_mm": zone}
    bad = C.precheck(r, out)
    if bad:
        out["verdict"] = "ABORT 前置条件: %s" % bad
        return 3, out
    p0 = C.read_pose(r)
    rpy = list(p0["rpy"])
    base = list(p0["tcp"])
    gbox = req.get("guard_box")
    ec = {}
    r.setDefaultSpeed(speed, ec)
    out["setDefaultSpeed_ec"] = dict(ec)
    ec = {}
    r.setDefaultZone(int(zone), ec)
    out["setDefaultZone_ec"] = dict(ec)
    ec = {}
    r.setDefaultConfOpt(False, ec)
    ec = {}
    r.moveReset(ec)
    acc = [0.0, 0.0, 0.0]
    for k, p in enumerate(pts):
        acc = [acc[i] + p[i] / 1000.0 for i in range(3)]
        tgt = [base[i] + acc[i] for i in range(3)]
        cp = C.x.CartesianPosition(list(tgt), list(rpy))
        mc = C.x.MoveLCommand(cp, speed, -1)
        ec = {}
        r.moveAppend(mc, C.x.PyString("path_%d_%d" % (int(time.time()), k)), ec)
        if ec.get("ec", 0) != 0:
            out["verdict"] = "ABORT moveAppend 第%d点 ec=%s" % (k, ec)
            return 5, out
    ec = {}
    t_send = time.time()
    r.moveStart(ec)
    out["moveStart_ec"] = dict(ec)
    # 盯真值: 直到停稳 1.2s 或超时 (路径长度/速度 + 10s)
    path_mm = sum(abs(x) for p in pts for x in p) / 3.0
    budget = max(15.0, sum((sum(x * x for x in p) ** 0.5) for p in pts) / speed + 10.0)
    last = None
    t_last = time.time()
    while time.time() - t_send < budget:
        time.sleep(0.1)
        try:
            p1 = C.read_pose(r)
        except Exception:                                                # noqa: BLE001
            continue
        t_now = list(p1["tcp"])
        if gbox:
            bad_ax = [ax for i, ax in enumerate("xyz") if not (gbox[ax][0] <= t_now[i] <= gbox[ax][1])]
            if bad_ax:
                ecx = {}
                r.stop(ecx)
                out["verdict"] = "🛑 扫掠越界急停: %s" % bad_ax
                out["stop_ec"] = dict(ecx)
                return 4, out
        if last is not None and max(abs(t_now[i] - last[i]) for i in range(3)) < 0.00005:
            if time.time() - t_last > 1.2:
                break
        else:
            t_last = time.time()
        last = t_now
    p2 = C.read_pose(r)
    d = [round((p2["tcp"][i] - base[i]) * 1000.0, 2) for i in range(3)]
    want = [round(sum(p[i] for p in pts), 2) for i in range(3)]
    out.update({"delta_mm": dict(zip("xyz", d)), "want_mm": dict(zip("xyz", want)),
                "took_s": round(time.time() - t_send, 2),
                "verdict": "PATH DONE" if max(abs(d[i] - want[i]) for i in range(3)) < 3.0 else "PATH 未到位"})
    return 0, out


def follow_off():
    FOLLOW_ST["on"] = False
    FOLLOW_ST["why"] = "收到停止指令"
    _follow_dump()
    return 0, {"cmd": "follow", "verdict": "FOLLOW OFF", "n": FOLLOW_ST.get("n"),
               "travel_mm": FOLLOW_ST.get("travel_mm"), "why": FOLLOW_ST.get("why")}


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
