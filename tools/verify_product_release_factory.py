#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_product_release_factory.py — 判据: 三个产品档 550A/550B/550C 能不能**跟着安装包一起发布**。

老倪 2026-10-15: 「完成后, 迭代推代码 5.50.735 版本, 同步发布 windows mac ubuntu 跨平台安装程序,
产品 550A 550B 550C 同步发布。」

为什么要有这条判据 (实捉的缺口):
  平台/实例解耦后 **实例真源 `config/platform/` 不进仓库** (data/ 被 gitignore) ⇒ 打出来的 Windows/macOS/Linux 包
  里**没有产品档真源** ⇒ 全新安装只能走"兜底=调试档全开", 三档 550A/B/C 根本选不出来 —— "同步发布"就成了空话。
  修法: ① 出厂骨架 `defaults/config/platform/zmax_product.json` (三档 dev_profile 全带) 进仓库;
        ② 读侧按 canvas 同一套规矩回落 (实例真源 → 仓库 defaults → 冻结包 _MEIPASS);
        ③ 打包 job 带 `defaults` 并断言三档在。

判据:
  ① 出厂骨架在位 + 三档齐 + 每档 dev_profile 关键键齐 (老倪的三产品分工口径)
  ② 三档真不同 (A 逻辑最多/开新算法; B topics=all+联调; C 白名单+comm=shm+关信号/3D)
  ③ **真回落**: 隔离目录 (只有 defaults, 没有 config/) 起子进程读产品档, 三档都读得到且 dev_profile 正确
  ④ studio 标题读侧也回落 (静态核 + 冻结包 _MEIPASS 候选在)
  ⑤ 打包 job 真带骨架 (Windows + macOS 两个 job 都有 --add-data defaults 且 Windows 断言三档)
  ⑥ 现役档位不被骨架顶掉 (实例真源优先 ⇒ 现场还是 550B)
  ⑦ 三产品开发分工判据本体仍过 (config/ss_task_binding 等既有判据不回归)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKEL = os.path.join(ROOT, "defaults", "config", "platform", "zmax_product.json")
WF = os.path.join(ROOT, ".github", "workflows", "build-win-exe.yml")
INST = os.path.join(ROOT, "config", "platform", "zmax_product.json")
ok = True


def chk(name, cond, detail=""):
    global ok
    print("   %s %s%s" % ("✅" if cond else "❌", name, (" · " + str(detail)) if detail else ""))
    ok = ok and bool(cond)


print("① 出厂骨架 (随仓库/安装包)")
d = json.load(open(SKEL, encoding="utf-8")) if os.path.isfile(SKEL) else {}
prods = d.get("products") or {}
chk("defaults/config/platform/zmax_product.json 在位", bool(d), SKEL)
chk("三档 550A/550B/550C 齐", set(("550A", "550B", "550C")) <= set(prods), list(prods.keys()))
_keys = ("role", "new_algorithms", "topics", "comm", "gui", "vscode_debug", "remote_bypass")
for p in ("550A", "550B", "550C"):
    dp = (prods.get(p) or {}).get("dev_profile") or {}
    _miss = [k for k in _keys if k not in dp]
    chk("  %s dev_profile 关键键齐" % p, not _miss, _miss or "全在 (role=%s)" % str(dp.get("role"))[:22])

print("② 三档真不同 (老倪三产品分工逐条)")
a = (prods.get("550A") or {}).get("dev_profile") or {}
b = (prods.get("550B") or {}).get("dev_profile") or {}
c = (prods.get("550C") or {}).get("dev_profile") or {}
chk("550A = 新技能/新算法 (new_algorithms 开 + logic_depth=max)",
    a.get("new_algorithms") in ("on", True or "debug", "debug") and str(a.get("logic_depth")) == "max",
    "new_algorithms=%s logic_depth=%s" % (a.get("new_algorithms"), a.get("logic_depth")))
chk("550B = 全 topic + vscode 联调 + 信号/3D 全开",
    b.get("topics") == "all" and b.get("vscode_debug") is True and bool((b.get("gui") or {}).get("signal_analysis"))
    and bool((b.get("gui") or {}).get("scene_3d")),
    "topics=%s vscode=%s gui=%s" % (b.get("topics"), b.get("vscode_debug"), b.get("gui")))
chk("550C = 量产: 关新算法 + 白名单 + comm=shm + 不发 topic + 不开信号/3D",
    c.get("new_algorithms") in ("off", False) and str(c.get("comm")) == "shm" and c.get("topics") in ("none", "shm")
    and bool(c.get("verified_algorithms")) and not bool((c.get("gui") or {}).get("signal_analysis"))
    and not bool((c.get("gui") or {}).get("scene_3d")),
    "comm=%s topics=%s 白名单 %d 条 gui=%s" % (c.get("comm"), c.get("topics"),
                                             len(c.get("verified_algorithms") or []), c.get("gui")))
chk("三档 dev_profile 互不相同", len({json.dumps(x, sort_keys=True, ensure_ascii=False) for x in (a, b, c)}) == 3)

print("③ 真回落: 模拟全新安装 (只有 defaults, 没有 config/)")
_tmp = tempfile.mkdtemp(prefix="zmax_fresh_install_")
try:
    os.makedirs(os.path.join(_tmp, "tools"))
    shutil.copy2(os.path.join(ROOT, "tools", "zmax_profile.py"), os.path.join(_tmp, "tools", "zmax_profile.py"))
    os.makedirs(os.path.join(_tmp, "defaults", "config", "platform"))
    shutil.copy2(SKEL, os.path.join(_tmp, "defaults", "config", "platform", "zmax_product.json"))
    # 故意**不**建 config/ ⇒ 只能靠出厂骨架
    _code = ("import sys, json; sys.path.insert(0, %r);"
             "from tools import zmax_profile as Z;"
             "print(json.dumps({'path': Z.product_json(), 'active': Z.product(),"
             " 'profiles': {p: {k: Z.dev_profile(p).get(k) for k in"
             " ('new_algorithms','topics','comm','vscode_debug','role')} for p in ('550A','550B','550C')}},"
             " ensure_ascii=False))" % _tmp)
    r = subprocess.run([sys.executable, "-c", _code], capture_output=True, text=True, cwd=_tmp)
    chk("子进程 (无 config/) 能读到产品真源", r.returncode == 0, (r.stderr or "")[-160:])
    if r.returncode == 0:
        j = json.loads(r.stdout.strip().splitlines()[-1])
        chk("回落路径 = 出厂骨架", j["path"].endswith("defaults/config/platform/zmax_product.json"), j["path"])
        chk("三档都读得到且各自 dev_profile 正确",
            set(j["profiles"]) == {"550A", "550B", "550C"}
            and j["profiles"]["550B"]["topics"] == "all"
            and j["profiles"]["550C"]["comm"] == "shm"
            and j["profiles"]["550A"]["new_algorithms"] in ("on", True, "debug"),
            {k: (v["new_algorithms"], v["topics"], v["comm"]) for k, v in j["profiles"].items()})
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

print("④ studio 标题读侧也回落")
_s = open(os.path.join(ROOT, "tools", "gui", "studio.py"), encoding="utf-8").read()
chk("studio 有 _product_json_path() 回落函数", "_product_json_path" in _s)
chk("studio 读产品真源走回落路径", 'open(_product_json_path(), "r", encoding="utf-8")' in _s)
chk("studio 候选含冻结包 _MEIPASS/defaults", '_MEIPASS' in _s and 'defaults", "config", "platform' in _s)

print("⑤ 打包 job 真带骨架")
_w = open(WF, encoding="utf-8").read()
chk("Windows job 带 --add-data defaults", "--add-data \"$env:GITHUB_WORKSPACE\\defaults;defaults\"" in _w)
chk("macOS job 带 --add-data defaults", '--add-data "$GITHUB_WORKSPACE/defaults:defaults"' in _w)
chk("打包前断言三档在 (骨架自检)", "factory products:" in _w and "550A" in _w)

print("⑥ 现役档位不被骨架顶掉 (实例真源优先)")
sys.path.insert(0, ROOT)
from tools import zmax_profile as Z2                                                # noqa: E402
chk("现场仍读实例真源", Z2.product_json() == INST, Z2.product_json())
chk("现场在役档 = 550B (与配置中心同源)", Z2.product() == "550B", Z2.product())

print("⑦ 三产品开发分工判据本体")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "verify_product_dev_profiles.py")],
                   capture_output=True, text=True, cwd=ROOT)
chk("verify_product_dev_profiles 仍过", r.returncode == 0, (r.stdout or "").strip().splitlines()[-1:] or r.stderr[-120:])

print("\n" + "=" * 82)
print("结论: %s" % ("✅ 三档 550A/550B/550C 随包发布 (出厂骨架 + 读侧回落 + 打包带上), 现役 550B 不受影响"
                    if ok else "❌ 未通过"))
print("=" * 82)
sys.exit(0 if ok else 1)
