#!/usr/bin/env python3
"""判据: 快反射层「只提示不拦」开关真的生效(且关掉后立刻回 fail-closed)。

老倪 2026-10-12: 「别拦我，有提示就行了。」
验证对象 = 执行器里的真判定函数 `l2_daemon._fast_block` / `_fast_warn_only`(不是我自己另写一套)。
零下发: 喂**假裁决**进去, 不下发任何动作、不碰真设备。
"""
import importlib.util, json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
FILE = os.path.join(ROOT, "tools", "l2_daemon.py")
SW = os.path.expanduser("~/zmax/zmax_data/vl_fast_warn_only.json")
P = F = 0


def ok(c, m):
    global P, F
    if c:
        P += 1; print("  ✅ %s" % m)
    else:
        F += 1; print("  ❌ %s" % m)


def load():
    spec = importlib.util.spec_from_file_location("l2d", FILE)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


print("=== ① 执行器模块能安全 import(有 __main__ 保护, 不会起第二个执行器) ===")
src = open(FILE, encoding="utf-8").read()
ok('if __name__ == "__main__":' in src, "有 __main__ 保护")
before = subprocess.run(["pgrep", "-fc", "tools/l2_daemon.py"], capture_output=True, text=True).stdout.strip()
m = load()
after = subprocess.run(["pgrep", "-fc", "tools/l2_daemon.py"], capture_output=True, text=True).stdout.strip()
ok(before == after, "import 前后执行器实例数不变(%s→%s)" % (before, after))

print("\n=== ② 开关文件在 → _fast_warn_only() 为真 ===")
d = json.load(open(SW, encoding="utf-8")) if os.path.exists(SW) else {}
on, why = m._fast_warn_only()
print("   开关: %s" % json.dumps(d, ensure_ascii=False))
ok(on is True and d.get("enabled") is True, "开关=开 ⇒ _fast_warn_only()=%s (%s)" % (on, why))

print("\n=== ③ 开了开关: 遮挡/糊化裁决 ⇒ **不拦**(只提示) ===")
bad = {"safe": False, "unsafe_cams": ["local"], "why": "local: 遮挡/糊化(uniform=1.00 lap=0 mean=5)", "ts": time.time()}
blk, msg = m._fast_block(bad, 0.1, 4.0)
print("   ⇒ 拦=%s · 日志=%s" % (blk, msg))
ok(blk is False, "不再拒发(现场要的: 有提示就行)")
ok("只提示不拦" in msg and "遮挡" in msg, "日志里仍写明原因 + “只提示不拦”(提示还在)")

print("\n=== ④ 其它两种快层故障同样只提示: 裁决过期 / 裁决缺失 ===")
blk2, msg2 = m._fast_block({"safe": True}, 9.9, 4.0)
ok(blk2 is False and "过期" in msg2, "裁决过期 ⇒ 不拦(日志=%s)" % msg2[:70])
blk3, msg3 = m._fast_block({}, 0.0, 4.0, err=RuntimeError("裁决文件缺失"))
ok(blk3 is False and "缺失" in msg3, "裁决缺失 ⇒ 不拦(日志=%s)" % msg3[:70])

print("\n=== ⑤ 正常裁决仍然照常放行(没改坏) ===")
good = {"safe": True, "unsafe_cams": [], "why": "臂上/笔记本画面纹理正常、无遮挡", "ts": time.time()}
blk4, msg4 = m._fast_block(good, 0.2, 4.0)
ok(blk4 is False and "放行" in msg4, "safe=True ⇒ 放行(日志=%s)" % msg4)

print("\n=== ⑥ 关掉开关(off) ⇒ **立刻**回 fail-closed, 且不用重启执行器 ===")
r = subprocess.run([PY, os.path.join(ROOT, "tools", "vl_fast_warn_ctl.py"), "off", "--by", "判据", "--note", "临时验证"],
                   capture_output=True, text=True, timeout=60, cwd=ROOT)
ok(r.returncode == 0, "off 执行成功")
on2, why2 = m._fast_warn_only()
ok(on2 is False, "关掉后 _fast_warn_only()=%s" % on2)
blk5, msg5 = m._fast_block(bad, 0.1, 4.0)
ok(blk5 is True and "拒发" not in msg5, "同样的遮挡裁决 ⇒ 又拦了(拦=%s · %s)" % (blk5, msg5[:70]))
blk6, _ = m._fast_block({"safe": True}, 9.9, 4.0)
ok(blk6 is True, "裁决过期 ⇒ 又拦(minutes=0 的开关文件不再被当成开)")

print("\n=== ⑦ 审计: 开关动作都留痕 ===")
AUD = SW + "l"
lines = open(AUD, encoding="utf-8").read().strip().splitlines() if os.path.exists(AUD) else []
ok(len(lines) >= 2, "审计 %s 有 %d 行(开/关/查询各一行)" % (os.path.basename(AUD), len(lines)))
ok(any('"cmd": "off"' in l for l in lines[-3:]), "最近有 off 记录(谁/何时/为什么)")

print("\n=== ⑧ 恢复现场口径(重开开关) ===")
# 备份文件已由 off 动作生成 ⇒ 直接从备份恢复, 保住 by/note 原值
baks = sorted([f for f in os.listdir(os.path.dirname(SW)) if f.startswith(os.path.basename(SW) + ".bak_")])
if baks:
    import shutil
    shutil.copyfile(os.path.join(os.path.dirname(SW), baks[-1]), SW)
    on3, why3 = m._fast_warn_only()
    ok(on3 is True, "已从备份恢复开关=%s (%s)" % (on3, why3[:60]))
else:
    ok(False, "没找到备份文件")

print("\n=== 汇总: PASS %d · FAIL %d ===" % (P, F))
sys.exit(1 if F else 0)
