#!/usr/bin/env python3
"""判据: 「⛔ 被拒: (本地检测, 亚秒级)」这类**没原因**的横幅不再出现 —— 页面必须把真实原因摆出来。

老倪 2026-10-12: 「⛔ 被拒: (本地检测, 亚秒级) 又是怎么回事?」
实测根因: 执行器日志那行末尾的括号备注被 station.html 里通用的 `/拒发[：:]*(...)/` 抢先捕获
          ⇒ 横幅只剩「(本地检测, 亚秒级)」, 现场看不到**哪路相机·什么指标**。
本判据: 把 station.html 里的 `_moveReason()` 抠出来, 用真 node 跑真实日志样本, 断言返回的是**原因**。
"""
import os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "tools", "web", "station.html")
NODE = os.environ.get("ZMAX_NODE") or "/home/ubuntu/.hermes/tools/node-26.7.0-linux-x64/bin/node"

P = F = 0


def ok(c, m):
    global P, F
    if c:
        P += 1; print("  ✅ %s" % m)
    else:
        F += 1; print("  ❌ %s" % m)


src = open(HTML, encoding="utf-8").read()
i = src.index("function _moveReason(")
j = src.index("\n}\n", i) + 3
fn = src[i:j]
print("=== 抠出 _moveReason(): %d 字符 ===" % len(fn))

ok("/被拦\\(快层" in fn, "① 有专门抓「🛑 被拦(快层…)」那条日志的规则(原因+相机+指标都在那条上)")
ok("纯括号" in fn or "48" in fn, "② 抓到**纯括号备注**(如「(本地检测, 亚秒级)」)会跳过, 继续找下一条")

L = ("[09:11:13] 🛡 VL 安全闸(快层): **遮挡/糊化**(['local']): local: 遮挡/糊化(uniform=1.00 lap=0 mean=5) ⇒ 拒发(本地检测, 亚秒级)\n"
     "[09:11:13] 🛑 被拦(快层·本地反射(5Hz)): 遮挡/糊化 ['local']: local: 遮挡/糊化(uniform=1.00 lap=0 mean=5)\n"
     "[09:11:13] 受理: 🛑 被拦(快层·本地反射(5Hz)): 遮挡/糊化 ['local']: local: 遮挡/糊化(uniform=1.00 lap=0 mean=5)")

CASES = [
    ("快层遮挡(现场原样)", {"msg": "", "lines": L.split("\n")}, ["遮挡", "local", "uniform"]),
    ("包络出界", {"msg": "⛔ 目标出已验证包络: x=0.3348 越界[0.3368, 0.7975]", "lines": []}, ["越界", "0.3348"]),
    ("未授权", {"msg": "", "lines": ["⛔ 未授权真动: 需现场授权窗"]}, ["未授权"]),
    ("只有一句括号(旧 bug 的输入)", {"msg": "", "lines": ["⇒ 拒发(本地检测, 亚秒级)"]}, ["拒发"]),
    ("空输入", {"msg": "", "lines": []}, []),
]

script = fn + "\nconst CASES=%s;\nfor(const [n,j,need] of CASES){const r=_moveReason(j);console.log(JSON.stringify({n,r,need}));}\n" % (
    __import__("json").dumps(CASES, ensure_ascii=False))
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
    f.write(script); tmp = f.name

print("\n=== 真 node 跑 %s ===" % os.path.basename(NODE))
out = subprocess.run([NODE, tmp], capture_output=True, text=True, timeout=60)
os.unlink(tmp)
if out.returncode != 0:
    print(out.stdout[-800:], out.stderr[-800:])
ok(out.returncode == 0, "③ node 执行成功(说明抠出的 JS 语法就是页面上跑的)")

rows = {}
for line in out.stdout.splitlines():
    try:
        d = __import__("json").loads(line)
    except Exception:
        continue
    rows[d["n"]] = d

for n, _, need in CASES:
    r = rows.get(n, {}).get("r", None)
    if need:
        ok(r is not None and all(k in (r or "") for k in need), "④ 「%s」⇒ 横幅 = %r" % (n, (r or "")[:90]))
    else:
        ok(r == "", "④ 「%s」⇒ 空(不瞎报)" % n)

# 关键回归: 绝不允许再把「(本地检测, 亚秒级)」当唯一原因
bad = rows.get("快层遮挡(现场原样)", {}).get("r", "")
ok(not re.fullmatch(r"^[（(][^（()）]{0,48}[)）]$", (bad or "").strip()),
   "⑤ 回归红线: 快层那条不再只返回一句括号 (实际 = %r)" % (bad or "")[:70])
ok("⊘" not in (bad or "") and "本地检测" not in (bad or "").split(":")[0],
   "⑥ 返回里有「遮挡」这类**人话原因**(不是内部备注)")

print("\n=== 汇总: PASS %d · FAIL %d ===" % (P, F))
sys.exit(1 if F else 0)
