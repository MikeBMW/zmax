#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 ~ 下所有 zmax 相关目录/仓库/venv 收进 /home/ubuntu/zmax 单一命名空间。

老倪 2026-10-07 口径: 「只保留 zmax 根路径, 其它所有的文件/代码都汇总到 zmax 根目录;
                        zmax 同级目录不要出现任何其它 zmax 相关文件夹和代码;
                        保证代码一致性。」

做法(照 Orin 那次 ~/.zmax 整理的同一套):
  1) 同盘 `os.rename` 搬(瞬间、不复制、不占额外空间), 并在**老路径留软链** => 过渡期零断链;
  2) 搬完**就地修内部写死的绝对路径**(venv/conda: `bin/*` 的 shebang + `pyvenv.cfg` + `activate*`);
  3) 同步改**仓库外**引用: `/etc/systemd/system/*.service` + `~/.hermes/scripts/*`(改前 .bak);
  4) 逐项自验(目标在 / 大小对 / venv 能跑 / 服务 active / 端口 200);
  5) 落清单 `zmax_data/backups/HOME_CONSOLIDATE_MANIFEST.jsonl`(src→dst + 指纹 + 结果) + 回滚脚本。

用法:
  python3 tools/consolidate_home.py --dry                 # 只看要做什么(默认)
  python3 tools/consolidate_home.py --apply --stage A     # 不涉及在跑服务的部分(安全)
  python3 tools/consolidate_home.py --apply --stage B     # 涉及在跑服务(zmax_data/lerobot-venv/dds-venv) => 会重启单元
  python3 tools/consolidate_home.py --apply --stage C     # 清掉老软链(引用已改完)
  python3 tools/consolidate_home.py --verify              # 只做核验, 不动任何东西
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HOME = "/home/ubuntu"
REPO = os.path.join(HOME, "zmax")
DATA_OLD = os.path.join(HOME, "zmax_data")
DATA_NEW = os.path.join(REPO, "zmax_data")
MANIFEST = os.path.join(DATA_OLD, "backups", "HOME_CONSOLIDATE_MANIFEST.jsonl")
ROLLBACK = os.path.join(DATA_OLD, "backups", "home_consolidate_rollback.sh")

# ───────────────────────── 搬迁计划 ─────────────────────────
# stage A = 不涉及正在跑的服务; stage B = 涉及(搬完要重启单元); stage C = 删老软链
PLAN = [
    # (stage, 老路径, 新路径, 类型, 说明)
    ("A", "INTACT-JEPA",          "external/INTACT-JEPA",          "repo",  "第三方仓库(git main, 11G)"),
    ("A", "lerobot-smolvla-lew",  "external/lerobot-smolvla-lew",  "repo",  "fork 工作树(git mac-hw, 70G)"),
    ("A", "gs-venv",              "venvs/gs-venv",                 "venv",  "3DGS 训练环境(6.9G)"),
    ("A", "colmap-venv",          "venvs/colmap-venv",             "venv",  "colmap 环境(216M)"),
    ("A", "cuda-nvcc-env",        "venvs/cuda-nvcc-env",           "conda", "conda 环境(nvcc, 1.2G)"),
    ("A", "cuda-shim",            "toolchains/cuda-shim",          "dir",   "CUDA shim(792K)"),
    ("A", "hermes-install",       "hermes/install",                "dir",   "Hermes 安装包(8K)"),
    ("B", "zmax_data",            "zmax_data",                     "dir",   "★数据/模型根(180G) —— 在跑服务全指着它"),
    ("B", "lerobot-venv",         "venvs/lerobot-venv",            "venv",  "lerobot 环境(7.9G, 4 个单元在用)"),
    ("B", "dds-venv",             "venvs/dds-venv",                "venv",  "DDS 环境(62M, 4 个单元在用)"),
]

# ~/bin 里属于 zmax 的两个脚本(~/bin 本身是标准用户目录, 保留)
BIN_MOVE = ["dual_screen_setup.sh", "orin_lan_setup.sh"]

# stage C: 老软链 —— 指向 zmax 内部的直接删; 指向 zmax_data 的在 B 之后删
DEAD_LINKS_INNER = ["zmax_rel", "zmax_dds", "zmax_aoi", "state3d_app", "dl_intact"]
DEAD_LINKS_DATA = ["stable-wm-cache", "zmax_ss_remote", "zmax_moveit_plan", "aoi_v4", "l4_ab", "android-sdk"]

# 引用需要改的文件(仓库外)
SED_UNITS = ["/etc/systemd/system"]
SED_SCRIPTS = [os.path.join(HOME, ".hermes/scripts")]

# 老路径 → 新路径(纯字符串替换表)。⚠️ 本文件自身会被 R 阶段跳过(见 rewrite_repo_refs),
#    否则第一遍就把这张表自己改成了恒等映射(2026-10-07 实测踩过)。
PLAN_MAP = [("/home/ubuntu/zmax/zmax_data", "/home/ubuntu/zmax/zmax_data"),
            ("/home/ubuntu/zmax/external/lerobot-smolvla-lew", "/home/ubuntu/zmax/external/lerobot-smolvla-lew"),
            ("/home/ubuntu/zmax/external/INTACT-JEPA", "/home/ubuntu/zmax/external/INTACT-JEPA"),
            ("/home/ubuntu/zmax/venvs/gs-venv", "/home/ubuntu/zmax/venvs/gs-venv"),
            ("/home/ubuntu/zmax/venvs/lerobot-venv", "/home/ubuntu/zmax/venvs/lerobot-venv"),
            ("/home/ubuntu/zmax/venvs/dds-venv", "/home/ubuntu/zmax/venvs/dds-venv"),
            ("/home/ubuntu/zmax/venvs/colmap-venv", "/home/ubuntu/zmax/venvs/colmap-venv"),
            ("/home/ubuntu/zmax/venvs/cuda-nvcc-env", "/home/ubuntu/zmax/venvs/cuda-nvcc-env"),
            ("/home/ubuntu/zmax/toolchains/cuda-shim", "/home/ubuntu/zmax/toolchains/cuda-shim"),
            ("/home/ubuntu/zmax/hermes/install", "/home/ubuntu/zmax/hermes/install"),
            ("/home/ubuntu/zmax/zmax_data/ss_live", "/home/ubuntu/zmax/zmax_data/ss_live"),
            ("/home/ubuntu/zmax/zmax_data/runtime/moveit_plan", "/home/ubuntu/zmax/zmax_data/runtime/moveit_plan"),
            ("/home/ubuntu/zmax/zmax_data/stable-wm-cache", "/home/ubuntu/zmax/zmax_data/stable-wm-cache"),
            ("/home/ubuntu/zmax/zmax_data/aoi_v4", "/home/ubuntu/zmax/zmax_data/aoi_v4"),
            ("/home/ubuntu/zmax/zmax_data/l4_ab", "/home/ubuntu/zmax/zmax_data/l4_ab"),
            ("/home/ubuntu/zmax/zmax_data/toolchains/android-sdk", "/home/ubuntu/zmax/zmax_data/toolchains/android-sdk"),
            ("/home/ubuntu/zmax", "/home/ubuntu/zmax"),
            ("/home/ubuntu/zmax/dds", "/home/ubuntu/zmax/dds"),
            ("/home/ubuntu/zmax/tools/aoi", "/home/ubuntu/zmax/tools/aoi"),
            ("/home/ubuntu/zmax/tools/web/state3d_app", "/home/ubuntu/zmax/tools/web/state3d_app"),
            ("/home/ubuntu/zmax/tools/oneoff/dl_intact", "/home/ubuntu/zmax/tools/oneoff/dl_intact")]


def sed_map():
    """老路径 → 工程内新路径。三套写法都要覆盖: 绝对、`~/`、`$HOME/`。

    🐛 2026-10-07 实测: 只改绝对路径漏了 `os.path.expanduser("~/zmax/zmax_data")` 这类写法 ——
    它照样能跑(家目录没变), 但老目录一删, 进程会**静默地**新建一个空目录往里写, 不报错。
    """
    m = []
    for old, new in sorted(PLAN_MAP, key=lambda x: -len(x[0])):
        if old.startswith(HOME + "/"):
            rel_old, rel_new = old[len(HOME) + 1:], new[len(HOME) + 1:]
            m += [("~/" + rel_old, "~/" + rel_new),
                  ("$HOME/" + rel_old, "$HOME/" + rel_new),
                  ("${HOME}/" + rel_old, "${HOME}/" + rel_new)]
        m.append((old, new))
    return m


def sh(cmd, timeout=600, check=False):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError("命令失败: %s\n%s" % (cmd, (r.stderr or r.stdout)[:400]))
    return r


def human(p):
    r = sh(["du", "-sh", p], timeout=180)
    return (r.stdout or "").split()[0] if r.stdout else "?"


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def manifest_write(rec, apply_):
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    rec["ts"] = time.time()
    rec["applied"] = bool(apply_)
    with open(MANIFEST, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ───────────────────────── 各项动作 ─────────────────────────
def do_move(stage, name, rel, kind, note, apply_):
    src = os.path.join(HOME, name)
    dst = rel if os.path.isabs(rel) else os.path.join(REPO, rel)
    if os.path.islink(src) and os.path.realpath(src) == os.path.realpath(dst) and os.path.exists(dst):
        log("  ⏭ %-22s 已搬过(老路径已是软链) ⇒ 跳过" % name)
        return True
    if not os.path.exists(src) and not os.path.islink(src):
        log("  ⏭ %-22s 老路径不存在, 跳过" % name)
        return True
    already = os.path.exists(dst)
    if already and not os.path.islink(src):
        log("  ⏭ %-22s 目标已存在, 跳过(不覆盖)" % name)
        return True
    size = human(src)
    log("  → %-22s %s  %s ⇒ %s" % (name, size, src, dst))
    if not apply_:
        return True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    old_target = os.path.realpath(src) if os.path.islink(src) else src
    os.rename(old_target, dst)                                    # 同盘 rename, 瞬时
    if os.path.islink(src):
        os.unlink(src)
    os.symlink(dst, src)                                          # 过渡期留软链
    ok, detail = True, ""
    # 类型相关: 内部路径修补 + 自验
    if kind in ("venv", "conda"):
        fixed = fix_env_paths(dst, kind)
        ok, detail = verify_venv(dst, kind)
        detail = "修补内部路径 %d 处 · %s" % (fixed, detail)
    if kind == "repo":
        r = sh(["git", "-C", dst, "status", "--porcelain"], timeout=300)
        ok = r.returncode == 0
        detail = "git 可用=%s" % ok
    manifest_write({"stage": stage, "name": name, "src": src, "dst": dst, "kind": kind,
                    "size": size, "note": note, "ok": ok, "detail": detail}, apply_)
    log("     %s %s" % ("✅" if ok else "❌", detail))
    return ok


def fix_env_paths(env_dir, kind):
    """把 venv/conda 里写死的绝对路径改成新位置。返回修补的文件数。"""
    old, new = None, env_dir
    # 反推老前缀: .../venvs/<name> 或 .../<name>
    for m in sed_map():
        if new.startswith(m[1]):
            old = m[0]
            break
    if not old:
        base = os.path.basename(env_dir)
        old = "/home/ubuntu/" + base
    n = 0
    pats = ["bin/*", "pyvenv.cfg", "activate*"] if kind == "venv" else ["bin/*", "conda-meta/*.json", "etc/*"]
    files = []
    for pat in pats:
        import glob
        files += [f for f in glob.glob(os.path.join(env_dir, pat)) if os.path.isfile(f)]
    # conda-meta 可能上千个, 限制一下但别漏 shebang
    for f in files:
        try:
            with open(f, "rb") as fh:
                b = fh.read()
            if b[:2] == b"#!" or b"prefix" in b[:4096] or f.endswith(("pyvenv.cfg", ".json")) or b"/home/ubuntu/" in b[:8192]:
                t = b.decode("utf-8", "surrogateescape")
                if old in t:
                    with open(f, "w", encoding="utf-8", errors="surrogateescape") as fh:
                        fh.write(t.replace(old, new))
                    n += 1
                    os.chmod(f, os.stat(f).st_mode)
        except Exception:                                                   # noqa: BLE001
            pass
    return n


def verify_venv(env_dir, kind):
    cands = [os.path.join(env_dir, "bin", x) for x in ("python3", "python", "python3.11", "python3.12")]
    py = next((c for c in cands if os.path.exists(c)), None)
    if not py:
        # conda 环境可能只装了工具链(nvcc 之类), 没有解释器 —— 按"环境目录+可执行文件在"判活
        hasbin = os.path.isdir(os.path.join(env_dir, "bin"))
        n_exe = 0
        if hasbin:
            for f in os.listdir(os.path.join(env_dir, "bin")):
                p = os.path.join(env_dir, "bin", f)
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    n_exe += 1
        if hasbin and n_exe:
            r = sh("ls -l %s/bin | head -5" % env_dir, timeout=30)
            return True, "无解释器(工具链型环境) · bin 内可执行文件 %d 个" % n_exe
        return False, "缺 bin/python 且 bin 不可用"
    r = sh([py, "-c", "import sys;print(sys.prefix)"], timeout=120)
    if r.returncode != 0:
        return False, "解释器跑不起来: %s" % (r.stderr or "")[:120]
    pref = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    ok = os.path.realpath(pref) == os.path.realpath(env_dir)
    return ok, "sys.prefix=%s" % pref


def rewrite_refs(apply_):
    """仓库外引用: systemd 单元(需 root, 走 sudo) + Hermes 脚本(改前 .bak)。返回改了多少文件。"""
    m = sed_map()
    changed = []
    targets = []
    for d in SED_UNITS:
        targets += [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".service") or f.endswith(".timer")]
    for d in SED_SCRIPTS:
        if os.path.isdir(d):
            targets += [os.path.join(d, f) for f in os.listdir(d) if f.endswith((".sh", ".py"))]
    for f in targets:
        try:
            t = open(f, encoding="utf-8", errors="surrogateescape").read()
        except Exception:                                                   # noqa: BLE001
            continue
        if not any(o in t for o, _ in m):
            continue
        n = t
        for o, w in m:
            n = n.replace(o, w)
        if n != t:
            changed.append(f)
            if apply_:
                root_owned = f.startswith("/etc/")
                try:
                    if not os.path.exists(f + ".bak_homecons"):
                        if root_owned:
                            sh("sudo cp -a %s %s.bak_homecons" % (f, f), timeout=60)
                        else:
                            shutil.copy2(f, f + ".bak_homecons")
                    if root_owned:
                        sh(["sudo", "tee", f], timeout=60) if False else None
                        p = subprocess.run(["sudo", "tee", f], input=n.encode("utf-8"),
                                           capture_output=True, timeout=60)
                        if p.returncode != 0:
                            raise RuntimeError((p.stderr or b"").decode("utf-8", "replace")[:200])
                    else:
                        with open(f, "w", encoding="utf-8", errors="surrogateescape") as fh:
                            fh.write(n)
                except Exception as e:                                      # noqa: BLE001
                    log("  ⚠️ 写不动 %s: %s" % (f, str(e)[:120]))
                    changed.pop()
    return changed


def unit_restart(apply_):
    """重载+重启引用了老路径的活单元。"""
    live = sh("systemctl list-units --type=service --state=running --no-legend | awk '{print $1}'", timeout=120).stdout
    units = [u for u in live.split() if any(k in u for k in ("zmax", "ss-", "aoi", "sam3"))]
    if apply_:
        sh(["sudo", "systemctl", "daemon-reload"], timeout=180)
    out = []
    for u in units:
        if apply_:
            sh(["sudo", "systemctl", "restart", u], timeout=180)
        st = sh(["systemctl", "is-active", u], timeout=60).stdout.strip()
        out.append((u, st))
    return out


def remove_links(names, apply_):
    n = 0
    for name in names:
        p = os.path.join(HOME, name)
        if os.path.islink(p):
            tgt = os.readlink(p)
            log("  ✂ 删软链 %-18s → %s" % (name, tgt))
            if apply_:
                os.unlink(p)
                manifest_write({"stage": "C", "name": name, "src": p, "dst": tgt, "kind": "unlink", "ok": True}, apply_)
            n += 1
        elif os.path.exists(p):
            log("  ⚠️ %s 不是软链(真实文件), 不动" % name)
    return n


def gitignore_add(apply_):
    gi = os.path.join(REPO, ".gitignore")
    want = ["zmax_data/", "external/", "venvs/", "toolchains/", "hermes/"]
    t = open(gi, encoding="utf-8").read() if os.path.exists(gi) else ""
    add = [w for w in want if not re.search(r"^%s$" % re.escape(w), t, re.M)]
    if add and apply_:
        with open(gi, "a", encoding="utf-8") as f:
            f.write("\n# ~ 整合进 zmax 命名空间(2026-10-07): 数据/第三方仓库/venv 不进库\n" + "\n".join(add) + "\n")
    return add


def report_verify():
    print("\n──────── 核验 ────────")
    ok = 0
    for st, name, rel, kind, note in PLAN:
        dst = os.path.join(REPO, rel)
        e = os.path.exists(dst)
        ok += e
        print("  %s %-22s → %s" % ("✅" if e else "✗", name, dst))
    print("  搬到位: %d/%d" % (ok, len(PLAN)))
    print("  老路径残留(应为软链):")
    for _, name, _, _, _ in PLAN:
        p = os.path.join(HOME, name)
        if os.path.islink(p):
            t = os.readlink(p)
            print("    %-22s → %s %s" % (name, t, "✅通" if os.path.exists(p) else "✗断"))
        elif os.path.exists(p):
            print("    %-22s ⚠️ 还是真实目录" % name)
    print("  ~ 顶层 zmax 相关项(目标: 只剩 zmax):")
    for e in sorted(os.listdir(HOME)):
        if e.lower().startswith(("zmax", "intact", "lerobot", "stable-wm", "dds-venv", "gs-venv", "colmap-venv",
                                 "cuda", "aoi_v4", "l4_ab", "android-sdk", "hermes-install", "state3d_app")):
            print("    %s" % e)
    ports = [(8791, "/"), (8793, "/station"), (8798, "/"), (8794, "")]
    print("  端口:")
    for p, path in ports:
        r = sh(["curl", "-s", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:%d%s" % (p, path)], timeout=30)
        print("    %-6d %s" % (p, r.stdout.strip()))


def rewrite_repo_refs(apply_):
    """仓库**内**的老路径字面量改写(排除 .git/大目录/技能镜像/报告/venv)。

    老倪口径「保证代码一致性」: 代码里不该再出现 /home/ubuntu/<老名>。
    改前整树 tar 备份; docs/skills|docs/memory 是 ~/.hermes 的镜像 ⇒ 跳过(要改改源)。
    """
    ex = ("--exclude-dir=.git --exclude-dir=reports --exclude-dir=zmax_data --exclude-dir=external "
          "--exclude-dir=venvs --exclude-dir=toolchains --exclude-dir=hermes --exclude-dir=hermes-all "
          "--exclude-dir=memory --exclude-dir=gui-venv311 --exclude-dir=node_modules --exclude-dir=__pycache__ "
          "--exclude-dir=sample_pt --exclude-dir=assets")
    m = sed_map()
    pats = [o for o, _ in m]
    r = sh("grep -rlZ %s -e %s ." % (ex, " -e ".join("'%s'" % p for p in pats)), timeout=420)
    files = [f for f in (r.stdout or "").split("\0") if f and os.path.isfile(f)]
    files = [f for f in files if not f.startswith("./docs/skills/") and not f.startswith("./docs/memory/")]
    files = [f for f in files if "homecons" not in os.path.basename(f)]      # 别改改写器自己
    if not files:
        return [], 0
    if apply_:
        bk = os.path.join(DATA_NEW, "backups", "repo_pre_rewrite_%s.tar.gz" % time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(os.path.dirname(bk), exist_ok=True)
        sh(["tar", "-czf", bk, "--exclude=.git"] + files, timeout=600)
        log("  备份: %s (%s)" % (bk, human(bk)))
    n = 0
    for f in files:
        try:
            with open(f, "rb") as fh:
                b = fh.read()
            t = b.decode("utf-8", "surrogateescape")
        except Exception:                                                   # noqa: BLE001
            continue
        orig = t
        for o, w in m:
            t = t.replace(o, w)
        if t != orig:
            n += 1
            if apply_:
                try:
                    with open(f, "w", encoding="utf-8", errors="surrogateescape") as fh:
                        fh.write(t)
                except Exception as e:                                      # noqa: BLE001
                    log("  ⚠️ 写不动 %s: %s" % (f, str(e)[:80]))
    return files, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--stage", default="A", choices=["A", "B", "C", "R", "all"])
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    apply_ = bool(a.apply)
    stages = ["A", "B", "C", "R"] if a.stage == "all" else [a.stage]

    log("家目录整合 → %s  ·  模式=%s  ·  阶段=%s" % (REPO, "APPLY" if apply_ else "DRY", "+".join(stages)))
    if a.verify:
        report_verify()
        return 0

    bad = 0
    for st in stages:
        items = [x for x in PLAN if x[0] == st]
        if items:
            log("── 阶段 %s: 搬 %d 项 ──" % (st, len(items)))
            for _, name, rel, kind, note in items:
                if not do_move(st, name, rel, kind, note, apply_):
                    bad += 1
        if st == "A":
            log("── 阶段 A: ~/bin 里的 zmax 脚本 ──")
            for b in BIN_MOVE:
                s = os.path.join(HOME, "bin", b)
                d = os.path.join(REPO, "tools", "host", b)
                if os.path.exists(s):
                    log("  → %-22s ⇒ %s" % (b, d))
                    if apply_:
                        os.makedirs(os.path.dirname(d), exist_ok=True)
                        shutil.move(s, d)
                        os.symlink(d, s)
                        manifest_write({"stage": "A", "name": "bin/" + b, "src": s, "dst": d, "kind": "file", "ok": True}, apply_)
        if st in ("A", "B", "C"):
            log("── 阶段 %s: 改仓库外引用(systemd + Hermes 脚本) ──" % st)
            ch = rewrite_refs(apply_)
            log("  引用改动 %d 个文件%s" % (len(ch), "" if not ch else ":\n    " + "\n    ".join(ch[:12])))
        if st == "B":
            log("── 阶段 B: 重载+重启活单元 ──")
            for u, s in unit_restart(apply_):
                log("  %-34s %s" % (u, s))
        if st == "R":
            log("── 阶段 R: 改仓库内老路径字面量(保证代码一致性) ──")
            files, n = rewrite_repo_refs(apply_)
            log("  命中 %d 个文件 · 实际改写 %d 个%s" % (len(files), n, "" if not files else
                                                        "\n    " + "\n    ".join(files[:10])))
        if st == "C":
            log("── 阶段 C: 删老软链 ──")
            moved_links = [x[1] for x in PLAN if os.path.islink(os.path.join(HOME, x[1]))]
            n1 = remove_links(DEAD_LINKS_INNER + DEAD_LINKS_DATA + moved_links, apply_)
            log("  共 %d 条(含搬迁过渡软链 %d 条)" % (n1, len(moved_links)))
        if st == "A":
            add = gitignore_add(apply_)
            log("  .gitignore 需补: %s" % (add or "无"))

    if not apply_:
        log("(dry-run 结束: 上面每一项都会做; 真执行加 --apply)")
    report_verify()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
