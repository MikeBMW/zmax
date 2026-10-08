#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态空间工程文件 (.zmaxproj) —— 保存 / 加载老倪的调试工程 (2026-10-08)

老倪: 「在控制台，文件下拉菜单，增加一个保存工程文件的功能，这样，我下次进入控制台，
       直接加载这个工程文件，就可以继续调试状态空间工程了。」

一个工程文件 = **自包含** JSON (拿走一个文件就能在别处复原这次调试), 四段:
  meta      schema/时间/控制台版本/备注/画布指纹(md5 + 节点·连线数)
  canvas    画布真源全文 —— src/lerobot/engineering/flows/state_space_obs.json
  run_cfg   画布页 6 个运行档位勾选框状态
  ui        界面线索(画布栈索引等), 加载后用它把界面带回画布

🔴 铁律 (来自技能 state-space-canvas-engineering, 别绕):
  ① 画布只经 `flows.save_canvas()` 写 —— 它**自己校验**(不过就拒写) + 自动备份到
     `src/lerobot/engineering/flows/_archive/<name>_before_<reason>_<ts>.json`。
  ② 仓库根 `flows/state_space_obs.json` 是**软链**(→ 包里真源); 真源路径由 `paths.canvas_json()` 给,
     本模块**绝不**自己 os.replace 到软链上。
  ③ 保存前先校验画布: 存出去的是坏工程比"存不上"更糟(下次加载会把画布搞坏)。
"""
import hashlib
import json
import os
import time

SCHEMA = "zmax.statespace.project/1"
EXT = ".zmaxproj"

# 画布页工具栏那 6 个运行档位 (属性名, 界面文字) —— 与 simulink_module.py 逐字对应
RUN_CHECKS = (
    ("chk_engine_demo", "⚡引擎快演"),
    ("chk_l3_full", "🚀 L3 全链(插拔+AOI)"),
    ("chk_mani_yaw", "🧠 流形 yaw 执行"),
    ("chk_intact_exec", "🤖 L4 用 INTACT 节点执行"),
    ("chk_l4_dit", "🎯 L4 意图 → DiT 精炼"),
    ("chk_l2_compat", "🧩 L2 兼容 (前馈 MLP + YOLO)"),
)


def _flows():
    """延迟导入工程包 (GUI 之外也能用, 例如命令行自检)"""
    from lerobot.engineering import flows
    return flows


def _ver():
    try:
        from update_checker import CURRENT_VERSION
        return "v%s" % CURRENT_VERSION.lstrip("v")
    except Exception:                                                            # noqa: BLE001
        return "?"


def canvas_md5(d):
    """画布内容指纹 (键序无关, 便于判断"工程里的画布与当前画布是否同一份")"""
    return hashlib.md5(json.dumps(d, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def collect_run_cfg(sim):
    """从画布窗口读 6 个档位勾选状态; sim 为 None(画布还没建) 时返回 {}"""
    out = {}
    for attr, label in RUN_CHECKS:
        w = getattr(sim, attr, None) if sim is not None else None
        if w is None:
            continue
        try:
            out[attr] = {"label": label, "checked": bool(w.isChecked())}
        except Exception:                                                        # noqa: BLE001
            pass
    return out


def apply_run_cfg(sim, cfg):
    """把工程文件里的勾选状态写回界面; 返回 (写回项数, 跳过项说明)"""
    done, skip = [], []
    if sim is None or not isinstance(cfg, dict):
        return 0, list(cfg or {}) if isinstance(cfg, dict) else []
    for attr, label in RUN_CHECKS:
        item = cfg.get(attr)
        if not isinstance(item, dict):
            continue
        w = getattr(sim, attr, None)
        if w is None:
            skip.append("%s(界面里没有这个勾选框)" % label)
            continue
        try:
            w.setChecked(bool(item.get("checked")))
            done.append(label)
        except Exception as e:                                                   # noqa: BLE001
            skip.append("%s(%s)" % (label, e))
    return len(done), skip


def canvas_status():
    """当前画布: (数据, 校验问题列表, 指纹, 统计)"""
    flows = _flows()
    d, probs = flows.load_canvas()
    return d, list(probs or []), canvas_md5(d), flows.stats()


def save_project(path, sim=None, page=None, note=""):
    """把"现在的状态空间工程"存成一个自包含工程文件。返回摘要 dict。"""
    flows = _flows()
    d, probs, md5, stats = canvas_status()
    if probs:
        raise ValueError("当前画布有 %d 处问题, 先修好再存 (前 3 条): %s" % (len(probs), probs[:3]))
    proj = {
        "schema": SCHEMA,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "saved_by": "Z-MAX 控制台 · 文件 → 💾 保存工程文件",
        "zmax_version": _ver(),
        "note": note or "",
        "canvas_source": flows.canvas_path(),
        "canvas_fingerprint": {"md5": md5, "stats": stats},
        "canvas": d,
        "run_cfg": collect_run_cfg(sim),
        "ui": {"canvas_stack_index": page},
    }
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, str(path))                      # path 是用户选的普通文件(不是软链), 安全
    return {"path": os.path.abspath(str(path)), "md5": md5, "stats": stats,
            "run_cfg": proj["run_cfg"], "bytes": os.path.getsize(str(path)),
            "version": proj["zmax_version"], "saved_at": proj["saved_at"]}


def read_summary(path):
    """只读工程文件摘要 (加载前给用户看"这文件里是什么")"""
    with open(str(path), encoding="utf-8") as f:
        proj = json.load(f)
    if not isinstance(proj, dict) or proj.get("schema") != SCHEMA:
        raise ValueError("不是 Z-MAX 工程文件 (schema=%s)" % (proj.get("schema") if isinstance(proj, dict) else type(proj).__name__))
    d = proj.get("canvas")
    return {"saved_at": proj.get("saved_at"), "note": proj.get("note"),
            "version": proj.get("zmax_version"), "canvas_source": proj.get("canvas_source"),
            "fingerprint": proj.get("canvas_fingerprint") or {},
            "canvas_ok": isinstance(d, dict) and bool(d),
            "run_cfg": proj.get("run_cfg") or {},
            "ui": proj.get("ui") or {}}


def load_project(path):
    """把工程文件写回画布真源(自动备份), 返回摘要 + 需要写回界面的东西。"""
    flows = _flows()
    with open(str(path), encoding="utf-8") as f:
        proj = json.load(f)
    if not isinstance(proj, dict) or proj.get("schema") != SCHEMA:
        raise ValueError("不是 Z-MAX 工程文件 (schema=%s)" % (proj.get("schema") if isinstance(proj, dict) else type(proj).__name__))
    d = proj.get("canvas")
    if not isinstance(d, dict) or not d:
        raise ValueError("工程文件里没有画布数据 (canvas 段是空的)")
    probs = list(flows.validate_canvas(d) or [])
    if probs:
        raise ValueError("工程文件里的画布校验不过, 拒绝写盘 (前 3 条): %s" % probs[:3])
    _, _, cur_md5, _ = canvas_status()
    new_md5 = canvas_md5(d)
    # ✅ 唯一的写盘点: 校验 + 备份 + 原子替换 (由工程包负责, 见模块头铁律①②)
    p, bak = flows.save_canvas(d, reason="project_load")
    return {"path": os.path.abspath(str(path)), "written": p, "backup": bak,
            "same_as_before": new_md5 == cur_md5, "md5": new_md5,
            "stats": flows.stats(), "run_cfg": proj.get("run_cfg") or {},
            "ui": proj.get("ui") or {}, "saved_at": proj.get("saved_at"),
            "version": proj.get("zmax_version"), "note": proj.get("note")}


def project_dir(root=None):
    """工程文件默认目录: <仓库根>/reports/projects (老倪要能一眼找到)"""
    root = root or os.path.expanduser("~/zmax")
    d = os.path.join(root, "reports", "projects")
    os.makedirs(d, exist_ok=True)
    return d


if __name__ == "__main__":                       # 命令行自检: python project_file.py
    import sys
    print("schema=%s ext=%s 档位=%d 个" % (SCHEMA, EXT, len(RUN_CHECKS)))
    d, probs, md5, stats = canvas_status()
    print("画布真源: %s" % _flows().canvas_path())
    print("md5=%s · stats=%s · 校验问题=%s" % (md5, stats, probs or "无 ✅"))
    print("默认工程目录: %s" % project_dir(sys.argv[1] if len(sys.argv) > 1 else None))
