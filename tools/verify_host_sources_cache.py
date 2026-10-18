#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: host_sources.read_file 按 (mtime_ns,size) 缓存 —— 文件没变就零 JSON 解析

背景 (2026-10-18 整机 OOM 事故的根因):
  bpftrace 抓到热路径 `_PyObject_ArenaMmap ← PyDict_SetItem ← scan_once_unicode` = 高频 json 解析。
  信号页 ~10Hz 调 topics(), 而 topics() 对 FILES 里 14 个文件每个都全量 json.load + flatten,
  不看文件有没有变 ⇒ 每秒上百次解析、上万个临时 dict/str ⇒ pymalloc arena 只增不减 ⇒ 20.2GB。

本判据证明:
  ① 文件没变 → N 次读只解析 1 次 (旧实现解析 N 次)
  ② 返回的 fields 是副本 (下游改了不污染缓存)
  ③ 文件一变 → 立刻重新解析, 拿到新值
  ④ age_s (帧龄) 每次调用都刷新, 不受缓存影响
  ⑤ topics() 连续调用不再产生额外解析

跑: python3 tools/verify_host_sources_cache.py
"""
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

from lerobot.middleware import host_sources as hs  # noqa: E402

ROWS = []


def ck(name, ok, detail=""):
    ROWS.append({"判据": name, "结果": "PASS" if ok else "FAIL", "实测": detail})
    print(("✅ " if ok else "❌ ") + name + ("  " + detail if detail else ""))


# ── 计数用的探针: 替换 host_sources 里的 json.load ────────────────────────────
class Counter:
    def __init__(self):
        self.n = 0
        self._orig = hs.json.load

    def __enter__(self):
        def wrapped(*a, **k):
            self.n += 1
            return self._orig(*a, **k)
        hs.json.load = wrapped
        return self

    def __exit__(self, *exc):
        hs.json.load = self._orig


REL = "zmax_data/__cache_probe.json"
ABS = os.path.join(hs.ROOT, REL)


def write_probe(v, adelay=0.0):
    os.makedirs(os.path.dirname(ABS), exist_ok=True)
    with open(ABS, "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "值_a": v, "值_b": v * 2}, f)
    if adelay:
        time.sleep(adelay)


def main():
    hs._RF_CACHE.clear()
    write_probe(1.0)

    # ① 50 次连读, 只解析 1 次
    with Counter() as c:
        for _ in range(50):
            hs.read_file("space", REL)
    ck("①文件没变: 50 次读只解析 1 次", c.n == 1, f"json.load 调用 {c.n} 次 (旧实现 50 次)")

    # ② 返回值是副本
    a = hs.read_file("space", REL)
    a["fields"]["值_a"] = 999.0
    b = hs.read_file("space", REL)
    ck("②fields 是副本, 改它不污染缓存", float(b["fields"].get("值_a", -1)) == 1.0,
       f"缓存里 值_a={b['fields'].get('值_a')}")

    # ③ 文件一变立刻重解析
    time.sleep(0.02)
    write_probe(7.0)
    with Counter() as c:
        got = hs.read_file("space", REL)
    val = float(got["fields"].get("值_a", -1)) if got else -1
    ck("③文件一变: 重新解析并拿到新值", c.n == 1 and abs(val - 7.0) < 1e-9,
       f"解析 {c.n} 次, 值_a={val}")

    # ④ age_s 每次都刷新
    a1 = hs.read_file("space", REL)["age_s"]
    time.sleep(1.05)
    a2 = hs.read_file("space", REL)["age_s"]
    ck("④帧龄 age_s 每次刷新(不被缓存冻住)", a2 >= a1 + 0.9, f"{a1:.2f}s → {a2:.2f}s")

    # ⑤ topics() 连续调用不再产生额外解析
    hs._RF_CACHE.clear()
    hs.topics()
    with Counter() as c:
        for _ in range(20):
            hs.topics()
    # 20 次里可能有几个真源正在被别处实时写 (mtime 变了 ⇒ 正常重解析), 只要远小于 20 就算命中
    ck("⑤topics() 连调 20 次: 绝大多数命中缓存", c.n <= 6,
       f"json.load 调用 {c.n} 次 (旧实现 ≥20×14=280 次; 有几次是真源正在写文件)")

    try:
        os.remove(ABS)
    except OSError:
        pass

    n_pass = sum(1 for r in ROWS if r["结果"] == "PASS")
    out = os.path.join(REPO, "zmax_data", "eval", "verify_host_sources_cache.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "判据": ROWS, "PASS": n_pass, "总": len(ROWS)}, f,
                  ensure_ascii=False, indent=1)
    print("\n" + "=" * 78)
    print(f"判据 {n_pass}/{len(ROWS)} PASS")
    print(f"落盘: {out}")
    return 0 if n_pass == len(ROWS) else 3


if __name__ == "__main__":
    sys.exit(main())
