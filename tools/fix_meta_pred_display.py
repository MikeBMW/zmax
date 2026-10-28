#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_meta_pred_display.py — 信号页显示**确切的元任务** (老倪 2026-10-15)。

老倪: 「流形引擎的输出, 元任务预测发出的 topic 是什么? 需要显示确切的元任务, 在信号分析窗口要显示」

现状: 话题 zmax/ss_meta_pred (type zmax::SSMetaPred) 里已有 top_ids / top_scores (字符串, top-8),
但 ① `top_ids` 只有功能号 (FN-SYS2-29) —— 认不出是哪个元任务; ② 信号页只把 3 个数值摘出来画, 名字根本没上屏。
做法 (三段都不改 DDS 结构, 只加内容):
 ① 守护: `top_ids` 从「FN-SYS2-29」改成「FN-SYS2-29 小目标插入」(唯一依据 meta_pred.json 里 top[].name) ⇒ 载荷自解释;
 ② 探针: digest 里数值槽 mt1..mt5 (可画/可导出) + 文本槽 top_txt (top-3「功能号 名字 得分」, 供上屏);
 ③ 信号页: 解析 digest 里的**字符串**叶子 (此前只解数值) → 在状态栏上方出一行
    「🧾 元任务预测 top3: FN-SYS2-29 小目标插入 0.0366 › …」; 并把 mt1..mt5 纳入首屏默认勾选。
"""
from __future__ import annotations

import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
n = 0


def patch(path, pairs):
    global n
    p = os.path.join(REPO, path)
    s = io.open(p, encoding="utf-8").read()
    for old, new in pairs:
        assert old in s, "%s 锚点没找到: %r" % (path, old[:70])
        s = s.replace(old, new, 1)
        n += 1
    io.open(p, "w", encoding="utf-8").write(s)
    print("已改 %s (%d 处)" % (path, len(pairs)))


# ── ① 守护: top_ids 带上元任务名 (载荷自解释) ────────────────────────────────
patch("tools/dds/ss_daemon.py", [(
    '''        for it in top[:8]:
            if isinstance(it, dict):
                ids.append(str(it.get("fn_id") or it.get("id") or ""))
                scs.append("%.4f" % float(it.get("score") or it.get("s") or 0.0))''',
    '''        for it in top[:8]:
            if isinstance(it, dict):
                # 🧾 2026-10-15 老倪「需要显示确切的元任务」: 功能号后面**带上元任务名**
                #   (唯一依据 meta_pred.json 的 top[].name) ⇒ 话题本身就自解释, 下游不用再查表。
                _fid = str(it.get("fn_id") or it.get("id") or "")
                _nm = str(it.get("name") or "").strip()
                ids.append((_fid + " " + _nm).strip() if _nm else _fid)
                scs.append("%.4f" % float(it.get("score") or it.get("s") or 0.0))'''
)])

# ── ② 探针: digest 数值槽 + 文本槽 ──────────────────────────────────────────
patch("src/lerobot/dataspace/probe.py", [(
    '''            _sc = [x for x in str(f.get("top_scores") or "").replace(" ", "").split(",") if x]
            _ids = [x.strip() for x in str(f.get("top_ids") or "").split(",") if x.strip()]
            _v = []
            for _x in _sc[:3]:
                try:
                    _v.append(float(_x))
                except Exception:                                              # noqa: BLE001
                    pass
            return json.dumps({"top1": (_v[0] if _v else None),
                               "top2": (_v[1] if len(_v) > 1 else None),
                               "top3": (_v[2] if len(_v) > 2 else None),
                               "spread": (round(_v[0] - _v[1], 6) if len(_v) > 1 else None),
                               "n_meta": f.get("n_meta"), "n_cand": f.get("n_cand"),
                               "trained": f.get("trained"), "frozen": f.get("frozen"),
                               "input_ok": f.get("input_ok"),
                               "t_pred_s": (round(float(f.get("ts") or 0) - float(f.get("ts_pred") or 0), 3)
                                            if f.get("ts_pred") else None),
                               "in_age_s": f.get("input_age_s"),
                               "top1_id": (_ids[0] if _ids else ""),
                               "scene": f.get("scene") or ""}, ensure_ascii=False)[:400]''',
    '''            _sc = [x for x in str(f.get("top_scores") or "").replace(" ", "").split(",") if x]
            _ids = [x.strip() for x in str(f.get("top_ids") or "").split(",") if x.strip()]
            _v = []
            for _x in _sc[:5]:
                try:
                    _v.append(float(_x))
                except Exception:                                              # noqa: BLE001
                    pass
            # 🧾 文本槽: 确切元任务 (功能号 + 名字 + 得分) —— 信号页拿它上屏, 不是只画数
            _txt = " › ".join("%s %.4f" % (_ids[i], _v[i]) for i in range(min(3, len(_ids), len(_v))))
            return json.dumps({"mt1": (_v[0] if _v else None),
                               "mt2": (_v[1] if len(_v) > 1 else None),
                               "mt3": (_v[2] if len(_v) > 2 else None),
                               "mt4": (_v[3] if len(_v) > 3 else None),
                               "mt5": (_v[4] if len(_v) > 4 else None),
                               "spread": (round(_v[0] - _v[1], 6) if len(_v) > 1 else None),
                               "n_meta": f.get("n_meta"), "n_cand": f.get("n_cand"),
                               "trained": f.get("trained"), "frozen": f.get("frozen"),
                               "input_ok": f.get("input_ok"),
                               "t_pred_s": (round(float(f.get("ts") or 0) - float(f.get("ts_pred") or 0), 3)
                                            if f.get("ts_pred") else None),
                               "in_age_s": f.get("input_age_s"),
                               "top_txt": _txt, "scene": f.get("scene") or ""},
                              ensure_ascii=False)[:400]'''
)])

# ── ③ 信号页: 解析字符串叶子 + 文本行 ───────────────────────────────────────
patch("tools/gui/canoe_graphic.py", [
    # 3.1 字符串叶子的解析器 (放在数值解析器旁边)
    ('''_DS_JSONNUM_RE = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"\\s*:\\s*(-?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)')''',
     '''_DS_JSONNUM_RE = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"\\s*:\\s*(-?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)')
# 🧾 字符串叶子 (2026-10-15 老倪「需要显示确切的元任务」): digest 里除了数值还有**名字/ID 串**
#   (如 ss_meta_pred 的 top_txt = "FN-SYS2-29 小目标插入 0.0366 › …") —— 那些不是画出来的信号,
#   是要**直接上屏**的文字。此前只解数值 ⇒ 名字永远看不到。
_DS_JSONSTR_RE = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"\\s*:\\s*"([^"]{1,400})"')


def parse_ds_digest_str(d):
    """从 digest 抠出**字符串**叶子 → {键: 文本} (供元任务等"名字"上屏)"""
    out = {}
    if not d:
        return out
    s = d if isinstance(d, str) else json.dumps(d, ensure_ascii=False)
    for _m in _DS_JSONSTR_RE.finditer(s):
        _k, _v = _m.group(1), _m.group(2).strip()
        if _v:
            out[_k] = _v
    return out'''),
    # 3.2 数据空间源: 把字符串叶子也存进 store
    ('''        self.store.push_many({pref + k: v for k, v in vals.items()},
                             x, src="ds", scene=_scene)''',
     '''        # 🧾 字符串叶子 (元任务名/ID 等) 不进波形, 存进 store 供上屏
        _strs = parse_ds_digest_str(rec.get("digest"))
        if _strs:
            try:
                self.store.ds_text[topic] = _strs
            except AttributeError:
                pass
        self.store.push_many({pref + k: v for k, v in vals.items()},
                             x, src="ds", scene=_scene)'''),
    # 3.3 store 加 ds_text 容器
    ('''        self.notes = collections.deque(maxlen=50)   # 最近几条"波形为什么变了"的说明''',
     '''        self.notes = collections.deque(maxlen=50)   # 最近几条"波形为什么变了"的说明
        # 🧾 话题里的**字符串**叶子 (元任务名/ID...): 不是波形, 是要上屏的"确切内容"
        self.ds_text = {}'''),
])
print("共 %d 处" % n)
