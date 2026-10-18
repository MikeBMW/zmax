#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""studio.py 内存看门狗 — 防止控制台 GUI 把整机吃满(2026-10-18 死机复盘)

事故 (2026-10-18):
  08:35 手动清掉一个跑 8h53m、RSS 20.2GB + swap 8.5GB 的 studio.py → available 13GB
  08:52/09:40/10:28/11:17/12:00/12:10/12:14 又 F5 启动了 **7 次** (VSCode 窗口同时崩过 3 次)
  ⇒ 孤儿实例叠加 + 各自泄漏 ⇒ 内存+swap 耗尽 ⇒ 12:26 只能强重启 (内核未留 OOM-kill 记录,
    systemd-oomd 累计吃了 49s CPU 在压制, 系统最后是 thrash 到无响应而不是被 OOM killer 干净杀掉)

本看门狗 (systemd timer 每 2 分钟):
  ① 单实例 RSS > MAX_GB(默认 8GB)            → SIGTERM, 记事故
  ② 孤儿实例 (ppid==1, 调试器已断) 且 > 2GB   → SIGTERM, 记事故 (这是叠加泄漏的来源)
  ③ 全部实例 RSS 合计 > TOTAL_GB(默认 12GB)   → 先杀最大的那个
  ④ 杀掉后**自动拉起**(STUDIO_AUTO_RESTART=1, 默认开) ⇒ 控制台不会凭空消失;
     不想被自动拉起就设 STUDIO_AUTO_RESTART=0。
  只做只读判断 + 精准 SIGTERM, 不动引擎/采样/总线。

用法:
  python3 tools/studio_mem_guard.py            # 检查一次 (report 模式, 只报告不杀)
  python3 tools/studio_mem_guard.py --enforce  # 按上面规则处理
  python3 tools/studio_mem_guard.py --status   # 只看现状
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
AUTO_RESTART = os.environ.get("STUDIO_AUTO_RESTART", "1") != "0"
RESTART_SH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "restart_studio.sh")
LOG = os.path.join(REPO, "zmax_data", "ops", "studio_mem_guard.jsonl")
MAX_GB = float(os.environ.get("STUDIO_MAX_GB", "8"))
ORPHAN_GB = float(os.environ.get("STUDIO_ORPHAN_GB", "2"))
TOTAL_GB = float(os.environ.get("STUDIO_TOTAL_GB", "12"))
PROC = "tools/gui/studio.py"


def _read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def scan():
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        cmd = _read("/proc/%s/cmdline" % d).replace("\0", " ").strip()
        if PROC not in cmd:
            continue
        st = _read("/proc/%s/status" % d)
        rss_kb = 0
        for ln in st.splitlines():
            if ln.startswith("VmRSS:"):
                rss_kb = int(ln.split()[1])
                break
        ppid = 0
        for ln in _read("/proc/%s/stat" % d).split(") ")[-1].split()[:2]:
            try:
                ppid = int(ln)
                break
            except ValueError:
                pass
        bt = 0.0
        try:
            bt = os.path.getmtime("/proc/%s" % d)
        except Exception:
            pass
        out.append({"pid": int(d), "pid_s": d, "rss_gb": round(rss_kb / 1048576.0, 2),
                    "ppid": ppid, "age_min": round((time.time() - bt) / 60.0, 1) if bt else None,
                    "debugged": "debugpy" in cmd})
    return sorted(out, key=lambda x: -x["rss_gb"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enforce", action="store_true", help="按规则 SIGTERM (默认只报告)")
    ap.add_argument("--status", action="store_true", help="只看现状")
    a = ap.parse_args()

    ps = scan()
    tot = round(sum(p["rss_gb"] for p in ps), 2)
    if a.status:
        print("studio.py 实例 %d 个 · 合计 %.2fGB" % (len(ps), tot))
        for p in ps:
            print("  pid=%s %.2fGB ppid=%s 跑=%s分钟 调试=%s" % (
                p["pid_s"], p["rss_gb"], p["ppid"], p["age_min"], p["debugged"]))
        return 0

    kill = []
    for p in ps:
        if p["rss_gb"] >= MAX_GB:
            kill.append((p, "单实例 %.2fGB ≥ %.0fGB" % (p["rss_gb"], MAX_GB)))
        elif p["ppid"] == 1 and p["rss_gb"] >= ORPHAN_GB and p["debugged"]:
            kill.append((p, "孤儿实例 %.2fGB (调试器已断, 会继续泄漏)" % p["rss_gb"]))
    if not kill and tot >= TOTAL_GB and ps:
        kill.append((ps[0], "合计 %.2fGB ≥ %.0fGB" % (tot, TOTAL_GB)))

    rec = {"ts": time.time(), "n": len(ps), "total_gb": tot, "max_gb": ps[0]["rss_gb"] if ps else 0,
           "procs": ps, "action": [{"pid": k[0]["pid"], "why": k[1]} for k in kill],
           "enforce": bool(a.enforce)}
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    msg = "studio 看门狗: %d 实例 合计%.2fGB 最大%.2fGB" % (len(ps), tot, rec["max_gb"])
    if not kill:
        print(msg + " · 正常")
        return 0
    killed = 0
    for p, why in kill:
        print("⚠ " + msg + " · 触发: pid=%s %s" % (p["pid_s"], why))
        if a.enforce:
            try:
                os.kill(p["pid"], signal.SIGTERM)
                killed += 1
                print("  → 已 SIGTERM pid=%s (记录 %s)" % (p["pid_s"], LOG))
            except Exception as e:                                  # noqa: BLE001
                print("  → 杀失败: %s" % e)
    # ④ 杀掉后自动拉起 —— 否则用户会看到"控制台自己没了"却不知道原因
    if killed and AUTO_RESTART:
        time.sleep(3)          # 等 SIGTERM 生效再查, 否则会把刚杀的算成"还在跑"
        # 只有"全杀光"了才需要拉起 (还留着一个在跑的就不重复开窗口)
        left = [p for p in scan() if p["rss_gb"] >= 1.0]
        if not left:
            try:
                with open(LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.time(), "action": "auto_restart",
                                        "sh": RESTART_SH}, ensure_ascii=False) + "\n")
                subprocess.Popen(["bash", RESTART_SH],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                print("  → 已自动拉起控制台 (%s)" % RESTART_SH)
            except Exception as e:                                  # noqa: BLE001
                print("  → 自动拉起失败: %s" % e)
        else:
            print("  → 仍有 %d 个实例在跑, 不重复拉起" % len(left))
    return 0 if a.enforce else 3


if __name__ == "__main__":
    raise SystemExit(main())
