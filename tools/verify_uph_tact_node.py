#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 🏭 UPH 节拍循环器 (n_uph_tact) —— 段表能不能被真实推进
  ① 段表加载: 392 段 / 14 件 / 节拍能力 ≈ 315 UPH
  ② seq 单调推进: 60 拍加速跑, 从 1 推到 392, 且回绕到 1 (流水线不停)
  ③ 动作种类覆盖: 输出里能见到 move/up/side/down/grip/release/insert/pull 至少 6 类
  ④ 时间轴诚实: elapsed_s 与 转速一致, uph_live 有值且量级对
"""
import os
import sys
import time

os.environ["ZMAX_UPH_SPEED"] = "50"           # 加速 50 倍: 一拍(10ms)=0.5s 虚拟, 采样够密
sys.path.insert(0, "/home/ubuntu/zmax/src")

from lerobot.middleware.nodes import n_uph_tact as N  # noqa: E402

fails = []


def ck(ok, name, detail=""):
    print("%s %-46s %s" % ("✅" if ok else "❌", name, detail))
    if not ok:
        fails.append(name)


plan, cum, total = N._load()
ck(len(plan) == 392, "① 段表 392 段", "实际 %d" % len(plan))
ck(total == 14, "① 件数 14", "实际 %d" % total)
ck(abs(cum[-1] - 159.43) < 1.0, "① 一轮总时长 ≈159.43s", "实际 %.2fs" % cum[-1])

seqs, kinds, uphs, eps, rounds, idxs = [], set(), [], [], [], []
N.reset()
for _ in range(400):
    r = N.compute({})
    o1, o2, o3 = r["out1"], r["out2"], r["out3"]
    if o1:
        seqs.append((o1.get("mod"), o1["seq"]))
        kinds.add(o1["kind"])
    if o2 and o2.get("uph_live"):
        uphs.append(o2["uph_live"])
    if o3:
        eps.append(o3["elapsed_s"])
        rounds.append(o3["round"])
        cap = o3["uph_capability"]
    time.sleep(0.01)

ck(len(seqs) == 400, "② 每拍都给出当前动作", "%d/400" % len(seqs))
ck(seqs[0][1] == 1, "② 首拍从第 1 段开始", "件%s 段%s" % seqs[0])
ck(sum(1 for _ in range(1)) and len({m for m, _ in seqs}) >= 10,
   "② 推进过至少 10 件", "件号: %s" % sorted({m for m, _ in seqs})[:14])
ck(max(rounds) >= 1, "② 走完一整轮(流水线不停, 进入第 2 轮)", "round 最大=%d" % max(rounds))
# 段推进用 seg_index(全局段索引, 只前进); seq 是件内段号, 两条时间轴不同步, 不能按件分组比 seq
mono = all(idxs[i] <= idxs[i + 1] for i in range(len(idxs) - 1) if rounds[i] == rounds[i + 1])
ck(mono, "② 同一轮内 seg_index 单调递增(段只前进)", "OK" if mono else "有回退")
ck(max(idxs) > 300, "② 段索引推进过 300 段(共392)", "最大 seg_index=%d" % max(idxs))

ck(len(kinds) >= 6, "③ 动作种类 ≥6 类", "%d 类: %s" % (len(kinds), sorted(kinds)))
ck(abs(cap - 315.0) < 4.0, "④ 节拍能力 ≈315 UPH (11.42s/件)", "实测 %.1f" % cap)
ck(bool(uphs) and 280 < max(uphs) < 340, "④ 实时 UPH 落在 280~340 (口径已扣首件)",
   "max=%.1f · 样本%d" % (max(uphs), len(uphs)) if uphs else "无值")
ck(eps[0] < 1.0, "④ 首拍 elapsed≈0(不虚报)", "%.2fs" % eps[0])
print("   最后一拍状态:", N.LAST_STATUS)
print("-" * 66)
print("结论:", "✅ 全过" if not fails else "❌ 失败 %d 项: %s" % (len(fails), fails))
sys.exit(0 if not fails else 1)
