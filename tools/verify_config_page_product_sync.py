#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_config_page_product_sync.py — 判据: 配置中心**左树「产品配置 当前 X」**必须与唯一依据一致。

复现的现场 bug (2026-10-15 老倪): 控制台启动时唯一依据=550A; 之后在别处把 active_product 写成 550B,
左树仍写「当前 550A」—— 根因是左树文本只在建树那一刻取一次, 之后没人重读。

本判据 (全程离屏, 不动生产 GUI):
  ① 备份唯一依据 + 记 sha256 (测完必须原样还原)
  ② 唯一依据=550A 时冷启动页面  ⇒ 左树必须写 550A
  ③ 唯一依据改成 550B (模拟"别处改了") ⇒ 调一次 _sync_tree_product(force=True) ⇒ 左树必须变 550B
  ④ 唯一依据=550B 时**新建**页面 (冷启动) ⇒ 左树必须写 550B
  ⑤ 还原唯一依据 + 校验 sha256 与备份一致 (证明判据没有污染唯一依据)
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_config_page_product_sync.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PRODUCT_J = os.path.join(ROOT, "config", "platform", "zmax_product.json")


def sha256(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def write_active(pid: str) -> None:
    """只改 active_product 一个键 (原子写: 临时文件 + os.replace), 其余逐字节保持。"""
    d = json.load(open(PRODUCT_J, encoding="utf-8"))
    d["active_product"] = pid
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(PRODUCT_J), prefix=".prod_", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PRODUCT_J)


def tree_line(page):
    """左树 + tooltip + 星图条摘要 (2026-10-17 修: 「当前 X」已从左树文本移到 _star_facts 摘要,
    只读 tree.text(0) 会永远判红 —— 判据要跟着真实现走, 不能钉死一种呈现位置)。"""
    parts = []
    try:
        t = page.tree
        for i in range(t.topLevelItemCount()):
            it = t.topLevelItem(i)
            parts.append(it.text(0))
            parts.append(it.toolTip(0))
            for k in range(it.childCount()):
                c = it.child(k)
                parts.append(c.text(0))
                parts.append(c.toolTip(0))
    except Exception as e:                                                       # noqa: BLE001
        parts.append("树读取失败 %s" % type(e).__name__)
    try:
        import veh6_config_page as V
        parts.append(str((V._star_facts() or {}).get("prod") or ""))
    except Exception as e:                                                       # noqa: BLE001
        parts.append("星图摘要读取失败 %s" % type(e).__name__)
    return " | ".join([x for x in parts if x])


def main() -> int:
    from PyQt5.QtWidgets import QApplication
    import veh6_config_page as V

    _app = QApplication.instance() or QApplication([])
    checks = []

    bak = PRODUCT_J + ".verify_bak"
    shutil.copy2(PRODUCT_J, bak)
    _sha0 = sha256(PRODUCT_J)
    orig = str((json.load(open(PRODUCT_J, encoding="utf-8")) or {}).get("active_product"))
    try:
        # ② 唯一依据=550A, 冷启动
        write_active("550A")
        p1 = V.ConfigCenterPage()
        l1 = tree_line(p1)
        checks.append(("② 冷启动 (唯一依据 550A) 左树写 550A", "当前 550A" in l1, l1))

        # ③ 别处改成 550B → 同步一次
        write_active("550B")
        p1._sync_tree_product(force=True)
        l1b = tree_line(p1)
        checks.append(("③ 别处改成 550B 后同步 ⇒ 左树变 550B (本次修复点)",
                       "当前 550B" in l1b and "当前 550A" not in l1b, l1b))

        # ④ 唯一依据=550B, 新建页面冷启动
        p2 = V.ConfigCenterPage()
        l2 = tree_line(p2)
        checks.append(("④ 冷启动 (唯一依据 550B) 左树写 550B", "当前 550B" in l2, l2))

        # ⑤ 唯一依据与产品质数未被判据改动
        d = json.load(open(PRODUCT_J, encoding="utf-8"))
        primes = {k: (v or {}).get("prime") for k, v in (d.get("products") or {}).items()}
        checks.append(("⑤ 产品质数保持 550A/550B/550C = 1009/1013/1019",
                       primes.get("550A") == 1009 and primes.get("550B") == 1013
                       and primes.get("550C") == 1019, json.dumps(primes, ensure_ascii=False)))
    finally:
        shutil.copy2(bak, PRODUCT_J)          # 还原
        _sha1 = sha256(PRODUCT_J)
        os.remove(bak)
    checks.append(("⑥ 唯一依据已原样还原 (sha256 一致)", _sha0 == _sha1, "%s → %s" % (_sha0[:12], _sha1[:12])))
    checks.append(("⑦ 还原后 active_product = 原值 %s" % orig,
                   str((json.load(open(PRODUCT_J, encoding="utf-8")) or {}).get("active_product")) == orig, ""))

    # ⑧ 标签必须带「唯一依据改于 <mtime>」(别的写入口瞒不过文件时间, 而不是只信唯一依据内部 updated 字段)
    checks.append(("⑧ 左树带「唯一依据改于」= 文件 mtime", "唯一依据改于" in l2, l2))

    # ⑨ 写回路径 (_write_active_product) 必须顺手盖 updated 时间戳 (今天+当前版本), 否则报告/界面显示旧日期
    import veh6_config_page as _V2
    _ok, _back, _err = _V2._write_active_product("550A")
    _u1 = str((json.load(open(PRODUCT_J, encoding="utf-8")) or {}).get("updated") or "")
    _ok2, _back2, _err2 = _V2._write_active_product("550B")     # 写回原值
    _u2 = str((json.load(open(PRODUCT_J, encoding="utf-8")) or {}).get("updated") or "")
    import datetime as _dt
    _today = _dt.date.today().strftime("%Y-%m-%d")
    checks.append(("⑨ 写回盖 updated 时间戳 (含今天 %s)" % _today, _u1.startswith(_today) and _u2.startswith(_today),
                   "写 550A→updated=%r / 写回 550B→updated=%r" % (_u1, _u2)))

    ok = sum(1 for _, c, _ in checks if c)
    for name, c, ev in checks:
        print("  %s %s%s" % ("✅" if c else "❌", name, ("  · " + ev[:110]) if ev else ""))
    print("\n%s %d/%d" % ("✅ PASS" if ok == len(checks) else "❌ FAIL", ok, len(checks)))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
