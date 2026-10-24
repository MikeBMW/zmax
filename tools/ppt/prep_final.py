# -*- coding: utf-8 -*-
"""prep_final.py — 14 家真机图 → fig6/<data_v5 里的 key>.jpg"""
import os

from PIL import Image, ImageOps

OUT = "/home/ubuntu/zmax_data/deliverables/robotics_landscape_2026-10-23/fig6"
os.makedirs(OUT, exist_ok=True)

MAP = {
    "/tmp/robots/agibot_c5.img": "zhiyuan",
    "/tmp/robots/galbot_c0.img": "galbot",
    "/tmp/robots/ai2_c0.img": "zhipingfang",
    "/tmp/robots/ubtech_c5.img": "ubtech",
    "/tmp/robots/neura_0.img": "neura",
    "/tmp/robots5/aubo_1.img": "aubo",
    "/tmp/robots5/fanuc_2.img": "fanuc",
    "/tmp/robots5/flexiv_0.img": "flexiv",
    "/tmp/robots5/jaka_1.img": "jaka",
    "/tmp/robots5/jiazhi_2.img": "jiazhi",
    "/tmp/robots5/productive_0.img": "productive",
    "/tmp/robots5/techman_0.img": "techman",
    "/tmp/robots5/xinsong_1.img": "xinsong",
    "/tmp/robots5/yunshenchu_0.img": "yunshenchu",
}
W, H = 900, 1125            # 4:5 竖构图，适合型号卡

# 清掉之前那批错名的
for f in os.listdir(OUT):
    if f.endswith(".jpg") and f.split(".")[0] not in MAP.values():
        os.remove(os.path.join(OUT, f))

for src, key in MAP.items():
    if not os.path.exists(src):
        print("缺 %s" % src)
        continue
    im = Image.open(src)
    if im.mode in ("P", "RGBA", "LA"):
        bg = Image.new("RGB", im.size, "white")
        _ = im.convert("RGBA")
        bg.paste(_, mask=_.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    canvas = Image.new("RGB", (W, H), "white")
    fit = ImageOps.contain(im, (W - 20, H - 20), Image.LANCZOS)
    canvas.paste(fit, ((W - fit.width) // 2, (H - fit.height) // 2))
    dst = os.path.join(OUT, key + ".jpg")
    canvas.save(dst, quality=88, optimize=True)
    print("%-14s ← %-28s %6d B" % (key, os.path.basename(src), os.path.getsize(dst)))
print("\nfig6 共 %d 张" % len([f for f in os.listdir(OUT) if f.endswith(".jpg")]))
