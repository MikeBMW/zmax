#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧪 ws-bus 跨网 DDS 判据 (老倪 2026-10-25 B 方案验收)

四段真判据, 每段都有实测数字, 不看"看着通了":
  ① web 层来回      : 直连中继 pub → 订阅端收到 (不经 DDS)
  ② 本地 DDS → web  : 真 DDS 的 HardwareState 结构 → dict (字段名/值对账)
  ③ web → 本地 DDS  : dict → DeployCommand 结构, 本机 DDS 订阅端真收到
  ④ 缺号统计        : seq 连续率 (latest-wins 下允许丢旧帧, 但 seq 必须单调)

用法:
  python3 tools/dds/verify_ws_bus.py                 # 本机自测 (自己起中继 :39099)
  python3 tools/dds/verify_ws_bus.py --url wss://datadrive.world/ws/bus/ --token xxx   # 用真中继
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ws_bridge import Bridge, WSClient, to_dict, from_dict      # noqa: E402
from ws_bus_relay import Relay                                  # noqa: E402

OK, NG = "✅", "❌"
res = []


def ck(name, cond, detail=""):
    res.append(bool(cond))
    print("  %s %s%s" % (OK if cond else NG, name, (" — %s" % detail) if detail else ""))
    return cond


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--token", default=os.environ.get("ZMAX_WS_BUS_TOKEN", "t"))
    ap.add_argument("--port", type=int, default=39099)
    a = ap.parse_args()
    url = a.url or ("ws://127.0.0.1:%d/" % a.port)
    if not a.url:
        threading.Thread(target=Relay(token=a.token, verbose=False).serve,
                         args=("127.0.0.1", a.port), daemon=True).start()
        time.sleep(0.5)

    print("=" * 78)
    print("🧪 ws-bus 判据 (中继 %s)" % url)
    print("=" * 78)

    # ── ① web 层来回 (不带 DDS) ──
    print("① web 层来回")
    got1 = []
    c1 = WSClient(url, a.token, on_msg=lambda m: got1.append(m) if m.get("op") == "msg" else None,
                  verbose=False)
    c1.sub(["probe_ch"])
    threading.Thread(target=c1.run_forever, daemon=True).start()
    time.sleep(1.0)
    for i in range(5):
        c1.pub("probe_ch", {"i": i}, i, time.time(), "verify")
        time.sleep(0.08)
    time.sleep(1.0)
    ck("发 5 收 %d" % len(got1), len(got1) >= 4)

    # ── ② 真 DDS 结构 → dict ──
    print("② 本地 DDS → web (IDL→dict 对账)")
    from zmax_node import TOPICS, Node                          # noqa: E402
    node = Node("verify_ws_bus")
    hs = TOPICS["hw_state"](node="550C", role="边缘端(550C)", backend="xpu",
                            device_name="Intel Arc B390", ts=time.time(),
                            util_pct=42.0, mem_used_mb=1234.0, mem_total_mb=30000.0,
                            temp_c=50.0, power_w=35.0, cpu_cores=16)
    got2 = []
    c2 = WSClient(url, a.token, on_msg=lambda m: got2.append(m) if m.get("op") == "msg"
                  and m.get("ch") == "hw_state" else None, verbose=False)
    c2.sub(["hw_state"])
    threading.Thread(target=c2.run_forever, daemon=True).start()
    time.sleep(1.0)
    # 走同一个 Bridge 的上行路径 (真 DDS 取样 → dict → web)
    br = Bridge("edge", url, a.token, ["hw_state"], [], "550C", verbose=False)
    threading.Thread(target=br.ws.run_forever, daemon=True).start()   # 必须真连上, 否则 send 全返回 False
    time.sleep(1.2)
    for _ in range(6):
        node.send("hw_state", hs)
        br.pump_up()
        time.sleep(0.2)
    time.sleep(1.0)
    if ck("收到 %d 条 hw_state" % len(got2), len(got2) >= 1):
        p = got2[-1]["payload"]
        ck("字段 node=%r" % p.get("node"), p.get("node") == "550C")
        ck("字段 device_name=%r" % p.get("device_name"), p.get("device_name") == "Intel Arc B390")
        ck("字段 util_pct=%r" % p.get("util_pct"), abs(float(p.get("util_pct", -1)) - 42.0) < 1e-6)
        ck("按键齐全 (%d 字段)" % len(p), "ts" in p and "cpu_cores" in p)

    # ── ③ web → 真 DDS 结构 ──
    print("③ web → 本地 DDS (dict→IDL 落地)")
    br2 = Bridge("edge", url, a.token, [], ["deploy_cmd"], "4060", verbose=False)
    threading.Thread(target=br2.ws.run_forever, daemon=True).start()
    time.sleep(1.2)
    reader = Node("verify_ws_bus_sub")
    reader.sub("deploy_cmd")
    payload = {"issuer": "verify", "layer": "L2", "artifact": "runs/probe",
               "action": "promote", "note": "ws-bus 判据", "ts": time.time()}
    c3 = WSClient(url, a.token, verbose=False)
    threading.Thread(target=c3.run_forever, daemon=True).start()
    time.sleep(0.8)
    for i in range(3):
        c3.pub("deploy_cmd", payload, i, time.time(), "verify")
        time.sleep(0.25)
    got3 = reader.take("deploy_cmd", 4.0)
    if ck("本机 DDS 收到 %d 条 deploy_cmd" % len(got3), len(got3) >= 1):
        m = got3[-1]
        ck("issuer=%r action=%r" % (m.issuer, m.action), m.issuer == "verify" and m.action == "promote")
        ck("note 原文到达", m.note == "ws-bus 判据")

    # ── ④ seq 单调 / 缺号 ──
    print("④ seq 单调与缺号")
    seqs = [m.get("seq") for m in got2 if isinstance(m.get("seq"), int)]
    mono = all(b >= x for x, b in zip(seqs, seqs[1:])) if len(seqs) >= 2 else True
    ck("hw_state seq 单调 (%s)" % seqs[-3:], mono)
    ck("缺号数 %d" % sum(v for v in br2.gap.values()), sum(v for v in br2.gap.values()) == 0)

    # ── IDL 往返 (不丢字段) ──
    print("⑤ IDL 往返不丢字段")
    back = from_dict(TOPICS["hw_state"], to_dict(hs))
    ck("to_dict→from_dict 一致", to_dict(back).get("device_name") == "Intel Arc B390"
       and abs(float(back.util_pct) - 42.0) < 1e-6)

    print("=" * 78)
    bad = res.count(False)
    print("=== %s (失败 %d 项 / 共 %d 项) ===" % ("全过" if bad == 0 else "有失败", bad, len(res)))
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
