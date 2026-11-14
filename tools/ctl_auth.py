#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ctl_auth.py — 「真动授权」的**单一唯一依据**(文件), 8793 工位总览与 L2 执行器共用。

为什么要有这个文件 (2026-09-29 老倪现场):
  「http://10.163.146.78:8793/station 我都取消授权了，手臂怎么还在动」
  根因两条, 都是**授权只活在 8793 进程的内存里**造成的:
    ① 其它会动臂的路径(GUI 原子技能 / 脚本 / 自动流程 / AOI 伺服)直接把命令写进
       ~/zmax/zmax_data/l2_cmd.fifo, 完全不经过 8793 的授权检查 ⇒ 授权对它们形同虚设;
    ② 执行器(l2_daemon)在下发前也不校验授权 ⇒ 点下授权后**排队的动作**会在
       VL 慢层等 300s 之后才真正下发, 那时人早就点了「撤销」—— 表现就是"取消了授权还在动"。

形态 (文件 ~/zmax/zmax_data/ctl_auth.json, 原子写):
  {until, since, window, epoch, ip, note, revoked_at, events:[{t,on,ip,note}]}
  · armed = (until > now)   —— 到期自动失效, 不需要任何人操作
  · epoch —— 单调递增: 每次**授权**或**撤销**都 +1。命令签发时把 epoch 带上;
    执行器下发前(以及等慢层期间)比对 epoch ⇒ 撤销前签发的命令一律作废, **在途/排队也能拦**。
"""
import json
import os
import time

PATH = os.path.expanduser(os.environ.get("ZMAX_CTL_AUTH", "~/zmax/zmax_data/ctl_auth.json"))
DEFAULT_WINDOW = float(os.environ.get("ZMAX_CTL_WINDOW", "1800"))  # 授权默认有效期(秒) — 2026-11-13 老倪: 半小时
# ↑ 2026-09-30 老倪现场定: 5 分钟 → **10 分钟**。理由: 号位技能是两阶段(先到正上方再下降),
#   慢速档一个阶段就走 22~40s, 两次技能连不上窗口就到期 ⇒ 阶段2 被"真动授权未开"拦下中止,
#   现场表现是"点了不动"。10 分钟仍然自动失效(人走开不会一直armed), 但够连做几套动作。
#   临时改回: 环境变量 ZMAX_CTL_WINDOW=300 或改这里的数字(已 armed 的窗口在 ctl_auth 文件里)。
_MAX_EVENTS = 40


def _read():
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:                                                   # noqa: BLE001
        return {}


def _write(d):
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, PATH)
    except Exception:                                                   # noqa: BLE001
        pass


def info():
    """当前授权状态(页面/执行器都读它)。

    两种形态:
      mode="window" (默认) —— until = since + window, 到点自动失效, 不接受任何"人为续期";
      mode="debug"          —— 调试档: 无时间限制(until=0, left_s=None), 只由 revoke 结束。
    老倪 2026-11-14:「授权时间前端改成可选: 30 分钟 / 调试(无时间限制)」。
    """
    d = _read()
    now = time.time()
    until = float(d.get("until") or 0)
    mode = str(d.get("mode") or "window")
    revoked = float(d.get("revoked_at") or 0)
    debug = (mode == "debug" and revoked <= 0)
    return {
        "mode": mode,
        "debug": debug,
        "armed": debug or (until > now),
        "until": until,
        "left_s": None if debug else max(0.0, round(until - now, 1)),
        "since": float(d.get("since") or 0),
        "window": 0.0 if debug else float(d.get("window") or DEFAULT_WINDOW),
        "epoch": int(d.get("epoch") or 0),
        "ip": d.get("ip") or "",
        "note": d.get("note") or "",
        "revoked_at": float(d.get("revoked_at") or 0),
        "events": (d.get("events") or [])[-12:],
        "path": PATH,
    }


def epoch():
    return int(_read().get("epoch") or 0)


def _event(d, on, ip, note):
    ev = d.get("events") or []
    ev.append({"t": time.time(), "on": bool(on), "ip": ip or "", "note": (note or "")[:80]})
    d["events"] = ev[-_MAX_EVENTS:]


def grant(ip="", note="", window=None, mode="window"):
    """授权真动。每次授权 epoch+1(旧命令随之作废)。

    mode="window" ⇒ 定时授权(window 缺省 1800s);
    mode="debug"  ⇒ 调试档, 无时间限制(until=0, 只有 revoke 能结束)。
    """
    d = _read()
    now = time.time()
    if str(mode) == "debug":
        d["mode"] = "debug"
        d["window"] = 0.0
        d["until"] = 0.0
    else:
        d["mode"] = "window"
        d["window"] = float(window or d.get("window") or DEFAULT_WINDOW)
        d["until"] = now + d["window"]
    d["since"] = now
    d["epoch"] = int(d.get("epoch") or 0) + 1
    d["ip"] = ip or ""
    d["note"] = (note or "")[:80]
    d["revoked_at"] = 0
    _event(d, True, ip, note or "授权")
    _write(d)
    return info()


def revoke(ip="", note="", bump=True):
    """撤销授权: 立即失效 + epoch+1 ⇒ 已签发未下发的命令全部作废(在途也能拦)。"""
    d = _read()
    d["until"] = 0
    if bump:
        d["epoch"] = int(d.get("epoch") or 0) + 1
    d["revoked_at"] = time.time()
    d["ip"] = ip or d.get("ip") or ""
    d["note"] = (note or "")[:80]
    _event(d, False, ip, note or "撤销")
    _write(d)
    return info()


def check(cmd_epoch=None, ignore_always_allow=False):
    """执行器下发前调用。返回 (ok, why)。

    · 未授权/已过期 ⇒ 拒发;
    · cmd_epoch 比当前 epoch 旧 ⇒ 这条命令是**撤销之前**签发的 ⇒ 拒发(在途/排队也能拦)。
    """
    st = info()
    if st.get("debug") and st["armed"]:
        return True, "已授权(调试·无限) · epoch=%s · ip=%s" % (st["epoch"], st["ip"] or "-")
    if not st["armed"]:
        _why = "真动授权未开(现场安全): 先在工位总览 8793 点『🔓 授权真动』并二次确认"
        if st["revoked_at"] and (time.time() - st["revoked_at"]) < 3600:
            _why = "真动授权已被撤销(%s 前 · ip=%s) ⇒ 拒发" % (
                time.strftime("%H:%M:%S", time.localtime(st["revoked_at"])), st["ip"] or "-")
        return False, _why
    if cmd_epoch is not None:
        try:
            if int(cmd_epoch) < st["epoch"]:
                return False, ("该命令签发于授权撤销/更换之前(命令 epoch=%s < 当前 %s) ⇒ 拒发"
                               % (cmd_epoch, st["epoch"]))
        except Exception:                                               # noqa: BLE001
            pass
    return True, "已授权 · 剩 %.0fs · epoch=%s · ip=%s" % (st["left_s"], st["epoch"], st["ip"] or "-")


if __name__ == "__main__":                                              # 命令行自检
    import sys
    _a = sys.argv[1] if len(sys.argv) > 1 else "info"
    if _a == "on":
        print(json.dumps(grant(ip="cli", note="cli"), ensure_ascii=False, indent=1))
    elif _a in ("on-debug", "debug"):
        print(json.dumps(grant(ip="cli", note="cli-调试档", mode="debug"),
                         ensure_ascii=False, indent=1))
    elif _a in ("on-30", "30"):
        print(json.dumps(grant(ip="cli", note="cli-30分钟", window=1800),
                         ensure_ascii=False, indent=1))
    elif _a == "off":
        print(json.dumps(revoke(ip="cli", note="cli"), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(info(), ensure_ascii=False, indent=1))
        print("check() =>", check())
