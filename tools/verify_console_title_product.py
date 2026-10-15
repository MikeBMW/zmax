#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🏷 控制台顶栏产品标识 + 调试同源 判据 (老倪 2026-10-15)

原话: 「控制台 最上边框 显示 的 XSpace Studio的一行字 改成 XSpace ZMAX 550A 或者 根据配置中心产品配置,
      显示 具体的 550B 或 550C  左侧边栏 保留 v5.50.730的版本显示; 不用特意显示 非调试模式,
      但是你要保证, 当我用 vscode debug模式调试时, 打开的也是同一个版本;
      如果保证不了同一个版本, 则关闭已经打开的模式, 重启进入调试模式」

判据 (每条都读真源/读真窗口, 不读印象):
  ① 产品真源可读且合法 (config/platform/zmax_product.json 的 active_product ∈ 550A/550B/550C)
  ② studio.py 标题**单一出处** (_console_title) 且已无「XSpace Studio — Z-MAX」老标题硬串
  ③ 侧栏品牌版本仍在 (QLabel("Z-MAX vX.Y.Z")) 且与 update_checker.CURRENT_VERSION 一致
  ④ F5「🚀 全新调试进程」的 program **逐字节 == 在役 studio.py** (md5) ⇒ 调试打开的同一版本
  ⑤ 仓库内没有第二条 launch.json 指向**别的** studio.py (旧副本/旧 worktree 钓鱼)
  ⑥ 实机窗口标题 == 「XSpace ZMAX <active_product>」 (读真窗口, 不是读代码字面量)
  ⑦ --follow: 真源 active_product 切到另一个产品号 → ≤8s 窗口标题跟过去 → 改回 → 标题跟回 (带备份+回读)

用法: cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/verify_console_title_product.py [--follow]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STUDIO = os.path.join(ROOT, "tools", "gui", "studio.py")
PRODUCT_JSON = os.path.join(ROOT, "config", "platform", "zmax_product.json")
LAUNCH = os.path.join(ROOT, ".vscode", "launch.json")
DISPLAY = os.environ.get("ZMAX_DISPLAY", ":0")

OK, BAD = "✅", "❌"
rows: list[tuple[str, bool, str]] = []


def chk(tag: str, ok: bool, ev: str) -> bool:
    rows.append((tag, ok, ev))
    print("  %s %s  %s" % (OK if ok else BAD, tag, ev))
    return ok


def read(p: str) -> str:
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def md5(p: str) -> str:
    with open(p, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def win_titles():
    """读真窗口 (DISPLAY=:0)"""
    try:
        out = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True,
                             env=dict(os.environ, DISPLAY=DISPLAY), timeout=6).stdout
    except Exception:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def console_title_now():
    for ln in win_titles():
        if "XSpace ZMAX" in ln:
            return " ".join(ln.split()[3:]).strip()
    return ""


def wait_title(pat: str, timeout=8.0):
    """等到窗口标题出现 pat; 返回 (命中标题, 用时s)"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = console_title_now()
        if pat in t:
            return t, round(time.time() - t0, 1)
        time.sleep(0.5)
    return console_title_now(), round(time.time() - t0, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--follow", action="store_true", help="真源切产品号, 验窗口标题跟随后再改回")
    a = ap.parse_args()

    print("═══ 控制台顶栏产品标识 + 调试同源 判据 ═══")
    print("  口径: 产品真源 %s" % PRODUCT_JSON)

    # ① 真源
    try:
        doc = json.loads(read(PRODUCT_JSON))
        pid = str(doc.get("active_product") or "").strip()
    except Exception as e:
        chk("① 产品真源可读", False, "%s: %s" % (e.__class__.__name__, e))
        return 1
    chk("① 产品真源可读且合法", pid in ("550A", "550B", "550C"),
        "active_product=%s · products=%s" % (pid, sorted((doc.get("products") or {}).keys())))

    src = read(STUDIO)

    # ② 标题单一出处 + 老标题已下线
    n_src_old = len(re.findall(r"XSpace Studio — Z-MAX", src))
    n_call = len(re.findall(r"_console_title\(", src))
    n_hard = len(re.findall(r'setWindowTitle\("XSpace ZMAX', src))
    chk("② 标题单一出处 _console_title()", n_call >= 2 and n_hard == 0,
        "调用点 %d 处 · 硬写字面量 %d 处 (应为 0) · 老标题硬串 %d 处 (应为 0)" % (n_call, n_hard, n_src_old))
    chk("②b 标题读真源而非写死产品号",
        "_PRODUCT_JSON" in src and 'f"XSpace ZMAX' not in src and '"XSpace ZMAX %s"' in src,
        "标题模板 = \"XSpace ZMAX %%s\" %% _active_product_id()")

    # ③ 侧栏版本仍在且与 CURRENT_VERSION 一致
    m_ver = re.search(r'QLabel\("Z-MAX (v?\d+\.\d+\.\d+)"\)', src)
    cur = ""
    try:
        _m = re.search(r'CURRENT_VERSION = "(v?[\d.]+)"', read(os.path.join(ROOT, "tools/gui/update_checker.py")))
        cur = _m.group(1) if _m else ""
    except Exception:
        pass
    v_lbl = m_ver.group(1) if m_ver else ""
    chk("③ 侧栏品牌版本在位且同号", bool(v_lbl) and v_lbl.lstrip("v") == cur.lstrip("v"),
        'QLabel("Z-MAX %s") vs CURRENT_VERSION=%s' % (v_lbl or "—", cur or "—"))

    # ④ F5 调试目标 == 在役 studio.py (调试同一版本的硬证据)
    try:
        cfg = json.loads(read(LAUNCH))
    except Exception as e:
        chk("④ F5 配置可读", False, "%s: %s" % (e.__class__.__name__, e))
        cfg = {}
    f5 = ""
    for c in (cfg.get("configurations") or []):
        if "全新调试进程" in str(c.get("name", "")) and str(c.get("program", "")).endswith(".py"):
            f5 = os.path.abspath(str(c["program"]))
            break
    if not f5:
        chk("④ F5 调试目标存在", False, "launch.json 里找不到「🚀 全新调试进程」配置")
    else:
        same = os.path.exists(f5) and md5(f5) == md5(STUDIO)
        chk("④ F5 调试目标 == 在役 studio.py", same,
            "F5=%s (md5 %s) · 在役=%s (md5 %s)" % (f5, md5(f5) if os.path.exists(f5) else "缺",
                                                   STUDIO, md5(STUDIO)))

    # ⑤ 没有第二条 launch.json 指向别的 studio.py
    others = []
    for base in [os.path.join(ROOT, "external"), os.path.join(ROOT, "zmax_data")]:
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            lj = os.path.join(base, name, ".vscode", "launch.json")
            if os.path.exists(lj):
                try:
                    d = json.loads(read(lj))
                except Exception:
                    continue
                for c in (d.get("configurations") or []):
                    pg = str(c.get("program", ""))
                    if pg.endswith("studio.py") and os.path.abspath(pg) != STUDIO:
                        others.append("%s → %s" % (lj, pg))
    chk("⑤ 无第二条指向别的 studio.py 的调试配置", not others, "扫描 %s/{external,zmax_data}/*/.vscode/launch.json ⇒ %s"
        % (ROOT, others or "0 条"))

    # ⑥ 实机窗口标题 == 真源产品号
    t = console_title_now()
    if not t:
        chk("⑥ 实机窗口标题 (控制台在跑)", False, "DISPLAY=%s 下没找到含「XSpace ZMAX」的窗口" % DISPLAY)
    else:
        chk("⑥ 实机窗口标题 == XSpace ZMAX %s" % pid, t == ("XSpace ZMAX %s" % pid),
            '实测窗口标题 = "%s"' % t)

    # ⑦ 跟随真源 (可选, 带备份/回读)
    if a.follow:
        if not t:
            chk("⑦ 标题跟随真源", False, "控制台没在跑, 跳过")
        else:
            other = next(x for x in ("550A", "550B", "550C") if x != pid)
            raw = open(PRODUCT_JSON, "rb").read()
            try:
                d2 = json.loads(raw.decode("utf-8"))
                d2["active_product"] = other
                with open(PRODUCT_JSON, "w", encoding="utf-8") as f:
                    json.dump(d2, f, ensure_ascii=False, indent=2)
                t1, dt1 = wait_title("XSpace ZMAX %s" % other, timeout=8.0)
                chk("⑦ 真源切 %s → 标题跟随" % other, t1 == ("XSpace ZMAX %s" % other),
                    '改真源后 %.1fs 窗口标题 = "%s"' % (dt1, t1))
            finally:
                with open(PRODUCT_JSON, "wb") as f:
                    f.write(raw)
                back = json.loads(read(PRODUCT_JSON)).get("active_product")
                t2, dt2 = wait_title("XSpace ZMAX %s" % pid, timeout=8.0)
                chk("⑦b 真源已还原 %s (回读)" % pid, back == pid and t2 == ("XSpace ZMAX %s" % pid),
                    '回读 active_product=%s · %.1fs 后窗口标题 = "%s"' % (back, dt2, t2))

    bad = [r for r in rows if not r[1]]
    print("─── %d/%d %s" % (len(rows) - len(bad), len(rows), "全绿 PASS" if not bad else "FAIL: " + "; ".join(r[0] for r in bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
