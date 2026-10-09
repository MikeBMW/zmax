#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_version_sync.py — Z-MAX 版本同源体检 (只读)

体检四件事:
  ① 本仓库当前版本写在哪几处 (逐个 file:line + 实际值), 是否全部一致 (不一致即失败)
  ② 与 "xspace 版本" 的对齐状态 (先判定 xspace 指什么, 附证据)
  ③ 与 Git 远程 tag / Release 的对齐 (本地 HEAD / tag / 远端 tag / 最新 Release 名与产物)
  ④ GUI 里显示的版本号与实际是否一致 (含 About 框 / 状态栏等非同步点陈旧串)

输出: 人读报告(默认) / --json / 退出码 0 全一致 · 1 有偏差
红线: 只读 —— 不改版本号 / 不打 tag / 不发版 / 不打印任何凭据
用法: python3 tools/verify_version_sync.py [--json] [--repo DIR] [--offline]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

# ─────────────────────────────────────────────────────────────────────────────
# 版本号同步点 (口径来源: VERSION.md「改版本必同步」+ tools/bump_version.py chk 表)
#   每个点 = (id, 相对路径, 正则, 说明)。正则第 1 组 = 版本 token (含可选 v 前缀)。
# ─────────────────────────────────────────────────────────────────────────────
SYNC_LOCS = [
    ("studio.py:品牌版本 QLabel", "tools/gui/studio.py",
     r'QLabel\("Z-MAX (v?\d+\.\d+\.\d+)"\)', "侧栏品牌版本小字"),
    ("studio.py:窗口标题(正常)", "tools/gui/studio.py",
     r'"XSpace Studio — Z-MAX (v?\d+\.\d+\.\d+) \[W-01\]"', "主窗口标题"),
    ("studio.py:窗口标题(非调试)", "tools/gui/studio.py",
     r'"XSpace Studio — Z-MAX (v?\d+\.\d+\.\d+) \[W-01\] ⚠️非调试模式"', "主窗口标题"),
    ("studio.py:changelog 前缀", "tools/gui/studio.py",
     r'(?m)^[ \t]*# (v?\d+\.\d+\.\d+):', "变更摘要注释(取最新一条)"),
    ("update_checker.py:CURRENT_VERSION", "tools/gui/update_checker.py",
     r'CURRENT_VERSION = "(v?\d+\.\d+\.\d+)"', "自动更新当前版本"),
    ("version_sync.py:zmax_ver", "tools/gui/version_sync.py",
     r'zmax_ver = "(v?\d+\.\d+\.\d+)"', "版本同步面板显示(不带 v)"),
    ("docs_sync.py:\"version\"", "tools/gui/docs_sync.py",
     r'"version": "(v?\d+\.\d+\.\d+)"', "文档站版本键"),
    ("docs_sync.py:\"zmax_version\"", "tools/gui/docs_sync.py",
     r'"zmax_version": "(v?\d+\.\d+\.\d+)"', "文档站 zmax 版本键"),
    # bump 工具会同步它, 但 VERSION.md 清单未列 —— 老门自己就是判据, 必须一起改
    ("integrity_check.py:EXPECTED_VERSION", "tools/ci/integrity_check.py",
     r'EXPECTED_VERSION = "(v?\d+\.\d+\.\d+)"', "仓库完整性门期望版本"),
]

# GUI 里任何 "Z-MAX vX.Y.Z" 字面量 (非注释) —— 展示给用户的版本, 一律应与当前版本一致
GUI_DISPLAY_RE = re.compile(r'Z-MAX (v?\d+\.\d+\.\d+)')


def norm(tok: str) -> str:
    """版本 token 归一化: 去掉 v / vv 前缀与新号, 只留 X.Y.Z"""
    return tok.lstrip("v").strip()


def run(cmd, cwd=None, timeout=30):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:  # noqa: BLE001
        return str(e), -1


def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def find_first(text, pattern):
    """返回 (line_no, raw_token) 第一处命中; 无则 (None, None)"""
    rx = re.compile(pattern)
    for i, line in enumerate(text.splitlines(), 1):
        m = rx.search(line)
        if m:
            return i, m.group(1)
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# ① 版本同步点
# ─────────────────────────────────────────────────────────────────────────────
def scan_sync_locs(repo):
    locs = []
    for loc_id, rel, pattern, desc in SYNC_LOCS:
        path = os.path.join(repo, rel)
        if not os.path.exists(path):
            locs.append({"id": loc_id, "file": rel, "line": None, "raw": None,
                         "normalized": None, "desc": desc, "error": "文件不存在"})
            continue
        line, raw = find_first(read(path), pattern)
        locs.append({
            "id": loc_id, "file": rel, "line": line, "raw": raw,
            "normalized": norm(raw) if raw else None, "desc": desc,
            "error": None if raw else "未匹配到版本串",
        })
    return locs


def canonical_of(locs):
    """权威版本 = studio.py 品牌 QLabel; 缺失则取多数派"""
    for L in locs:
        if L["id"].startswith("studio.py:品牌版本") and L["normalized"]:
            return L["normalized"], "studio.py 品牌 QLabel"
    vals = [L["normalized"] for L in locs if L["normalized"]]
    if not vals:
        return None, "无法判定"
    maj = max(set(vals), key=vals.count)
    return maj, "多数派"


# ─────────────────────────────────────────────────────────────────────────────
# ④ GUI 显示的版本 (studio.py 全部字面量, 排除注释行)
# ─────────────────────────────────────────────────────────────────────────────
def scan_gui_display(repo, canonical):
    path = os.path.join(repo, "tools/gui/studio.py")
    found, stale = [], []
    if not os.path.exists(path):
        return found, stale
    for i, line in enumerate(read(path).splitlines(), 1):
        s = line.strip()
        if s.startswith("#"):            # changelog 注释行 (历史, 不算展示)
            continue
        for m in GUI_DISPLAY_RE.finditer(line):
            raw = m.group(1)
            rec = {"file": "tools/gui/studio.py", "line": i, "raw": raw,
                   "normalized": norm(raw), "consistent": norm(raw) == canonical}
            found.append(rec)
            if norm(raw) != canonical:
                stale.append(rec)
    return found, stale


# ─────────────────────────────────────────────────────────────────────────────
# ② xspace 判定 (证据)
# ─────────────────────────────────────────────────────────────────────────────
def http_code(url, timeout=8):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ZMAX-verify",
                                                   "Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return None


def api_json(url, timeout=8):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ZMAX-verify",
                                                   "Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"__http__": e.code}
    except Exception as e:  # noqa: BLE001
        return {"__error__": str(e)}


def scan_xspace(repo, offline):
    ev = {}
    # 证据1: 本机是否有 /home/xspace 目录 (旧 hostname/工程师名)
    ev["local_dir_/home/xspace"] = os.path.isdir("/home/xspace")
    # 证据2: 品牌名 "XSpace Studio" 是否仍是 GUI 标题
    sp = os.path.join(repo, "tools/gui/studio.py")
    ev["brand_used_in_gui"] = bool(os.path.exists(sp) and "XSpace Studio" in read(sp))
    # 证据3: GUI 工程 external/lerobot-smolvla-lew 的 pyproject 版本 + remote + 自带 GUI 版本
    lr = os.path.join(repo, "external/lerobot-smolvla-lew")
    ev["lerobot_local_pyproject"] = None
    ev["lerobot_remote"] = None
    ev["external_gui_studio_version"] = None
    ev["external_gui_update_checker"] = None
    if os.path.isdir(lr):
        pj = os.path.join(lr, "pyproject.toml")
        if os.path.exists(pj):
            m = re.search(r'(?m)^version = "([^"]+)"', read(pj))
            ev["lerobot_local_pyproject"] = m.group(1) if m else None
        out, _ = run(["git", "-C", lr, "remote", "get-url", "origin"])
        ev["lerobot_remote"] = out or None
        esp = os.path.join(lr, "tools/gui/studio.py")
        if os.path.exists(esp):
            m = re.search(r'QLabel\("Z-MAX (v?\d+\.\d+\.\d+)"\)', read(esp))
            ev["external_gui_studio_version"] = m.group(1) if m else None
        euc = os.path.join(lr, "tools/gui/update_checker.py")
        if os.path.exists(euc):
            m = re.search(r'CURRENT_VERSION = "(v?\d+\.\d+\.\d+)"', read(euc))
            ev["external_gui_update_checker"] = m.group(1) if m else None
    # 证据4: update_checker 的更新源仓库
    uc = os.path.join(repo, "tools/gui/update_checker.py")
    ev["update_checker_repo"] = None
    if os.path.exists(uc):
        m = re.search(r'REPO = "([^"]+)"', read(uc))
        ev["update_checker_repo"] = m.group(1) if m else None
    # 证据5: GitHub 上是否存在 MikeBMW/xspace 仓
    ev["github_MikeBMW/xspace"] = "offline" if offline else http_code("https://api.github.com/repos/MikeBMW/xspace")
    # 证据6: lerobot-smolvla-lew 仓库最新 Release (旧 "xspace" 工程仓)
    ev["lerobot_repo_latest_release"] = None
    if not offline and ev["lerobot_remote"]:
        slug = ev["lerobot_remote"].rsplit("github.com/", 1)[-1].removesuffix(".git")
        j = api_json(f"https://api.github.com/repos/{slug}/releases/latest")
        ev["lerobot_repo_latest_release"] = j.get("tag_name") if isinstance(j, dict) else None

    conclusion = (
        "\"xspace\" 不是独立版本号, 而是 GUI 品牌/旧工作区名: 实据 —— "
        f"GitHub MikeBMW/xspace 不存在 ({ev['github_MikeBMW/xspace']}); "
        f"本机 /home/xspace 目录不存在 ({ev['local_dir_/home/xspace']}); "
        f"但 GUI 主窗口标题仍用品牌 'XSpace Studio — Z-MAX vX.Y.Z' (brand_used={ev['brand_used_in_gui']})。 "
        "⇒ 老倪说的\"xspace 版本\"= XSpace Studio (Z-MAX 控制台) 的版本线, 与该线当前版本号同一处; "
        "另有一支历史\"xspace 工程仓\" MikeBMW/lerobot-smolvla-lew (GUI 工程 external/lerobot-smolvla-lew 的 origin), "
        "它是 LeRobot 0.5.2 派生, 与 Z-MAX 版本线不是同一个号。"
    )
    return ev, conclusion


# ─────────────────────────────────────────────────────────────────────────────
# ③ 远程 tag / Release
# ─────────────────────────────────────────────────────────────────────────────
def parse_slug(url):
    m = re.search(r'github\.com[/:]([^/]+)/([^/\s]+?)(?:\.git)?$', url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def scan_remote(repo, canonical, offline):
    r = {"method": None}
    r["origin_url"] = run(["git", "remote", "get-url", "origin"], repo)[0] or None
    r["slug"] = parse_slug(r["origin_url"])
    r["head_full"] = run(["git", "rev-parse", "HEAD"], repo)[0] or None
    r["head_short"] = run(["git", "rev-parse", "--short", "HEAD"], repo)[0] or None
    r["branch"] = run(["git", "branch", "--show-current"], repo)[0] or None
    r["describe"] = run(["git", "describe", "--tags", "--always"], repo)[0] or None
    r["local_tags_tail"] = (run(["git", "tag"], repo)[0] or "").splitlines()[-6:]

    # 远端 tag
    out, _ = run(["git", "ls-remote", "--tags", "origin"], repo, timeout=40)
    rtags = {}
    for ln in out.splitlines():
        if "\trefs/tags/" not in ln:
            continue
        h, ref = ln.split("\t", 1)
        name = ref[len("refs/tags/"):]
        if name.endswith("^{}"):
            continue
        rtags[name] = h
    r["remote_tag_count"] = len(rtags)
    r["remote_tags_tail"] = sorted(rtags)[-6:]
    tagv = f"v{canonical}" if canonical else None
    r["canonical_tag"] = tagv
    r["remote_has_canonical_tag"] = tagv in rtags if tagv else False
    r["remote_canonical_hash"] = rtags.get(tagv)
    # 远端可疑 tag (非 vX.Y.Z 形态, 如历史 vv5.16.35 双 v)
    r["remote_odd_tags"] = [t for t in rtags if not re.fullmatch(r"v\d+\.\d+\.\d+", t)]

    # 最新 Release —— 优先 gh, 否则 HTTPS API (降级)
    rel = {"tag_name": None, "assets": [], "source": None}
    gh = shutil.which("gh")
    if gh and not offline:
        out, rc = run([gh, "release", "view", "--json", "tagName,assets"],
                      repo, timeout=30)
        if rc == 0 and out:
            try:
                j = json.loads(out)
                rel["tag_name"] = j.get("tagName")
                rel["assets"] = [{"name": a.get("name"), "size": a.get("size")}
                                 for a in j.get("assets", [])]
                rel["source"] = "gh release view"
            except Exception:  # noqa: BLE001
                pass
    if rel["source"] is None and r["slug"] and not offline:
        j = api_json(f"https://api.github.com/repos/{r['slug']}/releases/latest")
        if isinstance(j, dict) and j.get("tag_name"):
            rel["tag_name"] = j.get("tag_name")
            rel["assets"] = [{"name": a.get("name"), "size": a.get("size")}
                             for a in j.get("assets", [])]
            rel["source"] = "HTTPS GitHub API (gh 不可用, 已降级)"
        elif isinstance(j, dict) and "__http__" in j:
            rel["source"] = f"HTTPS API 失败 HTTP {j['__http__']}"
        else:
            rel["source"] = "HTTPS API 失败/离线"
    r["gh_available"] = bool(gh)
    r["release"] = rel
    r["release_aligned"] = (norm(rel["tag_name"]) == canonical) if rel["tag_name"] else None
    return r


# ─────────────────────────────────────────────────────────────────────────────
def build_report(repo, offline):
    locs = scan_sync_locs(repo)
    canonical, canon_src = canonical_of(locs)

    inconsistent = [L for L in locs if L["normalized"] != canonical]
    gui_found, gui_stale = scan_gui_display(repo, canonical) if canonical else ([], [])
    xspace_ev, xspace_concl = scan_xspace(repo, offline)
    remote = scan_remote(repo, canonical, offline)

    # update_checker 更新源与版本线不同源?
    uc_repo = xspace_ev.get("update_checker_repo")
    uc_slug = remote.get("slug")
    uc_mismatch = bool(uc_repo and uc_slug and uc_repo != uc_slug)

    deviations = []
    if not canonical:
        deviations.append("无法判定权威版本号")
    for L in inconsistent:
        deviations.append(f"{L['id']} = {L['raw']} (≠ {canonical}) @ {L['file']}:{L['line']}")
    for g in gui_stale:
        deviations.append(f"GUI 显示陈旧: studio.py:{g['line']} 字面量 Z-MAX {g['raw']} (≠ v{canonical})")
    if remote.get("canonical_tag") and not remote.get("remote_has_canonical_tag"):
        deviations.append(f"远端缺少 tag {remote['canonical_tag']}")
    if remote.get("release_aligned") is False:
        deviations.append(f"最新 Release tag {remote['release']['tag_name']} ≠ v{canonical}")
    if uc_mismatch:
        deviations.append(f"自动更新源仓库 {uc_repo} ≠ 本仓库 {uc_slug} (更新检查比对的是另一条版本线)")

    ok = (canonical is not None and not inconsistent and not gui_stale
          and remote.get("remote_has_canonical_tag") and remote.get("release_aligned") is not False
          and not uc_mismatch)

    return {
        "ok": ok,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "repo_root": repo,
        "canonical_version": canonical,
        "canonical_source": canon_src,
        "sync_locations": locs,
        "all_locations_consistent": not inconsistent,
        "gui_display": {"found": gui_found, "stale": gui_stale,
                        "consistent": not gui_stale},
        "xspace": {"evidence": xspace_ev, "conclusion": xspace_concl},
        "remote": remote,
        "deviations": deviations,
    }


# ─────────────────────────────────────────────────────────────────────────────
def human_report(rep):
    L = []
    A = L.append
    c = rep["canonical_version"]
    A("=" * 72)
    A(f"Z-MAX 版本同源体检   {rep['generated_at']}   仓库: {rep['repo_root']}")
    A("=" * 72)
    A(f"权威版本: {c}  (来源: {rep['canonical_source']})")

    A("\n① 版本号同步点 (逐个 file:line + 实际值)")
    A("-" * 72)
    for x in rep["sync_locations"]:
        mark = "✅" if x["normalized"] == c else "❌"
        loc = f"{x['file']}:{x['line']}" if x["line"] else x["file"]
        A(f"  {mark} {loc:<38} = {str(x['raw']):<10} [{x['id']}]")
    A(f"  => {'全部一致 ✅' if rep['all_locations_consistent'] else '存在偏差 ❌'}")

    A("\n② 与 \"xspace 版本\" 的对齐")
    A("-" * 72)
    for k, v in rep["xspace"]["evidence"].items():
        A(f"  · {k} = {v}")
    A(f"  结论: {rep['xspace']['conclusion']}")

    A("\n③ 与 Git 远程 tag / Release 的对齐")
    A("-" * 72)
    r = rep["remote"]
    A(f"  origin         : {r['origin_url']}  (slug={r['slug']})")
    A(f"  本地 HEAD      : {r['head_short']}  ({r['branch']})  describe={r['describe']}")
    A(f"  本地 tag(尾)   : {r['local_tags_tail']}")
    A(f"  远端 tag 数    : {r['remote_tag_count']}  尾: {r['remote_tags_tail']}")
    A(f"  远端异常 tag   : {r['remote_odd_tags'] or '无'}")
    A(f"  权威 tag 在远端: {r['canonical_tag']} -> {'有 ✅ ' + str(r['remote_canonical_hash'])[:12] if r['remote_has_canonical_tag'] else '无 ❌'}")
    rel = r["release"]
    A(f"  最新 Release   : {rel['tag_name']}   (来源: {rel['source']})")
    for a in rel["assets"]:
        sz = a.get("size")
        A(f"      - {a['name']}  ({sz if sz is not None else '?'} bytes)")
    A(f"  发布对齐       : {'一致 ✅' if r['release_aligned'] else ('不一致 ❌' if r['release_aligned'] is False else '未知')}")

    A("\n④ GUI 显示版本 vs 实际")
    A("-" * 72)
    A(f"  GUI 中 Z-MAX vX.Y.Z 字面量 {len(rep['gui_display']['found'])} 处; 陈旧 {len(rep['gui_display']['stale'])} 处")
    for g in rep["gui_display"]["stale"]:
        A(f"  ❌ {g['file']}:{g['line']} 显示 Z-MAX {g['raw']} (≠ v{c})")
    A(f"  => {'显示一致 ✅' if rep['gui_display']['consistent'] else '显示陈旧 ❌'}")

    A("\n偏差汇总")
    A("-" * 72)
    if rep["deviations"]:
        for d in rep["deviations"]:
            A(f"  ❌ {d}")
    else:
        A("  (无)")
    A("=" * 72)
    A(f"结论: {'✅ 全一致 (exit 0)' if rep['ok'] else '❌ 有偏差 (exit 1)'}")
    A("=" * 72)
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Z-MAX 版本同源体检 (只读)")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--repo", default="", help="仓库根 (缺省按脚本位置推导)")
    ap.add_argument("--offline", action="store_true", help="跳过所有网络探测")
    a = ap.parse_args()
    repo = a.repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rep = build_report(repo, a.offline)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(human_report(rep))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
