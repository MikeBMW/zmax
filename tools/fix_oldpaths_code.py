#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_oldpaths_code.py — 把**代码区**里的老路径写法批量改成"从工程根推/带 env 口子"(2026-10-08)

背景: 家目录整合只按 绝对路径 / `~/x` / `$HOME/x` 三种写法改, 漏了:
  第4种  os.path.join(os.path.expanduser("~"), "zmax_data", ...)
  第5种  Path.home() / "zmax_data" / ... , Path.home() / "lerobot-smolvla-lew"
后果(已实测): SDK 执行腿整体失效(页面报已下发但机器人不动); CICD/训练工具把产物写回家目录老目录。

策略: 统一替换成 `os.environ.get("ZMAX_DATA"|"ZMAX_FORK", "<工程根>/...")`, 与原写法语义等价且可 override。
  · 只动 tools/ src/ hermes/ web/ config/ configs/ .github/ 与仓库根脚本
  · 不碰 docs/(历史留档) 与本次的三个迁移/扫描工具自身
  · 每处改动写进 JSONL 清单, 可逐条回滚
用法: python3 tools/fix_oldpaths_code.py           # 预演, 只打印
      python3 tools/fix_oldpaths_code.py --apply   # 真改 + 写清单
"""
import json
import os
import re
import sys
import time

REPO = "/home/ubuntu/zmax"
DATA = REPO + "/zmax_data"
FORK = REPO + "/external/lerobot-smolvla-lew"
SKIP_FILES = {"tools/audit_paths.py", "tools/scan_oldpaths.py",
              "tools/fix_oldpaths_code.py", "tools/fix_symlinks_homecons.py",
              # ⚠️ 这几个文件里的老路径是**探测/判据字符串**(改了反而抓不到老路径), 不能动
              "tools/preflight_shutdown.sh", "tools/verify_functions.sh"}
CODE_DIRS = ("tools/", "src/", "hermes/", "web/", "config/", "configs/", ".github/")
EXT = (".py", ".sh", ".bash", ".json", ".yaml", ".yml", ".html", ".php", ".service", ".desktop")
MANIFEST = REPO + "/zmax_data/backups/oldpaths_code_fix_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S")

# (正则, 替换) —— 顺序有讲究: 长模式在前, 避免被短模式先吃掉
SUBS = [
    # 第4种 / 第5种: join(expanduser("~"), "zmax_data", ...) 与 join(os.environ["HOME"], "zmax_data", ...)
    (re.compile(r'os\.path\.expanduser\(\s*"~"\s*\)\s*,\s*"zmax_data"'), 'os.environ.get("ZMAX_DATA", "%s")' % DATA),
    (re.compile(r'os\.path\.expanduser\(\s*"~"\s*\)\s*,\s*"lerobot-smolvla-lew"'), 'os.environ.get("ZMAX_FORK", "%s")' % FORK),
    (re.compile(r'os\.environ(?:\.get)?\(\s*"HOME"\s*\)\s*,\s*"zmax_data"'), 'os.environ.get("ZMAX_DATA", "%s")' % DATA),
    (re.compile(r'Path\.home\(\)\s*/\s*"zmax_data"'), 'Path(os.environ.get("ZMAX_DATA", "%s"))' % DATA),
    (re.compile(r'Path\.home\(\)\s*/\s*"lerobot-smolvla-lew"'), 'Path(os.environ.get("ZMAX_FORK", "%s"))' % FORK),
    # 老扁平绝对 / ~ 形式(字符串字面量)
    (re.compile(r'"/home/ubuntu/zmax_data'), '"/home/ubuntu/zmax/zmax_data'),
    (re.compile(r'"/home/ubuntu/lerobot-smolvla-lew'), '"/home/ubuntu/zmax/external/lerobot-smolvla-lew'),
    (re.compile(r"'/home/ubuntu/zmax_data"), "'/home/ubuntu/zmax/zmax_data"),
    (re.compile(r"'/home/ubuntu/lerobot-smolvla-lew"), "'/home/ubuntu/zmax/external/lerobot-smolvla-lew"),
    (re.compile(r'"~/zmax_data'), '"~/zmax/zmax_data'),
    (re.compile(r'"~/lerobot-smolvla-lew'), '"~/zmax/external/lerobot-smolvla-lew'),
]


def needs_os_import(txt):
    return not re.search(r'^\s*import os\b', txt, re.M) and not re.search(r'^\s*import os\s*$', txt, re.M)


def main():
    apply = "--apply" in sys.argv
    changed = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in {".git", "zmax_data", "external", "venvs", "toolchains", "node_modules", "__pycache__"}]
        rel_root = os.path.relpath(root, REPO) + os.sep
        if not (rel_root.startswith(CODE_DIRS) or root == REPO):
            continue
        for fn in files:
            if not fn.endswith(EXT):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, REPO)
            if rel in SKIP_FILES or rel.startswith("docs/"):
                continue
            try:
                txt = open(p, encoding="utf-8").read()
            except OSError:
                continue
            orig = txt
            added_os = False
            for rx, rep in SUBS:
                txt = rx.sub(rep, txt)
            if txt == orig:
                continue
            # 若替换引入了 os.environ 但文件没 import os, 补上(插到第一个 import 之前)
            if ("os.environ" in txt) and needs_os_import(txt):
                m = re.search(r'^(?:from __future__.*\n(?:.*\n)*?)?(import |from )', txt, re.M)
                if m:
                    txt = txt[:m.start()] + "import os\n" + txt[m.start():]
                else:
                    txt = "import os\n" + txt
                added_os = True
            changed.append({"f": rel, "added_import_os": added_os})
            if apply:
                open(p, "w", encoding="utf-8").write(txt)

    print(("✅ 已改" if apply else "预演(未落盘)") + " %d 个文件:" % len(changed))
    for c in changed:
        print("   %-58s%s" % (c["f"], "  (+import os)" if c["added_import_os"] else ""))
    if apply:
        os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
        with open(MANIFEST, "w", encoding="utf-8") as f:
            for c in changed:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        print("\n清单: %s" % MANIFEST)
        print("回滚: git -C %s checkout -- <上面每个文件>" % REPO)
    return 0


if __name__ == "__main__":
    sys.exit(main())
