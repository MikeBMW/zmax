#!/usr/bin/env python3
"""全量节点单步普查: 每个节点单独跑一拍, 分三类报数 (实现执行 / 直通 / 异常)。

回答的是「能不能每个节点都单步真跑」这类问题 —— 答案必须由这三类计数给出,
而不是「GUI 里点得动」。

用法 (确保目标 venv 装了工程依赖, 一般是仓库的 gui-venv311):
    ./gui-venv311/bin/python scripts/sweep_all_nodes_step.py
    ./gui-venv311/bin/python scripts/sweep_all_nodes_step.py --slow 200
    ./gui-venv311/bin/python scripts/sweep_all_nodes_step.py --only ssdec,ssplan,ssact

判读:
    实现执行  节点返回结果字典, 走的是真实现
    直通      画布 params.pure_verified 未开 (或实现返回非 dict), 只走数据面, 不产生计算
    异常      step 抛错, 必须为 0 —— 不为 0 就是接线/实现真坏了

注意:
    - 跑之前先停常驻循环 (`systemctl stop zmax-ss-canvas-loop`), 否则同一批
      zmax_data/ss_live/*.json 会被另一个进程每拍重写, 你看到的数对不上盘。
    - 本脚本只读执行, 不下发任何动作; 但它会让节点真跑, 有副作用的节点
      (写 live 文件、起模型) 会照常发生。
"""
import argparse
import os
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.getcwd(), help="仓库根 (默认当前目录)")
    ap.add_argument("--slow", type=float, default=200.0, help="超过多少 ms 单列为慢节点")
    ap.add_argument("--only", default="", help="只跑这些节点 id, 逗号分隔")
    a = ap.parse_args()

    src = os.path.join(os.path.abspath(a.root), "src")
    if not os.path.isdir(src):
        raise SystemExit("找不到 %s —— 用 --root 指到仓库根" % src)
    sys.path.insert(0, src)

    from lerobot.middleware import load_project          # noqa: PLC0415

    prj = load_project()
    ids = list(prj.nodes.keys())
    if a.only:
        want = {x.strip() for x in a.only.split(",") if x.strip()}
        ids = [i for i in ids if i in want]

    ok, passthru, err, slow = [], [], [], []
    for i in ids:
        t0 = time.time()
        try:
            tr = prj.step(only=[i])
            t = tr[0]
            ms = (time.time() - t0) * 1000.0
            if t.get("status") == "实现执行":
                ok.append((i, round(ms)))
            else:
                passthru.append((i, t.get("status"), round(ms)))
            if ms > a.slow:
                slow.append((i, round(ms)))
        except Exception as e:                                    # noqa: BLE001
            err.append((i, "%s: %s" % (type(e).__name__, e)))

    print("节点 %d · 实现执行 %d · 直通 %d · 异常 %d"
          % (len(ids), len(ok), len(passthru), len(err)))

    if ok:
        print("\n[实现执行]")
        for i, ms in ok:
            print("  %-16s %sms" % (i, ms))
    if slow:
        print("\n[慢节点 > %sms]" % int(a.slow))
        for i, ms in slow:
            print("  %-16s %sms" % (i, ms))
    if passthru:
        print("\n[直通/非实现]")
        for i, st, ms in passthru:
            print("  %-16s %-28s %sms" % (i, str(st)[:28], ms))
    if err:
        print("\n[异常]")
        for i, e in err:
            print("  %-16s %s" % (i, e))

    return 0 if not err else 1


if __name__ == "__main__":
    raise SystemExit(main())
