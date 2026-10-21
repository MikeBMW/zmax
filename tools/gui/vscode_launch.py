#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚀 550B 标定版 · 打开工程后自动起 VSCode (低耗 · 单线程 debug)

老倪 2026-10-21 (逐字):
  「550B 标定版，选择后，从 文件，打开工程，你要自动启动 vscode的 状态空间工程，
    要注意节约资源，因为vscode每次启动后，机器都显得很慢；
    标定配置版本，不需要那么多并行逻辑，多线程，要保持稳定的，面向 清晰单线程逻辑的debug模式」

口径 (为什么这么写):
  · **只对 550B 自动起**。550A(开发档)/550C(量产档) 不起 —— 省资源是硬要求, 不是"顺手都开"。
    产品档唯一真源: config/platform/zmax_product.json → active_product (不手抄档位)。
  · **省资源**四件事 (都能实测):
      ① `--reuse-window`: 已有窗口就复用, 不再开第二个 Electron 主进程 (原来一次一个新窗, 内存翻倍);
      ② `--disable-gpu`: 本机 Electron GPU 进程曾多次 SIGTRAP 崩 (见 studio 台账), 也省显存;
      ③ `--skip-welcome / --skip-release-notes / --disable-workspace-trust`: 关掉启动期的欢迎页/信任询问;
      ④ 工作区 `.vscode/settings.json` 关掉重型索引与文件监视 (仓库 9 万+ 文件, 监视器本身就是 CPU 大头)。
  · **单线程 debug**: 起 VSCode 时把线程数环境变量钉成 1 (OMP/MKL/OPENBLAS/NUMEXPR/NumPy/Torch),
    调试启动的进程继承它们 ⇒ 标定档跑的是**一条清晰单线程**路径, 断点不会被多线程交错打断。
    同时置 ZMAX_DEBUG_MODE=1 / ZMAX_PRODUCT=550B, 让下游代码知道自己处在标定调试模式。
  · **脱离控制台 cgroup**: 用 `systemd-run --user --scope` 起独立 scope, 关/崩控制台不会带走 VSCode
    (2026-10-17 实测过同秒双双消失的坑)。

调用面 (只有两个):
  · autostart(root=None) -> dict      给 GUI 用 (打开工程成功后调一次)
  · CLI: python tools/gui/vscode_launch.py [--dry-run] [--product 550B]   给人/判据用
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRODUCT_JSON = os.path.join(ROOT, "config", "platform", "zmax_product.json")

# 🅱 只有标定档 (550B) 自动起 VSCode。改这里 = 改规矩 (判据会核这条与真源 dev_profile 一致)。
AUTOSTART_PRODUCTS = ("550B",)

# 单线程 debug 口径 —— 这一份是**唯一真源**: launch.json 里的同名配置、判据都按它对齐。
SINGLE_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "TORCH_NUM_THREADS": "1",
    "MALLOC_ARENA_MAX": "2",
    "ZMAX_SINGLE_THREAD": "1",
    "ZMAX_DEBUG_MODE": "1",
    "PYTHONUNBUFFERED": "1",
}

# 省资源启动参数 —— 只放**本机 code --help 实测存在**的两个 (未知参数会被当成路径去打开, 危险)
GUI_FLAGS = (
    "--reuse-window",              # ① 复用窗口: 不开第二个主进程 (省内存的大头)
    "--disable-gpu",               # ② 关 GPU 加速 (本机 Electron GPU 进程 SIGTRAP 崩过)
)
# ③ 标定调试用不到的**重型扩展** (实测占用最大): 关掉它们 = 真省内存, 且不影响 F5 断点
#    ms-python.vscode-pylance        实测 920 MB (语言服务器; 标定单线程 debug 不需要智能补全)
#    ms-azuretools.vscode-containers / ms-vscode-remote.remote-containers  各起 node 子进程 (合计 ~1 GB)
#    ms-python.vscode-python-envs    环境探测后台进程
#    ⚠️ 只保留 ms-python.python + ms-python.debugpy (断点/单步靠它们)
DISABLE_EXTENSIONS = (
    "ms-python.vscode-pylance",
    "ms-azuretools.vscode-containers",
    "ms-vscode-remote.remote-containers",
    "ms-python.vscode-python-envs",
)

# ④ 欢迎页/发行说明/工作区信任/自动更新 这些没有 CLI 开关, 统一由工作区 settings 关掉 —— 唯一真源:
SETTINGS_KEYS = {
    "workbench.startupEditor": "none",
    "workbench.tips.enabled": False,
    "security.workspace.trust.enabled": False,
    "update.mode": "none",
    "extensions.autoUpdate": False,
}
LOG = os.path.join(os.path.expanduser("~"), ".cache", "zmax", "vscode_autostart.log")


def _log(line: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except Exception:                                                           # noqa: BLE001
        pass


def active_product(root: str = None) -> str:
    """当前产品档 (真源 active_product); 读不到返回 ""。"""
    rel = os.path.join("config", "platform", "zmax_product.json")
    for p in ([os.path.join(root, rel)] if root else []) + [PRODUCT_JSON]:
        try:
            with open(p, encoding="utf-8") as f:
                v = str((json.load(f) or {}).get("active_product") or "").strip()
            if v:
                return v
        except Exception:                                                       # noqa: BLE001
            continue
    return ""


def workspace_target(root: str = None) -> str:
    """开哪个"状态空间工程": 有 ZMAX.code-workspace 就开它, 否则开仓库根目录。"""
    root = root or ROOT
    ws = os.path.join(root, "ZMAX.code-workspace")
    return ws if os.path.isfile(ws) else root


def build_cmd(root: str = None, code_bin: str = None) -> list:
    """完整命令行 (不含 systemd-run 外壳)。"""
    root = root or ROOT
    code = code_bin or shutil.which("code") or "/usr/bin/code"
    _dis = []
    for _e in DISABLE_EXTENSIONS:
        _dis += ["--disable-extension", _e]
    # 落点 = 状态空间工程画布源码第 1 行: 免得一进来停在「欢迎页」(看着像"没打开工程"),
    # 且 F5 就在这个文件上 (调 550B 单线程逻辑的入口)。
    _entry = os.path.join(root, "tools", "gui", "simulink_module.py")
    _goto = ["--goto", "%s:1" % _entry] if os.path.isfile(_entry) else []
    return [code] + list(GUI_FLAGS) + _dis + _goto + [workspace_target(root)]


def launch_env(product: str = None, base: dict = None) -> dict:
    """起 VSCode 用的环境: 550B 追加单线程口径; 其它档原样。"""
    env = dict(os.environ if base is None else base)
    if (product or active_product()) in AUTOSTART_PRODUCTS:
        env.update(SINGLE_THREAD_ENV)
        env["ZMAX_PRODUCT"] = product or active_product()
    return env


def wrap_isolated(argv: list) -> list:
    """systemd-run --user --scope 包一层 (脱离控制台 cgroup); 没有 systemd-run 就原样返回。"""
    if not shutil.which("systemd-run"):
        return list(argv)
    return ["systemd-run", "--user", "--scope", "--collect",
            "--unit=zmax-vscode-%d" % int(time.time())] + list(argv)


def should_autostart(root: str = None) -> tuple:
    """(要不要起, 当前档, 一句话原因)"""
    prod = active_product(root)
    if not prod:
        return False, prod, "读不到产品真源 (config/platform/zmax_product.json)"
    if prod not in AUTOSTART_PRODUCTS:
        return False, prod, "当前 %s 不是标定档 (只有 %s 自动起 VSCode · 省资源)" % (
            prod, "/".join(AUTOSTART_PRODUCTS))
    return True, prod, "标定档 %s → 自动起 VSCode (复用窗口/关 GPU · 单线程 debug)" % prod


def autostart(root: str = None, spawn=None, force_product: str = None, dry_run: bool = False) -> dict:
    """打开工程后调用: 需要就起 VSCode。返回 {"ok","skipped","why","product","cmd"}。

    spawn: 测试注入 (签名 spawn(argv, env) -> bool); 默认走 systemd-run + Popen。
    永不抛异常 —— 打开工程是主线, VSCode 起不来只记一行日志/一句提示。
    """
    out = {"ok": False, "skipped": True, "why": "", "product": "", "cmd": [], "isolated": False}
    try:
        if force_product:
            ok = force_product in AUTOSTART_PRODUCTS
            prod, why = force_product, ("自动起 (--product 指定)" if ok else "非标定档, 不起")
        else:
            ok, prod, why = should_autostart(root)
        out.update({"product": prod, "why": why, "skipped": not ok})
        if not ok:
            _log("SKIP %s" % why)
            return out
        cmd = build_cmd(root)
        argv = wrap_isolated(cmd)
        env = launch_env(prod)
        out["cmd"] = cmd
        out["isolated"] = argv is not cmd
        if dry_run:
            out.update({"ok": True, "dry_run": True})
            _log("DRY-RUN %s" % " ".join(cmd))
            return out

        def _default_spawn(a, e):
            subprocess.Popen(a, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=e)
            return True

        f = spawn or _default_spawn
        try:
            launched = bool(f(argv, env))
        except TypeError:                      # 兼容只收 argv 的替身
            launched = bool(f(argv))
        if not launched and argv != cmd:
            try:
                launched = bool(f(cmd, env))   # 兜底: systemd-run 不可用/失败时按老路开
            except TypeError:                  # 替身只收 argv
                launched = bool(f(cmd))        # type: ignore[call-arg]
            out["isolated"] = False
        out["ok"] = launched
        if not launched:
            out["why"] = "拉起 VSCode 失败 (见 ~/.cache/zmax/vscode_autostart.log)"
        _log("%s product=%s isolated=%s single_thread=%s cmd=%s"
             % ("OK" if launched else "FAIL", prod, out["isolated"], prod in AUTOSTART_PRODUCTS,
                " ".join(cmd)))
        return out
    except Exception as e:                                                       # noqa: BLE001
        out["why"] = "异常: %r" % (e,)
        _log("ERR %r" % (e,))
        return out


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="550B 标定版 · 打开工程后自动起 VSCode (低耗/单线程)")
    ap.add_argument("--dry-run", action="store_true", help="只打印命令行, 不真起")
    ap.add_argument("--product", default=None, help="临时按这个档判断 (默认读真源)")
    ap.add_argument("--root", default=None)
    a = ap.parse_args(argv)
    r = autostart(root=a.root, force_product=a.product, dry_run=a.dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if r.get("cmd"):
        print("\n命令: " + " ".join(r["cmd"]))
    if r.get("product") in AUTOSTART_PRODUCTS:
        print("单线程环境: " + " ".join("%s=%s" % (k, v) for k, v in sorted(SINGLE_THREAD_ENV.items())))
    return 0 if (r["ok"] or r["skipped"]) else 1


if __name__ == "__main__":
    sys.exit(main())
