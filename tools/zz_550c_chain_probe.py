#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧪 550C 接管链路取证: 只验"谁收、谁执行、闸在哪", 绝不让机械臂动。

老倪 2026-10-26:「要保证, 这些轨迹, 发到 550C, 由 550C 统一执行, 是这样的么? 你全局验证一下;
                先不用发真实操作指令」

做法: 构造一份**故意不可能执行**的段表发出去, 让 550C 的闸必然拒, 然后去 550C 的台账里
      查它到底收没收到、拒的理由是什么。三条保险, 任一成立都不会动臂:
  ① 授权 remaining=0 (过期)  ⇒ 550C 授权闸必拒
  ② start_mm=[0,0,0]         ⇒ 与当前 TCP 差 500mm+, 起点闸必拒
  ③ 单段 1mm 且目标点 base 原点 ⇒ 就算前两闸都失效, 包络/起点也会挡
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "dds"))


def main() -> int:
    plan = {
        "ts": time.time(),
        "tcp0_mm": [0.0, 0.0, 0.0],
        "segs": [{"axis": "z", "dir": "+", "d_mm": 1.0, "to_mm": [0.0, 0.0, 1.0]}],
        "total_mm": 1.0,
        "note": "CHAIN-PROBE 只验链路, 故意非法",
    }
    pid = "PROBE-%s" % time.strftime("%Y%m%d-%H%M%S")
    import plan_publish                                                        # noqa: PLC0415
    out = plan_publish.publish_plan(plan, 1.0, {"epoch": 0, "until": time.time() - 5}, pid)
    print("[1] 发布结果:", json.dumps(out, ensure_ascii=False))
    print("[1] plan_id =", pid, "· 授权 remaining = 0 (过期) · start_mm=[0,0,0] (离当前 TCP 500mm+)")

    print("[2] 等 8s 让 hub → 550C 走完…")
    time.sleep(8)

    cmd = ("python3 - <<'PY'\n"
           "import json,os\n"
           "p='/home/intel/zmax_550c/zmax_data/runtime/plan'\n"
           "for f in ('plan_exec_state.json','plan_exec_seen.json'):\n"
           "    try:\n"
           "        d=json.load(open(os.path.join(p,f),encoding='utf-8'))\n"
           "        print(f, '→', json.dumps(d, ensure_ascii=False)[:400])\n"
           "    except Exception as e:\n"
           "        print(f,'读不到',e)\n"
           "try:\n"
           "    ls=open(os.path.join(p,'plan_exec_550c.jsonl'),encoding='utf-8').read().strip().splitlines()\n"
           "    for ln in ls[-3:]: print('ledger:', ln[:300])\n"
           "except Exception as e:\n"
           "    print('ledger 读不到', e)\n"
           "PY")
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                        "intel@192.168.23.70", cmd], capture_output=True, text=True, timeout=60)
    print("[3] 550C 侧状态:")
    print((r.stdout or "").strip() or "(空)")
    if r.stderr.strip():
        print("   stderr:", r.stderr.strip()[:200])

    hit = pid in (r.stdout or "")
    print("[4] 判定: 550C %s这份段表 (plan_id 在它状态里%s)"
          % ("收到了" if hit else "没收到", "出现" if hit else "未出现"))
    return 0 if hit else 1


if __name__ == "__main__":
    sys.exit(main())
