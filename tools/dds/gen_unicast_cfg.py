#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 生成 Cyclone DDS 单播配置 dds/cyclonedds_unicast.xml (按**本机实际地址**渲染)

为什么要有这个生成器 (2026-10-13 实测):
  · 本机 DDS 参与者原先不带配置 ⇒ 默认**多播发现**。本机有 lo / wlp0s20f3 / docker0,
    多播 discovery 可能挑错网卡; 更致命的是 DDS 进程**长时间常驻**后网卡/IP 变化
    (实测探针 participant 一直在往 **172.18.0.1** 和 239.255.0.1 发, 全部 retcode -1),
    ⇒ 本机自己都收不到 ⇒ 数据空间 10 个话题全黑灯。
  · 口径: 一律走**单播** (AllowMulticast=false + 显式 Peers), 127.0.0.1 恒列 —— 同机互见不靠多播。
  · IP 不要手改: 本脚本按 `ip -4 addr` 现读现渲染 (改机器/改网段后重跑一次即可)。

用法:
  python3 tools/dds/gen_unicast_cfg.py                 # 渲染到 dds/cyclonedds_unicast.xml
  python3 tools/dds/gen_unicast_cfg.py --check         # 只校验现值与现网是否一致(不写盘)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "dds", "cyclonedds_unicast.xml")

# 恒列: 本机回环 (同机四个 DDS 进程靠这条互见, 少一条就全黑)
ALWAYS = ["127.0.0.1"]
# 静态对端 (在场时可发现, 不在场静默无害): 备份端/产线协作端 · ECS 公网中转
STATIC = ["192.168.23.50", "39.102.211.79"]
# 明确排除的网卡 (docker/虚拟桥: 历史上正是它把 discovery 带偏)
SKIP_IF = ("docker", "br-", "veth", "virbr", "tun", "tap")

HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<!-- 📡 Cyclone DDS 单播配置 —— 由 tools/dds/gen_unicast_cfg.py 从本机实际地址生成, 勿手改 IP

生成时间: %(ts)s
本机地址: %(addrs)s

为什么必须单播 (2026-10-13 实测, 现场黑灯根因):
  · 默认多播发现 + 多网卡 ⇒ 挑错网卡; 常驻进程在 IP/网卡变化后 participant 不恢复
    (实测探针持续往 172.18.0.1 / 239.255.0.1 发, retcode -1) ⇒ 本机自己都收不到,
    数据空间 10 个话题全黑灯。
  · 修法(唯一有效): AllowMulticast=false + 显式 <Peers>; 127.0.0.1 恒列。
  · 实测对照(同机 pub→sub 跨进程): 带本配置 ⇒ 6/6 条到达; 不带 ⇒ 视网卡状态而定, 不可依赖。

★ 本版本实测不可用元素 (DDS_RETCODE_ERROR, 勿加回):
    ❌ <Interfaces><NetworkInterface name="auto"/></Interfaces>
    ❌ <General><Ports><Base>…</Base><Max>…</Max></Ports></General>
    ❌ <Internal><LeaseDuration>  ← 必须放 <Discovery> 下

使用: 服务单元 Environment=CYCLONEDDS_URI=file://%(out)s · 或脚本 --cfg dds/cyclonedds_unicast.xml
-->
<CycloneDDS xmlns="https://cdds.io/config">
  <Domain id="any">

    <General>
      <AllowMulticast>false</AllowMulticast>
    </General>

    <Discovery>
      <ParticipantIndex>auto</ParticipantIndex>
      <LeaseDuration>30s</LeaseDuration>
      <Peers>
%(peers)s
      </Peers>
    </Discovery>

    <Internal>
      <HeartbeatInterval>2s</HeartbeatInterval>
      <WriterLingerDuration>2s</WriterLingerDuration>
    </Internal>

  </Domain>
</CycloneDDS>
"""

PEER_NOTE = {
    "127.0.0.1": "本机回环 —— 同机探针/发布端/聚合器/流形扭矩靠这条互见 (必须留)",
}


def live_addrs() -> list:
    """现读本机非回环 IPv4 (排除 docker/虚拟网卡)。"""
    out = []
    try:
        r = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True, timeout=8)
        for ln in (r.stdout or "").splitlines():
            f = ln.split()
            if len(f) < 4:
                continue
            dev, cidr = f[1], f[3]
            if any(s in dev for s in SKIP_IF):
                continue
            ip = cidr.split("/")[0]
            if ip and ip not in out:
                out.append(ip)
    except Exception as e:                                                       # noqa: BLE001
        print("⚠️ 读网卡失败: %r" % (e,), file=sys.stderr)
    return out


def render() -> str:
    import datetime
    peers = []
    for ip in ALWAYS + live_addrs() + STATIC:
        if ip not in peers:
            peers.append(ip)
    body = []
    for ip in peers:
        note = PEER_NOTE.get(ip, "")
        if note:
            body.append('        <Peer address="%s"/>   <!-- %s -->' % (ip, note))
        else:
            body.append('        <Peer address="%s"/>' % ip)
    return HEAD % {"ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "addrs": ", ".join(live_addrs()) or "(无)",
                   "peers": "\n".join(body),
                   "out": OUT}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="不写盘, 只比对新渲染结果与现文件")
    a = ap.parse_args()
    new = render()
    old = ""
    if os.path.isfile(OUT):
        old = open(OUT, encoding="utf-8").read()
    # 时间戳行不参与比较
    norm = lambda s: "\n".join(l for l in s.splitlines() if "生成时间" not in l)     # noqa: E731
    if a.check:
        same = norm(new) == norm(old)
        print(json_dumps_check(same, old))
        return 0 if same else 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(new)
    print("✅ 写 %s (peers: %s)" % (OUT, ", ".join(live_addrs()) or "无"))
    return 0


def json_dumps_check(same, old):
    import json
    peers = [l.split('"')[1] for l in old.splitlines() if "<Peer address=" in l]
    return json.dumps({"一致": bool(same), "现值_peers": peers}, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
