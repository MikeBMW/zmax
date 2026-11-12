#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""site_inventory.py — 现场"程序/驱动"清单器 (2026-11-12)

和 site_snapshot.py 互补: 那个抄"数据"(位姿/相机/AR帧), 这个抄"程序与驱动口径"——
· 本机与 550C 上在跑什么服务、监听哪些端口、入口脚本是什么、代码是哪一版
· Orin 侧 ROS2 有哪些节点/话题/类型、驱动包版本 (只读, 不装包不下发)

为什么: 断网离场后要能回答"当时现场跑的是哪套程序、机器人驱动什么口径",
否则离线复现出来的东西和现场对不上, 进化就是白跑。

用法:
  python tools/site_inventory.py --out ~/zmax_data/site_snapshot/<ts> --hosts local,intel,orin
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time

shell_quote = shlex.quote

TS = time.strftime("%Y%m%d_%H%M%S")

SSH = {
    "intel": ["ssh", "-o", "BatchMode=yes", "intel"],
    "orin": ["ssh", "-o", "BatchMode=yes", "orin-lan"],          # 产线口优先 (orin 别名走 wifi, 断网就没了)
}

PORTS = [
    ("8791", "相机流/pose"), ("8793", "执行腿/建图"), ("8797", "AR 页"),
    ("8802", "AR 渲染"), ("10082", "AOI 金手指"), ("10083", "AOI 表面"),
    ("20082", "AOI 本地镜像金手指"), ("20083", "AOI 本地镜像表面"),
]


def run(cmd, t=25, host="local"):
    """(rc, stdout) — host=local 直接跑, 否则经 ssh 只读执行。"""
    if host == "local":
        full, sh = cmd, True
    else:                                   # 远端用一条 shell 串, 免去 list+shell=False 的引号坑
        full, sh = " ".join(SSH[host]) + " " + shell_quote(cmd), True
    try:
        p = subprocess.run(full, capture_output=True, text=True, timeout=t, shell=sh)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:                                              # noqa: BLE001
        return 127, "ERR %s" % e


def units(host: str) -> dict:
    rc, out = run("systemctl list-units --type=service --all --no-legend --plain "
                  "| grep -iE 'zmax|aoi|evo|hermes|ros|dds' | head -40", host=host)
    rows = []
    for ln in out.splitlines():
        f = ln.split()
        if len(f) >= 4 and f[0].endswith(".service"):
            rows.append({"unit": f[0], "load": f[1], "active": f[2], "sub": f[3]})
    return {"rc": rc, "units": rows}


def exec_lines(host: str, names: list[str]) -> dict:
    out = {}
    for u in names:
        rc, o = run("systemctl cat %s 2>/dev/null | grep -E '^ExecStart|^WorkingDirectory' | head -3" % u, host=host)
        if rc == 0 and o.strip():
            out[u] = o.strip().splitlines()
    return out


def tunnels(host: str) -> dict:
    """ssh -L / socat 转发: AOI 10082 在本机只有隧道在听, 真目标在别处 —— 断网后必须知道这层。"""
    rc, out = run("ps -eo pid,etime,cmd 2>/dev/null | grep -E -- '-L [0-9]|socat' | grep -v grep | head -12", host=host)
    return {"rc": rc, "rows": [l.strip()[:400] for l in out.splitlines() if l.strip()]}


def ports(host: str) -> dict:
    rc, out = run("ss -ltnp 2>/dev/null | awk 'NR>1{print $4, $6}' | head -40", host=host)
    return {"rc": rc, "listeners": [l.strip() for l in out.splitlines() if l.strip()][:40]}


def code_fingerprint(host: str, root: str) -> dict:
    rc, out = run("cd %s 2>/dev/null && git rev-parse HEAD 2>/dev/null; git log -1 --format='%%ci %%s' 2>/dev/null" % root, host=host)
    files = ["src/lerobot/policies/left_right/state_space/su2.py",
             "src/lerobot/middleware/nodes/impl/ss_obs.py",
             "src/lerobot/engineering/exec/daemon.py",
             "tools/evolve_ar_world.py", "tools/zmax_evolve_intel.py"]
    rc2, md5 = run("cd %s 2>/dev/null && md5sum %s 2>/dev/null" % (root, " ".join(files)), host=host)
    return {"code": out.strip().splitlines()[:2], "md5": [l.strip() for l in md5.splitlines() if l.strip()]}


def orin_driver() -> dict:
    """Orin 侧只读口径: 节点/话题/类型 + 驱动包版本。"""
    q = ("source /opt/ros/humble/setup.bash 2>/dev/null; "
         "timeout 8 ros2 topic list 2>/dev/null | head -60; echo '---TYPES---'; "
         "for t in /robot/tcp_pose /robot/gripper_state /joint_states; do "
         "timeout 5 ros2 topic info $t 2>/dev/null | head -4; done; echo '---NODES---'; "
         "timeout 8 ros2 node list 2>/dev/null | head -30; echo '---PKGS---'; "
         "ls /opt/ros/humble/share 2>/dev/null | grep -iE 'rokae|xcore|rm_|zmax' | head -10")
    rc, out = run(q, t=60, host="orin")
    return {"rc": rc, "raw": out[:8000]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--hosts", default="local,intel,orin")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    hosts = [h.strip() for h in a.hosts.split(",") if h.strip()]
    inv = {"ts": TS, "hosts": {}}

    for h in hosts:
        if h == "local":
            root = "/home/ubuntu/zmax"
        elif h == "intel":
            root = "~/zmax_map"        # 550C 在役树 (不是 ~/zmax)
        else:
            root = "~/zmax"            # orin 上未必有仓库, 允许失败
        blk = {"units": units(h), "ports": ports(h), "tunnels": tunnels(h)}
        names = [u["unit"] for u in blk["units"]["units"]][:18]
        blk["exec"] = exec_lines(h, names) if h != "orin" else {}
        blk["code"] = code_fingerprint(h, root)
        if h == "orin":
            blk["driver"] = orin_driver()
        inv["hosts"][h] = blk

    # 端口可达性 (本地口径, 现场断网前的事实)
    reach = {}
    for p, desc in PORTS:
        rc, _ = run("timeout 2 bash -c '</dev/tcp/127.0.0.1/%s' 2>/dev/null" % p)
        reach[p] = {"desc": desc, "listening": rc == 0}
    inv["local_ports_reach"] = reach

    path = os.path.join(a.out, "inventory.json")
    json.dump(inv, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("写:", path, os.path.getsize(path), "字节")
    for h, b in inv["hosts"].items():
        print("  %-6s 服务 %2d · 监听 %2d · 代码 %s" % (
            h, len(b["units"]["units"]), len(b["ports"]["listeners"]),
            (b["code"]["code"][0][:8] if b["code"]["code"] else "?")))
    print("  本机端口:", {k: ("通" if v["listening"] else "不通") for k, v in reach.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
