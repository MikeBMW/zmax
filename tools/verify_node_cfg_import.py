#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""判据: 「🧮 标定诊断测量 · 主参数 M」节点 = 配置中心配置数据的收口口 (老倪 2026-10-12)。

老倪原话:
> 这个配置中心的配置数据, 要写入状态空间的 标定诊断测量 主参数M 节点,
> 我右键打开这个节点, 要直接定位到, 导入配置文件的位置, 而且要能够运行, 要有能加载配置文件的逻辑

五条断言:
  ① 注册表: match_node("🧮 标定诊断测量 · 主参数 M") == n_calib_mani (节点有可运行逻辑)
  ② 右键定位: 节点 params.source == src/lerobot/engineering/config_import.py
     + params.source_symbol 能在该文件里解析出行号 (GUI 同一规则: source 优先 + 符号动态定位)
     ⇒ 期望命令 `code -g <root>/src/lerobot/engineering/config_import.py:<行>`, 且**不含** node_logic.py
  ③ 真运行: 真跑节点逻辑 → 配置导入 8 唯一依据 + 工程库 OK
  ④ 真写入: 跑完回读画布, 节点 params.cfg_loaded_at / cfg_files / cfg_snapshot 已更新
  ⑤ 唯一依据在位: 8 项配置文件 + 工程库 + 工单 全部存在 (缺什么就 FAIL 什么)
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_node_cfg_import.py
"""
import importlib
import json
import os
import re
import sys
import time

ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)
NODE_NAME = "🧮 标定诊断测量 · 主参数 M"
import glob as _glob                                                                # noqa: E402
CANVAS = next((c for c in (os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json"),
                           os.path.join(ROOT, "flows/state_space_obs.json")) if os.path.isfile(c)),
              os.path.join(ROOT, "flows/state_space_obs.json"))
SRC_REL = "src/lerobot/engineering/config_import.py"
SYM = "def import_config_files("

_ok = _bad = 0


def ck(name, cond, ev=""):
    global _ok, _bad
    if cond:
        _ok += 1
        print("  ✅ %s%s" % (name, ("   ← %s" % ev) if ev else ""))
    else:
        _bad += 1
        print("  ❌ %s%s" % (name, ("   ← %s" % ev) if ev else ""))
    return bool(cond)


def sym_line(path, sym):
    try:
        with open(path, encoding="utf-8") as f:
            for i, ln in enumerate(f, 1):
                if sym in ln:
                    return i
    except Exception:                                                           # noqa: BLE001
        pass
    return None


print("═══ 判据: 主参数 M 节点 ← 配置中心配置数据 (唯一依据导入) ═══")
print("① 注册表匹配")
from lerobot.engineering import registry                                              # noqa: E402
key = registry.match_node(NODE_NAME)
ck("match_node 命中 n_calib_mani", key == "n_calib_mani", "key=%s" % key)
info = registry.get(key) or {}
ck("该 key 有可运行函数 fn", callable(info.get("fn")), "%s @ %s:%s" % (info.get("module"),
                                                                        (info.get("file") or "").replace(ROOT + "/", ""),
                                                                        info.get("line")))

print("② 右键「打开源码」应直达导入配置文件的位置")
node = next((n for n in (json.load(open(CANVAS, encoding="utf-8")).get("nodes") or [])
             if n.get("id") == "n_calib_mani" or (n.get("params") or {}).get("manifold_calib")), None)
p = (node or {}).get("params") or {}
src = str(p.get("source") or "")
ck("节点 params.source 指向配置导入逻辑", src == SRC_REL, "source=%s" % src)
ln = sym_line(os.path.join(ROOT, SRC_REL), str(p.get("source_symbol") or SYM))
ck("source_symbol 能解析出行号", bool(ln), "source_symbol=%r → %s:%s" %
   (p.get("source_symbol"), SRC_REL, ln))
if src and ln:
    cmd = "code -g %s:%s" % (os.path.join(ROOT, SRC_REL), ln)
    print("     ⇒ 期望 VSCode 命令: %s" % cmd)
    ck("定位命令不含 GUI/node_logic.py", "node_logic.py" not in cmd and "tools/gui" not in cmd, cmd)
    ck("定位命令落到 config_import.py 的导入函数行", ("config_import.py:%d" % ln) in cmd, cmd)

print("③ 唯一依据在位 (节点运行时要加载的文件)")
ci = importlib.import_module("lerobot.engineering.config_import")
res = ci.import_config_files(ROOT, verbose=False)
ck("8 项配置唯一依据全部在位", res["summary"]["files_ok"] == res["summary"]["files_total"],
   "%s/%s%s" % (res["summary"]["files_ok"], res["summary"]["files_total"],
                (" 缺: " + ",".join(res["missing"])) if res["missing"] else ""))
ck("工程库 (单一唯一依据) 可读且登记了工程", res["summary"]["db_ok"] and bool(res["summary"]["project"]),
   "%s → %s" % (res["summary"]["project"], res["summary"]["project_path"]))
ck("工单 BS_*.json 在位", res["summary"]["orders"] >= 5, "%d 个" % res["summary"]["orders"])

print("④ 真运行节点逻辑 (真加载 + 真写回)")
from lerobot.engineering.nodes import library as L                                     # noqa: E402
t0 = time.time()
before = json.load(open(CANVAS, encoding="utf-8"))
_blog = next((n for n in before["nodes"] if n.get("id") == "n_calib_mani"), {}).get("params", {}).get("cfg_loaded_at")
try:
    r = L.node_ss_calib_mani({"log": None, "params": {}, "module": None})
    err = ""
except Exception as e:                                                                 # noqa: BLE001
    r, err = {}, repr(e)
ck("节点运行无异常", not err, err or "%.0f ms" % ((time.time() - t0) * 1000))
print("⑤ 写回回读 (配置数据真进了节点)")
after = json.load(open(CANVAS, encoding="utf-8"))
ap = next((n for n in after["nodes"] if n.get("id") == "n_calib_mani"), {}).get("params", {})
_ts = str(ap.get("cfg_loaded_at") or "")
_fresh = False
try:
    _fresh = (time.time() - time.mktime(time.strptime(_ts, "%Y-%m-%d %H:%M:%S"))) < 300
except Exception:                                                                     # noqa: BLE001
    _fresh = False
ck("cfg_loaded_at 是本次真跑的 (5 分钟内)", bool(_ts) and _fresh, "%s → %s" % (_blog, _ts))
ck("cfg_files 列出加载过的文件", len(ap.get("cfg_files") or []) >= 9, "%d 项" % len(ap.get("cfg_files") or []))
ck("cfg_snapshot 带就绪度/活跃任务/工单", all((ap.get("cfg_snapshot") or {}).get(k) is not None
                                              for k in ("params_ready", "params_total", "active_task", "orders")),
   str({k: (ap.get("cfg_snapshot") or {}).get(k) for k in ("params_ready", "params_total", "active_task", "orders")}))
ck("cfg_source 标注导入函数", "config_import.py::import_config_files" in str(ap.get("cfg_source")),
   str(ap.get("cfg_source")))
ck("画布结构未被动 (89 节点 / 184 连线)",
   len(after["nodes"]) == 89 and len([l for l in after.get("links") or []]) == 184,
   "%d 节点 / %d 连线" % (len(after["nodes"]), len(after.get("links") or [])))

print()
print("判据结论: %s   (%d 通过 / %d 失败)" % ("✅ PASS" if _bad == 0 else "❌ FAIL", _ok, _bad))
raise SystemExit(0 if _bad == 0 else 1)
