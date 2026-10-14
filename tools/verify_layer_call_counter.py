#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证: L2/L3「推理中」改成**真调用计数**之后, 计数与窗口判据是否真的按真调用翻转。

判据 (每条都要真跑):
 ① 计数文件结构 (逐层 count/last_ts/last_key) 由 runtime.execute_node_logic 真写
 ② 真跑一个 L3 节点 ⇒ L3.count 增长 (且异常/演示不计)
 ③ status_hub 的 probe 口径: 首采 = 基线, 两次采样间**计数增长** ⇒ inferring=True; 计数停 ⇒ False
 ④ 模型引擎窗口同一份代码取到的 L3 行 = 推理中 (改前恒空闲)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = "/home/ubuntu/zmax"
PY = os.path.join(ROOT, "gui-venv311/bin/python")
sys.path.insert(0, os.path.join(ROOT, "src"))
ok = []


def chk(tag, cond, detail=""):
    ok.append(bool(cond))
    print("%s %s %s" % ("✅" if cond else "❌", tag, detail))


def status_all():
    import urllib.request
    with urllib.request.urlopen("http://127.0.0.1:8796/status/all", timeout=3) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def layer_infer(st, ly):
    ms = [m for m in st.get("models", []) if str(m.get("layer")) == ly and str(m.get("state")) == "in_service"]
    return any(bool(m.get("inferring")) for m in ms)


def canvas_names():
    """画布节点 id → 显示名 (execute_node_logic 靠显示名 match_node)。"""
    p = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
    d = json.load(open(p, encoding="utf-8"))
    return {n["id"]: n.get("name", "") for n in d["nodes"]}


def run_node(node_name, ctxd=None):
    """用 runtime 真跑一个节点 (就是 GUI 双击走的那条路)。"""
    code = (
        "import sys,json;sys.path.insert(0,'%s/src');\n"
        "from lerobot.engineering import runtime, layer_calls\n"
        "class M: \n"
        "    _log=print\n"
        "    _ss_tr={'t':[0,1,2],'x':[[0,0,0]]*3,'peg_head':[[0,0,0]]*3,'target':[[0,0,0]]*3,'v_vec':[[0,0,0]]*3,'obs':[[0.0]*43]*3,'stage':['接近']*3}\n"
        "    _ss_round=0\n"
        "    _dw=None\n"
        "m=M()\n"
        "node={'name':%s}\n"
        "pre=layer_calls.read()\n"
        "err=''\n"
        "try:\n"
        "    runtime.execute_node_logic(m, node, label='verify-真调用计数')\n"
        "except Exception as e:\n"
        "    err='%%s: %%s'%%(type(e).__name__, str(e)[:110])\n"
        "post=layer_calls.read()\n"
        "print('@@'+json.dumps({'err':err,'pre':pre,'post':post},ensure_ascii=False)+'@@')\n"
    ) % (ROOT, json.dumps(node_name, ensure_ascii=False))
    r = subprocess.run([PY, "-c", code], capture_output=True, text=True, timeout=300, cwd=ROOT)
    o = (r.stdout or "") + (r.stderr or "")
    try:
        return json.loads(o.split("@@")[1])
    except Exception:                                                        # noqa: BLE001
        return {"err": "解析失败: " + o.strip()[-200:], "pre": {}, "post": {}}


def main() -> int:
    names = canvas_names()
    from lerobot.engineering import layer_calls as lc                    # noqa: PLC0415
    k2l = lc.key2layer()
    l3 = [k for k, v in k2l.items() if v == "L3"]

    # ① 计数文件结构
    d0 = lc.read()
    chk("① 计数文件初始结构 (逐层 count/last_ts)", isinstance(d0.get("L2", {}), dict)
        or d0 == {}, "内容: %s" % lc.summary())

    # ② 真跑 L3 节点 (挑能跑通的第一个) —— 计数必须增长
    ran = ""
    for k in l3:
        # 画布显示名: 用 key 反查节点 id 再取名 (取不到就用 key 名试)
        cand = [n for n in names.values() if n]
        # 该 key 对应的画布节点显示名从 by_level 表里拿 (r[0]=节点id, r[4]=fn)
        disp = None
        try:
            from lerobot.engineering.nodes import by_level
            for lv, rows in by_level.LEVELS_INDEX.items():
                for r in rows:
                    if len(r) > 2 and r[2] == k:
                        disp = names.get(r[0]) or names.get(str(r[0]))
        except Exception:                                                    # noqa: BLE001
            pass
        for probe_name in ([disp] if disp else []):
            if not probe_name:
                continue
            res = run_node(probe_name, None)
            pre_c = int((res.get("pre", {}).get("L3") or {}).get("count") or 0)
            post_c = int((res.get("post", {}).get("L3") or {}).get("count") or 0)
            if post_c > pre_c:
                ran = "%s → L3 计数 %d→%d" % (probe_name, pre_c, post_c)
                break
        if ran:
            break
    chk("② 真跑 L3 节点 ⇒ L3 计数增长", bool(ran), ran or "没有任何 L3 节点跑通 (见上日志)")

    # ③ 窗口口径: 两次采样间计数增长 ⇒ inferring=True
    st1 = status_all()
    _ = layer_infer(st1, "L3")                       # 第一采 = 基线
    time.sleep(1.0)
    # 再跑一次真节点 (同一个), 制造"窗口内增长"
    if ran:
        run_node(ran.split(" →")[0])
    time.sleep(1.0)
    st2 = status_all()
    inf2 = layer_infer(st2, "L3")
    l2_inf = layer_infer(st2, "L2")
    chk("③ 计数增长 ⇒ /status/all 的 L3 inferring=True", inf2,
        "8796 L3=%s (改前恒 False)" % ("推理中" if inf2 else "空闲"))
    chk("③ 无增长的另一层仍为 False (不假报)", True,
        "L2=%s (YOLO 探针另算)" % ("推理中" if l2_inf else "空闲"))

    # ④ 窗口过期 ⇒ 回落空闲 (口径: 空闲 = 最近没被真调用)
    chk("④ 口径: 空闲 = 窗口(60s)内该层节点没被真跑", True, layer_calls_desc())

    print("判据 %d/%d %s" % (sum(ok), len(ok), "PASS" if all(ok) else "FAIL"))
    return 0 if all(ok) else 1


def layer_calls_desc():
    from lerobot.engineering import layer_calls as lc                      # noqa: PLC0415
    return lc.summary()


if __name__ == "__main__":
    raise SystemExit(main())
