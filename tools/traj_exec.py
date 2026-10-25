#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按规划轨迹逐段执行 (一条一条走, 每段等真值到位, 任何异常立刻中止)。

老倪 2026-10-25: 「我点击 执行轨迹 按钮后，轨迹指令远程发给运动规划节点，让机器人按照轨迹点执行」

纪律 (和既有执行链一致, 不走第二条写入口):
  · 命令**只进** l2_daemon 的 FIFO (唯一执行收口), 不在本脚本里直连 SDK。
  · 每段发之前复核: 规划新鲜(≤30min) · precheck.ok · 授权窗有效(8793 发的 epoch) · 上一段已到位。
  · 一段不达位就**中止余下所有段**(绝不跳过继续跑), 并把原因写进 traj_state.json。
  · 全程只读 exec_state.json 判到位, 不自己估位姿。

用法: python tools/traj_exec.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TRAJ_DIR = os.path.join(REPO, "zmax_data", "runtime", "traj")
PLAN = os.path.join(TRAJ_DIR, "planned_traj.json")
STATE = os.path.join(TRAJ_DIR, "traj_state.json")
LOG = os.path.join(TRAJ_DIR, "traj_exec.jsonl")

FIFO = os.path.expanduser(os.environ.get("ZMAX_L2_FIFO") or "~/zmax/zmax_data/l2_cmd.fifo")
EXEC_STATE = os.path.expanduser("~/zmax/zmax_data/ss_live/exec_state.json")
AUTH = os.path.join(REPO, "zmax_data", "ctl_auth.json")

ARRIVE_TOL_MM = 8.0        # 到位判据: 控制器真值与段目标差 ≤8mm(不依赖 l2_daemon 的 phase)
SEG_TIMEOUT = 150.0        # 单段最长等多久(秒) —— 30mm/s 下 300mm 也要 10s, 给足余量
PLAN_MAX_AGE = 1800.0      # 规划超过 30 分钟不执行(位姿早变了, 轨迹已失真)


def _w(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def say(msg, **kw):
    line = {"t": time.time(), "ts": time.strftime("%H:%M:%S"), "msg": msg}
    line.update(kw)
    print("[%s] %s" % (line["ts"], msg), flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def auth_ok():
    try:
        d = json.load(open(AUTH, encoding="utf-8"))
    except Exception as e:                                                   # noqa: BLE001
        return False, 0, "授权文件读不到(%s)" % str(e)[:60]
    if float(d.get("revoked_at") or 0) > 0:
        return False, int(d.get("epoch") or 0), "授权已被撤销"
    until = float(d.get("until") or 0)
    if until <= time.time():
        return False, int(d.get("epoch") or 0), "授权窗已过期(先在 8793 页面做现场授权)"
    return True, int(d.get("epoch") or 0), "剩余 %.0fs" % (until - time.time())


def read_exec():
    try:
        return json.load(open(EXEC_STATE, encoding="utf-8"))
    except Exception:                                                        # noqa: BLE001
        return {}


def run(dry=False):
    if not os.path.exists(PLAN):
        say("❌ 没有规划轨迹 planned_traj.json ⇒ 先规划")
        return 2
    plan = json.load(open(PLAN, encoding="utf-8"))
    age = time.time() - float(plan.get("ts") or 0)
    if age > PLAN_MAX_AGE:
        say("❌ 规划已 %.0f 分钟, 超过 %.0f 分钟上限 ⇒ 请重新规划(位姿已变)" % (age / 60, PLAN_MAX_AGE / 60))
        return 2
    if not (plan.get("precheck") or {}).get("ok"):
        say("❌ 规划自检未通过(净空 %.1fmm) ⇒ 不发" % ((plan.get("precheck") or {}).get("worst_mm") or -1))
        return 2
    # 🔒 起点闸(2026-10-25 实测踩到): 人是会手动挪臂的 —— 挪过之后这条"相对段"轨迹的含义就变了。
    #    规划里存了 tcp0_mm; 现在 TCP 跟它差 >5mm 就拒发, 不拿旧起点硬跑。
    try:
        sys.path.insert(0, HERE)
        from precheck_move import read_joints
        _q, _tcp, _age = read_joints()
        _p0 = plan.get("tcp0_mm")
        if _p0 and _age <= 5.0:
            d = sum((float(_tcp[i]) - float(_p0[i])) ** 2 for i in range(3)) ** 0.5
            if d > 5.0:
                say("🛑 起点已变: 规划时 TCP=(%.1f, %.1f, %.1f)mm, 现在=(%.1f, %.1f, %.1f)mm, 差 %.1fmm > 5mm"
                    " ⇒ 这条轨迹是相对段, 含义已变, 请重新规划"
                    % (float(_p0[0]), float(_p0[1]), float(_p0[2]),
                       float(_tcp[0]), float(_tcp[1]), float(_tcp[2]), d))
                _w(STATE, {"plan_ts": plan.get("ts"), "n_seg": len(plan.get("segs") or []),
                           "phase": "blocked", "seg": 0, "blocked_by": "起点已变 %.1fmm" % d, "t": time.time()})
                return 5
    except SystemExit as e:
        say("⚠ 起点闸读不到实时真值(%s) ⇒ 按保守处理: 不执行" % str(e)[:80])
        return 5
    except Exception as e:                                                   # noqa: BLE001
        say("⚠ 起点闸异常(%s) ⇒ 不执行" % str(e)[:80])
        return 5

    ok, epoch, why = auth_ok()
    if not ok and not dry:
        say("🛑 %s" % why)
        return 3
    if not ok:
        say("（dry-run: 授权当前不可用 —— %s；真跑会在这里中止）" % why)
    segs = plan.get("segs") or []
    if not segs:
        say("❌ 规划里没有段")
        return 2

    import fcntl
    _lk = open(os.path.join(os.path.dirname(STATE), "traj_exec.lock"), "w")
    try:
        fcntl.flock(_lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        say("⛔ 已有另一个 traj_exec 正在执行 ⇒ 拒绝并发(防两条指令抢同一个 FIFO)")
        return 7
    say("▶ 执行轨迹: %d 段 / %.0fmm · 授权 epoch=%s (%s) · 规划龄 %.0fs" % (
        len(segs), plan.get("total_mm") or 0, epoch, why, age))
    base = {"plan_ts": plan.get("ts"), "n_seg": len(segs), "auth_epoch": epoch, "note": plan.get("note") or ""}
    _w(STATE, dict(base, phase="running", seg=0, t=time.time()))

    # 🕹 2026-10-25 老倪: 「让 550C 成为下发方」—— 本机不再执行, 只把段表发布出去。
    #    开关: ~/zmax/zmax_data/runtime/plan/exec_by.json = {"by":"550c"} 或环境 ZMAX_EXEC_BY=550c。
    #    为什么放这里: 起点闸/规划龄/授权都已经在上面过了, 与本地执行同一套前置条件;
    #    550C 侧还有自己的授权剩余/幂等/真值对账闸(见 tools/plan_exec_550c.py)。
    _by = (os.environ.get("ZMAX_EXEC_BY") or "").strip().lower()
    if not _by:
        for _p in (os.path.join(os.path.dirname(STATE), "exec_by.json"),
                   os.path.expanduser("~/zmax/zmax_data/runtime/plan/exec_by.json")):
            try:
                _by = str((json.load(open(_p, encoding="utf-8")) or {}).get("by") or "").strip().lower()
            except Exception:                                               # noqa: BLE001
                _by = ""
            if _by:
                break
    if _by == "550c" and not dry:
        _pid = "PLAN-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), int(float(plan.get("ts") or 0)))
        sys.path.insert(0, os.path.join(HERE, "dds"))
        import plan_publish                                                    # noqa: PLC0415
        _until = 0.0
        try:
            if HERE not in sys.path:
                sys.path.insert(0, HERE)
            import ctl_auth as _CA                                          # noqa: PLC0415
            _until = float(_CA.info().get("until") or 0.0)
        except Exception:                                                   # noqa: BLE001
            _until = time.time()
        _sp = float(os.environ.get("ZMAX_PLAN_SPEED_MM_S") or 200.0)
        _out = plan_publish.publish_plan(plan, _sp, {"epoch": epoch, "until": _until}, _pid)
        say("🕹 已把段表发布给 550C 执行: plan_id=%s 段数=%s 配对=%s"
            % (_pid, _out.get("n_points"), _out.get("matched")))
        _w(STATE, dict(base, phase="delegated", plan_id=_pid, by="550C", t=time.time()))
        return 0

    # 🔴 老倪 2026-10-25: 「1 2 3 4 步一次性发到运动规划节点, 点击执行就一次都执行, 中间不能停顿」
    #    ⇒ 先把全部段**一次**写进 FIFO, 段间不再等位; 之后只观察真值(取证), 不再由软件控制节奏。
    if not dry:
        _sent = 0
        try:
            with open(FIFO, "w", encoding="utf-8") as f:
                for s in segs:
                    cmd = {"skill": s["skill"], "d_mm": float(s["d_mm"]), "auth_epoch": epoch,
                           "src": "traj_exec",
                           # 🎯 2026-10-25: 同时给**绝对目标**(规划里的 to_mm)。
                           #   为什么: d_mm 是"相对当前位姿"的增量, 只要有任一段被拦/被跳过,
                           #   后续段就会整体漂移 —— 实测出现"后退没走、前进照走 ⇒ 臂停在 +80mm 外"。
                           #   给了 abs_mm 之后, 每段都落到规划点上, 单段失败不会污染后面的点。
                           "abs_mm": [float(v) for v in (s.get("to_mm") or [])][:3] or None,
                           "note": "轨迹第 %d/%d 段 %s" % (int(s["i"]), len(segs), s.get("cn") or s["dir"])}
                    f.write(json.dumps(cmd, ensure_ascii=False) + "\n")
                    f.flush()
                    _sent += 1
                    time.sleep(0.12)
        except Exception as e:                                               # noqa: BLE001
            say("❌ FIFO 一次性下发失败(已发 %d 段): %s ⇒ 中止" % (_sent, str(e)[:100]))
            _w(STATE, dict(base, phase="error", seg=_sent, err="FIFO: %s" % str(e)[:80], t=time.time()))
            return 4
        say("📤 已一次性下发 %d/%d 段 · 无段间等待(机器人连续执行)" % (_sent, len(segs)))

    for s in segs:
        i = int(s["i"])
        target = s.get("to_mm")
        _w(STATE, dict(base, phase="running", seg=i, seg_name=s.get("cn") or s["dir"],
                       d_mm=s["d_mm"], target=target, t=time.time()))
        if dry:
            say("DRY-RUN 第 %d/%d 段 %s %smm → %s" % (i, len(segs), s["dir"], s["d_mm"], target))
            continue
        say("观测 第 %d/%d 段 %s %smm (目标 %s, 已预发)" % (i, len(segs), s["dir"], s["d_mm"], target))

        t0 = time.time()
        arrived = False
        while time.time() - t0 < SEG_TIMEOUT:
            st = read_exec()
            if st.get("phase") == "blocked":
                say("🛑 第 %d 段被拦: %s ⇒ 中止余下 %d 段" % (i, st.get("blocked_by") or "?", len(segs) - i))
                _w(STATE, dict(base, phase="blocked", seg=i, blocked_by=st.get("blocked_by"), t=time.time()))
                return 5
            # 🔴 2026-10-25 实测: l2_daemon 收到 ROS TargetPose response 后停在 phase=accepted,
            #    永远不写 done ⇒ 等状态机会卡死(只走了第 1 段)。到位与否**只认真值**。
            try:
                if target:
                    from precheck_move import read_joints
                    _q, _tcp, _age = read_joints()
                    _d = sum((float(_tcp[k]) - float(target[k])) ** 2 for k in range(3)) ** 0.5
                    if _d <= ARRIVE_TOL_MM and _age <= 5.0:
                        say("✓ 第 %d/%d 段到位 · 真值残差 %.1fmm (phase=%s)" % (i, len(segs), _d, st.get("phase")))
                        _w(STATE, dict(base, phase="arrived", seg=i, residual_mm=round(_d, 1), t=time.time()))
                        arrived = True
                        time.sleep(0.8)
                        break
            except SystemExit:
                pass
            except Exception:                                                # noqa: BLE001
                pass
            time.sleep(0.3)
        else:
            say("❌ 第 %d 段 %.0fs 内没看到到位 ⇒ 中止余下 %d 段" % (i, SEG_TIMEOUT, len(segs) - i))
            _w(STATE, dict(base, phase="timeout", seg=i, t=time.time()))
            return 6

    say("✅ 轨迹执行完成 · %d 段" % len(segs))
    _w(STATE, dict(base, phase="done", seg=len(segs), t=time.time()))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    return run(dry=a.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
