#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_add_gs_recon_port.py — 给 📡 融合定位建图(sssensor) 加第 3 路输出「高保真重建 (3DGS)」。

背景(2026-11-19 老倪): 「我们的算法，在哪里？应该是状态空间工程的融合定位建图节点」
  实测: sssensor 的真实源只有 ①状态融合(perception.fuse_sensors) ②ORB 建图(localization_mapping.py,
  最后更新 10-13 就停了)。我们真正在用的 3DGS 高保真重建(采集→建集→550C训练→splat→8816)
  全在 tools/ 里各跑各的 ⇒ 画布上看不到、状态空间里查不到。

本脚本只做**画布接线**(不造假数字):
  ① sssensor.outputs 追加 out3
  ② 连线 sssensor.out3 → ssobs.in2, 标签写明"地图覆盖/PSNR/资产帧龄"
  ③ params 记录 out3 真源文件 / 生成脚本 / 常驻服务名
硬断言: 备份 / id 唯一 / 端口存在 / 坐标不动 / JSON 可解析 / 幂等(重复跑不重复加)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")
SRC, DST = "sssensor", "ssobs"
PORT, TPORT = "out3", "in2"
LID = "lk_gs_recon"
LABEL = "🧊 高保真重建状态 (地图覆盖 / 留出PSNR / 资产帧龄) ← gs_recon_live.json"


def main() -> int:
    dry = "--dry-run" in sys.argv
    d = json.load(open(FLOW, encoding="utf-8"))
    by = {n["id"]: n for n in d["nodes"]}
    assert SRC in by, "缺节点 %s" % SRC
    assert DST in by, "缺节点 %s" % DST
    src, dst = by[SRC], by[DST]
    src.setdefault("outputs", [])
    dst.setdefault("inputs", [])

    changed = []
    if PORT not in src["outputs"]:
        src["outputs"].append(PORT)
        changed.append("outputs += %s" % PORT)
    p = src.setdefault("params", {})
    p["out3_name"] = "🧊 高保真重建 (3DGS)"
    p["out3_source"] = "zmax_data/mapping/gs_recon_live.json"
    p["out3_tool"] = "tools/gs_recon_state.py"
    p["out3_service"] = "zmax-gs-recon-state.service"
    p["out3_api"] = "http://10.163.146.76:8793/api/gs/recon"
    p["out3_fields"] = "stage / capture / train / asset(psnr_holdout_db,n_gauss,splat_bytes) / state_space{map_coverage_mm,map_psnr_db,map_asset_age_s}"
    if TPORT not in dst["inputs"]:
        dst["inputs"].append(TPORT)
        changed.append("ssobs.inputs += %s" % TPORT)
    if not any(l.get("id") == LID for l in d["links"]):
        d["links"].append({"id": LID, "f": SRC, "t": DST,
                           "f_port": PORT, "t_port": TPORT, "label": LABEL})
        changed.append("link %s.%s → %s.%s" % (SRC, PORT, DST, TPORT))

    # 一致性断言
    ids = [n["id"] for n in d["nodes"]]
    assert len(ids) == len(set(ids)), "节点 id 重复"
    by2 = {n["id"]: n for n in d["nodes"]}
    for l in d["links"]:
        if l.get("id") == LID:
            assert l["f_port"] in by2[l["f"]].get("outputs", []), "源端口不存在"
            assert l["t_port"] in by2[l["t"]].get("inputs", []), "目标端口不存在"
    print("变更: %s" % (", ".join(changed) if changed else "无(已接好)"))
    if dry or not changed:
        return 0
    bak = FLOW + ".bak_gsrecon_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(FLOW, bak)
    tmp = FLOW + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    json.load(open(tmp, encoding="utf-8"))          # 回读校验
    os.replace(tmp, FLOW)
    print("备份 %s" % os.path.basename(bak))
    print("已写入 %s (节点 %d · 连线 %d)" % (os.path.relpath(FLOW, ROOT), len(d["nodes"]), len(d["links"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
