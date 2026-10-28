#!/usr/bin/env python3
"""AR 场景 L5 理解桥 —— 把「底图一帧」交给**引擎 L5**(left_right/state_space/scene_vlm.py :: SceneVLM)理解。

为什么要桥: 引擎会拉 torch(实测 ~GB 级), 而 AR 服务(8797)是常驻的轻进程 —— 直接在服务里 import
引擎会把常驻内存顶到红线(同刻只允许一个模型进程)。⇒ 用**子进程桥**: 理解完就退出, 内存还给系统。
解释器与口径与 tools/l5_hil_agent.py 完全一致(gui-venv311), 提示词/解析复用 tools/gen_overlay_from_vlm.py。

用法:
  ./gui-venv311/bin/python tools/ar_l5_understand.py --jpg /tmp/f.jpg --w 640 --h 480 [--hint "..."] [--cam arm]
输出(单行 JSON, 永远可解析; 失败也如实回 ok=False):
  {"ok":true,"text":"...","boxes":[...],"n_boxes":N,"model":"...","latency_s":1.2,"via":"engine:SceneVLM"}
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space"))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _load_by_path(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _publish_scene_vec(boxes, w, h, model):
    """把 L5 的场景理解落成**一个三维方向矢量** (给分层力 L5 用)。

    口径 (只做能追溯到画面的换算, 不编):
      取面积最大的目标框 → 框心相对画面中心的偏移 (归一化 dx,dy) → 相机系方向 (dx, -dy, 0) 归一
      → 乘该框置信度 (没有置信度就按 0.5, 并在 src 里写明)。
    输出 zmax_data/ss_live/l5_scene_vec.json:
      {"vec":[x,y,z], "conf":c, "ts":..., "src":"ar_l5_understand:<model>", "box":[cx,cy,bw,bh], "w":w, "h":h}
    没有框 ⇒ vec=null (调用方据此写"缺 L5", 不拿 0 冒充)。
    """
    try:
        import math as _m
        import time as _t
        vec, conf, bb = None, 0.0, None
        if boxes:
            def _area(b):
                try:
                    return float(b.get("w") or b.get("bw") or 0) * float(b.get("h") or b.get("bh") or 0)
                except Exception:                                                # noqa: BLE001
                    return 0.0
            b = max(boxes, key=_area)
            cx = float(b.get("cx") or b.get("x") or 0) + float(b.get("w") or b.get("bw") or 0) / 2.0
            cy = float(b.get("cy") or b.get("y") or 0) + float(b.get("h") or b.get("bh") or 0) / 2.0
            conf = float(b.get("conf") or b.get("score") or 0.5)
            dx = (cx - w / 2.0) / max(1.0, w / 2.0)
            dy = (cy - h / 2.0) / max(1.0, h / 2.0)
            n = _m.hypot(dx, dy)
            vec = [0.0, 0.0, 0.0] if n < 1e-6 else [dx / n * conf, -dy / n * conf, 0.0]
            bb = [round(cx, 1), round(cy, 1), b.get("w") or b.get("bw"), b.get("h") or b.get("bh")]
        out = {"ts": _t.time(), "vec": vec, "conf": conf, "box": bb, "w": w, "h": h,
               "src": "ar_l5_understand:%s" % (model or "SceneVLM")}
        path = os.path.join(ROOT, "zmax_data", "ss_live", "l5_scene_vec.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        os.replace(tmp, path)
        return out
    except Exception:                                                            # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jpg", required=True, help="要理解的图(与页面看到的是同一路的快照)")
    ap.add_argument("--w", type=int, default=640)
    ap.add_argument("--h", type=int, default=480)
    ap.add_argument("--hint", default="")
    ap.add_argument("--cam", default="")
    ap.add_argument("--max-tokens", type=int, default=0)
    a = ap.parse_args()

    t0 = time.time()
    out = {"ok": False, "via": "engine:SceneVLM", "cam": a.cam}
    try:
        from lerobot.policies.left_right.state_space.scene_vlm import SceneVLM   # 引擎 L5(单一唯一依据)
    except Exception as e:                                                       # noqa: BLE001
        out["err"] = "引擎不可用(import 失败): %s: %s" % (type(e).__name__, e)
        print(json.dumps(out, ensure_ascii=False))
        return 0

    prompt = ("你是 Z-MAX 具身智能平台的 L5 视觉理解层。用中文简述这帧真实机器人工作场景里的物体与状态, "
              "并以 {\"objects\":[{\"label\":\"..\",\"bbox\":[x1,y1,x2,y2]}]} 给框。")
    parse = None
    maxtok = int(os.environ.get("SS_VLM_MAXTOK_AGENT", "2000"))
    try:                                                                          # 优先复用平台既有提示词/解析
        G = _load_by_path("zmax_gen_ovl_vlm", os.path.join(ROOT, "tools", "gen_overlay_from_vlm.py"))
        prompt = str(getattr(G, "PROMPT", prompt)).format(W=a.w, H=a.h)
        parse = getattr(G, "parse_json", None)
        maxtok = int(getattr(G, "MAXTOK", maxtok))
    except Exception:                                                             # noqa: BLE001
        pass
    if a.hint:
        prompt += "\n\n现场补充说明: " + a.hint
    if a.max_tokens:
        maxtok = a.max_tokens

    try:
        vlm = SceneVLM()
        r = vlm.ask(a.jpg, prompt, max_tokens=maxtok)
        if not r.get("ok"):
            out["err"] = "引擎 L5 未返回: %s" % r.get("why")
            print(json.dumps(out, ensure_ascii=False))
            return 0
        txt = (r.get("text") or "").strip()
        boxes = []
        if parse is not None:
            try:
                boxes = (parse(txt) or {}).get("objects") or []
            except Exception:                                                     # noqa: BLE001
                boxes = []
        try:
            _publish_scene_vec(boxes, a.w, a.h, (out.get("model") or ""))   # L5 分层力的唯一依据
        except Exception:                                                        # noqa: BLE001
            pass
        out.update({"ok": True, "text": txt, "boxes": boxes, "n_boxes": len(boxes),
                    "model": r.get("src"), "text_len": len(txt)})
    except Exception as e:                                                        # noqa: BLE001
        out["err"] = "L5 调用失败: %s: %s" % (type(e).__name__, e)
    out["latency_s"] = round(time.time() - t0, 1)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
