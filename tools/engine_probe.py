#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎有效性体检 —— 只输出能复算的数字, 供方案册最后一页引用。

查四件事:
  1) 画布完整性: 节点数 / 连线数 / 各层节点数
  2) 实现落位: 每个节点声明了实现文件, 文件在不在
  3) 权重可加载: models/ 下权重文件存在、大小、header 可读 (YOLO 读得到类别名)
  4) 推理与训练入口: YOLO 真跑一次计时; 训练/合并入口脚本语法可编译

结果写 zmax_data/ss_live/engine_probe.json, 同时打印人读摘要。
"""
import glob
import json
import os
import py_compile
import sys
import time

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, ROOT + "/tools")
sys.path.insert(0, ROOT + "/src")

import l2_chain_pages as LC

OUT = ROOT + "/zmax_data/ss_live/engine_probe.json"


def main():
    rep = {}
    nodes, l2, links = LC.l2_nodes()
    from lerobot.engineering.nodes.by_level import LEVELS_INDEX

    rep["nodes"] = len(nodes)
    rep["links"] = len(links)
    rep["layers"] = {k: len([x[0] for x in v if x[0] in nodes]) for k, v in LEVELS_INDEX.items()}

    # 1) 实现落位
    def _path_of(s):
        """SOURCE 字段混着「文件 · 函数」「文件::类.方法」「脚本 --参数」, 只取文件那一段。"""
        s = str(s or "").strip()
        for sep in (" · ", "::", " --", " ("):
            if sep in s:
                s = s.split(sep)[0]
        return s.strip()

    impl = {}
    missing = []
    for nid in nodes:
        mi = LC._mod_info(nid)[1]
        src = _path_of(mi.get("SOURCE")) or _path_of((mi.get("PARAMS") or {}).get("source"))
        if not src or src in ("metaworld", "?"):
            impl[nid] = "未声明"
            missing.append(nid)
            continue
        p = src if src.startswith("/") else os.path.join(ROOT, src)
        ok = os.path.isfile(p)
        impl[nid] = "有" if ok else "缺文件"
        if not ok:
            missing.append(nid)
    rep["impl_ok"] = len([v for v in impl.values() if v == "有"])
    rep["impl_missing"] = missing

    # 2) 权重
    wpaths = sorted(glob.glob(ROOT + "/models/*.pt") + glob.glob(ROOT + "/models/*.safetensors"))
    ws = []
    for p in wpaths:
        try:
            mb = round(os.path.getsize(p) / 1e6, 1)
        except OSError:
            continue
        item = {"file": os.path.basename(p), "mb": mb, "loads": None, "names": None}
        if p.endswith(".pt") and mb < 60:
            try:
                import torch
                ck = torch.load(p, map_location="cpu", weights_only=False)
                m = ck.get("model") or ck
                nm = getattr(m, "names", None) or ck.get("names")
                item["loads"] = True
                item["names"] = list(nm.values()) if isinstance(nm, dict) else (nm if isinstance(nm, list) else None)
            except Exception as e:                                   # noqa: BLE001
                item["loads"] = "%s: %s" % (type(e).__name__, str(e)[:60])
        ws.append(item)
    rep["weights"] = ws
    rep["weights_ok"] = len([w for w in ws if w["loads"] is True])

    # 3) 推理实测 (在役检测权重, 480x480 随机帧)
    try:
        import numpy as np
        from ultralytics import YOLO
        y = YOLO(ROOT + "/models/yolo_peg_live.pt")
        img = (np.random.rand(480, 480, 3) * 255).astype("uint8")
        y.predict(img, conf=0.4, verbose=False)
        ts = []
        for _ in range(10):
            t0 = time.perf_counter()
            y.predict(img, conf=0.4, verbose=False)
            ts.append((time.perf_counter() - t0) * 1e3)
        ts.sort()
        rep["infer_ms_median"] = round(ts[len(ts) // 2], 2)
        rep["infer_frames"] = len(ts)
    except Exception as e:                                           # noqa: BLE001
        rep["infer_ms_median"] = None
        rep["infer_err"] = "%s: %s" % (type(e).__name__, str(e)[:80])

    # 4) 训练与后处理入口
    ent = ["tools/joint_train_all.py", "tools/yolo_annot_train.py", "tools/train_yolo_full.py",
           "tools/lora_inject.py", "tools/merge_lora_ckpt.py", "tools/auto_annotate.py",
           "tools/l5_annotate_train_loop.py"]
    ok_ent, bad_ent = [], []
    for r in ent:
        p = os.path.join(ROOT, r)
        if not os.path.isfile(p):
            bad_ent.append((r, "缺文件"))
            continue
        try:
            py_compile.compile(p, doraise=True, cfile="/tmp/_probe.pyc")
            ok_ent.append(r)
        except Exception as e:                                       # noqa: BLE001
            bad_ent.append((r, "%s" % type(e).__name__))
    rep["train_entries_ok"] = ok_ent
    rep["train_entries_bad"] = bad_ent

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rep, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("节点 %d / 连线 %d · 各层 %s" % (rep["nodes"], rep["links"], rep["layers"]))
    print("实现落位 %d / %d, 缺: %s" % (rep["impl_ok"], rep["nodes"], rep["impl_missing"][:6]))
    print("权重 %d 个, 可加载 %d 个:" % (len(ws), rep["weights_ok"]))
    for w in ws[:8]:
        print("   %-34s %6.1f MB  loads=%s names=%s" % (w["file"], w["mb"], w["loads"], w["names"]))
    print("推理中位 %s ms (在役检测权重, 480x480)" % rep["infer_ms_median"])
    print("训练/后处理入口可编译 %d / %d, 异常: %s" % (len(ok_ent), len(ent), bad_ent))
    print("写出:", OUT)


if __name__ == "__main__":
    main()
