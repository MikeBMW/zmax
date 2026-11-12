#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_state100.py — 100D 级联缓冲状态空间验收 (只报数值)

V1  段表: 覆盖 0:100 / 50 字段 / 新增 45 维 / 每字段有单位·来源·含义
V2  零回归: 同一份 55D 灌进去, 前 55 位逐位相同 (5 组随机)
V3  一致性: named 重组成 x 逐位相同
V4  几何锚: 段表抽 5 锚 (mm→m) 并写进对应区间
V5  UPH 模型: 串行 450 / 双工 900 / 瓶颈=flash; 反例 (机械臂太慢) 必须报瓶颈=robot 且够不到 900
V6  缓冲需求: 停机 60s、双工 CT 4s ⇒ N_need=16 (ceil(60/4)+1)
V7  派生量: fill/UPH/背压/全局暂停 口径唯一
V8  调度状态机: 7 个场景的意图序列必须与设计一致
V9  槽位位图: 16 槽 pack/unpack 往返 + 四态计数
V10 fail-closed: 未注册通道 / 维度不符 全抛错
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.policies.left_right.state_space.desktop_buffer_state100 import (   # noqa: E402
    DesktopBuffer100, ALL_FIELDS, BUF_FIELDS, STATE100_DIM, OBS55_DIM,
    anchors_from_segment_table, validate_layout, uph_model, pack_slots, unpack_slots,
    slot_counts, FLASH_IDLE, FLASH_RUNNING, FLASH_DONE, ROBOT_WAIT,
    SLOT_EMPTY, SLOT_UNPROC, SLOT_INFLIGHT, SLOT_DONE,
    ACT_PICK_INFEED, ACT_LOAD_FLASH, ACT_UNLOAD_FLASH, ACT_STORE_OUTFEED,
    ACT_RETRY_FLASH, ACT_PAUSE, ACT_THROTTLE,
)

PASS, FAIL = [], []


def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %-40s %s" % ("✅" if cond else "❌", name, detail))


def main() -> int:
    print("═" * 84)
    print("V1 段表 (%d 字段 / %d 维)" % (len(ALL_FIELDS), STATE100_DIM))
    validate_layout()
    no_meta = [f.name for f in ALL_FIELDS if not (f.unit and f.source and f.note)]
    new_dims = sum(f.dim for f in BUF_FIELDS)
    chk("V1 覆盖 0:100 首尾相接", ALL_FIELDS[0].start == 0 and ALL_FIELDS[-1].stop == STATE100_DIM,
        "0..%d / %d 段" % (ALL_FIELDS[-1].stop, len(ALL_FIELDS)))
    chk("V1 新增 45 维", new_dims == STATE100_DIM - OBS55_DIM, "%d 维 / %d 段" % (new_dims, len(BUF_FIELDS)))
    chk("V1 每字段有 单位/来源/含义", not no_meta, "缺: %s" % (no_meta or "无"))

    st = DesktopBuffer100()
    rng = np.random.default_rng(11)
    same = 0
    for _ in range(5):
        base = rng.normal(size=OBS55_DIM)
        x = st.fuse(obs55=base, buf={"infeed_count": 3, "outfeed_count": 1})
        same += int(np.array_equal(x[:OBS55_DIM], base))
    chk("V2 前 55 位逐位零回归", same == 5, "%d/5 组" % same)

    rebuilt = np.concatenate([st.named[f.name] for f in ALL_FIELDS])
    chk("V3 named 重组 == x", np.array_equal(rebuilt, x), "‖差‖=%.1e" % float(np.max(np.abs(rebuilt - x))))

    tab = os.path.join(ROOT, "docs", "5-玉衡-指标验收", "l2_300uph_closure_20261102.json")
    res = anchors_from_segment_table(tab) if os.path.exists(tab) else {"anchors": {}, "missing": ["(段表缺失)"]}
    a = res["anchors"]
    chk("V4 几何锚 5/5 装载", not res["missing"],
        "%s" % {k: tuple(round(v, 3) for v in val) for k, val in a.items()})
    x = st.fuse(obs55=np.zeros(OBS55_DIM), buf=dict(a))
    chk("V4 锚写入对应区间", all(np.allclose(st.get(k, x), v) for k, v in a.items()),
        "loader=%s" % np.round(st.get("loader_slot_xyz", x), 3))

    m_ok = uph_model(4.0, 2.0, 2.0, 0.0, 900.0)
    chk("V5 串行 UPH=450 (2+4+2=8s)", abs(m_ok["uph_serial"] - 450.0) < 0.6, "%.1f" % m_ok["uph_serial"])
    chk("V5 双工 UPH=900 (机器人 4s 全藏进 4s)", abs(m_ok["uph_duplex"] - 900.0) < 1.2, "%.1f" % m_ok["uph_duplex"])
    chk("V5 瓶颈=flash 且够到 900", m_ok["bottleneck"] == "flash" and m_ok["reach_target"],
        "bottleneck=%s overlap=%.2f" % (m_ok["bottleneck"], m_ok["overlap_ratio"]))
    m_trav = uph_model(4.0, 2.0, 2.0, 0.5, 900.0)
    chk("V5 加 0.5s 空走 ⇒ 800, 瓶颈转 robot", abs(m_trav["uph_duplex"] - 800.0) < 1.2
        and m_trav["bottleneck"] == "robot", "CT=%.2fs UPH=%.1f"
        % (m_trav["ct_duplex_s"], m_trav["uph_duplex"]))
    m_bad = uph_model(4.0, 3.0, 3.0, 0.5, 900.0)
    chk("V5 机械臂太慢 ⇒ 瓶颈=robot", m_bad["bottleneck"] == "robot" and not m_bad["reach_target"],
        "CT=%.1fs UPH=%.0f" % (m_bad["ct_duplex_s"], m_bad["uph_duplex"]))

    m_buf = uph_model(4.0, 2.0, 2.0, 0.0, 900.0, stall_max=60.0)
    chk("V6 停机 60s ⇒ N_need=16", m_buf["n_need_for_stall"] == 16, "%d 件" % m_buf["n_need_for_stall"])

    x = st.fuse(obs55=np.zeros(OBS55_DIM),
                buf={"infeed_count": 14, "outfeed_count": 8, "hi_watermark": 0.875,
                     "lo_watermark": 0.125, "cycle_time": 4.0, "flash_state": FLASH_RUNNING},
                N=16, M=8, t_flash=4.0)
    chk("V7 infeed_fill=14/16", abs(float(st.get("infeed_fill")[0]) - 0.875) < 1e-12,
        "%.4f" % float(st.get("infeed_fill")[0]))
    chk("V7 uph_actual=3600/4", abs(float(st.get("uph_actual")[0]) - 900.0) < 1e-9,
        "%.2f" % float(st.get("uph_actual")[0]))
    chk("V7 14/16 ≥ 高水位 ⇒ 背压=1", float(st.get("backpressure")[0]) == 1.0,
        "bp=%d" % int(st.get("backpressure")[0]))
    chk("V7 Outfeed 8/8 ⇒ 全局暂停=1", float(st.get("global_pause")[0]) == 1.0,
        "pause=%d" % int(st.get("global_pause")[0]))

    def sched(**kw):
        cfg = {"N": 16, "M": 8, "t_flash": 4.0}
        cfg.update({k: kw.pop(k) for k in list(kw) if k in ("N", "M", "t_flash")})
        st.fuse(obs55=np.zeros(OBS55_DIM), buf=kw, **cfg)
        return st.schedule()

    r = sched(flash_state=FLASH_DONE, outfeed_count=2, infeed_count=6)
    chk("V8 设备 DONE ⇒ 取出→放入", r["actions"] == [ACT_UNLOAD_FLASH, ACT_STORE_OUTFEED], str(r["actions"]))
    r = sched(flash_state=FLASH_IDLE, infeed_count=6, outfeed_count=2)
    chk("V8 设备 IDLE+有料 ⇒ 取件→送入", r["actions"] == [ACT_PICK_INFEED, ACT_LOAD_FLASH], str(r["actions"]))
    r = sched(flash_state=FLASH_RUNNING, outfeed_count=2, infeed_count=6)
    chk("V8 刷写中 ⇒ 伺候 Outfeed", r["actions"] == [ACT_STORE_OUTFEED], str(r["actions"]))
    r = sched(flash_state=FLASH_RUNNING, outfeed_count=2, retry_len=1)
    chk("V8 有重试 ⇒ 优先插队", r["actions"] == [ACT_RETRY_FLASH], str(r["actions"]))
    r = sched(flash_state=FLASH_RUNNING, outfeed_count=8)
    chk("V8 Outfeed 满 ⇒ 全局暂停", r["actions"] == [ACT_PAUSE], str(r["actions"]))
    r = sched(flash_state=FLASH_RUNNING, outfeed_count=2, infeed_count=14, hi_watermark=0.875)
    chk("V8 Infeed 高水位 ⇒ 追加背压", ACT_THROTTLE in r["actions"], str(r["actions"]))
    r = sched(flash_state=FLASH_RUNNING, outfeed_count=2, robot_state=ROBOT_WAIT)
    chk("V8 robot_wait 被点出", r["robot_wait"] is True and any("干等" in w for w in r["reason"]),
        "wait=%s" % r["robot_wait"])

    slots = [SLOT_UNPROC] * 6 + [SLOT_INFLIGHT] * 1 + [SLOT_DONE] * 2 + [SLOT_EMPTY] * 7
    mask = pack_slots(slots)
    back = unpack_slots(mask, 16)
    cnt = slot_counts(back)
    chk("V9 位图 16 槽往返一致", back == slots, "mask=0x%08x" % mask)
    chk("V9 四态计数正确", cnt == {"EMPTY": 7, "OCCUPIED_UNPROCESSED": 6,
                                "PROCESSING": 1, "OCCUPIED_PROCESSED": 2}, str(cnt))

    bad = 0
    for kwargs in ({"nope": 1.0}, {"infeed_count": [1, 2]}):
        try:
            st.fuse(obs55=np.zeros(OBS55_DIM), buf=kwargs)
        except (KeyError, ValueError):
            bad += 1
    chk("V10 未注册通道/维度不符 全拒", bad == 2, "%d/2 抛错" % bad)

    print("═" * 84)
    print("结果: PASS %d / FAIL %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项:", FAIL)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
