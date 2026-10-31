"""🧭 原子技能约束 (SK01-08 · 3D 约束通道) —— 左侧栏页

老倪 2026-10-31: 「在左侧增加原子技能约束, 每个操作我都要检查。」

这一页只做两件事, 但都是**真读真算**:
  ① 把 8 段技能的约束通道摊开: 半径 / 轴长 / 节拍 / 轴向速度上限 / 单拍行程 / 当前横向偏差 / 在不在通道内
  ② 每行一个「检查」按钮: 用当前 3D 坐标 + 当前通道, 把一个**故意越界**的动作丢进 project_stage,
     看它有没有被切外 + 回中 (这才能证明通道真的在约束, 而不是画了条线)。

数据真源:
  · 通道: zmax_data/ss_live/skill_corridors.json  (tools/ss_corridor_build.py 生成)
  · 3D 坐标: zmax_data/ss_live/trace_live.json 的 末端/光模块 (与 AR 场景同源)
  · 算法: src/lerobot/policies/left_right/state_space/corridor.py (技能过闸每拍用的是同一份)
"""
from __future__ import annotations

import json
import os
import time

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
                             QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE = os.path.join(ROOT, "zmax_data", "ss_live")
CORR = os.path.join(LIVE, "skill_corridors.json")
TRACE = os.path.join(LIVE, "trace_live.json")

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
SK_ID = {"接近": "SK01", "对位": "SK02", "下降": "SK03", "抓取": "SK04",
         "抬起": "SK05", "转移": "SK06", "插入": "SK07", "完成": "SK08"}
HDR = ["段", "技能", "半径 mm", "包络长 mm", "机动数", "节拍 s", "轴向 v 上限", "单拍 mm",
       "当前偏差 mm", "状态", "操作"]

C_BG = "#0d1117"
C_CARD = "#161b22"
C_TXT = "#e6edf3"
C_DIM = "#7d8590"
C_OK = "#7ee787"
C_BAD = "#ff7b72"
C_WARN = "#d29922"


def _corr_mod():
    """与引擎/画布同一个 corridor 模块 (按文件路径加载, 避免包名差异)。"""
    import importlib.util as ilu
    import sys
    m = sys.modules.get("zmax_skill_corridor")
    if m is not None:
        return m
    p = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space", "corridor.py")
    spec = ilu.spec_from_file_location("zmax_skill_corridor", p)
    m = ilu.module_from_spec(spec)
    sys.modules["zmax_skill_corridor"] = m
    spec.loader.exec_module(m)
    return m


class SkillCorridorPage(QWidget):
    """左侧「原子技能约束」页。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C_BG};color:{C_TXT};")
        self._rows = []
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(8)

        head = QHBoxLayout()
        t = QLabel("🧭 原子技能约束 · SK01-08 3D 约束通道")
        t.setStyleSheet(f"font-size:15px;font-weight:600;color:{C_TXT};")
        head.addWidget(t)
        head.addStretch(1)
        for txt, slot in (("🔄 刷新", self.refresh),
                          ("🛠 重算通道 (并写 AR 边界)", self.rebuild),
                          ("⏱ 300 UPH 验收 (按顺序过通道)", self.uph_check),
                          ("📋 复制 TSV", self.copy_tsv)):
            b = QPushButton(txt)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{background:{C_CARD};color:{C_TXT};border:1px solid #30363d;"
                            f"border-radius:6px;padding:5px 10px;}}QPushButton:hover{{border-color:#58a6ff;}}")
            b.clicked.connect(slot)
            head.addWidget(b)
        v.addLayout(head)

        self.hint = QLabel("通道 = 实际轨迹的扫掠包络: 轴心取自 AR 场景真在跑的轨迹 "
                           "(sim_transport.json), 半径 = 工具/工件外廓; 点「检查」看越界动作有没有被切外+回中。")
        self.hint.setStyleSheet(f"color:{C_DIM};font-size:12px;")
        v.addWidget(self.hint)

        self.tbl = QTableWidget(len(STAGES), len(HDR))
        self.tbl.setHorizontalHeaderLabels(HDR)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setStyleSheet(
            f"QTableWidget{{background:{C_CARD};color:{C_TXT};gridline-color:#30363d;border:1px solid #30363d;}}"
            f"QHeaderView::section{{background:#21262d;color:{C_TXT};border:0;padding:5px;}}")
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(len(HDR) - 1, QHeaderView.ResizeToContents)
        v.addWidget(self.tbl, 1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(190)
        self.log.setStyleSheet(f"background:{C_CARD};color:{C_TXT};border:1px solid #30363d;font-size:12px;")
        v.addWidget(self.log)

        self.refresh()

    # ── 数据 ───────────────────────────────────────────────────────────
    def _pos_mm(self):
        """当前末端 mm —— 必须与通道同源: AR 帧 (ar_cmd / ar_exec 的 b), 不用 trace_live
        (那是另一路话题, 坐标系不同, 拿它比会差好几百 mm)。"""
        import time as _t
        for name, key in (("ar_cmd", "b"), ("ar_exec", "b")):
            p = os.path.join(LIVE, "%s.json" % name)
            try:
                if _t.time() - os.path.getmtime(p) > 86400:   # 同一帧系, 允许跨天; 只拒明显旧档
                    continue
                d = json.load(open(p, encoding="utf-8")) or {}
                v = d.get(key)
                if isinstance(v, (list, tuple)) and len(v) >= 3:
                    _age = _t.time() - os.path.getmtime(p)
                    return ([float(v[0]), float(v[1]), float(v[2])], d,
                            "%s 帧龄 %.0fs" % (name, _age) if _age > 120 else None)
            except Exception:                                              # noqa: BLE001
                continue
        try:
            t = json.load(open(TRACE, encoding="utf-8")) or {}
            e = t.get("末端")
            if isinstance(e, (list, tuple)) and len(e) >= 3:
                return [float(x) * 1000.0 for x in e[:3]], t, "trace_live (不同坐标系, 仅参考)"
        except Exception as e:                                             # noqa: BLE001
            return None, None, repr(e)
        return None, None, "无 AR 指令 (ar_cmd/ar_exec 都没有)"

    def _corridors(self):
        try:
            d = json.load(open(CORR, encoding="utf-8")) or {}
            return d.get("corridors") or {}, d.get("built_at"), (d.get("tact_tab_s") or d.get("tact_s"))
        except Exception:                                                 # noqa: BLE001
            return {}, None, None

    # ── 刷新 ───────────────────────────────────────────────────────────
    def refresh(self):
        C = _corr_mod()
        corrs, built_at, tact = self._corridors()
        E, P, why = self._pos_mm()
        self._rows = []
        for i, st in enumerate(STAGES):
            c = corrs.get(st) or {}
            dev = None
            state, color = "无通道", C_WARN
            if c and E is not None:
                try:
                    _, info = C.project_stage(st, [0.0, 0.0, 0.0, 0.0], E, c)
                    dev = info.get("dev_mm")
                    if info.get("in_channel"):
                        state, color = "通道内", C_OK
                    else:
                        state, color = "越界 %s mm" % info.get("excess_mm"), C_BAD
                except Exception as e:                                    # noqa: BLE001
                    state, color = "算不出: %s" % type(e).__name__, C_BAD
            elif c and E is None:
                state, color = "无 3D 坐标", C_WARN
            vals = [st, SK_ID.get(st, ""),
                    ("%.2f" % c["r_mm"]) if c else "—",
                    ("%.2f" % c["L_mm"]) if c else "—",
                    (str(c.get("n_poly") or 1)) if c else "—",
                    ("%.2f" % c["tact_s"]) if c.get("tact_s") else "—",
                    ("%.4f" % c["v_along_cap"]) if c else "—",
                    ("%.2f" % c["s_tick_mm"]) if c else "—",
                    ("%.2f" % dev) if dev is not None else "—",
                    state]
            for j, s in enumerate(vals):
                it = QTableWidgetItem(str(s))
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if j == len(vals) - 1:
                    it.setForeground(Qt.green if color == C_OK else (Qt.red if color == C_BAD else Qt.yellow))
                self.tbl.setItem(i, j, it)
            b = QPushButton("检查")
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{background:#21262d;color:{C_TXT};border:1px solid #30363d;"
                            f"border-radius:5px;padding:3px 8px;}}QPushButton:hover{{border-color:#58a6ff;}}")
            b.clicked.connect(lambda _=False, _st=st: self.check(_st))
            self.tbl.setCellWidget(i, len(HDR) - 1, b)
            self._rows.append([str(x) for x in vals])
        src = ("通道建于 %s · 段表节拍 %ss/件" % (built_at, tact)) if built_at else "通道未生成 (点「🛠 重算通道」)"
        pos = "末端 %s" % ([round(x, 1) for x in E] if E else "无")
        self.hint.setText("%s · 3D 坐标: %s%s" % (src, pos, ("  ⚠️ " + why) if why else ""))

    # ── 逐段检查 ───────────────────────────────────────────────────────
    def check(self, stage):
        C = _corr_mod()
        corrs, _, _ = self._corridors()
        c = corrs.get(stage)
        if not c:
            self._say(f"⛔ {stage}: 没有通道 —— 先点「🛠 重算通道」", C_BAD)
            return
        E, P, why = self._pos_mm()
        if E is None:
            self._say(f"⚠️ {stage}: 没有 3D 坐标 ({why}) ⇒ 只能用轴向/节拍判据", C_WARN)
            pos = list(c["a"])
        else:
            pos = E
        # 故意越界: 从通道轴外 3r 处、以 0.30 m/s 朝外速度冲
        k_mul, pos_bad = 3.0, None
        while k_mul <= 40:
            off = [c["e1"][k] * c["r_mm"] * k_mul for k in range(3)]
            pos_bad = [pos[k] + off[k] for k in range(3)]
            try:
                _, _i0 = C.project_stage(stage, [0, 0, 0, 0], pos_bad, c)
                if not _i0.get("in_channel"):
                    break
            except Exception:                                          # noqa: BLE001
                break
            k_mul += 1.0
        u_bad = [c["e1"][0] * 0.30, c["e1"][1] * 0.30, c["e1"][2] * 0.30, 0.0]
        u_out, info = C.project_stage(stage, u_bad, pos_bad, c)
        ok = ("横向切外" in info["why"]) and (info["step_mm"] <= info["s_tick_mm"] + 1e-6
                                             or "单拍行程" in info["why"])
        self._say(("✅ " if ok else "❌ ") + f"{stage} ({SK_ID.get(stage,'')}) 检查",
                  C_OK if ok else C_BAD)
        self._say("  通道: r=%.2fmm 总长%.1fmm %d 次真实机动" %
                  (c["r_mm"], c["L_mm"], c.get("n_poly") or 1))
        self._say("  越界输入: 外移 %.0fr · dev=%.2fmm (超 %.2fmm) u_in=%s" %
                  (k_mul, info["dev_mm"], info["excess_mm"], [round(x, 3) for x in u_bad[:3]]))
        self._say("  过闸输出: u_out=%s · 单拍 %.2fmm (限额 %.2fmm)" %
                  ([round(x, 3) for x in u_out[:3]], info["step_mm"], info["s_tick_mm"]))
        self._say("  削因: %s ⇒ %s" % (info["why"], "动作被关回通道" if ok else "没被关住, 需查通道/参数"))

    def _say(self, text, color=None):
        color = color or C_TXT
        self.log.append(f'<span style="color:{color}">{text}</span>')

    # ── 重算通道 ───────────────────────────────────────────────────────
    def rebuild(self):
        try:
            import importlib.util as ilu
            p = os.path.join(ROOT, "tools", "ss_corridor_build.py")
            spec = ilu.spec_from_file_location("zmax_corridor_build", p)
            mod = ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            doc = mod.build_all(tact_s=1.43)
            if doc is None:
                self._say("⛔ 没有 3D 真坐标 ⇒ 不造通道 (不编坐标)", C_BAD)
                return
            os.makedirs(LIVE, exist_ok=True)
            json.dump(doc, open(CORR + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            os.replace(CORR + ".tmp", CORR)
            n = mod.write_ar_fences(doc)
            self._say(f"✅ 已重算 8 段通道 (节拍 1.43s/段), 并写入 AR 边界线 {n} 条", C_OK)
            self.refresh()
        except Exception as e:                                            # noqa: BLE001
            self._say(f"❌ 重算失败: {type(e).__name__}: {e}", C_BAD)

    def uph_check(self):
        """按顺序把 392 段逐段过通道, 算实际节拍与 UPH (真算, 与 ss_uph_300_check.py 同源)。"""
        try:
            import importlib.util as ilu
            p = os.path.join(ROOT, "tools", "ss_uph_300_check.py")
            spec = ilu.spec_from_file_location("zmax_uph_check", p)
            mod = ilu.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(mod)
            segs, tact, corrs = mod.load()
            rows, _ = mod.run_once(segs, corrs)
            by, tp, ta, slow, per_piece, uph = mod.summarize(rows, tact)
            ok = uph >= 300
            self._say("%s 按顺序过通道: 段数 %d · 计划 %.2fs → 实测 %.2fs (慢 %.1f%%)"
                      % ("✅" if ok else "❌", len(rows), tp, ta, 100 * (slow - 1)), C_OK if ok else C_BAD)
            for st in STAGES:
                d = by.get(st)
                if not d:
                    continue
                c = corrs.get(st) or {}
                self._say("   %s %-6s %3d 次 · 计划 %6.2fs → 实测 %6.2fs · v上限 %.3f m/s"
                          % (SK_ID.get(st, ''), st, d["n"], d["tp"], d["ta"],
                             float(c.get("v_along_cap") or 0)), C_TXT)
            self._say("   ⇒ 节拍 %.2fs/件 · UPH %.0f · %s"
                      % (per_piece, uph, "达到 300" if ok else "低于 300, 需放宽速度上限"), C_OK if ok else C_BAD)
        except Exception as e:                                            # noqa: BLE001
            self._say("❌ 验收失败: %s: %s" % (type(e).__name__, e), C_BAD)

    def copy_tsv(self):
        try:
            from PyQt5.QtWidgets import QApplication
            txt = "\t".join(HDR) + "\n" + "\n".join("\t".join(r) for r in self._rows)
            QApplication.clipboard().setText(txt)
            self._say("📋 已复制 %d 行 TSV" % len(self._rows), C_OK)
        except Exception as e:                                            # noqa: BLE001
            self._say(f"复制失败: {e}", C_BAD)
