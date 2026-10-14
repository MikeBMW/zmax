#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订阅 zmax/ss_torque, 打印**标识信息** (任务/场景/产品质数/主参数) —— 给"输出 topic 看到"取证。

用法: venvs/dds-venv/bin/python tools/dds_sub_torque_identity.py [--n 3] [--raw]
"""
import argparse
import json
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax/dds")
from zmax_node import Node                                                          # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3, help="收几条")
    ap.add_argument("--seconds", type=float, default=14.0)
    ap.add_argument("--raw", action="store_true", help="原样打印完整 identity_json")
    a = ap.parse_args()

    n = Node("torque_identity_probe", domain=0)
    n.sub("ss_torque")
    got, t0 = [], time.time()
    while time.time() - t0 < a.seconds and len(got) < a.n:
        s = n.take("ss_torque", timeout=1.5)
        if s:
            got.extend(s)
    if not got:
        print("❌ 没收到 ss_torque 样本 (发布器/守护没跑? 检查 systemctl status zmax-torque-bus zmax-dds-ss)")
        return 2
    print("收到 %d 条 · 话题 zmax/ss_torque · type zmax::SSDrivingTorque" % len(got))
    for i, m in enumerate(got[: a.n]):
        print("\n── 第 %d 条 (ts=%.3f · 帧龄 %.2fs) ──" % (i + 1, float(m.ts), time.time() - float(m.ts)))
        print("  任务      : %s · %s" % (m.task_id, m.task_name))
        print("  产品      : %s · 产品质数 %s" % (m.product, m.product_prime))
        print("  主参数 M  : %s   (+ 载荷 metric_dim=%s)" % (m.m_scale, m.metric_dim))
        print("  场景      : %s · node %s · ‖T‖=%.3f %s · H=%.3f %s"
              % (m.scene, m.node, float(sum(v * v for v in m.torque)) ** 0.5, m.unit, float(m.health), m.status))
        if a.raw:
            print("  identity_json: %s" % m.identity_json)
        else:
            try:
                idb = json.loads(m.identity_json)
                print("  标识块    : 任务 %s / 场景 %s(%s) / 站点 %s / 产品 %s 版本段 %s / 主参数 M=%s dim=%s mode=%s / 工艺 %d 项"
                      % (idb.get("task_id"), idb.get("scene"), idb.get("scene_name"), idb.get("site"),
                         idb.get("product_name"), idb.get("version_segment"),
                         (idb.get("main_params") or {}).get("metric_M"),
                         (idb.get("main_params") or {}).get("metric_dim"),
                         (idb.get("main_params") or {}).get("metric_mode"),
                         len((idb.get("main_params") or {}).get("task_params") or {})))
            except Exception as e:                                                  # noqa: BLE001
                print("  identity_json 解析失败: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
