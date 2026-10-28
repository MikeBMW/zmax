#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按性能等级 A/B/C 生成三张生产工单 (T1/T2/T3) —— 供「🧾 工单配置」页与 ar3d 演练选用。

真源:
  基础工单 config/orders/BS_SCN-07-AOI.json   (场景/工艺/配方/目标, 勿手改)
  成本口径 tools/spec/cost_model.json          (单价) → tools/cost_model.build_tiers() 现算结论
做法: 读基础工单 → 复制 → 覆盖 identity/options/targets 里的档位字段 + 挂 cost 快照 → 写 BS_SCN-07-AOI-T{1,2,3}.json
CLI: python3 tools/gen_tier_orders.py
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from cost_model import build_tiers                                             # noqa: E402

BASE = os.path.join(ROOT, "config", "orders", "BS_SCN-07-AOI.json")
OUTDIR = os.path.join(ROOT, "config", "orders")

TIER_META = {
    "A": {"no": "T1", "name": "基础工单 · L2 单任务节拍", "mode": "single_task",
          "scope": "摆盘 + 插拔 + AOI 五点 (固定序, 人工选流程)", "shifts": "两班 16h",
          "hours": 4800, "oee": 0.85, "deliver": "14 天 (标定 3 + 集成 7 + 验收 4)"},
    "B": {"no": "T2", "name": "精细工单 · L2+L3 多任务编排", "mode": "multi_task",
          "scope": "多品种换型 + 技能序列组合 + 双臂并行", "shifts": "两班 16h",
          "hours": 4800, "oee": 0.85, "deliver": "28 天 (含采数 7 + 训练 7 + 联调 10)"},
    "C": {"no": "T3", "name": "专业工单 · L2+L3+L4(+L5) 安全分级自主", "mode": "autonomous",
          "scope": "无人夜班 + 异常自主恢复 + 质量担保 (目标 PL d)", "shifts": "三班 20h",
          "hours": 6000, "oee": 0.88, "deliver": "60 天 (含安全验证 21 + 认证送审 14)"},
}


def main():
    base = json.load(open(BASE, encoding="utf-8"))
    cm = build_tiers()
    by_id = {r["id"]: r for r in cm["tiers"]}
    made = []
    for tid, meta in TIER_META.items():
        r = by_id[tid]
        o = json.loads(json.dumps(base))                                        # 深拷贝
        ident = o.setdefault("identity", {})
        ident["order_no"] = "BS-SCN-07-AOI-%s-0001" % meta["no"]
        ident["name"] = meta["name"]
        ident["tier"] = tid
        ident["goal"] = ("%s · 任务7 (摆盘/插拔/AOI) 产能 %d 件/年 (%.0f UPH × %.0fh × OEE %.2f)"
                         % (meta["scope"], r["pieces_year"], cm["uph_geo"], meta["hours"], meta["oee"]))
        ident["batch"] = "1 批 (按件计价, 可覆盖)"
        o.setdefault("options", {})["selected"] = ["tier=%s" % tid, "mode=%s" % meta["mode"]]
        o["options"]["_derived"] = ("档位派生 · 性能配置 %s (%s · ≤%s TOPS) · 工程配置 %s 档 WI"
                                    % (tid, r["layers"], r["tops"], tid))
        tg = o.setdefault("targets", {})
        tg["产能 UPH"] = "%.1f 件/h (几何) · 年产量 %d 件 (%.0fh × OEE %.2f)" % (
            cm["uph_geo"], r["pieces_year"], meta["hours"], meta["oee"])
        tg["加工单价"] = "%.2f 元/件 (%s)" % (r["price_per_piece"], r["price_basis"])
        tg["班次"] = meta["shifts"]
        tg["交付周期"] = meta["deliver"]
        o["cost"] = {
            "tier": tid, "layers": r["layers"], "tops": r["tops"],
            "capex": r["capex"], "nre": r["nre_sum"], "opex_year": r["opex_year"],
            "pieces_year": r["pieces_year"], "price_per_piece": r["price_per_piece"],
            "unit_cost": r["unit_cost"], "unit_margin": r["unit_margin"],
            "revenue_year": r["revenue_year"], "gross_year": r["gross_year"],
            "gross_margin_pct": r["gross_margin_pct"], "payback_years": r["payback_years"],
            "split_recommend": cm["split_recommend"],
            "split_hybrid_pct": cm["split"][tid]["s3_hybrid"]["pct"],
            "_src": "tools/cost_model.build_tiers() @ tools/spec/cost_model.json",
        }
        o["_note"] = ("工单配置单 (Build Sheet) · 档位 %s。由 tools/gen_tier_orders.py 从 "
                      "BS_SCN-07-AOI.json + 成本模型生成, 勿手改。" % tid)
        p = os.path.join(OUTDIR, "BS_SCN-07-AOI-%s.json" % meta["no"])
        with open(p, "w", encoding="utf-8") as f:
            json.dump(o, f, ensure_ascii=False, indent=1)
        back = json.load(open(p, encoding="utf-8"))                              # 回读校验
        assert back["identity"]["order_no"] == ident["order_no"], p
        made.append((os.path.basename(p), r["pieces_year"], r["price_per_piece"], r["unit_cost"]))
    for n, pc, pr, uc in made:
        print("写出 %-28s 年产 %8d 件 · 单价 %.2f · 单件成本 %.4f" % (n, pc, pr, uc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
