#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_console_popup.py — 发布 Windows 包前的闸：不许留下会闪黑窗的子进程调用。

背景（2026-11-28 现场事故）
--------------------------
786 的 Windows 包换上后屏幕上一直闪黑框。根因不是 nvidia-smi（那个早用 IFEO 盖掉了），
而是探活代码 `subprocess.run(["powershell", "-Command", "Get-CimInstance Win32_Process ..."])`
**没带 CREATE_NO_WINDOW**：GUI 主进程没有控制台，每调一次系统就新建一个控制台窗口。
有多路探活 + 5s 缓存 ⇒ 每 7 秒一个黑框，用户看到的就是「一秒好几个」。

判据
----
扫 .py 源码里的 `subprocess.run / Popen / call / check_output / check_call` 调用点：
  · 同一个调用（含跨行的括号内）出现 Windows 控制台工具字样：
    powershell / pwsh / cmd.exe / tasklist / taskkill / wmic / netstat / sc.exe /
    reg.exe / where.exe / nvidia-smi / chcp
  · 且该调用没带 `creationflags=` 或同文件没有统一的 NOWIN 助手 ⇒ 违规。

放行方式
--------
1) 调用里带 `creationflags=`（推荐 `_NOWIN` 这种模块常量）；
2) 该行或上一行写 `# noqa: console-popup`（确有理由，比如要交互）；
3) 该调用带 `startupinfo=` 且同文件出现 `STARTF_USESHOWWINDOW`。

用法
----
    python tools/ci/check_console_popup.py            # 扫默认目录
    python tools/ci/check_console_popup.py --paths tools server src
退出码：0 = 干净，1 = 有违规（CI 直接红）。
"""
from __future__ import annotations

import argparse
import os
import re
import sys

CONSOLE_TOOLS = re.compile(
    r"""powershell|pwsh|cmd\.exe|\btasklist\b|\btaskkill\b|\bwmic\b|\bnetstat\b"""
    r"""|\bsc\.exe|\breg\.exe|\bwhere\.exe|nvidia-smi|\bchcp\b""",
    re.IGNORECASE,
)
CALL_RE = re.compile(r"subprocess\.(?:run|Popen|call|check_output|check_call)\s*\(|"
                     r"\b_sp\.(?:run|Popen|call|check_output|check_call)\s*\(")
SKIP_DIRS = {".git", "_internal", "dist_nounpack", "dist", "build", "__pycache__",
             "node_modules", ".venv", "venv", "site-packages", "_bak", "_sync_bak"}
SKIP_FILES = {os.path.join("tools", "ci", "check_console_popup.py")}

# 这些目录/文件跑在 GUI 进程里（没有控制台）⇒ 违规直接让 CI 红
FATAL_PREFIXES = ("tools/gui/", "tools\\gui\\", "server/", "server\\")
FATAL_FILES = {"tools/cam_live_stream.py", "tools\\cam_live_stream.py",
               "tools/dashboard_server.py", "tools\\dashboard_server.py"}

SKIP_NORM = {os.path.normpath(p) for p in SKIP_FILES}

NOWIN_RE = re.compile(r"^\s*(?:from\s+nowin\s+import|import\s+nowin)", re.MULTILINE)


def call_block(lines: list[str], start: int, hard_limit: int = 40) -> tuple[str, int]:
    """从 start 行起取到括号配平的调用块（最多 hard_limit 行）。"""
    depth = 0
    buf: list[str] = []
    for i in range(start, min(len(lines), start + hard_limit)):
        line = lines[i]
        buf.append(line)
        depth += line.count("(") - line.count(")")
        if i > start and depth <= 0:
            return "\n".join(buf), i
    return "\n".join(buf), start


def scan_file(path: str) -> list[tuple[int, str]]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError:
        return []
    src = "\n".join(lines)
    if NOWIN_RE.search(src):
        return []                     # 整文件由 nowin 全局守卫覆盖
    has_si_helper = "STARTF_USESHOWWINDOW" in src
    bad: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        if not CALL_RE.search(line):
            continue
        block, _end = call_block(lines, idx)
        if not CONSOLE_TOOLS.search(block):
            continue
        if "creationflags=" in block or "noqa: console-popup" in block:
            continue
        if has_si_helper and "startupinfo=" in block:
            continue
        first_tool = CONSOLE_TOOLS.search(block)
        bad.append((idx + 1, first_tool.group(0) if first_tool else "?"))
    return bad


def walk(paths: list[str]) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for root in paths:
        if os.path.isfile(root):
            for ln, tool in scan_file(root):
                hits.append((root, ln, tool))
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith("_bak_")]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                if os.path.normpath(full) in SKIP_NORM:
                    continue
                for ln, tool in scan_file(full):
                    hits.append((full, ln, tool))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", nargs="*", default=["tools", "server", "src"])
    args = ap.parse_args()
    roots = [p for p in args.paths if os.path.exists(p)]
    if not roots:
        print("[console-popup] 没有可扫的目录，跳过")
        return 0
    hits = walk(roots)
    if not hits:
        print("[console-popup] ✓ 干净：没有会闪黑窗的子进程调用（扫了 %s）" % ", ".join(roots))
        return 0

    def _is_fatal(path: str) -> bool:
        norm = path.replace(os.sep, "/")
        return norm.startswith(FATAL_PREFIXES) or norm in FATAL_FILES

    fatal = [h for h in hits if _is_fatal(h[0])]
    warn = [h for h in hits if not _is_fatal(h[0])]

    if warn:
        print("[console-popup] · %d 处非 GUI 调用会弹窗（终端里跑，影响小；建议顺手修）：" % len(warn))
        for path, ln, tool in warn[:20]:
            print("    %s:%d  调 %s" % (path, ln, tool))
    if fatal:
        print("[console-popup] ✗ %d 处 GUI 侧调用会弹控制台窗口（每调一次闪一个黑框）：" % len(fatal))
        for path, ln, tool in fatal:
            print("  %s:%d  调 %s 没带 creationflags=CREATE_NO_WINDOW" % (path, ln, tool))
        print()
        print("修法二选一：")
        print("  ① 文件顶部 `import nowin`（GUI 入口全局守卫，最省事）；")
        print("  ② 该调用加 creationflags=CREATE_NO_WINDOW + STARTUPINFO(SW_HIDE)；")
        print("  确需交互窗口的写 `# noqa: console-popup`。细节见技能 windows-gui-console-popup。")
        return 1
    print("[console-popup] ✓ GUI 侧干净（只余上面那些终端脚本的提示）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
