#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ar_layout.py — 8797 AR/VR 页的「三维视图与相机窗口同尺寸 + 三个坐标系」判据

老倪 2026-10-12:「VR 三维视图(base 系, 拖动可转) 要跟相机的窗口一样大, 现在太小了, 就放在相机窗口的下面;
你已经指导了机器人的世界坐标系, 也知道了当前的坐标系是 tool1 的, 即夹爪的坐标系, 你能看到机器人的每个坐标系么?
世界坐标系, tool0 是 6 轴末端的法兰盘中心点, tool1 是夹爪夹住光模块(手臂相机看到的屏幕最下方的小光模块头部的中心点)」

口径(实测过一次就固化):
  A. 版面: 左列 = 相机窗口(#stagewrap) + 三维视图(#vrcard>#vr), 三维视图在相机窗口**下面**且**同宽同高**;
     右栏(aside)不许再有 #vr; #vr 全页只出现一次。
  B. 尺寸: 画布高由 syncVr() 跟着相机窗口 clientHeight 走(宽度靠 CSS 通宽 calc(100% + 24px) 抵消卡内边距)。
  C. 坐标系: 服务端 /api/tcp 必须给 frames(base / tool0 / tool1) ——
     tool1 = 珞石 endInRef 上报位姿(控制器 toolset=tool1);
     tool0(法兰) = tool1 ⊖ URDF tool0→tool1 固定位姿(与姿态无关, 两点相距 259.8mm);
     三轴必须是单位正交列(数值自检)。
  D. 画面: 页面上真的画出来了(红X/绿Y/蓝Z 三色轴) —— 这一条要在浏览器里量(本脚本只做静态部分, 见末尾提示)。

用法: python3 tools/verify_ar_layout.py            # 静态 + 服务端(需 8797 在跑)
返回码: 0 = 全过
"""
import json
import math
import os
import re
import subprocess
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(REPO, "tools", "web", "tcp-ar.html")
AR = os.environ.get("AR_URL", "http://127.0.0.1:8797")
ok_n = 0
bad = []


def chk(cond, msg, detail=""):
    global ok_n
    if cond:
        ok_n += 1
        print("  ✅", msg)
    else:
        bad.append(msg)
        print("  ❌", msg, ("· " + str(detail)) if detail else "")


def main():
    src = open(PAGE, encoding="utf-8").read()
    print("═══ A. 版面: 三维视图在相机窗口下面 ═══")
    m = re.search(r'<div id="leftcol">(.*?)<aside>', src, re.S)
    col = m.group(1) if m else ""
    chk(bool(col), "#leftcol 存在(把相机与三维视图包成一列)")
    chk('id="stagewrap"' in col, "#leftcol 里有相机窗口 #stagewrap")
    chk('id="vrcard"' in col, "#leftcol 里有三维视图 #vrcard")
    chk(col.find('id="stagewrap"') < col.find('id="vrcard"'), "三维视图排在相机窗口**之后**(在下面)")
    chk(src.count('id="vr"') == 1, "#vr 全页只出现一次(没在别处留重复画布)", src.count('id="vr"'))
    chk(not re.search(r'<aside>.*?id="vr"', src, re.S), "右栏 aside 里没有旧的 #vr")

    print("═══ B. 尺寸: 跟相机窗口一样大 ═══")
    chk(re.search(r'#vrcard\s+#vr\{[^}]*calc\(100% \+ 24px\)', src) is not None,
        "画布通宽(calc(100% + 24px) 抵消卡内边距) ⇒ 与相机窗口同宽")
    chk("function syncVr()" in src, "syncVr() 存在(画布高 = 相机窗口 clientHeight)")
    chk("syncVr();" in src, "syncVr() 挂进了布局链(applyRot/ResizeObserver)")

    print("═══ C. 三个坐标系(base / tool0 / tool1) ═══")
    for k in ("'base'", "'tool0'", "'tool1'"):
        chk(k in src, "页面里画 %s" % k)
    chk("VR.frames" in src, "有 🧭 坐标系 开关(VR.frames)")
    chk("frames" in src and "flange_mm" in src, "读数里给出 tool0/tool1 与法兰间距")

    print("═══ D. 服务端 /api/tcp 的 frames(真算一遍对照) ═══")
    try:
        d = json.load(urllib.request.urlopen(AR + "/api/tcp", timeout=10))
    except Exception as e:                                                        # noqa: BLE001
        chk(False, "取 %s/api/tcp" % AR, e)
        return summary()
    chk(bool(d.get("ok")), "/api/tcp ok")
    chk(d.get("frame") == "base_link", "frame = base_link(世界/基座系)", d.get("frame"))
    fr = d.get("frames") or {}
    chk(set(("base", "tool0", "tool1")) <= set(fr), "frames 含 base/tool0/tool1", sorted(fr))
    chk(fr.get("base", {}).get("origin") == [0.0, 0.0, 0.0], "base 原点 = (0,0,0)")

    # 独立实现: tool0 = tool1 ⊖ URDF tool0→tool1 固定位姿
    q = [float(v) for v in d["quat"]]
    _qnorm = math.sqrt(sum(t * t for t in q))
    x, y, z, w = [t / _qnorm for t in q]
    R1 = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    r, p, yw = d["tool01_const"]["rpy"]
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(yw), math.sin(yw)
    Roff = [[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr]]
    Rt = [[Roff[j][i] for j in range(3)] for i in range(3)]
    tt = [sum(Rt[i][j] * d["tool01_const"]["xyz"][j] for j in range(3)) for i in range(3)]
    p1 = [d["x"], d["y"], d["z"]]
    p0 = [p1[i] - sum(R1[i][k] * tt[k] for k in range(3)) for i in range(3)]
    srv0 = fr.get("tool0", {}).get("origin", [9, 9, 9])
    chk(all(abs(p0[i] - srv0[i]) < 1e-5 for i in range(3)),
        "tool0(法兰) = 独立算的值(差 <1e-5m)", "我=%s 服务端=%s" % ([round(v, 5) for v in p0], srv0))
    chk(abs(fr.get("flange_mm", 0) - 259.8) < 0.2, "法兰↔模块头 = 259.8mm", fr.get("flange_mm"))
    for k in ("tool0", "tool1"):
        ax = fr.get(k) or {}
        lens = [math.sqrt(sum(v * v for v in ax[a])) for a in ("x", "y", "z")]
        dots = [abs(sum(ax["x"][i] * ax["y"][i] for i in range(3))), abs(sum(ax["x"][i] * ax["z"][i] for i in range(3))),
                abs(sum(ax["y"][i] * ax["z"][i] for i in range(3)))]
        chk(all(abs(v - 1) < 1e-4 for v in lens) and max(dots) < 1e-4,
            "%s 三轴单位正交" % k, "len=%s dot=%s" % ([round(v, 5) for v in lens], [round(v, 5) for v in dots]))

    print("═══ E. 页面 JS 语法(全块 node --check) ═══")
    if subprocess.run(["which", "node"], capture_output=True).returncode == 0:
        nb = 0
        for i, b in enumerate(re.findall(r"<script[^>]*>(.*?)</script>", src, re.S)):
            f = "/tmp/_arjs_%d.js" % i
            open(f, "w").write(b)
            r = subprocess.run(["node", "--check", f], capture_output=True, text=True)
            nb += 1
            chk(r.returncode == 0, "JS 块 %d 语法" % i, (r.stderr or "")[:200])
        chk(nb > 0, "确实抽到 script 块")
    else:
        print("  ⚠️ 没装 node ⇒ 跳过 JS 语法检查")

    print("\n(画面侧证据: 在浏览器里量 —— canvas#vr 的 clientHeight 应等于 #stagewrap.clientHeight, "
          "且 #vr 的 top ≥ #stagewrap 的 bottom; 画布上红X/绿Y/蓝Z 像素数 > 0)")
    return summary()


def summary():
    print("\n" + ("═" * 46))
    if bad:
        print("❌ 未过 %d 项: %s" % (len(bad), "; ".join(bad)))
        return 1
    print("✅ 全部通过 (%d 项)" % ok_n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
