#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""debug_map_logic.py —— 只跑**建图逻辑本体**，给 VSCode 断点用（不经过画布节点壳）。

为什么单独一个 runner：
  画布节点 `node_ss_s1` 只是派发层（ensure 守护 / 写一行日志），建图算法全在
  `state_space/map_fusion.py`。要检查算法就得直接调它的入口:
      realtime_cycle()  一轮"攒帧 → 够阈值 → build_ds → train → publish"的决策与执行
      offline()         离线的一次性建图（同一个 build_ds→train→publish）

断点层级（环境变量 ZMAX_DEBUG_MAPFUSION）:
  1 → 停 realtime_cycle(一轮建图决策)
  2 → 再停 build_ds(建数据集) / train(发训练)
  3 → 再停 publish(发布资产)

本 runner 用 force=True 跳过"攒够多少帧才开一轮"的门槛，直接走一遍真实流程；
数据集与产物都落在临时目录（MF_ROOT/MF_ASSETS 指到 scratch），不污染产线资产。
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src", "lerobot", "policies", "left_right", "state_space"))


def log(msg: str) -> None:
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def main() -> int:
    import map_fusion as mf

    log("建图实现: %s" % mf.__file__)
    log("会话源: %s | 数据集根: %s | 断点层级 ZMAX_DEBUG_MAPFUSION=%s"
        % (mf.SESSIONS, mf.ROOT, os.environ.get("ZMAX_DEBUG_MAPFUSION", "0")))
    sess = mf.latest_session()
    log("最新会话: %s · 帧数 %d" % (sess or "(无)", mf.count_imgs(sess)))

    state = mf.st_read()
    state["sess_marker"] = ""            # 强制按新会话建立基线, 否则 pending 恒 0 不进建图
    state["last_trained_frames"] = 0
    log("进入 realtime_cycle(force=True) —— 下面就是建图的真实决策逻辑")
    out = mf.realtime_cycle(state, force=True)
    log("一轮返回: %s" % {k: out.get(k) for k in
                        ("phase", "frames_now", "pending", "steps", "n_gaussians",
                         "psnr_holdout_db", "error")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
