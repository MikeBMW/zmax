#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L5(DeepSeek VL) 引导小步移动 —— 给建图取景用。

为什么要有它: D405 只有 0.07~1.0m 有效量程; 现场"该往哪走"用固定脚本猜不准(相机装歪一点就全错),
而人一眼就能看出"台面在画面左下、太远"。所以把这一步交给视觉大模型, 输出**受限 JSON**,
由外层只接受 6 个预定义方向 + 限幅步长 ⇒ 模型不可能输出危险动作。

用法:
  vl_move_guide.py --img /tmp/arm.jpg --view arm
  vl_move_guide.py --img /tmp/top.jpg --view top

输出(单行 JSON):
  {"ok":true,"see":"...","subject":"table|workpiece|tray|none","where":"left|center|right|up|down|full",
   "distance":"near|ok|far","move":"left|right|forward|backward|down|none","mm":40,"why":"..."}
"""
import argparse
import base64
import json
import os
import re

ENV = os.path.expanduser("~/.hermes/.env")

ALLOWED_MOVE = ("left", "right", "forward", "backward", "down", "none")

PROMPT = """你是工业机械臂的视觉向导。机械臂末端装着深度相机, 现在要让它对准台面上的工件/料盘来建图。
看这张{view}画面, 只回答下面 6 项, 用 JSON 输出, 不要多余文字:
{{
 "see": "不超过20字的客观描述",
 "subject": "table|workpiece|tray|none",
 "where": "主体在画面的位置: left|center|right|up|down|full",
 "distance": "近|正好|远 (主体离相机大致多远; 看不出就写 未知)",
 "move": "下一步该让机械臂往哪走: left|right|forward|backward|down|none",
 "mm": 20到80之间的整数(不确定就给30),
 "why": "一句话理由"
}}
判据: 如果画面里台面/工件只占一小块或明显在边缘 ⇒ 朝它所在的方向走; 如果是大片背景/远处墙面 ⇒ 往前走或往下;
如果主体已经充满画面且清楚 ⇒ move 填 none。绝对不要建议上升。"""


def _env(key, default=""):
    if os.environ.get(key):
        return os.environ[key]
    try:
        for ln in open(ENV, encoding="utf-8"):
            ln = ln.strip()
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return default


def ask(img_path, view="arm", timeout=300):
    base = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    key = _env("DEEPSEEK_API_KEY")
    model = _env("DEEPSEEK_VLM_MODEL", "deepseek-v4-flash")
    if not key:
        return {"ok": False, "err": "DEEPSEEK_API_KEY 未配置", "hint": ENV}
    b64 = base64.b64encode(open(img_path, "rb").read()).decode()
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
            {"type": "text", "text": PROMPT.format(view=view)},
        ]}],
        "max_tokens": 3000,
    }
    import urllib.request
    req = urllib.request.Request(
        base + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode() or "{}")
    msg = (d.get("choices") or [{}])[0].get("message") or {}
    txt = (msg.get("content") or "").strip()
    m = re.search(r"\{.*\}", txt, re.S)
    j = None
    if m:
        try:
            j = json.loads(m.group(0))
        except Exception:
            j = None
    if j is None:                       # 输出被截断时按字段保障抓(模型偶发把 see 写超长)
        j = {}
        for k in ("see", "subject", "where", "distance", "move", "why"):
            mm2 = re.search(r'"%s"\s*:\s*"([^"]*)"' % k, txt)
            if mm2:
                j[k] = mm2.group(1)
        mm3 = re.search(r'"mm"\s*:\s*(\d+)', txt)
        if mm3:
            j["mm"] = int(mm3.group(1))
        if not j.get("move"):
            return {"ok": False, "err": "模型没给可用 JSON", "raw": txt[:400], "model": model}
    mv = str(j.get("move") or "none").strip().lower()
    if mv not in ALLOWED_MOVE:
        mv = "none"
    try:
        mm = int(float(j.get("mm") or 30))
    except Exception:
        mm = 30
    mm = max(20, min(80, mm))
    return {"ok": True, "see": j.get("see"), "subject": j.get("subject"),
            "where": j.get("where"), "distance": j.get("distance"),
            "move": mv, "mm": mm, "why": j.get("why"), "model": model,
            "usage": d.get("usage")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--view", default="arm", choices=["arm", "top"])
    a = ap.parse_args()
    print(json.dumps(ask(a.img, a.view), ensure_ascii=False))


if __name__ == "__main__":
    main()
