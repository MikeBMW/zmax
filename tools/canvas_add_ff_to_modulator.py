#!/usr/bin/env python3
"""加一条连线: ⚡ 前馈加速器(out1) → 🧭 动作调制器(in9)

老倪 2026-10-15: 「前馈加速器的输出，要连到动作调制器；前馈加速器是 L2 功能一个状态预测模型，
使用 MLP 实现；这个预测的状态，进入动作调制器，变成规范动作」

真源口径 (代码):
  parallel.py:3   快通道 (前馈加速器 = 左脑 MLP): obs → 建议动作 u_ff (权重 30%)
  parallel.py:20  输出汇合到 S3 认知决策层: 调度器 u = w_ff·u_ff + (1−w_ff)·u_fb
  cognition.py:240 def decide(self, u_ff, u_fb, contact_p, residual) → u (规范动作, 按阶段限速+否决)

纪律 (state-space-canvas-engineering):
  · 只加连线, 不动任何现有节点坐标;
  · 写盘只走 flows.save_canvas (自动校验 + 备份);
  · 验收 = 旧连线逐条比对不变 + 渲染级 node/link items 复核。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.getcwd(), "src"))
sys.path.insert(0, os.path.join(os.getcwd(), "tools"))

from lerobot.engineering import flows                                    # noqa: E402

F, T = "ssff", "sssched"
FPORT, TPORT = "out1", "in9"
LID = "lk_ff_sched"
LABEL = "⚡ 前馈建议 u_ff (MLP 快通道) → 动作调制器融合 · 按阶段限速 ⇒ 规范动作"


def key(n):
    return json.dumps(n, ensure_ascii=False, sort_keys=True)


def main():
    d, _errs = flows.load_canvas(validate=True)      # (data, errors)
    nodes = {n["id"]: n for n in d["nodes"]}
    links = d.get("links") or []
    before = sorted(key(l) for l in links)
    fn, tn = nodes.get(F), nodes.get(T)
    assert fn and tn, "找不到节点 %s / %s" % (F, T)
    assert FPORT in (fn.get("outputs") or []), "%s 没有出口 %s" % (F, FPORT)
    ins = list(tn.get("inputs") or [])
    assert TPORT not in ins, "%s 已有 %s" % (T, TPORT)
    dup = [l for l in links if l.get("f") == F and l.get("t") == T]
    assert not dup, "已存在 %s→%s 的线: %s" % (F, T, dup)
    new = {"id": LID, "f": F, "f_port": FPORT, "t": T, "t_port": TPORT, "label": LABEL}
    # 端口补齐 (目标多一个入口) + 记录原 inputs (便于回溯)
    tn.setdefault("params", {}).setdefault("_inputs_before_ff_sched", list(ins))
    tn["inputs"] = ins + [TPORT]
    links.append(new)
    d["links"] = links
    p, bak = flows.save_canvas(d, reason="ff_to_modulator")
    print("✅ 已写盘 %s\n   备份 %s" % (p, bak))
    # 回读复核: 旧连线逐条不变 + 新线在
    d2, _e2 = flows.load_canvas(validate=True)
    l2 = d2.get("links") or []
    after = sorted(key({k: v for k, v in l.items() if k != "new"} ) for l in l2
                   if l.get("id") != LID)
    assert after == before, "旧连线发生变化! %d → %d" % (len(before), len(after))
    hit = [l for l in l2 if l.get("id") == LID]
    assert hit and hit[0]["t_port"] == TPORT, "新线没落盘"
    print("   旧连线 %d 条逐条一致 ✅ · 新线 %s ✅ (节点 %d · 连线 %d)"
          % (len(before), LID, len(d2["nodes"]), len(l2)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
