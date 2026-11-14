#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hero_round.py — 用手上已有的整段真机数据跑一轮高质量 3DGS(warm start)。

为什么不用"再走一遍真机": 今晚已有 3 段收口数据集(900/452/900 帧)，覆盖的就是这条轨迹；
重复同一条路径的边际收益很低(视角完全一样)，真正缺的是**新视角**。
所以先用现有最大的一段(900 帧全窗口) + 热启动跑 1500 步，看 PSNR 能不能顶到 15+。
"""
import json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gs_realtime_map as R                                    # noqa: E402

SESS = os.path.expanduser("~/gs_autocap/sessions/20261113_193134_2a34")
WINDOW = int(os.environ.get("HERO_WINDOW", "900"))
STEPS = int(os.environ.get("HERO_STEPS", "1500"))
ts = time.strftime("%Y%m%d_%H%M%S")
ds = os.path.join(R.ROOT, "ds_hero_%s" % ts)
out = os.path.join(R.ROOT, "out_hero_%s" % ts)

print("[hero] 会话", SESS, "窗口", WINDOW, "步数", STEPS, flush=True)
ok, msg = R.build_ds(SESS, ds, WINDOW)
print("[hero] 建数据集", ok, msg, flush=True)
if not ok:
    sys.exit(2)
init = os.path.join(R.ASSET, "gs.ply")
print("[hero] 热启动来源", init, os.path.exists(init), flush=True)
ok, msg, rep = R.train(ds, out, init)
print("[hero] 训练", ok, msg, flush=True)
print("[hero] 报告", json.dumps(rep, ensure_ascii=False)[:400], flush=True)
if ok:
    st = R.st_read()
    st.update({"phase": "collect", "hero_asset": os.path.join(R.ASSET, "gs.splat"),
               "hero_psnr": rep.get("psnr_holdout_db"), "hero_steps": STEPS,
               "hero_seconds": rep.get("seconds"), "hero_ds": ds})
    st.setdefault("log", []).append("[%s] HERO 轮完成: %s dB / %s 步" %
                                    (R.now(), rep.get("psnr_holdout_db"), STEPS))
    R.st_write(st)
    print("[hero] 已发布", os.path.join(R.ASSET, "gs.splat"), flush=True)
