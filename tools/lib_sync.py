#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_sync.py — 📚 Simulink 画布左侧「模块库」同步/体检/清理 (2026-10-09 老倪)

老倪原话:
  「全面检查 simulink 画布左侧的模块库, 现在状态空间的节点, 所有节点, 都要与模块库同步;
    模块库的每个模块节点, 可以交互式拖进画布, 或者删除, 可以保存为新的工程文件;
    你来全局检查同步功能; 没有联系的模块, 或者没有关联的, 都删掉」

判定「有联系/有关联」(命中任一即算活着):
  ① 同名节点存在于任一 flows/*.json 画布 (画布构件, 含 row_bg 行背景)
  ② 名字在 REFERENCE_APPS 模板应用里 (总系统 SYS 系列)
  ③ 名字在原子技能注册表 flows/atomic_skill_tokens.json (点 = 打开原子技能流程)
  ④ match_node(名字) 命中引擎节点逻辑真源 src/lerobot/engineering/nodes/library.py
  ⑤ 条目自带 flow / template / params.scene_id / params.atomic_gate (点了会打开流程/场景/闸)
只有①~⑤全不命中的, 才算「没有联系/没有关联」→ prune 删掉。

用法:
  lib_sync.py check          # 体检报告 (不写任何东西)
  lib_sync.py dead           # 只列"无关联"清单 (分组)
  lib_sync.py prune          # 把"无关联"写入 config/library_curation.json 删除名单 (可还原)
  lib_sync.py restore        # 清空删除名单 (全部还原)
  lib_sync.py list           # 列出当前删除名单
  lib_sync.py verify         # 同步判定: 画布节点是否都在库里 + 库里有无死条目
退出码: check/verify/prune 有死条目 → 1 (供 CI/判据用), 干净 → 0
"""
import glob
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))          # 引擎节点逻辑真源 (lerobot.engineering)
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))


def _flows():
    return sorted(set(glob.glob(os.path.join(ROOT, "src/lerobot/engineering/flows/*.json"))
                      + glob.glob(os.path.join(ROOT, "flows/*.json"))))


def canvas_nodes():
    """所有画布的功能节点名 → {名字: [画布文件...]}"""
    out = {}
    for fp in _flows():
        if os.path.basename(fp) in ("atomic_skill_tokens.json", "library_curation.json"):
            continue
        try:
            d = json.loads(open(fp, encoding="utf-8").read())
        except Exception:                                                        # noqa: BLE001
            continue
        if not isinstance(d, dict):
            continue
        for n in (d.get("nodes") or []):
            out.setdefault(n.get("name", ""), []).append(os.path.basename(fp))
    return out


def atomic_names():
    try:
        tk = json.loads(open(os.path.join(ROOT, "flows/atomic_skill_tokens.json"),
                             encoding="utf-8").read())
        return {"🧩 %s %s" % (s["skill_id"], s["name"][:16]) for s in tk["skills"]}
    except Exception:                                                            # noqa: BLE001
        return set()


def reference_names():
    """REFERENCE_APPS 模板节点名 (simulink_module 里的模板应用)"""
    try:
        import simulink_module as SM
        out = set()
        for app in SM.REFERENCE_APPS:
            for n in (app[1] or []):
                if n[1]:
                    out.add(n[1])
        return out
    except Exception:                                                            # noqa: BLE001
        return set()


def engine_hits(name):
    """match_node(名字) — 命中引擎节点逻辑真源?"""
    try:
        from lerobot.engineering.registry import match_node
        return bool(match_node(name))
    except Exception:                                                            # noqa: BLE001
        return False


def analyze():
    import simulink_module as SM
    cv, atom, ref = canvas_nodes(), atomic_names(), reference_names()
    alive, dead = [], []
    for gtype, gname, items in SM.LIBRARY:
        for it in items:
            nm = it.get("name") or ""
            ps = it.get("params") or {}
            why = []
            if nm in cv:
                why.append("画布节点(%s)" % cv[nm][0])
            if nm in ref:
                why.append("模板应用")
            if nm in atom:
                why.append("原子技能注册表")
            if it.get("flow"):
                why.append("绑 flow")
            if it.get("template"):
                why.append("模板节点")
            if ps.get("scene_id"):
                why.append("绑场景")
            if ps.get("atomic_gate"):
                why.append("绑原子闸")
            if not why and engine_hits(nm):
                why.append("引擎逻辑命中")
            (alive if why else dead).append((gname, nm, "|".join(why)))
    return cv, alive, dead


def _cur_path():
    return os.path.join(ROOT, "config", "library_curation.json")


def _cur_load():
    try:
        d = json.loads(open(_cur_path(), encoding="utf-8").read())
        return d if isinstance(d, dict) else {}
    except Exception:                                                            # noqa: BLE001
        return {}


def _cur_save(d):
    os.makedirs(os.path.dirname(_cur_path()), exist_ok=True)
    tmp = _cur_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _cur_path())


def cmd_check():
    cv, alive, dead = analyze()
    print("📚 模块库体检 (config/library_curation.json = %s)"
          % ("有删除名单" if _cur_load().get("removed") else "无删除名单"))
    print("   画布节点: %d 个 (来自 %d 个 flow)" % (len(cv), len(_flows())))
    print("   库条目: %d 条 (活 %d / 无关联 %d)" % (len(alive) + len(dead), len(alive), len(dead)))
    if dead:
        from collections import Counter
        c = Counter(g for g, _, _ in dead)
        print("   ⛔ 无关联条目:")
        for g, n in c.most_common():
            print("      %-34s %d" % (g[:34], n))
    return 1 if dead else 0


def cmd_dead():
    _, _, dead = analyze()
    for g, nm, _ in dead:
        print("%-34s %s" % (g[:34], nm))
    print("共 %d 条" % len(dead))
    return 1 if dead else 0


def cmd_prune():
    _, _, dead = analyze()
    d = _cur_load()
    rm = d.setdefault("removed", [])
    have = {(x.get("group"), x.get("name")) for x in rm}
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    add = 0
    for g, nm, _ in dead:
        if (g, nm) not in have:
            rm.append({"group": g, "name": nm, "why": "无联系/无关联 (无同名画布节点·无引擎逻辑·无flow/模板/场景/闸)",
                       "ts": ts})
            add += 1
    d["note"] = ("📚 模块库删除名单 — 老倪「没有联系的模块, 或者没有关联的, 都删掉」(2026-10-09)。"
                 "删条目不影响画布节点; restore 可整表还原。")
    _cur_save(d)
    print("✅ 已写入删除名单 %d 条 → %s (现共 %d 条)" % (add, _cur_path(), len(rm)))
    return 1 if dead else 0


def cmd_restore():
    d = _cur_load()
    n = len(d.get("removed") or [])
    _cur_save({"removed": [], "note": "已还原 (restore)"})
    print("✅ 删除名单已清空 (还原 %d 条)" % n)
    return 0


def cmd_list():
    rm = _cur_load().get("removed") or []
    print("📚 删除名单 %d 条:" % len(rm))
    for x in rm:
        print("   %-30s %-40s %s" % (x.get("group", "")[:30], x.get("name", "")[:40], x.get("ts", "")))
    return 0


def cmd_verify():
    """同步判定: ① 状态空间画布节点必须全在库里 ② 库里不得有死条目 ③ 同组内不得重名

    ① 只认「状态空间画布」(flows/state_space_obs.json = 库内 🧮 组镜像的那张) —— 别的 side canvas
       (model_zoo/dual_brain/测试 flow) 不要求出现在库里 (库不是所有 flow 的并集)。
    """
    import simulink_module as SM
    cv, _, dead = analyze()
    ss_path = os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json")
    ss = json.loads(open(ss_path, encoding="utf-8").read())
    ss_names = sorted({n.get("name") for n in (ss.get("nodes") or [])})
    lib_names = []
    for _, gname, items in SM.LIBRARY:
        lib_names += [(gname, it.get("name")) for it in items]
    lib_set = {n for _, n in lib_names}
    miss = [n for n in ss_names if n not in lib_set]
    other = sorted(set(cv) - set(ss_names))
    cover = len([n for n in other if n in lib_set])
    print("① 状态空间画布节点 %d 个 (功能 %d + 行背景 %d) → 库中缺 %d 个 %s"
          % (len(ss_names), len([n for n in ss_names if not str(n).startswith("row_bg")]),
             len([n for n in ss_names if str(n).startswith("row_bg")]), len(miss), miss[:6]))
    print("   (其它画布节点 %d 个, 库里覆盖 %d 个 — 仅供参照, 不作判据)" % (len(other), cover))
    print("② 库条目 %d 条 → 无关联 %d 条" % (len(lib_names), len(dead)))
    dup = {}
    for g, n in lib_names:
        dup[(g, n)] = dup.get((g, n), 0) + 1
    dups = {k: v for k, v in dup.items() if v > 1}
    print("③ 同组重名: %d %s" % (len(dups), list(dups)[:5]))
    ok = (not miss) and (not dead) and (not dups)
    print(("✅ 模块库与状态空间画布同步 (库 %d 条)" % len(lib_names)) if ok else "❌ 未同步")
    return 0 if ok else 1


def main():
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "check").strip()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv[:1])
        globals()["_APP"] = app
    except Exception:                                                            # noqa: BLE001
        pass
    fn = {"check": cmd_check, "dead": cmd_dead, "prune": cmd_prune,
          "restore": cmd_restore, "list": cmd_list, "verify": cmd_verify}.get(cmd)
    if fn is None:
        print(__doc__)
        return 2
    rc = fn()
    sys.stdout.flush()
    os._exit(rc)      # 画布/DDS 线程 → 直退, 免退出段 core dump


if __name__ == "__main__":
    main()
