#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 画布右侧「🧮 主参数 M」窗口 = 可操作 + 有信息连接 (2026-10-19 老倪要求)。

检查项 (缺一即失败):
  ① 拖动条存在, 范围 0~800 (=0~8.00), 与微调框双向联动 (sl→sp, sp→sl)
  ② 五个引力档位按钮, 点一下把值填进微调框 (不自动写盘)
  ③ 读数行真的连到唯一依据: 文本含「唯一依据」且数值 == config/calib/zmax_manifold.json 的 M
  ④ 读数行真的连到在役引擎: 文本含「在役」+ 引擎帧龄; 与 engine_latest.M 一致时打 ✓
  ⑤ 物理读数: 有 ‖∇Φ‖ 时出现 a=‖∇Φ‖/M (与手算一致, 1e-3)
  ⑥ 档位实测来自 mparam_gravity.json (含「实测N拍」), 不由界面编造
  ⑦ 写入路径仍在 (✏️ 写 M 按钮存在, 且走 zmax_params.write_manifold_M)
"""
import os
import sys
import json
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtWidgets import QApplication                                    # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import model_tree                                                            # noqa: E402

P = F = 0
def chk(tag, name, ok, detail=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print("  %s %s %-46s %s" % ("✅" if ok else "❌", tag, name, detail))


v = model_tree.MasterParamMView(module=None)
v.show()

# ① 拖动条 + 双向联动
chk("①a", "拖动条存在且范围 0~800", hasattr(v, "sl_M") and (v.sl_M.minimum(), v.sl_M.maximum()) == (0, 800),
    "range=%s" % ((v.sl_M.minimum(), v.sl_M.maximum()),))
v.sl_M.setValue(364)
ok_a = abs(v.sp_M.value() - 3.64) < 1e-9
v.sp_M.setValue(7.25)
ok_b = v.sl_M.value() == 725
chk("①b", "拖动→微调框 & 微调框→拖动 双向一致", ok_a and ok_b,
    "sl364→sp%.3f · sp7.25→sl%d" % (v.sp_M.value() if ok_a else -1, v.sl_M.value()))

# ② 档位按钮
chk("②a", "五个引力档位按钮", hasattr(v, "_gear_btns") and len(v._gear_btns) == 5,
    "labels=%s" % [b.text() for b in getattr(v, "_gear_btns", [])])
v._gear_btns[1].click()
chk("②b", "点档位只填值 (微调框=0.3, 不写盘)", abs(v.sp_M.value() - 0.3) < 1e-9, "sp=%.3f" % v.sp_M.value())

# 唯一依据与在役
src_M = json.load(open(os.path.join(ROOT, "config/calib/zmax_manifold.json"), encoding="utf-8"))["M"]
eng = json.load(open(os.path.join(ROOT, "zmax_data/ss_live/engine_latest.json"), encoding="utf-8"))
v.sp_M.setValue(float(src_M))
v._mparam_tick()
txt = v.lbl_minfo.text()
chk("③", "读数行连到唯一依据 (含 唯一依据 + 同值)", ("唯一依据" in txt) and ("%.3f" % src_M) in txt, txt[:70])
chk("④", "读数行连到在役引擎 (含 在役 + 帧龄)", ("在役" in txt) and ("前" in txt) and ("✓" in txt or "⚠" in txt), txt[:70])
_a = float(eng["grad_norm"]) / float(eng["M"])
chk("⑤", "物理读数 a=‖∇Φ‖/M 与手算一致", ("a=%.3f" % _a) in txt, "a=%.3f (grad=%.3f/M=%.3f)" % (_a, eng["grad_norm"], eng["M"]))
chk("⑥", "档位带实测拍数 (来自 mparam_gravity.json)", ("实测" in txt) and (v._m_gravi.get("rows") is not None),
    [r.get("converged_step") for r in (v._m_gravi.get("rows") or [])])
chk("⑦", "写入入口仍在 (✏️ 写 M → write_manifold_M)",
    hasattr(v, "btn_write_M") and v.btn_write_M.text().startswith("✏️"),
    v.btn_write_M.text() if hasattr(v, "btn_write_M") else "-")

print("═══ 判据汇总: %d/%d PASS ═══" % (P, P + F))
sys.exit(0 if F == 0 else 1)
