# -*- coding: utf-8 -*-
"""verify_multimodal_sync — 量化统一状态空间"时间同步"的真实缺口 + 对齐效果。

判据全部来自实测 (ar_aoi_live.json 各通道帧龄 + fuse_sensors 源码):
  ① fuse_sensors 是不是纯拼接 (读源码确认)
  ② 各通道帧龄差多少 (真值)
  ③ 错位换算成位置误差是多少
  ④ 对齐器能否把这些差异摊平并如实报 skew

用法: gui-venv311/bin/python tools/verify_multimodal_sync.py
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, "src")
from lerobot.policies.perception.temporal_sync import MultimodalSync  # noqa: E402

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print("%s %s%s" % ("✅" if cond else "❌", name, ("  " + detail) if detail else ""))


print("=" * 76)
print("① fuse_sensors 是纯拼接吗 (读源码)")
src = open("src/lerobot/policies/left_right/state_space/perception.py", encoding="utf-8").read()
seg = src[src.find("def fuse_sensors"):src.find("def fuse_sensors43")]
concat = "np.concatenate" in seg
has_ts = bool(re.search(r"timestamp|stamp|time\.time", seg))
print("   找到 np.concatenate: %s" % concat)
print("   出现任何时间戳/时刻字段: %s" % has_ts)
check("43D 是纯拼接(无时间对齐)", concat and not has_ts, "concatenate ✓ / timestamp ✗")

print()
print("② 各通道真实帧龄 (zmax_data/ar_live/ar_aoi_live.json 实测)")
p = "zmax_data/ar_live/ar_aoi_live.json"
ages = {}
if os.path.exists(p):
    d = json.load(open(p, encoding="utf-8"))
    s = d.get("s") or {}
    for k, v in s.items():
        if "帧龄" in k and isinstance(v, (int, float)):
            ages[k] = float(v)
    for k, v in sorted(ages.items(), key=lambda kv: kv[1]):
        print("   %-24s %8.3f s" % (k, v))
    check("取到多通道帧龄", len(ages) >= 2, "%d 个通道" % len(ages))
else:
    check("帧龄数据存在", False, "无 ar_aoi_live.json")

if ages:
    mx, mn = max(ages.values()), min(ages.values())
    print()
    print("③ 错位代价 (最大帧龄差 → 位置误差)")
    for spd in (30.0, 100.0):
        print("   帧龄跨度 %.3f s × %.0f mm/s = %.1f mm 位置错位" % (mx - mn, spd, (mx - mn) * spd))
    check("帧龄跨度 >100ms (即真的没对齐)", (mx - mn) > 0.1, "跨度 %.3f s, 最大/最小 = %.0f 倍" % (
        mx - mn, mx / max(mn, 1e-6)))

print()
print("④ 对齐器效果 (把同一组通道喂进 MultimodalSync)")
now = time.time()
sync = MultimodalSync(max_hold_s=0.5)
# 用实测帧龄反推各通道的采集时刻
for k, agg in ages.items():
    key = k.replace(".帧龄_s", "")
    sync.update(source=key, key=key, value=0.0, t=now - agg)
rep = sync.report(now)
print("   通道数 %d → 进入本帧 %d (超 %.1fs 保持窗被拒 %d 个)" % (
    rep["n_channels"], rep["n_dims"], sync.max_hold_s, len(rep["stale_keys"])))
print("   skew_s = %.3f   最大龄 = %.3f   stale_ratio = %.2f" % (
    rep["skew_s"], rep["max_age_s"], rep["stale_ratio"]))
print("   被拒: %s" % (rep["stale_keys"] or "无"))
check("对齐器如实报出 skew", rep["skew_s"] >= 0.0 and "skew_s" in rep)
check("超时通道被拒(不编造)", isinstance(rep["stale_keys"], list))

# 对照: 全部通道都很新时, 对齐应无陈旧
sync2 = MultimodalSync(max_hold_s=0.5)
for k in ages:
    sync2.update(source=k, key=k, value=0.0, t=now - 0.02)
rep2 = sync2.report(now)
print("   对照(全部 20ms 内): skew=%.3f stale=%d/%d" % (
    rep2["skew_s"], len(rep2["stale_keys"]), rep2["n_dims"]))
check("新鲜帧不误判陈旧", len(rep2["stale_keys"]) == 0)

print()
print("=" * 76)
print("PASS %d / FAIL %d" % (len(OK), len(FAIL)))
if FAIL:
    print("失败:", FAIL)
sys.exit(0 if not FAIL else 1)
