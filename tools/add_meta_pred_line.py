#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_meta_pred_line.py — 信号页加「🧾 元任务预测」文字行 (确切元任务名上屏)。

老倪 2026-10-15: 「需要显示确切的元任务, 在信号分析窗口要显示」

数据来自**话题载荷本身** (zmax/ss_meta_pred → trace.jsonl digest → DataSpaceTraceSource 抠出的字符串叶子
`top_txt` = "FN-SYS2-29 小目标插入 0.0366 › …"), 不是页面自己算的。没有数据时如实写"等话题/未生成",
不编元任务名。格局与既有的「🎛 八阶段」行一致 (ignored 宽度, 不撑窗口)。
"""
from __future__ import annotations

import io
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(REPO, "tools", "gui", "canoe_graphic.py")
s = io.open(P, encoding="utf-8").read()
n = 0


def rep(old, new):
    global s, n
    assert old in s, "锚点没找到: %r" % old[:70]
    s = s.replace(old, new, 1)
    n += 1


# ① 造控件 (紧跟八阶段行)
rep('''        root.addWidget(self.lb_stages)

        # ── 主体: 左信号栏 + 右波形 ──''',
    '''        root.addWidget(self.lb_stages)

        # ── 🧾 元任务预测: **文字**一行 (老倪 2026-10-15: 「需要显示确切的元任务, 在信号分析窗口要显示」) ──
        #    内容 = 话题 zmax/ss_meta_pred 载荷里的 top_txt (功能号 + 元任务名 + 得分), 取自 digest 的字符串叶子;
        #    页面**不自己编**名字: 没有载荷就写"等话题/未生成", 并给出怎么生成 (ss_meta_predict.py)。
        self.lb_meta = QLabel("")
        self.lb_meta.setTextFormat(Qt.RichText)
        self.lb_meta.setStyleSheet(f"color:{C_DIM}; font-size:13px; padding:2px 4px;")
        try:
            self.lb_meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self.lb_meta.setMinimumWidth(0)
        except Exception:                                                      # noqa: BLE001
            pass
        self.lb_meta.setToolTip("元任务预测 = 🧾 元任务预测节点 (驱动扭矩 T_drive=M·(−∇Φ) → 逐元任务得分);\\n"
                                "话题 zmax/ss_meta_pred (type zmax::SSMetaPred) · 唯一依据 zmax_data/ss_live/meta_pred.json\\n"
                                "生成: gui-venv311/bin/python tools/ss_meta_predict.py --scene SCN-01-FW --write")
        root.addWidget(self.lb_meta)

        # ── 主体: 左信号栏 + 右波形 ──''')

# ② 刷新函数 (放在 _stage_strip 前面, 同款读法)
rep('''    def _stage_strip(self):''',
    '''    def _meta_pred_text(self):
        """🧾 元任务预测一行 (确切元任务名) —— 内容直接来自话题载荷, 不是页面自造。

        返回 (HTML, 是否新鲜)。新鲜度用**该话题最后一帧的年龄**判 (store.bufs 里 ds.zmax/ss_meta_pred.* 的 age)。
        """
        txt = ""
        try:
            txt = str((getattr(self.store, "ds_text", None) or {}).get("zmax/ss_meta_pred", {}).get("top_txt") or "")
        except Exception:                                                      # noqa: BLE001
            txt = ""
        age = -1.0
        try:
            for k, b in self.store.bufs.items():
                if k.startswith("ds.zmax/ss_meta_pred.") and b.age is not None and b.age >= 0:
                    age = min(age, b.age) if age >= 0 else b.age
        except Exception:                                                      # noqa: BLE001
            pass
        head = "🧾 元任务预测: "
        if not txt:
            return (head + "<i>等话题 zmax/ss_meta_pred (跑一次 tools/ss_meta_predict.py --write 即生成)</i>", False)
        fresh = (age >= 0 and age <= 60.0)
        body = " › ".join("<b style='color:%s'>%s</b>" % (C_GREEN, x.strip()) if i == 0
                          else "<span style='color:%s'>%s</span>" % (C_DIM, x.strip())
                          for i, x in enumerate(txt.split("›")))
        if not fresh and age >= 0:
            body += " <span style='color:%s'>· 帧龄 %.0fs (非当下值)</span>" % (C_YELLOW, age)
        return (head + body, fresh)

    def _stage_strip(self):''')

# ③ 挂到刷新循环 (与八阶段行同一处)
rep('''        try:                                   # 八阶段**文字**一行 (八段名 + 当前段高亮)
            _strip, _ = self._stage_strip()
            self.lb_stages.setText(_strip)
        except Exception:                                                      # noqa: BLE001
            pass''',
    '''        try:                                   # 八阶段**文字**一行 (八段名 + 当前段高亮)
            _strip, _ = self._stage_strip()
            self.lb_stages.setText(_strip)
        except Exception:                                                      # noqa: BLE001
            pass
        try:                                   # 🧾 元任务预测一行 (确切元任务名, 来自话题载荷)
            _mt, _ = self._meta_pred_text()
            if self.lb_meta.text() != _mt:
                self.lb_meta.setText(_mt)
        except Exception:                                                      # noqa: BLE001
            pass''')

# ④ 首屏默认勾选: mt1..mt5 (逐元任务得分曲线)
rep('''                  "ds.zmax/ss_meta_pred.top1", "ds.zmax/ss_meta_pred.spread")''',
    '''                  "ds.zmax/ss_meta_pred.mt1", "ds.zmax/ss_meta_pred.mt2",
                  "ds.zmax/ss_meta_pred.mt3", "ds.zmax/ss_meta_pred.spread")''')

io.open(P, "w", encoding="utf-8").write(s)
print("已改 %d 处" % n)
