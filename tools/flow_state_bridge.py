"""把直连容器的 flow 跑批进度桥进 8797 的 traj_step_state.json。

为什么需要: 这轮 1x 慢速是绕过 8797 直接起 rokae_sdk_run.sh 跑的, 服务端的 state 文件没人更新
⇒ 页面 /api/arm/step_traj/status 还是上一轮的 running=false/cursor=22, 状态行显示「未开始」。
本脚本每 2s 从跑批日志里取最后一条 progress 写进 state, 让页面的游标/MT 甘特光标跟上。
8797 的 _step_traj_status 是从 state['log'] 里读最后一条 progress 的, 所以 log 必须指向真实日志。
日志 60s 不再增长就退出(跑批结束或异常)。
"""
import json
import os
import sys
import time

REPO = "/home/ubuntu/zmax"
LOG = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "zmax_data/rokae_sdk/traj_step_flow_x1.log")
STATE = os.path.join(REPO, "zmax_data/rokae_sdk/traj_step_state.json")
PID = int(sys.argv[2]) if len(sys.argv) > 2 else 0
OFF = int(sys.argv[3]) if len(sys.argv) > 3 else 0      # 续跑时日志里的 progress 是"本轮内"计数, 要加起点偏移
IDLE_EXIT_S = 900.0     # 12 点块在 1x 慢速下要 2 分钟才出一条 progress, 60s 判定会误退出(实测断在 #57)


def last_progress(path):
    """返回 (已走点数, 累计运动秒)。累计秒用来当 elapsed 基准 ——
    不能用文件 ctime: 文件在被追加时 ctime 一直在变(实测 elapsed 只有 18s 而实际已跑 5 分钟)。"""
    k, tot = 0, 0.0
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for ln in f:
                ln = ln.strip()
                if not ln.startswith('{"progress"'):
                    continue
                try:
                    d = json.loads(ln)
                except Exception:  # noqa: BLE001
                    continue
                k = int(d.get("progress") or k)
                tot += float((d.get("step") or {}).get("secs") or 0.0)
    except FileNotFoundError:
        return None, 0.0
    return k, tot


def main() -> int:
    # t0 用日志创建时刻, 否则页面 elapsed 会从桥启动那一刻算(实测显示 11s 而实际已跑 5 分钟)
    try:
        t0 = os.path.getctime(LOG)
    except OSError:
        t0 = time.time()
    last_size, last_move = -1, time.time()
    while True:
        try:
            st = os.stat(LOG).st_size
        except FileNotFoundError:
            return 2
        if st != last_size:
            last_size, last_move = st, time.time()
        k, tot = last_progress(LOG) or (0, 0.0)
        t0 = time.time() - tot
        alive = True
        if PID:
            try:
                os.kill(PID, 0)
            except OSError:
                alive = False
        kk = k + OFF
        json.dump({"running": bool(alive and kk < 215), "t0": t0, "n": 215, "dry": False,
                   "start": OFF, "total": 215, "cursor": kk, "pid": PID, "done": kk,
                   "log": LOG, "grip_sent": [], "src": "flow_x1 bridge"},
                  open(STATE, "w"), ensure_ascii=False)
        print("done=%d alive=%s" % (k, alive), flush=True)
        if not alive or k >= 215 or (time.time() - last_move) > IDLE_EXIT_S:
            return 0
        time.sleep(2.0)


if __name__ == "__main__":
    raise SystemExit(main())
