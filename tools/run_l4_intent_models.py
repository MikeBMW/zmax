#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跑通 L4 层**所有意图模型** (老倪 2026-10-14: 「配置任务 摆盘任务，跑通 L4层 所有 意图模型」)

跑的是哪些 (L4 层的意图链, 与画布节点一一对应):
  ① 🧾 元任务预测 (n_intent_direct, 输入=驱动扭矩)      → ss_meta_predict
  ② 🧾 元任务派生 (任务 → 元任务清单)                    → ss_meta_task
  ③ 🎯 INTACT 意图解码器 (ssintact_dec, 在役 ckpt)      → IntactEncoderModel (真推理)
  ④ 🎛 L4 · INTACT LoRA 微调 (ss_lora_l4, 冻结原权重)   → node_ss_lora_l4
  ⑤ 🧠 流形专家预测器 (ssmani_exp)                      → node_ss_pred
  ⑥ 🧮 接触流形 (ssmani_c) / 🧮 性能流形 (ssmani_p)      → node_ss_mani ×2
  ⑦ 🧮 流形引擎 + L4 潜空间 (VLM 编码器) 常驻回路        → ss_engine_loop --encoder l4 (debug 实例)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = "/home/ubuntu/zmax"
PY = os.path.join(ROOT, "gui-venv311/bin/python")
TASK = os.environ.get("ZMAX_L4_TASK") or "TASK-06-TRAY"
SCENE = os.environ.get("ZMAX_L4_SCENE") or "SCN-06-TRAY"
ENV = {**os.environ, "INTACT_POLICY": "intact_l4_current",
       "STABLEWM_HOME": os.path.join(ROOT, "zmax_data/stable-wm-cache")}
ok_all = []


def chk(tag, cond, detail=""):
    ok_all.append(bool(cond))
    print("%s %s %s" % ("✅" if cond else "❌", tag, detail))


def run(args, timeout=600, tail=0):
    r = subprocess.run([PY] + args, capture_output=True, text=True, timeout=timeout, cwd=ROOT, env=ENV)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out, (out.strip().splitlines()[-tail:] if tail else [])


def main() -> int:
    print("══ 任务: %s (%s) · 时刻 %s ══" % (TASK, SCENE, time.strftime("%H:%M:%S")))

    # ① 元任务派生 (任务 → 元任务清单, 真源现算)
    rc, out, _ = run(["tools/ss_meta_task.py", "--task", TASK, "--write", "--json"], timeout=300)
    try:
        j = json.loads(out[out.index("{"):out.rindex("}") + 1])
        n_meta = len(j.get("meta_tasks") or j.get("items") or [])
    except Exception:                                                        # noqa: BLE001
        n_meta = 0
    chk("① 🧾 元任务派生", rc == 0 and n_meta > 0, "%s → %d 个元任务" % (TASK, n_meta))

    # ② 元任务预测 (输入 = 该场景驱动扭矩 tap)
    rc, out, _ = run(["tools/ss_meta_predict.py", "--scene", SCENE, "--write", "--json"], timeout=300)
    top = ""
    try:
        j = json.loads(out[out.index("{"):out.rindex("}") + 1])
        tl = j.get("top") or []
        top = "top1=%s(%.3f) · 候选 %d · frozen=%s" % (
            (tl[0].get("fn_id") if isinstance(tl[0], dict) else tl[0]), (tl[0].get("score") if isinstance(tl[0], dict) else 0.0),
            len(j.get("scores") or []), j.get("frozen"))
    except Exception:                                                        # noqa: BLE001
        top = out.strip().splitlines()[-1] if out.strip() else "无输出"
    chk("② 🧾 元任务预测 (驱动扭矩)", rc == 0, top[:130])

    # ③ INTACT 意图解码器 (真推理: 冻结在役 ckpt)
    code = ("import sys,json,numpy as np;sys.path.insert(0,'src');"
            "from lerobot.manifold.encoder_model import IntactEncoderModel;"
            "m=IntactEncoderModel('.');ok,why=m.available();"
            "lat=m.encode() if ok else {};"
            "print(json.dumps({'ok':ok,'why':why[:90],"
            "'z_t':bool(np.isfinite(np.asarray(lat.get('z_t'),float)).all()) if lat else False,"
            "'z_goal':bool(np.isfinite(np.asarray(lat.get('z_goal'),float)).all()) if lat else False,"
            "'delta':bool(np.isfinite(np.asarray(lat.get('delta'),float)).all()) if lat else False,"
            "'z_pred':bool(np.isfinite(np.asarray(lat.get('z_pred'),float)).all()) if lat else False,"
            "'dim':int(np.asarray(lat.get('z_t')).size) if lat else 0}))")
    rc, out, _ = run(["-c", code], timeout=600)
    try:
        j = json.loads(out[out.index("{"):out.rindex("}") + 1])
    except Exception:                                                        # noqa: BLE001
        j = {}
    chk("③ 🎯 INTACT 意图解码器", bool(j.get("ok")) and j.get("z_t") and j.get("delta"),
        "z_t/z_goal/delta 有限 (dim=%s) · z_pred %s" % (j.get("dim"), "有限" if j.get("z_pred") else "= NaN (上游动作块空, 如实)"))

    # ④ 摆盘轨迹真源 (seed) + 常驻回路 (L4 潜空间 encoder)
    rc, out, _ = run(["tools/ss_engine_loop.py", "seed", "--episode", "reports/ss_episode_latest.npz"], timeout=300)
    traj = json.load(open(os.path.join(ROOT, "data/database/zmax/sources/canvas/ss_traj_last.json"), encoding="utf-8"))
    n_obs = int(traj.get("n") or len(traj.get("obs") or []))
    chk("④ 摆盘轨迹真源 (任务标记)", n_obs > 0 and traj.get("task_id") == TASK,
        "%d 帧 × obs%d · 任务 %s · t 轴 %d (t 由画布播放填) · 源 %s"
        % (n_obs, int(traj.get("obs_dim") or 0), traj.get("task_id"), len(traj.get("t") or []),
           str(traj.get("src"))[:60]))
    rc, out, _ = run(["tools/ss_engine_loop.py", "run", "--instance", "l4tray", "--encoder", "l4",
                      "--l4-hz", "1", "--seconds", "7", "--no-lock"], timeout=420)
    attach = [l for l in out.splitlines() if "L4 潜空间已接入" in l]
    chk("⑦ 🧮 流形引擎 + L4 潜空间 (VLM 编码器) 常驻回路", bool(attach),
        (attach[0][-110:] if attach else (out.strip().splitlines()[-1][:110] if out.strip() else "无输出")))
    tap = "/dev/shm/zmax_ss_engine_l4tray/engine_default.jsonl"
    if os.path.exists(tap):
        d = json.loads(open(tap, encoding="utf-8").read().strip().splitlines()[-1])
        chk("⑦ 回路口径 (任务/编码链/潜坐标)", d.get("task_id") == TASK and d.get("encoder") == "l4"
            and len(d.get("z_latent") or []) == 16,
            "任务 %s · encoder %s · z_source %s" % (d.get("task_id"), d.get("encoder"), str(d.get("z_source"))[:90]))
        z_intent = d.get("z_latent") or []
    else:
        chk("⑦ 回路口径 (任务/编码链/潜坐标)", False, "tap 没生成")
        z_intent = []

    # ⑤⑥ 画布 L4 节点连跑 (LoRA → 专家预测器 → 接触/性能流形), 用摆盘轨迹
    code2 = """
import json, sys, numpy as np
sys.path.insert(0,'/home/ubuntu/zmax/src')
from lerobot.engineering.nodes import library as lib
import numpy as np
import numpy as _np
_z=_np.load('/home/ubuntu/zmax/reports/ss_episode_latest.npz', allow_pickle=True)
tr={k:([list(map(float,r)) for r in _z[k]] if _np.asarray(_z[k]).ndim>1 else list(_z[k])) for k in _z.files if _np.asarray(_z[k]).ndim<=2}
z=%s or []
lib._SS_STATE['mani_eng']={'z':z,'grad':[-0.01]*16,'M':3.643}
lib._SS_STATE['lora_in']={'u_int':z,'src':'摆盘常驻回路 L4 潜坐标 z_latent'}
logs=[]; out={}
ctx={'log':lambda s: logs.append(str(s)), 'module':type('M',(),{'_ss_tr':tr,'_ss_round':max(0,len(tr.get('t',[]))-1)})(), 'name':''}
for nid,fn,nm in (('ss_lora_l4',lib.node_ss_lora_l4,'🎛 L4 LoRA'),('ssmani_exp',lib.node_ss_pred,'🧠 专家预测器'),
                  ('ssmani_c',lib.node_ss_mani,'🧮 接触流形'),('ssmani_p',lib.node_ss_mani,'🧮 性能流形')):
    ctx['name']= ('🧮 接触流形' if nid=='ssmani_c' else '🧮 性能流形' if nid=='ssmani_p' else nm)
    r=fn(ctx); out[nid]=bool(r)
ll=lib._SS_STATE.get('lora_l4') or {}
out['du_norm']=float(ll.get('du_norm') or 0); out['trained']=bool(ll.get('trained'))
out['contact']=(ll.get('contact') or {}); out['perf']=(ll.get('performance') or {})
json.dump({'res':out,'logs':logs[-24:]}, open('/tmp/l4_nodes_result.json','w'), ensure_ascii=False)
print('RESULT_WRITTEN')
""" % (json.dumps(z_intent),)
    rc, out, _ = run(["-c", code2], timeout=300)
    try:
        blob = json.load(open("/tmp/l4_nodes_result.json", encoding="utf-8"))
        res, logs = blob.get("res", {}), blob.get("logs", [])
    except Exception as e:                                                   # noqa: BLE001
        res, logs = {}, []
        print("⚠️ 节点连跑结果读不到: %s · 原始尾: %s" % (e, out.strip().splitlines()[-1][:110] if out.strip() else ""))
    chk("⑤ 🎛 L4 INTACT LoRA 微调 (冻结原权重)", res.get("ss_lora_l4") and res.get("trained"),
        "‖Δu‖=%.3g · 已训练=%s" % (res.get("du_norm", 0.0), res.get("trained")))
    chk("⑥ 🧠 流形专家预测器", res.get("ssmani_exp"), "节点执行 True")
    chk("⑥ 🧮 接触流形", res.get("ssmani_c"),
        "f_n=%.3f · 锥内=%s · Φ_c=%.4g" % (float((res.get("contact") or {}).get("f_n") or 0),
                                        (res.get("contact") or {}).get("inside_cone"),
                                        float((res.get("contact") or {}).get("phi_c") or 0)))
    chk("⑥ 🧮 性能流形", res.get("ssmani_p"),
        "V_p=%.4g · η=%.4f" % (float((res.get("perf") or {}).get("V_p") or 0),
                              float((res.get("perf") or {}).get("eta") or 0)))
    print("══ 节点实测日志 (节选) ══")
    for l in logs[-12:]:
        print("   " + str(l)[:170])
    print("L4 意图模型 %d/%d %s (任务 %s)" % (sum(ok_all), len(ok_all), "全部跑通" if all(ok_all) else "有失败", TASK))
    return 0 if all(ok_all) else 1


if __name__ == "__main__":
    raise SystemExit(main())
