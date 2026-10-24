# -*- coding: utf-8 -*-
"""grab_all_robots.py — 批量抓 25 家官网产品图（每家取 3 张候选）"""
import os
import re
import subprocess
from urllib.parse import urljoin

OUT = "/tmp/robots5"
os.makedirs(OUT, exist_ok=True)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

SITES = {
    "qianxun": ["https://www.spirit-ai.com/", "https://spirit-ai.com/"],
    "xinghaitu": ["https://www.galaxea-ai.com/", "https://galaxea-ai.com/"],
    "zibianliang": ["https://x2robot.com/"],
    "yunshenchu": ["https://www.deeprobotics.cn/"],
    "fourier": ["https://www.fftai.com/", "https://www.fourierintelligence.com/"],
    "realman": ["https://www.realman-robotics.com/"],
    "youai": ["https://www.youibot.com/"],
    "xingdong": ["https://www.robotera.com/"],
    "kuaiwei": ["https://www.dexmal.com/"],
    "jiazhi": ["https://www.imrobotic.com/"],
    "ailite": ["https://www.elibot.cn/"],
    "jaka": ["https://www.jaka.com/"],
    "xiangong": ["https://www.seer-group.com/"],
    "hikrobot": ["https://www.hikrobotics.com/"],
    "xinsong": ["https://www.siasun.com/"],
    "aubo": ["https://www.aubo-robotics.cn/"],
    "techman": ["https://www.tm-robot.com/"],
    "flexiv": ["https://www.flexiv.com/"],
    "fanuc": ["https://www.fanuc.co.jp/", "https://www.fanuc.eu/"],
    "productive": ["https://www.productiverobotics.com/"],
    "lingxi": ["https://www.chinamobileltd.com/"],
    "zhongkehuiling": ["https://www.casbot.cn/"],
    "hechun": ["https://www.techman-robot.com/"],
    "fuwei": ["https://www.fuwei-robot.com/"],
    "youai_h": ["https://www.youibot.com/"],
}
BAD = re.compile(r"logo|icon|favicon|sprite|qr|wechat|avatar|placeholder|loading|banner|news|"
                 r"1x1|pixel|bg\.|background", re.I)


def fetch(url):
    try:
        return subprocess.run(["curl", "-sL", "-m", "20", "-A", UA, "-H",
                               "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8", url],
                              capture_output=True, timeout=30).stdout.decode("utf-8", "ignore")
    except Exception:
        return ""


for key, urls in SITES.items():
    got = 0
    for url in urls:
        html = fetch(url)
        if len(html) < 3000:
            continue
        cands = re.findall(r'<img[^>]+(?:src|data-src|data-original|data-lazy-src)=["\']([^"\']+)["\']', html, re.I)
        cands += re.findall(r'<source[^>]+srcset=["\']([^"\',\s]+)', html, re.I)
        cands += re.findall(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*content=["\']([^"\']+)', html, re.I)
        seen = set()
        for c in cands:
            if c in seen or BAD.search(c):
                continue
            seen.add(c)
            if c.startswith("//"):
                c = "https:" + c
            elif c.startswith("/"):
                c = urljoin(url, c)
            if not c.startswith("http"):
                continue
            dst = os.path.join(OUT, "%s_%d.img" % (key, got))
            try:
                subprocess.run(["curl", "-sL", "-m", "25", "-A", UA, "-e", url, "-o", dst, c],
                               capture_output=True, timeout=35)
                sz = os.path.getsize(dst) if os.path.exists(dst) else 0
                if sz < 35000:
                    os.remove(dst)
                    continue
                from PIL import Image
                im = Image.open(dst)
                im.load()
                w, h = im.size
                if w < 480 or h < 400:
                    os.remove(dst)
                    continue
                print("%-14s %4dx%-4d %7d B" % (key, w, h, sz))
                got += 1
            except Exception:
                if os.path.exists(dst):
                    try:
                        os.remove(dst)
                    except Exception:
                        pass
                continue
            if got >= 3:
                break
        if got >= 3:
            break
    if got == 0:
        print("%-14s (无)" % key)
