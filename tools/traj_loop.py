#!/usr/bin/env python3
"""traj_loop.py — 215 点回放循环驱动 (2026-11-15 老倪: "先循环操作 215 个点")

只做一件事: 反复驱动 8797 的 /api/arm/step_traj 走完 215 点 → reset → 再走。
不起 GUI、不加载 L3/L4 模型 ⇒ 不占显存, 可与 L5/L2 并行。

安全:
  · 授权唯一依据 tools/ctl_auth.py (与 8793 页面同一份), 未授权就停着等, 不重发
  · ZMAX_TRAJ_DRY=1 只演练
  · Ctrl+C / SIGTERM → 停驱动 (不紧急停止; 要停在 8797 /api/arm/stop)

取证: zmax_data/ss_live/traj_loop.json (轮次/游标/每轮耗时/累计)
用法: ZMAX_TRAJ_LOOP=1 ZMAX_TRAJ_SPEED=40 ./gui-venv311/bin/python tools/traj_loop.py
"""
from __future__ import annotations
import json, os, signal, sys, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
OUT = os.path.join(REPO, "zmax_data", "ss_live", "traj_loop.json")

_stop = False


def _sig(sig, frm):                                                    # noqa: ANN001
    global _stop
    _stop = True
    print("\n[traj_loop] 收到信号 %s → 停止驱动 (臂停在原位; 要急停在 8797 /api/arm/stop)" % sig, flush=True)


def main() -> int:
    os.environ.setdefault("ZMAX_TRAJ_LOOP", "1")
    from lerobot.policies.left_right.state_space.real_traj_flow import RealTrajFlow, auth_label

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    flow = RealTrajFlow(
        chunk=int(os.environ.get("ZMAX_TRAJ_CHUNK") or 1),
        speed=float(os.environ.get("ZMAX_TRAJ_SPEED") or 20),
        dwell_ms=int(os.environ.get("ZMAX_TRAJ_DWELL_MS") or 120),
        dry=os.environ.get("ZMAX_TRAJ_DRY") == "1",
    )
    print("[traj_loop] 轨迹 %d 点 · 每轮 chunk=%d · speed=%.0f%% · %s"
          % (flow.total, flow.chunk, flow.speed, "演练" if flow.dry else "真机"), flush=True)
    print("[traj_loop] 授权: %s" % auth_label(), flush=True)

    t_round = time.time()
    last_round = 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    while not _stop:
        try:
            flow.tick()
        except Exception as e:                                          # noqa: BLE001
            print("[traj_loop] tick 异常(不中断循环): %s: %s" % (type(e).__name__, str(e)[:120]), flush=True)
        if flow.rounds != last_round:                                   # 轮次变了
            last_round = flow.rounds
            dur = time.time() - t_round
            t_round = time.time()
            print("[traj_loop] ✅ 完成第 %d 轮 · 用时 %.1f min · %s"
                  % (last_round, dur / 60.0, flow.last_msg), flush=True)
        try:
            json.dump({"ts": time.time(), "phase": flow.phase, "cursor": flow.cursor,
                       "total": flow.total, "rounds": flow.rounds, "loop": flow.loop,
                       "dry": flow.dry, "speed": flow.speed, "chunk": flow.chunk,
                       "last_msg": flow.last_msg, "auth": auth_label(),
                       "round_started": t_round, "stopped": _stop},
                      open(OUT + ".tmp", "w"), ensure_ascii=False)
            os.replace(OUT + ".tmp", OUT)
        except Exception:                                               # noqa: BLE001
            pass
        time.sleep(1.0)

    print("[traj_loop] 已停止驱动 · 共完成 %d 轮" % flow.rounds, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
