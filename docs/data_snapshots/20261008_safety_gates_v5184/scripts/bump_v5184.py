#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v5.18.3 → v5.18.4 五处版本号同步 + VERSION.md 表行 + studio.py changelog 行。
   教训(上一轮): ①窗口标题锚点别带空格 ②changelog 行行首必须有 #(否则 integrity_check 的 ast.parse 拦住)
   ③VERSION.md 表无分隔行。本脚本每处改完立刻回读核验。"""
import os
import re
import sys

REPO = "/home/ubuntu/zmax"
OLD, NEW = "5.18.3", "5.18.4"
os.chdir(REPO)

CHANGELOG = (
    "# v5.18.4: 运动安全三件套(2026-10-08 一天三起近失事故后收口) —— "
    "① 安全区天花板闸: 老倪两次逐字「给你的空间点1～点7, 就是安全区域, 你要参考, 不要上升的太高」⇒ "
    "天花板 = 7 点最高 z + 50mm(0.3885); 执行器每阶段硬拦(目标超则拒发, 单段也拦) + 代理扫掠闸门每 0.15s 真值比对"
    "(包络 z 上限 0.6987→0.3885); 已做故意违规实测(临时压到 0.20)确认拒发且臂零位移。 "
    "② MoveJ 自愈默认关: 事故根因 = MoveL 判 50102 奇异点后被 MoveJ 接管, 关节插值不受 Δz 约束 ⇒ 臂自己往高处摆(老倪急停); "
    "现只有显式 ZMAX_MOVEJ_RETRY=1 才开, 升高类永不许开(唯一出路 = 停 + 问人)。 "
    "③ 回点配方改三段单轴: 斜线(space1→space7 Δ=(-11.5,+101.3,+86.0)mm)穿奇异构型被 50102 拒 ⇒ "
    "拆成「竖直抬到 max(当前z, 目标点z)+5mm → 保持高度横移 → 竖直落到位」; 横移余量 40→5mm"
    "(第三次近失根因: 目标只高 66mm 却抬 106.5mm, 40mm 全是无谓上升, 老倪当场急停)。 "
    "另: 姿态差 ≥0.3° 一律走 abs(带 rx,ry,rz)[修「绕 XYZ 三轴旋转不动」+「J6 自转只平移」], "
    "7 空间点姿态对齐 space1(旧姿态差 164° 会甩腕撞 50102), 建图移动速度 120→1000。 "
    "全部改动配事故档 docs/INCIDENT-20261008-*.md + 台账 + 碰撞库(8 条)。"
)

VERSION_ROW = (
    "| **v5.18.4** | 10-08 | 运动安全三件套(一天三起近失事故后收口): "
    "**① 安全区天花板闸** —— 老倪逐字「给你的空间点1～点7 就是安全区域, 不要上升的太高」⇒ 天花板 = 7 点最高 z+50mm = 0.3885m, "
    "三处收口(执行器每阶段硬拦含单段 · 代理扫掠闸门 0.15s 真值比对, 包络 z 0.6987→0.3885 · MoveJ 自愈关); "
    "故意违规实测(天花板临时压到 0.20)确认「拒发 + 臂零位移」。 "
    "**② MoveJ 自愈默认关**(MOVEJ_RETRY 默认 False, 只认 ZMAX_MOVEJ_RETRY=1) —— 事故根因: MoveL 判 50102 奇异点后 MoveJ 接管, "
    "关节插值不受 Δz 约束 ⇒ 臂自己往高处摆。**③ 回点配方改三段单轴** —— 斜线穿奇异构型被 50102 拒, 拆成"
    "「竖直抬到 max(当前z,目标点z)+5mm → 保持高度横移 → 竖直落到位」, 横移余量 40→5mm(一处近失根因: 目标只高 66mm 却抬 106.5mm, 40mm 全无谓); "
    "旋转变更为姿态差 ≥0.3° 一律走 abs(带 rx,ry,rz)(修「绕 XYZ 三轴旋转不动」「J6 自转只平移」); 7 空间点姿态对齐 space1(旧差 164° 必撞 50102); "
    "建图移动速度 120→1000。 事故档 3 份 + 台账 + 碰撞库 8 条 + 现场数据快照 docs/data_snapshots/。 |\n"
)


def rd(p):
    return open(p, encoding="utf-8").read()


def wr(p, s):
    open(p, "w", encoding="utf-8").write(s)


report = []


def rep(what, ok, detail=""):
    report.append("  %s %-46s %s" % ("✅" if ok else "❌", what, detail))


# ① studio.py: 品牌小字 + 两个窗口标题(用不带空格的锚点, 避免上轮踩的空格坑) + changelog 行
p = "tools/gui/studio.py"
s = rd(p)
n1 = s.count("Z-MAX v%s" % OLD)
s = s.replace("Z-MAX v%s" % OLD, "Z-MAX v%s" % NEW)
assert CHANGELOG not in s
old_cl = re.search(r"^\s*# v5\.18\.3:", s, re.M)
assert old_cl, "找不到 changelog 行 v5.18.3"
s = s[:old_cl.start()] + "        " + CHANGELOG + "\n" + s[old_cl.start():]
wr(p, s)
s2 = rd(p)
rep("studio.py 品牌小字+窗口标题 (%d 处)" % n1, s2.count("Z-MAX v%s" % NEW) == n1 + 0 and n1 >= 3)
rep("studio.py changelog v5.18.4 行", ("# v5.18.4: 运动安全三件套" in s2) and s2.count("# v5.18.4:") == 1)

# ② update_checker.py
p = "tools/gui/update_checker.py"
s = rd(p)
assert 'CURRENT_VERSION = "v%s"' % OLD in s
wr(p, s.replace('CURRENT_VERSION = "v%s"' % OLD, 'CURRENT_VERSION = "v%s"' % NEW))
rep("update_checker.py CURRENT_VERSION", 'CURRENT_VERSION = "v%s"' % NEW in rd(p))

# ③ version_sync.py
p = "tools/gui/version_sync.py"
s = rd(p)
m = re.search(r'zmax_ver\s*=\s*"%s"' % OLD, s)
assert m, "version_sync 里找不到 zmax_ver"
wr(p, s[:m.start()] + 'zmax_ver = "%s"' % NEW + s[m.end():])
rep("version_sync.py zmax_ver", '"%s"' % NEW in rd(p))

# ④ docs_sync.py 两处
p = "tools/gui/docs_sync.py"
s = rd(p)
c = s.count('"v%s"' % OLD)
s = s.replace('"v%s"' % OLD, '"v%s"' % NEW)
wr(p, s)
rep("docs_sync.py version+zmax_version (%d 处)" % c, rd(p).count('"v%s"' % NEW) >= 2)

# ⑤ integrity_check.py
p = "tools/ci/integrity_check.py"
s = rd(p)
assert 'EXPECTED_VERSION = "v%s"' % OLD in s
wr(p, s.replace('EXPECTED_VERSION = "v%s"' % OLD, 'EXPECTED_VERSION = "v%s"' % NEW))
rep("integrity_check.py EXPECTED_VERSION", 'EXPECTED_VERSION = "v%s"' % NEW in rd(p))

# ⑥ VERSION.md 新表行(表无分隔行, 插在表头后 = 最前)
p = "VERSION.md"
s = rd(p)
assert "| 版本 | 日期 | 内容 |" in s and VERSION_ROW.split("|")[1].strip() not in s
hdr = "| 版本 | 日期 | 内容 |\n"
s = s.replace(hdr, hdr + VERSION_ROW, 1)
wr(p, s)
rep("VERSION.md 表行 v5.18.4", "**v5.18.4**" in rd(p).split("## 版本历史")[1][:400])

# ⑦ 语法 + 残留检查
import ast                                                                    # noqa: E402
bad = []
for p in ("tools/gui/studio.py", "tools/gui/update_checker.py", "tools/gui/version_sync.py",
          "tools/gui/docs_sync.py", "tools/ci/integrity_check.py"):
    try:
        ast.parse(rd(p))
    except SyntaxError as e:
        bad.append("%s: %s" % (p, e))
rep("五个 py 文件语法", not bad, "" if not bad else str(bad))
left = []
for p in ("tools/gui/studio.py", "tools/gui/update_checker.py", "tools/gui/version_sync.py",
          "tools/gui/docs_sync.py", "tools/ci/integrity_check.py"):
    for i, ln in enumerate(rd(p).splitlines(), 1):
        if OLD in ln and "v5.18.3:" not in ln and not re.match(r"\s*#", ln):
            left.append("%s:%d" % (p, i))
rep("旧版本残留(除 changelog 历史行)", not left, "" if not left else " ".join(left))

print("\n".join(report))
print("\n结果: %s" % ("全部通过 ✓" if all("✅" in r for r in report) else "有失败 ❌"))
sys.exit(0 if all("✅" in r for r in report) else 1)
