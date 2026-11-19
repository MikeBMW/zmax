#!/usr/bin/env python3
"""整轮 215 点: 重建 cmd(带 quats, flow 1x) → 复位游标 → 下发起跑。只做前置与下发, 判据另跑。

用法: python3 tools/run_215_flow.py            # 真跑
      python3 tools/run_215_flow.py --dry      # 只写 cmd 不跑
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CMD = os.path.join(ROOT, "zmax_data/rokae_sdk/traj_step_cmd.json")


def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


def build():
    fr = json.load(open(os.path.join(ROOT, "tools/web/real_traj_joints.json")))["frames"]
    grip = json.load(open(os.path.join(ROOT, "tools/web/real_traj_grip.json"))).get("grip") or []
    adj = json.load(open(os.path.join(ROOT, "tools/web/traj_adj.json"))).get("points") or {}
    n = len(fr)
    frames = []
    for i, f in enumerate(fr):
        j = list(f["j"])
        a = adj.get(str(i)) or {}
        for k, v in enumerate(a.get("j_new_rad") or []):     # j_new_rad 是 6 元素 list
            j[k] = float(v)
        frames.append(j)
    quats0 = [list(map(float, f["q"])) for f in fr]
    # 🔴 执行器只认 cmd["quats"] (arm_step_traj.py:641 spec.get("quats"));
    #    写成 quats0 不报错但 flow v2 会退回纯关节口径 (轴/滚转两列全 0, 实测 32 块/464s)。
    cmd = {"frames": frames, "quats": quats0, "quats0": quats0, "t": [float(f["t"]) for f in fr],
           "grip": grip,                        # 执行器吃 list[{i,act,hold_ms}], 与 8797 写出的同构
           "start": 0, "n": n, "speed": 100.0, "dwell_ms": 120,
           "speed_mode": "flow", "flow_scale": 1.0,
           "adj_points": sorted(int(k) for k in adj.keys()),
           "src": "real_traj_joints.json", "ts": time.time()}
    json.dump(cmd, open(CMD, "w"), ensure_ascii=False)
    return cmd


def main() -> int:
    cmd = build()
    print("[cmd] n=%d quats=%d adj=%s grip=%s flow_scale=%s"
          % (cmd["n"], len(cmd["quats"]), cmd["adj_points"],
             [g["i"] for g in cmd["grip"]], cmd["flow_scale"]), flush=True)
    if "--dry" in sys.argv:
        return 0
    print("[reset]", post("http://127.0.0.1:8797/api/arm/step_traj", {"reset": True}), flush=True)
    log = os.path.join(ROOT, "zmax_data/rokae_sdk/traj_step_flow_full_%s.log" % time.strftime("%m%d_%H%M"))
    open("/tmp/flow_log_path", "w").write(log)
    fh = open(log, "w")
    p = subprocess.Popen(["bash", os.path.join(ROOT, "tools/rokae_sdk_run.sh"),
                          "--script", "arm_step_traj.py"], stdout=fh, stderr=subprocess.STDOUT,
                         cwd=ROOT, start_new_session=True)
    print("[run] pid=%d log=%s" % (p.pid, log), flush=True)
    br = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "tools/flow_state_bridge.py"),
                           log, str(p.pid), "0"], cwd=ROOT, start_new_session=True,
                          stdout=open("/tmp/flow_bridge.out", "w"), stderr=subprocess.STDOUT)
    print("[bridge] pid=%d" % br.pid, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
