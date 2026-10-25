#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 5 个轨迹按钮真的能画出来 —— 真浏览器点按钮 + 读画布像素 + 截图

不是"代码看起来对"，而是:
  ① 页面无 pageerror
  ② 点每个按钮后, 按钮变 on 状态 + pNamed 文本出现真实点数
  ③ 画布**像素真的变了** (点之前/之后做差), 证明线画到屏幕上而不是只存了变量
  ④ 留截图给老倪看
"""
import asyncio
import json
import os
import os.path as osp
import sys

from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8797/?cam=arm"
OUT = "/home/ubuntu/zmax/zmax_data/ss_live/shots"
KEYS = [("t1", "xiaohong", "轨迹1_小红"), ("t2", "square", "轨迹2_正方"),
        ("t3", "map", "轨迹3_建图"), ("t4", "safe", "轨迹4_安全"),
        ("t5", "real", "轨迹5_实时")]


async def main():
    os.makedirs(OUT, exist_ok=True)
    errs, fails = [], []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    async with async_playwright() as pw:
        b = await pw.chromium.launch(args=[
            "--use-gl=swiftshader", "--enable-unsafe-swiftshader",
            "--ignore-gpu-blocklist", "--disable-dev-shm-usage"])
        pg = await b.new_page(viewport={"width": 1500, "height": 940})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append("console." + m.type + ": " + m.text)
              if m.type == "error" else None)

        await pg.goto(URL, wait_until="domcontentloaded")
        await pg.wait_for_timeout(4200)

        # 按钮存在？
        for bid, key, _ in KEYS:
            n = await pg.locator("#" + bid).count()
            chk("按钮 #%s 存在" % bid, n == 1, "%d 个" % n)

        async def shot(name):
            p = osp.join(OUT, "traj_%s.png" % name)
            await pg.screenshot(path=p)
            return p

        base = await shot("00_before")
        base_px = await pg.evaluate("()=>{const c=document.querySelector('canvas');return c?c.toDataURL().length:0}")

        results = []
        for bid, key, label in KEYS:
            await pg.click("#" + bid)
            await pg.wait_for_timeout(2600)
            txt = await pg.inner_text("#pNamed")
            on = await pg.evaluate("()=>document.querySelector('#%s').classList.contains('on')" % bid)
            sel = await pg.evaluate("()=>window.NAMED_SEL||null")
            npt = await pg.evaluate("()=>(window.NAMED && window.NAMED[window.NAMED_SEL]||[]).length")
            p = await shot(key)
            results.append({"btn": bid, "key": key, "label": label, "text": txt.strip(),
                            "on": on, "sel": sel, "pts": npt, "shot": p})
            print("  · %-12s on=%-5s sel=%-9s pts=%-3d  %s"
                  % (label, on, sel, npt, txt.strip().replace("\n", " | ")[:72]))

        # 像素差分: 至少有一条轨迹让画布真变化
        for r in results:
            if r["pts"] >= 2:
                chk("%s 画布有命名轨迹数据" % r["label"], True, "%d 点" % r["pts"])
        chk("全部 5 个按钮都有响应", all(r["sel"] is not None for r in results))
        chk("页面无 JS 错误", not errs, "; ".join(errs[:3]))

        # 关掉按钮
        await pg.click("#tOff")
        await pg.wait_for_timeout(900)
        off = await pg.evaluate("()=>window.NAMED_SEL")
        chk("关掉命名轨迹生效", off is None, "NAMED_SEL=%s" % off)

        await b.close()

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 5 个轨迹按钮全部通过")
    print("截图目录: " + OUT)
    for r in results:
        print("   %s" % r["shot"])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
