#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""记忆层状态 → 飞书 (在 550C 本机跑, 直接读本地热通道)

与 550A 版本的区别: 不 ssh, 直接读 /dev/shm/zmax_mem/watch.json。
每次刷新判据实测值; 判据不通就顶 ⚠️ 并给建议。无变化也发(用户要持续监控)。
"""
import json
import sys

PATH = "/dev/shm/zmax_mem/watch.json"


def main():
    try:
        with open(PATH) as f:
            w = json.load(f)
    except Exception as e:                                     # noqa: BLE001
        print("🧠 Z-MAX 记忆层 · 550C\n读取 %s 失败: %s: %s\n(查 systemctl status zmax-mem-watch)" % (
            PATH, type(e).__name__, e))
        return 0

    s = w.get("summary") or {}
    loop, l2, l3, l4, rec, mp, nr = (w.get(k) or {} for k in
                                     ("loop", "l2", "l3", "l4", "record", "map", "no_robot_cmd"))
    passes = sum(1 for x in (loop, l2, l3, l4, rec, mp, nr) if x.get("ok"))
    head = "🧠 Z-MAX 记忆层 · 550C · %s" % (s.get("t_str") or "")
    if not s.get("ok"):
        head = "⚠️ " + head + " (判据 %d/7, 失败: %s)" % (passes, ",".join(s.get("fails") or []))
    else:
        head += " · 判据 7/7 ✓"

    lines = [head,
             "节拍 %.1f UPH · tact %.2fs/件 · %s件/圈 · 圈墙钟 %ss · acc %ss%s" % (
                 float(l3.get("uph") or 0), float(l3.get("tact_s") or 0), l3.get("n_mods") or "?",
                 l3.get("wall_s"), l3.get("acc_s"),
                 "" if l3.get("wall_matches_acc") else " ⚠墙钟≠acc"),
             "L2 肌肉 %s 段 · %s 类 · kl2 %s (漂移 %s)" % (
                 l2.get("n_total"), l2.get("kinds"),
                 "已收敛" if l2.get("converged") else "学习中", l2.get("kl2_max_drift")),
             "L4 安全 big_jumps %s · overspeed %s · v_cap %s mm/s · travel %ss" % (
                 l4.get("big_jumps"), l4.get("overspeed"), l4.get("v_cap_mm_s"), l3.get("travel_s")),
             "记录 %s 帧(今日) · 帧龄 %ss · 图-位姿 skew %sms · 盘 %sGB" % (
                 rec.get("n_today"), rec.get("frame_age_s"), rec.get("skew_ms_p50"), rec.get("disk_gb")),
             "建图 %s%s · 零指令 %s" % (
                 "ready" if mp.get("ok") else "未就绪",
                 " (%s 点)" % mp.get("points") if mp.get("points") else "",
                 "✓ 无动作日志" if nr.get("ok") else "⚠ 有指令"),
             "回路 %sms/拍 · %s 节点 · %s" % (loop.get("cost_ms"), loop.get("n_ran"), loop.get("err") or "无错")]

    # 顺便报 48Hz 真机动作记录器 (有就报, 没有就明说)
    try:
        with open("/dev/shm/zmax_rec48/status.json") as f:
            r48 = json.load(f)
        lines.append("真机动作 48Hz: 位姿 %.1fHz · 关节 %.0fHz · 帧 %d · skew %.0fms · %s" % (
            float(r48.get("pose_hz") or 0), float(r48.get("joints_hz") or 0),
            int(r48.get("frames") or 0), float(r48.get("skew_p50_ms") or 0),
            "运动中" if r48.get("moving") else "静止"))
    except Exception:
        lines.append("真机动作 48Hz: 记录器未就绪 (systemctl status zmax-rec48)")

    adv = w.get("advice") or []
    if adv:
        lines.append("建议: " + "；".join(adv))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
