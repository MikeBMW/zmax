#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 「打开工程」不再弹提示页 (老倪 2026-10-15: 「删除打开工程的提示页面，没什么用」)。

来龙去脉 (判据跟着口径走, 不是删判据了事):
  · 2026-10-14 老倪: 弹窗里数字字符串太多 ⇒ 只留「工程名 + 配置名称清单」;
  · 2026-10-15 老倪: **整页删掉** (弹窗本身没信息量, 还挡画布)。

新口径 = 不弹窗, 但信息不许丢:
  ① 工程唯一依据在盘上;
  ② 名称清单仍能**从工程文件现算** (唯一依据 = 文件里的段, 不硬编);
  ③ 两条加载路径 (🗂 打开状态空间总工程 / 📂 加载工程文件) 代码里**不再调用弹窗** `_msg_ok`;
  ④ 信息改走 ①状态栏 ②控制台日志一行 (含配置名清单) ③工程台账; 日志里那份清单 == 唯一依据算出来的清单;
  ⑤ 加载链零回退: 运行档位写回 (apply_run_cfg) 与右侧栏视图回填都还在 (别把弹窗连同功能一起删了);
  ⑥ 函数 `_pj_loaded_names` 保留 (日志还要用), 旧弹窗正文不再出现在源码里。

跑法: ./gui-venv311/bin/python tools/verify_proj_load_summary.py
"""
import json
import os
import re
import sys

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.chdir(ROOT)

res = []


def chk(name, cond, extra=""):
    res.append(("✓" if cond else "✗") + " " + name + (" :: %s" % (extra,) if extra else ""))


import project_file as PJ                                                      # noqa: E402
import studio as ST                                                            # noqa: E402

path = PJ.find_space(ROOT) if hasattr(PJ, "find_space") else None
if not path or not os.path.exists(path):
    path = os.path.join(ROOT, "reports/projects/SS_主工程_任务配置.zmaxproj")
chk("① 找到状态空间工程唯一依据", os.path.exists(path), os.path.basename(path or "?"))

d = json.load(open(path, encoding="utf-8"))
names = ST._pj_loaded_names(path)
_real = [k for k, _ in ST._PROJ_SECTION_NAMES if k in d]
chk("② 配置名清单仍从工程文件现算 (不硬编)",
    len(names) == len(_real) and len(names) >= 4,
    "%d 项: %s" % (len(names), " / ".join(names)))

_src = open(os.path.join(ROOT, "tools/gui/studio.py"), encoding="utf-8").read()

# ③ **成功**提示页已删 (老倪 2026-10-15: 「删除打开工程的提示页面, 没什么用」);
#    报错弹窗要保留 —— 无法打开/加载失败必须让用户看见 (别把报错也一起删掉)
_hit = [t for t in ('"🗂 状态空间工程已打开"', "已加载配置:\\n%s") if t in _src]
chk("③ 成功提示页已删 (打开成功不再弹窗)", not _hit, ", ".join(_hit) or "0 处")
chk("③b 报错弹窗保留 (无法打开/加载失败仍可见)",
    _src.count('_msg_ok(self, "📂 加载工程文件", "❌') >= 2,
    "%d 个报错弹窗" % _src.count('_msg_ok(self, "📂 加载工程文件", "❌'))

# ④ 信息没丢: 日志那一行 + 状态栏
chk("④a 日志仍有一行工程清单 (走 _ui_msg, 含配置名)",
    bool(re.search(r'_ui_msg\("🗂 总工程已打开: %s · 配置 %s', _src))
    and bool(re.search(r'_ui_msg\("📂 工程已加载: %s · 配置 %s', _src)),
    "_ui_msg 清单行 2 处" if _src.count(" · 配置 %s") >= 2 else "缺日志行")
chk("④b 状态栏仍给一行提示",
    '状态空间总工程已打开并切到画布' in _src or '总工程已打开并切到画布' in _src
    and '工程已加载: %s' in _src,
    "statusBar 提示保留")

# ⑤ 加载链零回退
chk("⑤a 运行档位写回仍在 (apply_run_cfg 2 处)",
    _src.count("apply_run_cfg") >= 2, "%d 处" % _src.count("apply_run_cfg"))
chk("⑤b 右侧栏视图回填仍在 (VIEW_KEYS)",
    "dock.VIEW_KEYS" in _src and "_view in list(getattr(dock" in _src, "VIEW_KEYS 回填保留")

# ⑥ 旧弹窗正文与函数
chk("⑥a 旧弹窗正文正文样式已不在源码里",
    "已加载配置:\\n%s" not in _src and '"\\n\\n已加载配置:' not in _src, "0 处")
chk("⑥b _pj_loaded_names 保留 (日志/台账还要用)",
    "def _pj_loaded_names(" in _src and _src.count("_pj_loaded_names(path)") >= 2,
    "%d 处调用" % _src.count("_pj_loaded_names(path)"))

print("\n".join(res))
n_ok = sum(1 for r in res if r.startswith("✓"))
print("\n判据汇总: %d/%d PASS" % (n_ok, len(res)))
sys.exit(0 if n_ok == len(res) else 1)
