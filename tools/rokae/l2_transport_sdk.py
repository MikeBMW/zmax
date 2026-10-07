#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_transport_sdk.py — L2 执行器的「本机 SDK 直连」执行腿  (2026-10-07 老倪选 A)

为什么要有它
  · Orin 上的产线 ROS 栈(提供 /move_line)没在跑 ⇒ 页面按钮 / 自动建图走到下发这一步就死,
    现场表现是"点了没反应"、"未到位 244mm"。
  · 老倪口径(逐字): 「不要改变 orin 原来的任何服务。你可以直接调用SDK，但要独立实现」
    以及架构原则「上层只给意图/条件, 执行永远由 L2 收口」⇒ 所以**L2 的闸一个都不动**
    (真动授权 8793 / VL 双层安全闸 / 包络 / 下向守卫 / 限速 全在 chan_send 之前照旧生效),
    只把 chan_send 里最后那段 `ssh → Orin ros2 service call /move_line` 换成本机 SDK 直连。

它只接「已被 L2 校验过」的目标位姿, 自己再叠一层独立守卫:
  · 单条绝对位移上限 MAX_ABS_MM(超过如实拒, 不静默夹取)
  · 速度上限 MAX_SPEED_MM_S
  · 目标过一遍 env_model 已验证包络(默认只记日志; ZMAX_SDK_LEG_ENV=1 则拦)
  · 逐条真值核对: 由常驻 SDK 代理(tools/rokae/sdk_agent.py)在控制器侧读回 TCP 落证据
  · 一条动作在飞时后续一律拒(不排队, 不并发)

开关(运行时, 不用重启): env ZMAX_MOVE_TRANSPORT > 文件 ~/zmax/zmax_data/move_transport.json > "ros"
"""

import json
import math
import os
import re
import sys
import threading
import time

HOME = os.path.expanduser("~")
# ⚠️ 2026-10-08 修正: 原写法是 join(expanduser("~"), "zmax_data/...")  —— 这是**第 4 种老路径写法**
#   (`~` 与 `zmax_data` 分开拼, 前面按 绝对路径 / `~/x` / `$HOME/x` 三种写法做的家目录整合**扫不到**)。
#   工程根搬到 `zmax/` 之后, 这里仍在找 /home/ubuntu/zmax_data/rokae_sdk/cmd_arm.fifo ⇒
#   **SDK 腿永远判定"常驻 SDK 代理未就绪" ⇒ 页面报「已下发(真动)」但机器人不动**(每条都在最后一跳被拦)。
#   统一从工程根推; 留 ZMAX_DATA / ZMAX_REPO 口子给容器/测试。
_REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
_DATA = os.environ.get("ZMAX_DATA", os.path.join(_REPO, "zmax_data"))
FIFO = os.path.join(_DATA, "rokae_sdk/cmd_arm.fifo")
RES = os.path.join(_DATA, "rokae_sdk/tcp_out/agent_result.json")
POSE = os.path.join(_DATA, "rokae_sdk/tcp_out/latest.json")
SWITCH = os.path.join(_DATA, "move_transport.json")
EVID = os.path.join(_DATA, "l2_sdk_leg.jsonl")

MAX_SPEED_MM_S = 30.0          # 速度上限(现场慢速优先; 与页面档位同量级)
MAX_ABS_MM = 800.0             # 单条绝对位移上限(空间点之间最远 ~470mm, 800 够且能拦住误目标)
REL_STEP_MM = 40.0             # rel 位移分片步长(代理硬上限 HARD_MAX_MM=50)
POSE_FRESH_S = 3.0             # 真值文件新鲜度要求
ENV_BLOCK = os.environ.get("ZMAX_SDK_LEG_ENV", "0") == "1"

_LOCK = threading.Lock()
_BUSY = {"in_flight": False, "what": "", "since": 0.0}
_STOP = {"flag": False, "t": 0.0, "why": ""}      # ⏹ 叫停位: 8793 撤销授权/SDK 侧停止 ⇒ 在途动作立即中止
_last = {"cfg_mtime": 0.0, "cfg": None}


def stop(reason="", logf=None):
    """⏹ 掐停在途 SDK 动作。**不依赖 Orin ROS 栈** —— 直接给常驻代理发 stop(控制器受控停止)。

    为什么要单独有它 (2026-10-07): 页面的「撤销授权⇒叫停」走 ctl_revoke_stop → /robot_stop,
    而那条路是 ssh 到 Orin 调 ros2 —— 产线栈没在跑时它**叫不停**。SDK 腿在动臂, 停止就必须走 SDK。
    幂等、不阻塞、失败只记日志(绝不能因为停止通道慢而拖住撤销)。
    """
    _STOP.update(flag=True, t=time.time(), why=str(reason)[:90])
    r = {}
    try:
        with open(FIFO, "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "stop_%d" % int(time.time() * 1000), "cmd": "stop"}) + "\n")
        r = {"rc": 0}
    except Exception as e:                                                          # noqa: BLE001
        r = {"err": str(e)[:80]}
    (logf or print)("⏹ SDK 腿叫停: %s | 代理 stop ⇒ %s" % (reason or "收到停止",
                                                          r.get("rc") if "rc" in r else r.get("err")))
    evidence({"leg": "sdk", "cmd": "stop", "why": str(reason)[:140],
              "fifo_rc": r.get("rc"), "err": r.get("err"), "busy": dict(_BUSY)})
    return True


# ───────────────────────── 开关 ─────────────────────────
def transport():
    """'ros' | 'sdk'。优先级: env > 运行时文件 > 默认 ros(行为与改前完全一致)。"""
    e = (os.environ.get("ZMAX_MOVE_TRANSPORT") or "").strip().lower()
    if e in ("ros", "sdk"):
        return e
    try:
        mt = os.path.getmtime(SWITCH)
        if mt != _last["cfg_mtime"]:
            _last["cfg_mtime"] = mt
            _last["cfg"] = json.loads(open(SWITCH, encoding="utf-8").read())
        t = (_last["cfg"] or {}).get("transport")
        if str(t).strip().lower() in ("ros", "sdk"):
            return str(t).strip().lower()
    except Exception:                                                       # noqa: BLE001
        pass
    return "ros"


def leg_status():
    st = {"transport": transport(), "switch_file": SWITCH, "fifo": FIFO,
          "fifo_ok": os.path.exists(FIFO), "busy": dict(_BUSY)}
    try:
        st["switch"] = json.loads(open(SWITCH, encoding="utf-8").read())
    except Exception:                                                       # noqa: BLE001
        st["switch"] = None
    try:
        st["pose_age_s"] = round(time.time() - os.path.getmtime(POSE), 2)
    except Exception:                                                       # noqa: BLE001
        st["pose_age_s"] = None
    return st


# ───────────────────────── 姿态换算 (口径已实测校验) ─────────────────────────
# 2026-10-07 只读校验: latest.json 的 qx..qw 与 rpy→quat(ZYX, 即 R=Rz·Ry·Rx) 逐位一致(0.00°),
# 且示教点 quat 与现姿态的夹角用 ZYX 得 7~43°(真差值)、用 XYZ 得 166~174°(翻转) ⇒ ZYX 正确。
def quat2rpy(x, y, z, w):
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    sinr = 2.0 * (w * x + y * z)
    cosr = 1.0 - 2.0 * (x * x + y * y)
    rx = math.atan2(sinr, cosr)
    sy = 2.0 * (w * y - z * x)
    ry = math.copysign(math.pi / 2.0, sy) if abs(sy) >= 1.0 else math.asin(sy)
    siny = 2.0 * (w * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    rz = math.atan2(siny, cosy)
    return [rx, ry, rz]


def quat_angle_deg(a, b):
    if not a or not b:
        return None
    d = abs(sum(float(p) * float(q) for p, q in zip(a, b)))
    return math.degrees(2.0 * math.acos(min(1.0, d)))


# ───────────────────────── 真值 / 证据 ─────────────────────────
def read_pose():
    d = json.loads(open(POSE, encoding="utf-8").read())
    age = time.time() - float(d.get("ts") or 0)
    return {"pos": [float(d["x"]), float(d["y"]), float(d["z"])],
            "rpy": [float(d.get("rx") or 0), float(d.get("ry") or 0), float(d.get("rz") or 0)],
            "quat": [float(d.get("qx") or 0), float(d.get("qy") or 0),
                     float(d.get("qz") or 0), float(d.get("qw") or 0)],
            "joint": d.get("joint"), "ts": d.get("ts"), "age": age}


def evidence(rec):
    rec = dict(rec)
    rec["t"] = time.strftime("%F %T")
    try:
        open(EVID, "a", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def env_check(pos):
    """复用 L2 的已验证包络(env_model), 本模块不改它。"""
    try:
        _t = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _t not in sys.path:
            sys.path.insert(0, _t)
        import env_model                                                            # noqa: PLC0415
        ok, msg = env_model.check_target([float(v) for v in pos])
        return bool(ok), str(msg)
    except Exception as e:                                                          # noqa: BLE001
        return True, "环境模型不可用(%s)" % str(e)[:60]


# ───────────────────────── 与常驻 SDK 代理通信 ─────────────────────────
def env_box():
    """🛡 实时扫掠闸门用的包络盒 —— 与 L2 同一真源(env_model 的 envelope)。

    为什么需要: 指令的**目标点**在包络内 ≠ **扫过的路径**在包络内。2026-10-07 碰撞就是
    MoveJ 关节插值把 TCP 带到 z=0.064(低于下限 0.0848) 撞上去的。代理每 0.15s 拿真值比
    这个盒子, 出界立刻 stop()。
    """
    try:
        _t = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _t not in sys.path:
            sys.path.insert(0, _t)
        import env_model                                                            # noqa: PLC0415
        m = json.load(open(env_model.OUT, encoding="utf-8"))
        env = m.get("envelope") or {}
        return {a: [float(env[a][0]), float(env[a][1])] for a in ("x", "y", "z") if a in env}
    except Exception:                                                               # noqa: BLE001
        return None

def send_agent(req, wait_s, logf):
    rid = "%s_%d" % (req.get("tag", "l2"), int(time.time() * 1000) % 100000000)
    req = dict(req, id=rid)
    line = json.dumps(req, ensure_ascii=False) + "\n"
    t0 = time.time()
    try:
        with open(FIFO, "w", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:                                                          # noqa: BLE001
        return {"rc": -1, "err": "写 SDK 代理 FIFO 失败: %s" % str(e)[:90], "id": rid}
    logf("🚚 SDK 腿: 已投递 %s (id=%s)" % (req.get("cmd"), rid))
    while time.time() - t0 < wait_s:
        try:
            d = json.loads(open(RES, encoding="utf-8").read())
            if d.get("id") == rid:
                d["_took_s"] = round(time.time() - t0, 2)
                return d
        except Exception:                                                           # noqa: BLE001
            pass
        time.sleep(0.2)
    return {"rc": -2, "err": "等 SDK 代理回执超时 %.0fs (id=%s)" % (wait_s, rid), "id": rid}


# ───────────────────────── 解析 L2 下发的 ros2 调用 ─────────────────────────
_MV_RE = re.compile(r"/move_(line|pose)\b")
_SPD_RE = re.compile(r"speed:\s*([-\d.eE+]+)")
_POS_RE = re.compile(r"position:\s*\{\s*x:\s*([-\d.eE+]+)\s*,\s*y:\s*([-\d.eE+]+)\s*,\s*z:\s*([-\d.eE+]+)")
_ORI_RE = re.compile(r"orientation:\s*\{\s*x:\s*([-\d.eE+]+)\s*,\s*y:\s*([-\d.eE+]+)"
                     r"\s*,\s*z:\s*([-\d.eE+]+)\s*,\s*w:\s*([-\d.eE+]+)")


def parse_call(call):
    m = _MV_RE.search(call or "")
    if not m:
        return None
    kind = "rot" if m.group(1) == "pose" else "lin"
    sp = _SPD_RE.search(call)
    po = _POS_RE.search(call)
    ori = _ORI_RE.search(call)
    if not (po and ori):
        return {"kind": kind, "bad": "解析不出目标位姿(调用格式变了?)"}
    return {"kind": kind, "srv": "/move_pose" if kind == "rot" else "/move_line",
            "speed_units": float(sp.group(1)) if sp else 60.0,
            "pos": [float(po.group(1)), float(po.group(2)), float(po.group(3))],
            "quat": [float(ori.group(1)), float(ori.group(2)), float(ori.group(3)), float(ori.group(4))]}


# ───────────────────────── 执行 ─────────────────────────
def _run_abs(tgt, rpy, sp_mm, meta, logf):
    if _STOP["flag"]:
        logf("⏹ SDK 腿: 收到叫停(%s) ⇒ 不发这条动作" % _STOP["why"])
        return False, None, {"rc": -9, "err": "stopped"}
    p0 = read_pose()
    d = [tgt[i] - p0["pos"][i] for i in range(3)]
    dist = math.sqrt(sum(v * v for v in d)) * 1000.0
    wait = max(60.0, min(1200.0, dist / max(sp_mm, 0.5) * 3.0 + 30.0))
    req = {"cmd": "move-abs", "tag": "l2", "x": tgt[0], "y": tgt[1], "z": tgt[2],
           "rx": rpy[0], "ry": rpy[1], "rz": rpy[2], "speed": sp_mm,
           "guard_box": env_box()}      # 🛡 实时扫掠闸门(包络盒): 代理每 0.15s 真值比对, 出界即 stop()
    r = send_agent(req, wait, logf)
    p1 = read_pose()
    err = [round((p1["pos"][i] - tgt[i]) * 1000.0, 2) for i in range(3)]
    ok = r.get("rc") == 0 and max(abs(v) for v in err) <= 3.0
    _o = (r.get("out") or {})
    rec = {"leg": "sdk", "cmd": "move-abs", "req_mm": [round(v * 1000, 1) for v in d], "meta": meta,
           "motion": _o.get("motion"), "checkPath": _o.get("checkPath"),
           "retry_after_moveL": _o.get("retry_after_moveL"),
           "speed_mm_s": sp_mm, "target": tgt, "target_rpy": [round(v, 5) for v in rpy],
           "id": r.get("id"), "rc": r.get("rc"), "verdict": r.get("verdict"), "err_mm": err,
           "pos_before": p0["pos"], "pos_after": p1["pos"], "took_s": r.get("_took_s")}
    evidence(rec)
    if ok:
        logf("✅ SDK 腿到位: %s | %s · 残差 %s mm · %.1fs · speed=%.1fmm/s%s"
             % (meta, _o.get("motion") or "?", err, r.get("_took_s") or 0, sp_mm,
                " (MoveL 被拒 ⇒ 已按控制器修法改 MoveJ 成功)" if _o.get("retry_after_moveL") else ""))
    else:
        logf("❌ SDK 腿失败: %s | %s · rc=%s · 残差 %s mm · %s | 真值 %s"
             % (meta, _o.get("motion") or "?", r.get("rc"), err,
                (r.get("verdict") or r.get("err") or "")[:120], [round(v, 4) for v in p1["pos"]]))
    return ok, err, r


def _run_rel(dxyz, sp_mm, meta, logf):
    """分片做完一段相对位移; 任一片失败立即停(不吞错)。"""
    left = [float(v) for v in dxyz]
    done = [0.0, 0.0, 0.0]
    while max(abs(v) for v in left) > 0.2:
        if _STOP["flag"]:
            logf("⏹ SDK 腿分片中止(收到叫停: %s) · 已完成 %s" % (_STOP["why"], done))
            return False, done
        step = [max(-REL_STEP_MM, min(REL_STEP_MM, v)) for v in left]
        wait = max(30.0, min(600.0, max(abs(v) for v in step) / max(sp_mm, 0.5) * 4.0 + 20.0))
        r = send_agent({"cmd": "move-rel", "tag": "l2", "dx": step[0], "dy": step[1], "dz": step[2],
                        "speed": sp_mm, "cap_mm": 50.0}, wait, logf)
        if r.get("rc") != 0 or str(r.get("verdict") or "").startswith("ABORT"):
            evidence({"leg": "sdk", "cmd": "move-rel", "step": step, "meta": meta, "rc": r.get("rc"),
                      "verdict": r.get("verdict"), "err": r.get("err"), "done_before": done})
            logf("❌ SDK 腿失败: %s | 分片 %s · rc=%s · %s"
                 % (meta, step, r.get("rc"), (r.get("verdict") or r.get("err") or "")[:140]))
            return False, done
        done = [done[i] + step[i] for i in range(3)]
        left = [left[i] - step[i] for i in range(3)]
        _p = read_pose()
        evidence({"leg": "sdk", "cmd": "move-rel", "step_mm": step, "done_mm": list(done), "meta": meta,
                  "rc": r.get("rc"), "verdict": r.get("verdict"), "sim": r.get("sim"),
                  "tcp": [round(v, 6) for v in _p["pos"]], "took_s": r.get("_took_s"), "id": r.get("id")})
    return True, done


def _worker(kind, tgt, quat, sp_mm, meta, logf, p0):
    try:
        rpy = quat2rpy(*quat) if quat else p0["rpy"]
        if kind == "rel":
            ok, done = _run_rel([(tgt[i] - p0["pos"][i]) * 1000.0 for i in range(3)], sp_mm, meta, logf)
        else:
            ok, err, _r = _run_abs(tgt, rpy, sp_mm, meta, logf)
        if ok:
            logf("🚚 SDK 腿完成: %s" % meta)
    except Exception as e:                                                          # noqa: BLE001
        logf("❌ SDK 腿异常: %s | %s" % (meta, str(e)[:140]))
    finally:
        _BUSY["in_flight"] = False
        _BUSY["what"] = ""


def exec_call(call, logf, meta=""):
    """chan_send 的 SDK 执行腿。返回 (ok, msg)。同步做守卫, 异步做动作(与 ROS 腿同为"已下发"语义)。"""
    mv = parse_call(call)
    if mv is None:
        return False, "🚚 SDK 腿: 认不出这是运动调用 ⇒ 拒(宁可不动)"
    if mv.get("bad"):
        return False, "🚚 SDK 腿: %s ⇒ 拒" % mv["bad"]
    if _BUSY["in_flight"]:
        return False, "🚚 SDK 腿: 上一条动作还在执行(%s, %.0fs) ⇒ 拒(不排队)" % (
            _BUSY["what"], time.time() - _BUSY["since"])
    if not os.path.exists(FIFO):
        return False, "🚚 SDK 腿: 常驻 SDK 代理未就绪(FIFO 不存在: %s)" % FIFO
    try:
        p0 = read_pose()
    except Exception as e:                                                          # noqa: BLE001
        return False, "🚚 SDK 腿: 读不到 TCP 真值(%s) ⇒ 拒" % str(e)[:60]
    if p0["age"] > POSE_FRESH_S:
        return False, "🚚 SDK 腿: TCP 真值陈旧 %.1fs > %.0fs ⇒ 拒(不拿旧位姿发动作)" % (p0["age"], POSE_FRESH_S)

    sp_mm = max(1.0, min(MAX_SPEED_MM_S, 0.0935 * float(mv["speed_units"])))
    dist_mm = math.sqrt(sum((mv["pos"][i] - p0["pos"][i]) ** 2 for i in range(3))) * 1000.0
    ang = quat_angle_deg(mv["quat"], p0["quat"])
    _a = "" if ang is None else " · 姿态差 %.1f°" % ang
    if dist_mm > MAX_ABS_MM:
        return False, ("🚚 SDK 腿: 本次位移 %.0fmm > 上限 %.0fmm ⇒ 拒(不夹取)" % (dist_mm, MAX_ABS_MM))
    if dist_mm < 0.3 and (ang is None or ang < 0.3):
        logf("🚚 SDK 腿: 目标已在当前位姿(%.2fmm%s) ⇒ 无需动作" % (dist_mm, _a))
        return True, "🚚 SDK 腿: 已在目标位姿"
    eok, emsg = env_check(mv["pos"])
    logf("🌍 SDK 腿环境校验: %s" % emsg)
    if not eok and ENV_BLOCK:
        return False, "🚚 SDK 腿: 目标出已验证包络 ⇒ 拒(ZMAX_SDK_LEG_ENV=1): %s" % emsg

    kind = "rel" if dist_mm <= REL_STEP_MM else "abs"
    with _LOCK:
        _BUSY.update(in_flight=True, what=meta or mv["srv"], since=time.time())
    _STOP.update(flag=False, t=0.0, why="")      # 🔄 新动作开始 ⇒ 清叫停位(上一条的叫停不牵连这一条)
    logf("🚚 SDK 腿下发: %s → pos=(%.4f, %.4f, %.4f) · 位移 %.0fmm%s · speed=%.1fmm/s (%s)"
         % (meta or mv["srv"], mv["pos"][0], mv["pos"][1], mv["pos"][2], dist_mm, _a, sp_mm, kind))
    th = threading.Thread(target=_worker, args=(kind, mv["pos"], mv["quat"], sp_mm,
                                                meta or mv["srv"], logf, p0), daemon=True)
    th.start()
    return True, ("🚚 SDK 腿已下发(本机 SDK 直连): %s · 位移 %.0fmm%s · speed=%.1fmm/s"
                  % (meta or mv["srv"], dist_mm, _a, sp_mm))


def preflight(logf=print):
    """不动机器人的自检: 开关/代理/真值/解析/包络 —— 供命令行与测试用。"""
    st = leg_status()
    logf("开关 transport = %s (file=%s)" % (st["transport"], st["switch_file"]))
    logf("常驻代理 FIFO = %s (%s)" % (st["fifo"], "在" if st["fifo_ok"] else "❌不在"))
    try:
        p = read_pose()
        logf("TCP 真值: pos=%s rpy(deg)=%s · 龄 %.2fs"
             % ([round(v, 4) for v in p["pos"]], [round(math.degrees(v), 2) for v in p["rpy"]], p["age"]))
    except Exception as e:                                                          # noqa: BLE001
        logf("❌ 读 TCP 真值失败: %s" % e)
    for nm, tx, ty, tz in (("space1", 0.6473608, 0.205931, 0.1076848),
                           ("space4", 0.4291576, 0.4931214, 0.3972216)):
        ok, msg = env_check([tx, ty, tz])
        logf("包络 %s: %s | %s" % (nm, "OK" if ok else "❗出包络", msg))
    return st


if __name__ == "__main__":
    preflight()
