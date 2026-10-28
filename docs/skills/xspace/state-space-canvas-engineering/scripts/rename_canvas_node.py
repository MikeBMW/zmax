#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画布节点改名: 画布 name + function_notes.json + zmax_platform.json 三处同改, 带前后闸。

用法 (在 zmax 仓库根跑):
    ./gui-venv311/bin/python <此文件> --id ssllm --old "L3 " --new ""
    ... --dry-run              只打印将要做的改动, 不写盘

为什么只做子串替换: 三处都是「值里的子串, 键不变」, 整表重序列化会重排键/缩进,
让后续 check 报假漂移。替换前后各 json.loads 验一次合法性, 改前备份到 /tmp。

门槛 (顺序不能换):
    ① 前置闸  registry 关键字里有没有被去掉的那个词 —— 在列表里就拒跑
              (必须先「加新名 + 保留旧名」再改画布, 否则双击看源码/单步/任务绑定全断)
    ② 写盘走 flows.save_canvas() (自带校验 + _archive 备份), 不用手写 JSON
    ③ 后置闸  回读画布名 · match_node(新名) == 原 key · 旧子串计数归零

生成物 (param_spec / dds_topic_types / mcd / 工程库) 不在这里改 —— 改完跟序跑:
    gen_topic_types.py → mcd_build.py → project_archive.py space-save
    → engineering_db.py build → engineering_db.py check

Exit: 0 ok · 2 前置闸拦下 · 3 后置闸失败
"""
import argparse
import json
import os
import shutil
import sys
import time


def _repo_root() -> str:
    """按标记向上找仓库根 (同目录下同时有 src/lerobot 与 tools)。"""
    for start in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
        d = start
        for _ in range(8):
            if os.path.isdir(os.path.join(d, "src", "lerobot")) and os.path.isdir(os.path.join(d, "tools")):
                return d
            d = os.path.dirname(d)
    raise SystemExit("❌ 找不到仓库根 (需同时有 src/lerobot 与 tools)")


JSON_SOURCES = (
    "data/database/zmax/function_notes.json",
    "data/database/zmax/sources/config/platform/zmax_platform.json",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="画布节点 id, 例如 ssllm")
    ap.add_argument("--old", required=True, help="要被替换掉的子串, 例如 \"L3 \"")
    ap.add_argument("--new", default="", help="替换成什么, 默认空串(=删掉)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root = _repo_root()
    sys.path.insert(0, os.path.join(root, "src"))
    from lerobot.engineering import flows, registry          # noqa: PLC0415

    # ── ① 前置闸: 拿节点的 key 与关键字 ────────────────────────────
    canvas, errs = flows.load_canvas()
    hit = [n for n in canvas["nodes"] if n.get("id") == a.id]
    if not hit:
        print("❌ 画布上没有节点 %s" % a.id)
        return 2
    node = hit[0]
    old_name = node.get("name") or ""
    key = registry.match_node(old_name)
    if not key:
        print("❌ 名字 %r 命中不了任何注册 key —— 先修关键字再改名" % old_name)
        return 2
    matches = (registry.get(key) or {}).get("match") or []
    stripped = a.old.strip()
    danger = [m for m in matches if stripped and stripped in m]
    print("节点 %s | key=%s | 关键字=%s" % (a.id, key, matches))
    print("名字: %r → %r" % (old_name, old_name.replace(a.old, a.new)))
    if danger:
        print("⛔ 前置闸: 要删的子串 %r 出现在注册关键字 %s 里 —— 直接改会让双击/单步/绑定断掉。"
              % (stripped, danger))
        print("   先往 library.py 的 _reg(<key>, [...]) 里加新名并保留旧名, 再来跑本脚本。")
        return 2
    if a.dry_run:
        for rel in JSON_SOURCES:
            p = os.path.join(root, rel)
            cnt = open(p, encoding="utf-8").read().count(a.old) if os.path.exists(p) else 0
            print("   %-62s 将替换 %d 处" % (os.path.basename(rel), cnt))
        print("(dry-run, 未写盘)")
        return 0

    # ── ② 写盘: 画布走 save_canvas, 两份 JSON 只做子串替换 ─────────
    node["name"] = old_name.replace(a.old, a.new)
    flows.save_canvas(canvas, reason="%s 改名: %r → %r" % (a.id, a.old, a.new))
    ts = time.strftime("%H%M%S")
    for rel in JSON_SOURCES:
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            print("   跳过(不存在): %s" % rel)
            continue
        raw = open(p, encoding="utf-8").read()
        cnt = raw.count(a.old)
        if not cnt:
            print("   无命中: %s" % os.path.basename(rel))
            continue
        json.loads(raw)                                   # 改前必须合法
        shutil.copy2(p, "/tmp/%s.bak_%s" % (os.path.basename(p), ts))
        new_raw = raw.replace(a.old, a.new)
        json.loads(new_raw)                               # 改后仍须合法
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(new_raw)
        print("   %s: 替换 %d 处" % (os.path.basename(rel), cnt))

    # ── ③ 后置闸 ─────────────────────────────────────────────────
    canvas2, _ = flows.load_canvas()
    new_name = [n for n in canvas2["nodes"] if n.get("id") == a.id][0]["name"]
    hit_key = registry.match_node(new_name)
    ok = (a.old not in new_name) and hit_key == key
    if ok:
        for rel in JSON_SOURCES:                          # 旧子串必须归零
            p = os.path.join(root, rel)
            if os.path.exists(p) and a.old in open(p, encoding="utf-8").read():
                ok, why = False, "%s 仍有残留" % os.path.basename(rel)
                break
    print("后置闸: 新名=%r · match_node → %s (原 %s)" % (new_name, hit_key, key))
    if not ok:
        print("❌ 后置闸失败 %s" % ("" if ok else ("(残留: %s)" % why if "why" in dir() else "")))
        return 3
    print("✅ 改名完成。接着跑: gen_topic_types → mcd_build → space-save → engineering_db build/check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
