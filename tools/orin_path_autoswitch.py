#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orin_path_autoswitch.py — 产线网卡在不在位, 自动选到 Orin 的路 (直连 / ECS 跳板)

老倪 2026-10-25: 「一会我会连上 USB 网卡, 你连入局域网」

两条路:
  direct : enx00e04c0c32a0 拿到 192.168.23.50 ⇒ `orin-lan`(tashan@192.168.23.66:22) 一跳直达,
           不再经 ECS, 延迟最低, 也不受 ECS 反向隧道抖动影响。
  ecs    : 没有产线地址 ⇒ `orin-ecs`(ECS:22 → 127.0.0.1:22022 = Orin 反向隧道)。

判据(硬): 直连 = `ping -c1 -W1 192.168.23.66` 通 **且** 本机有 192.168.23.0/24 地址。
只切一次(写 mode 进状态文件), 不来回抖: 直连断了要连续 2 轮才退回 ECS。

受影响 unit (都注入同一个 drop-in): 见 UNITS; 每个 unit 的端口参数从原 ExecStart 保留。
用法: python3 tools/orin_path_autoswitch.py [--force direct|ecs] [--dry-run]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

STATE = "/home/ubuntu/zmax/zmax_data/runtime/orin_path.json"
DROP_DIRS = "/etc/systemd/system"

# unit → (端口等待用的端口列表, 该 unit 的 ssh 参数, 目标 host 占位 __H__)
UNITS = {
    # 2026-10-25: 全部端口改成**一条连接**带走。原来是 5 个 unit 各一条 ssh, 断一条就各重启各的,
    # 十几秒内对 ECS 打十几次重连 ⇒ 撞 MaxStartups ⇒ "Connection closed by remote host" 随机踢
    # ⇒ 越踢越重启, 最后 0 端口在监听(看着像 Orin 死了, 实际 39053/39061 都活着)。
    "zmax-orin-legs": (
        "39071 19061 8792 18792 18800 18822 10082 10083 8816 8812",
        "-N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=10 "
        "-o ServerAliveCountMax=3 -o TCPKeepAlive=yes -o ConnectTimeout=20 "
        "-L 127.0.0.1:39071:127.0.0.1:39061 -L 127.0.0.1:19061:127.0.0.1:39061 "
        "-L 127.0.0.1:8792:127.0.0.1:8792 -L 127.0.0.1:18792:127.0.0.1:8792 "
        "-L 127.0.0.1:18800:192.168.23.70:8800 -L 127.0.0.1:18822:192.168.23.70:22 "
        "-L 127.0.0.1:10082:192.168.23.23:10082 -L 127.0.0.1:10083:192.168.23.23:10083 "
        "-L 127.0.0.1:8816:192.168.23.70:8816 -L 127.0.0.1:8812:192.168.23.70:8812 __H__"),
}
HOST = {"direct": "orin-lan", "ecs": "orin-ecs"}


def sh(cmd, timeout=20):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def lan_addr():
    r = sh("ip -4 -br addr | grep 192.168.23. | head -1")
    return r.stdout.strip()


def orin_ping():
    return sh("ping -c1 -W1 192.168.23.66").returncode == 0


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:                                                          # noqa: BLE001
        return {}


def save_state(d):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def apply_mode(mode, dry=False):
    """把每个 unit 的 drop-in 重写成指定路由 + 等待端口释放; 变了才重启。"""
    changed = []
    for unit, (ports, args) in UNITS.items():
        body = ("[Service]\n"
                "ExecStartPre=/bin/bash /home/ubuntu/zmax/tools/wait_ports_free.sh %s\n"
                "ExecStart=\n"
                "ExecStart=/usr/bin/ssh %s\n" % (ports, args.replace("__H__", HOST[mode])))
        d = os.path.join(DROP_DIRS, unit + ".service.d")
        p = os.path.join(d, "override-route.conf")
        old = ""
        if os.path.isfile(p):
            old = open(p, encoding="utf-8").read()
        if old == body:
            continue
        changed.append(unit)
        if dry:
            continue
        sh("sudo mkdir -p %s" % d)
        tmp = "/tmp/ov_%s.conf" % unit
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        sh("sudo cp %s %s" % (tmp, p), timeout=30)
    if changed and not dry:
        sh("sudo systemctl daemon-reload", timeout=60)
        for u in changed:
            sh("sudo systemctl reset-failed %s >/dev/null 2>&1; sudo systemctl restart %s" % (u, u), timeout=60)
            time.sleep(1)
    return changed


def main():
    dry = "--dry-run" in sys.argv
    force = None
    if "--force" in sys.argv:
        force = sys.argv[sys.argv.index("--force") + 1]

    st = load_state()
    addr = lan_addr()
    ping = orin_ping()
    want = force or ("direct" if (addr and ping) else "ecs")

    # 防抖: 已直连时, 直连判据不满足要连续 2 轮才退回
    prev = st.get("mode")
    if not force and prev == "direct" and want == "ecs":
        miss = int(st.get("miss", 0)) + 1
        st["miss"] = miss
        if miss < 2:
            save_state(dict(st, t=time.time(), addr=addr, ping=ping, mode=prev,
                            note="直连判据不满足第 %d 轮, 暂不切换" % miss))
            print("保持直连 (第 %d 轮判据不满足)" % miss)
            return 0
    st["miss"] = 0

    changed = apply_mode(want, dry)
    st.update({"t": time.time(), "t_str": time.strftime("%Y-%m-%d %H:%M:%S"),
               "mode": want, "addr": addr, "ping": ping, "changed": changed, "dry": dry})
    save_state(st)
    print("路由=%s · 产线地址=%r · Orin ping=%s · 改动 unit=%s"
          % (want, addr, "通" if ping else "不通", changed or "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
