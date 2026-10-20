#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ft_direct_sampler.py — 真机六维力直读采样 (只读; 不发任何运动/力控指令)

老倪 2026-10-20: 「将 AR 场景的末端执行器的 x y z 和 插拔的侧向力, 显示出来; 来自于真实的机器人」

为什么存在:
  · 平台原来在信号分析里那条「末端.切向力_N」= DDS zmax/ss_force_l2 的 x 分量, 那是**平台自己算的分层力**
    (前馈加速器), 不是机器人接触力 ⇒ 不能拿来当"侧向力"给现场看。
  · 真机六维力有两个活口: ① Orin 的 ROS 话题 /robot/force_torque (要产线网卡在位, 且 Orin 在跑)
    ② **珞石控制器 xCoreSDK** `forceControl().getEndTorque(ref, ...)` —— 与 TCP 位姿同一条直连会话,
    不需要 Orin。本文件走 ②, 与 tcp_direct_sampler.py 同一套连接/落盘口径 (直连 192.168.23.160)。

口径 (关键, 别改):
  · 参考系 = **世界/基座系** (FrameType.world)。插入轴 = base +x ⇒
    轴向力 = fx, 侧向力 = hypot(fy, fz)。工具系下算侧向力是错量 ⇒ 本采样器默认拒绝 tool。
  · **只读**: connectToRobot / forceControl / getEndTorque / disconnect ——
    不调 fcStart/fcStop/setCartesianDesiredForce, 不进力控模式, 不下发任何运动。
  · 读不到就写 `err`, **不写 0 冒充** (0 N 是一个合法读数, 与"没接"必须能区分)。
  · 控制器 SDK 会话是共享资源: 本机可能同时有 zmax-sdk-arm-agent(动作链) 与 tcp_direct_sampler(位姿真值)
    在连。**先跑一次 `--probe`** 看能不能拿到数 (拿不到就别硬开, 免得抢会话把位姿真值那条关键活路弄断)。
  · connect 报 `network: network connection` = 产线网卡不在位 / 控制器没上电 —— 先用 `ip -br addr` + `ping` 定性,
    别怀疑 API (2026-10-20 实测就是这个原因, 网卡掉了整条产线网段全不可达)。
  · 控制器未上电 / 报警时 SDK 可能返回全 0 或报错码 —— 全部按"未接"落 err, 由 ar_aoi_bus 判帧龄后不写键。

用法 (SDK 是 cpython-310 ⇒ 必须 python3.10 容器, 与 rokae_sdk_run.sh 同一镜像):
  sudo docker run --rm --network host -v ~/zmax/zmax_data/rokae_sdk:/sdk -w /sdk \
      ros:humble-ros-base python3 /sdk/ft_direct_sampler.py --rate 10 --secs 0
  sudo docker run --rm --network host -v ~/zmax/zmax_data/rokae_sdk:/sdk -w /sdk \
      ros:humble-ros-base python3 /sdk/ft_direct_sampler.py --probe      # 只探一次, 打印 API 实况

产出:
  /sdk/ft_out/latest.json                 最新一帧 (ar_aoi_bus 读这个)
  /sdk/ft_out/ft_direct_YYYYMMDD.jsonl    全量 (每行一帧)
"""
import argparse
import json
import math
import os
import sys
import time

SDK_DIR = os.environ.get("ROKAE_SDK_DIR", "/sdk")
ROBOT_IP = os.environ.get("ROKAE_IP", os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160"))
sys.path.insert(0, SDK_DIR)
import xcoresdk_python as x  # noqa: E402

SRC = "rokae_xcoresdk/getEndTorque (direct, read-only)"


def _vals(v):
    """PyTypeVectorDouble / list / tuple → list[float]"""
    if hasattr(v, "get"):
        return [float(t) for t in v.get()]
    if hasattr(v, "content"):
        return [float(t) for t in v.content()]
    return [float(t) for t in v]


def make_buffers():
    """SDK 的输出参数是 PyTypeVectorDouble; 老版本可能只吃 list —— 两种都准备好。"""
    try:
        return (x.PyTypeVectorDouble(), x.PyTypeVectorDouble(),
                x.PyTypeVectorDouble(), x.PyTypeVectorDouble()), "PyTypeVectorDouble"
    except Exception:                                                                    # noqa: BLE001
        return ([], [], [], []), "list"


def read_force(fc, ref, bufs):
    """一次只读: 返回 (fx, fy, fz, tx, ty, tz, extra) 或抛异常。

    getEndTorque 的 4 个输出参数 = (joint_torque_measured, external_torque_measured,
    cart_torque, cart_force); cart_force 是 [X, Y, Z] N, cart_torque 是 [X, Y, Z] Nm。
    """
    jtm, etm, ctq, cfo = bufs
    ec = {}
    fc.getEndTorque(ref, jtm, etm, ctq, cfo, ec)
    err = None
    try:
        if isinstance(ec, dict):
            err = ec.get("code") or ec.get("err") or (ec if ec else None)
        elif ec:
            err = ec
    except Exception:                                                                    # noqa: BLE001
        err = None
    if err:
        raise RuntimeError("getEndTorque 报错: %r" % (err,))
    f = _vals(cfo)
    t = _vals(ctq)
    if len(f) < 3:
        raise RuntimeError("cart_force 只有 %d 个分量 (期望 3): %r" % (len(f), f))
    tx, ty, tz = (t + [0.0, 0.0, 0.0])[:3]
    return float(f[0]), float(f[1]), float(f[2]), tx, ty, tz, {"joint_torque_measured": _vals(jtm)[:8]}


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as g:
        json.dump(obj, g, ensure_ascii=False)
    os.replace(tmp, path)


def connect():
    r = x.xMateRobot()
    r.connectToRobot(ROBOT_IP)
    return r


def probe(robot):
    """只读探针: 把 forceControl()/getEndTorque 的真实行为打出来 (不猜 API)。"""
    print("robot =", type(robot).__name__)
    print("有 forceControl():", hasattr(robot, "forceControl"))
    fc = robot.forceControl()
    print("forceControl() →", type(fc).__name__, "· 方法:",
          [m for m in dir(fc) if not m.startswith("_")][:14])
    for name in ("world", "base", "tool"):
        ref = getattr(x.FrameType, name, None)
        if ref is None:
            print("  FrameType.%s 不存在" % name)
            continue
        bufs, how = make_buffers()
        t0 = time.time()
        try:
            fx, fy, fz, tx, ty, tz, extra = read_force(fc, ref, bufs)
            print("  %-5s → fx=%+.4f fy=%+.4f fz=%+.4f N · tx=%+.4f ty=%+.4f tz=%+.4f Nm"
                  " · %.0fms · 参数类型=%s" % (name, fx, fy, fz, tx, ty, tz, (time.time() - t0) * 1000, how))
        except Exception as e:                                                           # noqa: BLE001
            print("  %-5s → 失败 %s: %s (%.0fms)" % (name, type(e).__name__, str(e)[:160],
                                                     (time.time() - t0) * 1000))
    try:
        print("powerState =", robot.powerState({}))
    except Exception as e:                                                               # noqa: BLE001
        print("powerState 读失败:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=10.0, help="采样率 Hz (默认 10; SDK 会话是共享资源)")
    ap.add_argument("--secs", type=float, default=0.0, help="持续秒数 (默认 0 = 一直跑)")
    ap.add_argument("--out", default=os.path.join(SDK_DIR, "ft_out"))
    ap.add_argument("--frame", default="world", choices=("world", "base", "flange", "tool"),
                    help="力的参考系; 侧向力(基座系 +x 插入轴)只认 world/base")
    ap.add_argument("--probe", action="store_true", help="只探一次 API 实况就退出 (不落盘)")
    a = ap.parse_args()

    if a.frame not in ("world", "base"):
        print("⛔ 参考系 %s 下「侧向力 = hypot(fy,fz)」没有物理意义 (插入轴是基座 +x)。"
              " 要绕开这个限制请先改口径, 不要用 tool 系硬算。" % a.frame, file=sys.stderr)
        return 2

    os.makedirs(a.out, exist_ok=True)
    latest = os.path.join(a.out, "latest.json")
    day = time.strftime("%Y%m%d")
    path = os.path.join(a.out, "ft_direct_%s.jsonl" % day)
    ref = getattr(x.FrameType, a.frame)

    robot = None
    try:
        robot = connect()
    except Exception as e:                                                               # noqa: BLE001
        msg = "连接控制器 %s 失败: %s: %s" % (ROBOT_IP, type(e).__name__, str(e)[:200])
        print("[ft] ⛔ " + msg, flush=True)
        print("[ft] 排查: ip -br addr 看产线网卡(192.168.23.x)在不在位; ping %s; 控制器是否上电"
              % ROBOT_IP, flush=True)
        # 落一条 err 真值 (带 ts, 不带 fx/fy/fz) ⇒ ar_aoi_bus 会把"未接"的原因原样报到信号分析 meta 里
        os.makedirs(a.out, exist_ok=True)
        rec = {"ts": round(time.time(), 4),
               "t": time.strftime("%Y-%m-%d %H:%M:%S"), "frame": a.frame, "src": SRC,
               "ip": ROBOT_IP, "err": msg}
        write_atomic(latest, rec)
        return 3
    print("[ft] 控制器 %s 已连接 · 参考系 %s · 输出 %s" % (ROBOT_IP, a.frame, path), flush=True)
    fc = robot.forceControl()
    if a.probe:
        probe(robot)
        try:
            robot.disconnect()
        except Exception:                                                                # noqa: BLE001
            pass
        return 0

    bufs, _how = make_buffers()
    period = 1.0 / max(a.rate, 0.5)
    n = errs = 0
    t0 = time.time()
    next_t = t0
    f = open(path, "a", buffering=1)
    last_err = None
    try:
        while a.secs <= 0 or time.time() - t0 < a.secs:
            next_t += period
            ts = time.time()
            rec = {"ts": round(ts, 4),
                   "t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) + (".%03d" % int(ts * 1000 % 1000)),
                   "frame": a.frame, "src": SRC, "ip": ROBOT_IP}
            try:
                fx, fy, fz, tx, ty, tz, extra = read_force(fc, ref, bufs)
                if not all(math.isfinite(v) for v in (fx, fy, fz, tx, ty, tz)):
                    raise RuntimeError("读数含 NaN/Inf")
                rec.update({"fx": round(fx, 4), "fy": round(fy, 4), "fz": round(fz, 4),
                            "tx": round(tx, 4), "ty": round(ty, 4), "tz": round(tz, 4),
                            "lateral_N": round(math.hypot(fy, fz), 4), "n_err": errs})
                n += 1
                last_err = None
            except Exception as e:                                                       # noqa: BLE001
                errs += 1
                last_err = "%s: %s" % (type(e).__name__, str(e)[:160])
                rec.update({"err": last_err, "n_err": errs})     # 取不到就明写 err, 不写 0
                if errs in (1, 10) or errs % 100 == 0:
                    print("[ft] 读失败 #%d: %s" % (errs, last_err), flush=True)
            f.write(json.dumps(rec) + "\n")
            write_atomic(latest, rec)
            if n and n % int(max(a.rate, 1) * 10) == 0:
                print("[ft] %d 帧 · 失败 %d · fx=%.3f fy=%.3f fz=%.3f N"
                      % (n, errs, rec.get("fx", float("nan")), rec.get("fy", float("nan")),
                         rec.get("fz", float("nan"))), flush=True)
            sl = next_t - time.time()
            if sl > 0:
                time.sleep(sl)
            else:
                next_t = time.time()
    finally:
        f.close()
        try:
            robot.disconnect()
        except Exception:                                                                # noqa: BLE001
            pass
    print("[ft] 结束: %d 帧 · 失败 %d · 最后错误 %s" % (n, errs, last_err), flush=True)
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
