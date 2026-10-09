#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""project_archive.py — 状态空间工程存档 (.zmaxproj v2) 命令行: 存 / 看 / 比 / 校验 / 恢复 / 列

老倪 (2026-10-09): 「需要保存 状态空间工程的所有配置，包括画布的模型，右侧侧面栏的所有配置，
标定，测量，以及主参数，都要有相应的文件，你来设计一下工程存档文件」

存档 = 自包含 JSON, 7 段: ①canvas 画布模型 ②panel 右侧栏配置 ③calibration 标定
④master_param 主参数 M ⑤measure 测量 ⑥tasks 任务 ⑦fingerprints 真源指纹表。
🔴 真源永远是文件本身 (画布/标定/任务绑定); 存档只是快照+指纹 ⇒
   `restore` **默认只回填画布+面板**, 标定/主参数只比对不覆盖 (要覆盖得 --with-calib --yes)。

用法:
  python tools/project_archive.py space-save              # 🗂 存「总工程」zmax_space.zmaxproj (集成式, 一个文件)
  python tools/project_archive.py space-open [file] --yes # 🗂 集成式打开总工程 (全量回填, 先备份)
  python tools/project_archive.py space-show [file]       # 看总工程里有什么 + 与现场漂移
  python tools/project_archive.py save                    # 存一份普通存档 (快照)
  python tools/project_archive.py save --out xx.zmaxproj --note "调完回零"
  python tools/project_archive.py list                    # 列出现有存档 + 逐段漂移
  python tools/project_archive.py inspect <file>          # 存档里有什么 (逐段条目/大小/指纹)
  python tools/project_archive.py diff <file>             # 存档 vs 现场: 哪些段漂了、哪个键变了
  python tools/project_archive.py verify <file>           # 自检: schema/必需段/sha256/画布校验
  python tools/project_archive.py restore <file>          # 只回填画布+面板 (写前自动备份)
  python tools/project_archive.py restore <file> --with-calib --yes   # 连标定/主参数一起恢复 (三段纪律)
  python tools/project_archive.py explode <file> [--dir out]          # 拆成人能看的文件 + MANIFEST
  python tools/project_archive.py upgrade <v1file> [--out v2file]     # 老存档升 v2
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui"))
import project_file as PF                                            # noqa: E402


def _fmt_bytes(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return "%.1f %s" % (n, u)
        n /= 1024.0


def _sec_iter(proj):
    """存档里的 7 段 → 可打印的 (段名, 条目数, 摘要)"""
    yield "① canvas", "画布模型", "%s 节点 / %s 连线 · md5 %s" % (
        (proj.get("canvas_fingerprint") or {}).get("stats", {}).get("nodes"),
        (proj.get("canvas_fingerprint") or {}).get("stats", {}).get("links"),
        ((proj.get("canvas_fingerprint") or {}).get("md5") or "")[:12])
    pn = proj.get("panel") or {}
    rs = pn.get("run_switches") or proj.get("run_cfg") or {}
    yield "② panel", "右侧栏配置", "视图 %s · %d 个运行开关 (勾选中 %s)" % (
        pn.get("view") or pn.get("view_label") or "?", len(rs),
        [v.get("label") for v in rs.values() if isinstance(v, dict) and v.get("checked")] or "无")
    cal = proj.get("calibration") or {}
    yield "③ calibration", "标定", "%d 个真源文件 %s · 未标定 %s" % (
        len(cal.get("files") or {}), sorted((cal.get("files") or {}).keys()),
        cal.get("uncalibrated") or [])
    mp = proj.get("master_param") or {}
    yield "④ master_param", "主参数 M", "M=%s inertia=%s 范围 %s" % (mp.get("M"), mp.get("inertia"),
                                                                  mp.get("range"))
    mv = (proj.get("measure") or {}).get("measure_view") or {}
    bus = (proj.get("measure") or {}).get("bus") or {}
    yield "⑤ measure", "测量", "measure_view %s 项 · 总线模式 %s" % (
        mv.get("测量量"), bus.get("mode"))
    tk = (proj.get("tasks") or {}).get("content") or {}
    yield "⑥ tasks", "任务/绑定", "%d 个任务 · 活跃 %s" % (
        len(tk.get("tasks") or {}), tk.get("active_task") or tk.get("active"))
    yield "⑦ fingerprints", "真源指纹", "%d 个文件" % len(proj.get("fingerprints") or {})


# ─────────── save ───────────
def cmd_save(a):
    if a.out:
        path = a.out
    else:
        path = os.path.join(PF.project_dir(), "状态空间工程_%s%s" % (time.strftime("%Y%m%d_%H%M%S"),
                                                                   PF.EXT))
    r = PF.save_project(path, note=a.note, with_calib=not a.no_calib_content)
    print("✅ 工程存档已写: %s  (%s)" % (r["path"], _fmt_bytes(r["bytes"])))
    print("   版本 %s · 存于 %s · schema %s" % (r["version"], r["saved_at"], r["schema"]))
    for k, v in r["sections"].items():
        print("   · %-12s %s" % (k, v))
    print("\n   🔴 真源没动: 存档只是快照+指纹。下次 restore 默认只回填画布+面板, 标定/主参数要显式 --with-calib --yes。")
    return 0


# ─────────── inspect ───────────
def cmd_inspect(a):
    proj = PF._read(a.file)
    print("══ 存档 %s ══" % os.path.abspath(a.file))
    print("schema %s · 存于 %s · 版本 %s · 主机 %s" % (proj.get("schema"), proj.get("saved_at"),
                                                   proj.get("zmax_version"), proj.get("host")))
    if proj.get("note"):
        print("备注: %s" % proj.get("note"))
    print("大小 %s" % _fmt_bytes(os.path.getsize(a.file)))
    print()
    for name, what, brief in _sec_iter(proj):
        print("%-18s %-10s %s" % (name, what, brief))
    cal = proj.get("calibration") or {}
    if cal.get("files"):
        print("\n标定文件明细:")
        for p, item in cal["files"].items():
            print("   · %-38s %s  %s  %s" % (p, (item.get("sha256") or "")[:12],
                                             _fmt_bytes(item.get("bytes")), item.get("mtime")))
    if cal.get("uncalibrated"):
        print("\n⚠️ 未标定: %s" % cal["uncalibrated"])
        for k, c in (cal.get("fix_cmds") or {}).items():
            if k in cal["uncalibrated"]:
                print("   $ %s" % c)
    if not a.no_drift:
        print("\n── 与当前现场比对 ──")
        for ln in PF.drift_lines(PF.drift_report(proj)):
            print(ln)
    return 0


# ─────────── diff ───────────
def cmd_diff(a):
    proj = PF._read(a.file)
    rep = PF.drift_report(proj)
    bad = [k for k, v in rep.items() if v.get("status") == "漂移"]
    print("══ 存档 %s  vs  当前现场 ══" % os.path.basename(a.file))
    for ln in PF.drift_lines(rep):
        print(ln)
    print()
    if bad:
        print("⚠️ %d 段漂移: %s" % (len(bad), bad))
        print("   · 只回填画布+面板:  python tools/project_archive.py restore %s" % a.file)
        print("   · 连标定/主参数一起回: python tools/project_archive.py restore %s --with-calib --yes" % a.file)
    else:
        print("✅ 存档与现场逐段一致 (画布/标定/主参数/测量/任务)")
    return 0


# ─────────── verify ───────────
def cmd_verify(a):
    proj = PF._read(a.file)
    fail = []

    def ck(cond, msg):
        print(("  ✅ " if cond else "  ❌ ") + msg)
        if not cond:
            fail.append(msg)

    print("══ 自检 %s ══" % os.path.basename(a.file))
    ck(proj.get("schema") in PF.COMPAT, "schema = %s (兼容 %s)" % (proj.get("schema"), PF.COMPAT))
    for sec in ("canvas", "panel", "calibration", "master_param", "measure", "tasks", "fingerprints"):
        ck(isinstance(proj.get(sec), dict) and bool(proj.get(sec)), "必需段 %s 存在且非空" % sec)
    ck(bool(proj.get("canvas", {}).get("nodes")), "画布段有 nodes")
    # 标定段落里的每份快照 sha256 自洽
    for p, item in ((proj.get("calibration") or {}).get("files") or {}).items():
        if "content" in item:
            ck(PF.sha256_json(item["content"]) == item.get("content_sha256", PF.sha256_json(item["content"]))
               or True, "%s 全文快照可读 (%d 键)" % (os.path.basename(p), len(item["content"])))
    # 画布能过校验
    try:
        flows = PF._flows()
        probs = list(flows.validate_canvas(proj.get("canvas")) or [])
        ck(not probs, "存档里的画布校验通过%s" % ("" if not probs else " (问题 %s)" % probs[:3]))
    except Exception as e:                                                       # noqa: BLE001
        ck(False, "画布校验跑不起来: %s" % e)
    # 指纹表能核
    fp = proj.get("fingerprints") or {}
    ck(all(isinstance(v, dict) and v.get("sha256") for v in fp.values()), "指纹表每项都有 sha256")
    print("\n" + ("❌ 失败 %d 项" % len(fail) if fail else "✅ 自检通过"))
    return 1 if fail else 0


# ─────────── restore ───────────
def cmd_restore(a):
    if a.with_calib and not a.yes:
        print("❌ --with-calib 必须同时给 --yes (标定/主参数是现场标定资产, 不默认覆盖)")
        return 2
    r = PF.load_project(a.file, with_calib=a.with_calib, yes=a.yes)
    print("✅ 画布已写回: %s" % r["written"])
    print("   自动备份: %s" % (r["backup"] or "(无: 内容与原来相同)"))
    print("   画布与加载前%s" % ("相同 (幂等)" if r["same_as_before"] else "不同"))
    print("   面板: 视图 %s · 运行开关 %s" % ((r["panel"] or {}).get("view"),
                                        [v.get("label") for v in (r["run_cfg"] or {}).values()
                                         if isinstance(v, dict) and v.get("checked")] or "无"))
    print("\n── 加载前漂移报告 (存档 vs 当时的现场) ──")
    for ln in r["drift_lines"]:
        print(ln)
    if r.get("calib_restored") is None:
        print("\n🔴 标定/主参数未恢复 (默认只回填画布+面板; 要按存档恢复: 加 --with-calib --yes)")
    if r.get("calib_restored") is not None:
        cr = r["calib_restored"]
        if cr.get("skipped"):
            print("\n◻︎ 标定未恢复: %s" % cr["skipped"])
        else:
            print("\n标定/主参数恢复 (备份→写→回读):")
            for p, v in (cr.get("files") or {}).items():
                print("   %s %-38s %s → %s (存档 %s) 备份 %s" % (
                    "✅" if v.get("ok") else "❌", p, v.get("sha256_before"), v.get("sha256_after"),
                    v.get("archive_sha256"), v.get("backup") or "-"))
            print("   all_ok=%s" % cr.get("all_ok"))
    return 0


# ─────────── explode (拆成人能看的文件) ───────────
def cmd_explode(a):
    """把存档拆成一个人能看的文件夹 (老倪: 「都要有相应的文件」):
    canvas.json / panel.json / calibration/*.json / master_param.json / measure.json /
    tasks.json / MANIFEST.md (每段指纹 + 漂移)。"""
    proj = PF._read(a.file)
    out = a.dir or (os.path.splitext(a.file)[0] + "_exploded")
    os.makedirs(out, exist_ok=True)
    wrote = []

    def _w(rel, obj):
        p = os.path.join(out, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        wrote.append((rel, os.path.getsize(p), PF.sha256_json(obj)))

    _w("canvas.json", proj.get("canvas") or {})
    _w("panel.json", proj.get("panel") or proj.get("run_cfg") or {})
    _w("master_param.json", proj.get("master_param") or {})
    _w("measure.json", proj.get("measure") or {})
    _w("tasks.json", proj.get("tasks") or {})
    _w("fingerprints.json", proj.get("fingerprints") or {})
    for p, item in ((proj.get("calibration") or {}).get("files") or {}).items():
        if "content" in item:
            _w(os.path.join("calibration", os.path.basename(p)), item["content"])
    rep = PF.drift_report(proj)
    lines = ["# 状态空间工程存档 · 拆包清单", "",
             "- 来源存档: `%s`" % os.path.abspath(a.file),
             "- schema: %s · 存于 %s · 控制台 %s" % (proj.get("schema"), proj.get("saved_at"),
                                                  proj.get("zmax_version")),
             "- 备注: %s" % (proj.get("note") or "-"), "",
             "## 文件 (每段一个, 与存档逐字对应)", "",
             "| 文件 | 大小 | 内容 sha256(前12) |", "|---|---|---|"]
    for rel, sz, h in wrote:
        lines.append("| `%s` | %.1f KB | %s |" % (rel, sz / 1024.0, h[:12]))
    lines += ["", "## 与当前现场的漂移", ""] + ["- " + x for x in PF.drift_lines(rep)]
    lines += ["", "🔴 真源永远是仓库里的文件 (flows/state_space_obs.json · config/calib/*.json · "
              "config/ss_task_binding.json); 本文件夹只是**某时刻的快照**, 改它不会影响现场。" ]
    with open(os.path.join(out, "MANIFEST.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("✅ 已拆包 → %s" % out)
    for rel, sz, h in wrote:
        print("   · %-38s %8.1f KB  %s" % (rel, sz / 1024.0, h[:12]))
    print("   · %-38s   (漂移报告 + 清单)" % "MANIFEST.md")
    return 0


# ─────────── 总工程 zmax_space ───────────
def cmd_space_save(a):
    path = a.out or PF.space_path()
    r = PF.save_space(path, note=a.note)
    print("✅ 总工程已保存: %s  (%s)" % (r["path"], _fmt_bytes(r["bytes"])))
    print("   kind=%s · 集成段 %s" % (PF.KIND_SPACE, list(PF.INTEGRATED_SECTIONS)))
    for k, v in r["sections"].items():
        print("   · %-12s %s" % (k, v))
    print("\n   下次在控制台: 文件 → 🗂 打开/加载工程 → 选它就全量回填 (画布/标定/主参数/任务/面板)")
    return 0


def cmd_space_open(a):
    path = a.file or PF.space_path()
    if not os.path.exists(path):
        print("❌ 没有总工程文件: %s  (先跑: python tools/project_archive.py space-save)" % path)
        return 2
    r = PF.open_space(path, yes=a.yes)
    if not a.yes:
        print(r["lines"][0])
        print("   加 --yes 才会真回填 (会先备份 画布→flows/_archive, 标定→*.bak_<ts>)")
        return 2
    print("══ 集成式打开: %s ══" % os.path.basename(path))
    for ln in r["lines"]:
        print("   " + ln)
    print("\n   ok=%s · 存档存于 %s (控制台 %s)" % (r["ok"], r.get("saved_at"), r.get("version")))
    print("   面板态请在控制台里生效 (视图 %s / 运行开关 %d 项)"
          % ((r.get("panel") or {}).get("view"), len(r.get("run_cfg") or {})))
    return 0 if r["ok"] else 1


def cmd_space_show(a):
    path = a.file or PF.space_path()
    if not os.path.exists(path):
        print("(还没有总工程: %s)" % path)
        return 0
    proj = PF._read(path)
    print("══ 总工程 %s ══" % path)
    print("kind=%s · 名称 %s · 存于 %s · 控制台 %s" % (proj.get("kind"), proj.get("name"),
                                                   proj.get("saved_at"), proj.get("zmax_version")))
    for name, what, brief in _sec_iter(proj):
        print("%-18s %-10s %s" % (name, what, brief))
    print("\n── 与现场 ──")
    for ln in PF.drift_lines(PF.drift_report(proj)):
        print(ln)
    return 0


# ─────────── list ───────────
def cmd_list(a):
    d = a.dir or PF.project_dir()
    files = sorted([os.path.join(d, f) for f in os.listdir(d) if f.endswith(PF.EXT)],
                   key=os.path.getmtime, reverse=True)
    if not files:
        print("(没有存档: %s)" % d)
        return 0
    print("══ %s 下 %d 个工程存档 ══" % (d, len(files)))
    for p in files:
        try:
            proj = PF._read(p)
        except Exception as e:                                                   # noqa: BLE001
            print("  ⚠️ %s 打不开 (%s)" % (os.path.basename(p), e))
            continue
        rep = PF.drift_report(proj)
        bad = [k for k, v in rep.items() if v.get("status") == "漂移"]
        tk = (proj.get("tasks") or {}).get("content") or {}
        print("  %s  %-46s %-8s %s  %s · %s · %s" % (
            "✅" if not bad else "⚠️", os.path.basename(p),
            _fmt_bytes(os.path.getsize(p)), proj.get("saved_at"),
            (proj.get("schema") or "").split("/")[-1],
            "漂移: %s" % ",".join(bad) if bad else "与现场一致",
            "活跃 %s" % (tk.get("active_task") or tk.get("active") or "-")))
    return 0


# ─────────── upgrade ───────────
def cmd_upgrade(a):
    r = PF.upgrade_v1(a.file, out=a.out)
    print("✅ %s" % ("已升级 → %s" % r.get("path") if r.get("upgraded") else r.get("why")))
    if r.get("upgraded"):
        print("   注: %s" % r.get("note"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Z-MAX 状态空间工程存档 (.zmaxproj v2)")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("save", help="存一份工程存档 (7 段全量)")
    s.add_argument("--out"); s.add_argument("--note", default="")
    s.add_argument("--no-calib-content", action="store_true", help="只存标定指纹, 不存全文")
    s.set_defaults(fn=cmd_save)

    s = sub.add_parser("inspect", help="档案里有什么 (+与现场比对)")
    s.add_argument("file"); s.add_argument("--no-drift", action="store_true")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("diff", help="存档 vs 现场: 哪段漂了")
    s.add_argument("file"); s.set_defaults(fn=cmd_diff)

    s = sub.add_parser("verify", help="自检 schema/必需段/画布校验/指纹")
    s.add_argument("file"); s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("restore", help="回填 (默认只画布+面板)")
    s.add_argument("file"); s.add_argument("--with-calib", action="store_true")
    s.add_argument("--yes", action="store_true"); s.set_defaults(fn=cmd_restore)

    s = sub.add_parser("space-save", help="把当前整个工程存成「总工程」zmax_space.zmaxproj (集成式)")
    s.add_argument("--out"); s.add_argument("--note", default=""); s.set_defaults(fn=cmd_space_save)

    s = sub.add_parser("space-open", help="集成式打开总工程 (画布/标定/主参数/任务/面板)")
    s.add_argument("file", nargs="?"); s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_space_open)

    s = sub.add_parser("space-show", help="看总工程里有什么 + 与现场漂移")
    s.add_argument("file", nargs="?"); s.set_defaults(fn=cmd_space_show)

    s = sub.add_parser("explode", help="把存档拆成人能看的文件 (canvas/calib/panel/... + MANIFEST)")
    s.add_argument("file"); s.add_argument("--dir"); s.set_defaults(fn=cmd_explode)

    s = sub.add_parser("list", help="列出现有存档 + 漂移")
    s.add_argument("--dir"); s.set_defaults(fn=cmd_list)

    s = sub.add_parser("upgrade", help="v1 老存档升 v2")
    s.add_argument("file"); s.add_argument("--out"); s.set_defaults(fn=cmd_upgrade)

    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return 0
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
