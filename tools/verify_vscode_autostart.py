#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 550B 标定版 → 文件→打开工程 → 自动起 VSCode 的状态空间工程 (省资源 · 单线程 debug)

老倪 2026-10-21 (逐字):
  「550B 标定版，选择后，从 文件，打开工程，你要自动启动 vscode的 状态空间工程，
    要注意节约资源，因为vscode每次启动后，机器都显得很慢；
    标定配置版本，不需要那么多并行逻辑，多线程，要保持稳定的，面向 清晰单线程逻辑的debug模式」

判据 (逐条都有实测值, 不看代码"看起来对"):
  ① 只有 550B 起: 唯一依据 550B=True; 临时唯一依据 550A/550C=False
  ② 省资源启动参数齐 + 目标是真状态空间工程 (ZMAX.code-workspace 存在)
  ③ 单线程口径: 550B 环境 = SINGLE_THREAD_ENV 逐键相等; 非标定档不被改写
  ④ 独立 scope (systemd-run) —— 关控制台不带走 VSCode
  ⑤ **真调用链**: 注入 spawn 替身跑 autostart → 550B 收到正确 argv+env; 550C 一次都不调
     (全程不真起进程: 前后 pgrep 计数必须一致)
  ⑥ studio.py 两条打开路径都接了钩子 (打开总工程 / 加载工程文件)
  ⑦ .vscode/launch.json 有「🅱 550B 标定版 · 单线程 debug (状态空间工程)」且 env 与唯一依据逐键一致
  ⑧ 右键「打开 VSCode」的模板 (_vscode_launch_cfg) 里也有同一条 (否则右键一按就被抹掉)
  ⑨ .vscode/settings.json 的资源开关在位 (索引/监视/minimap/git 轮询/自动更新)
  ⑩ 自证日志 ~/.cache/zmax/vscode_autostart.log 有本次记录
用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_vscode_autostart.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

import vscode_launch as VL                                                   # noqa: E402

CHECKS = []


def chk(name, cond, ev=""):
    CHECKS.append((name, bool(cond), str(ev)[:400]))
    print(("  ✅ " if cond else "  ❌ ") + name + (("  · " + str(ev)[:400]) if ev else ""))


def _jsonc(path):
    with open(path, encoding="utf-8") as f:
        s = f.read()
    s = re.sub(r"^\s*//.*$", "", s, flags=re.M)
    return json.loads(s)


def _code_procs():
    try:
        out = subprocess.run(["pgrep", "-f", "/usr/share/code/code|/usr/bin/code"],
                             capture_output=True, text=True).stdout
        return len([x for x in out.split() if x.strip()])
    except Exception:                                                           # noqa: BLE001
        return -1


print("=== ① 只有标定档 (550B) 自动起 ===")
_prod = VL.active_product()
chk("①a 唯一依据 active_product 读得到", _prod in ("550A", "550B", "550C"), "active_product=%r" % _prod)
chk("①b AUTOSTART_PRODUCTS 只含 550B", tuple(VL.AUTOSTART_PRODUCTS) == ("550B",), str(VL.AUTOSTART_PRODUCTS))
_tmp = tempfile.mkdtemp(prefix="zmax_prod_")
os.makedirs(os.path.join(_tmp, "config", "platform"), exist_ok=True)


def _mk_prod(p):
    with open(os.path.join(_tmp, "config", "platform", "zmax_product.json"), "w", encoding="utf-8") as f:
        json.dump({"active_product": p}, f, ensure_ascii=False)


_res = {}
for _p in ("550A", "550B", "550C"):
    _mk_prod(_p)
    _ok, _pp, _why = VL.should_autostart(_tmp)
    _res[_p] = _ok
chk("①c 550B 起 / 550A·550C 不起", _res.get("550B") is True and _res.get("550A") is False
    and _res.get("550C") is False, "550A=%s 550B=%s 550C=%s" % (_res["550A"], _res["550B"], _res["550C"]))

print("\n=== ② 省资源启动参数 + 目标工程 ===")
_cmd = VL.build_cmd()
_ws = VL.workspace_target()
# 只认本机 `code --help` 实测存在的开关 (未知参数会被当成"要打开的文件", 反而添乱);
# 欢迎页/信任/自动更新 没有 CLI 开关 ⇒ 由 .vscode/settings.json 承担 (⑨ 里核)。
_need = ["--reuse-window", "--disable-gpu"]
_missing = [f for f in _need if f not in _cmd]
chk("②a CLI 只带实测存在的省资源开关 (复用窗口 + 关GPU), 不塞未知参数", not _missing,
    "缺: %s" % (_missing or "无"))
_help = subprocess.run(["code", "--help"], capture_output=True, text=True).stdout
_unknown = [f for f in _cmd[1:] if f.startswith("--") and f not in _help]
chk("②a2 argv 里没有 code 不认识的参数 (否则会被当成路径打开)", not _unknown,
    "未知: %s" % (_unknown or "无"))
chk("②b 目标是真状态空间工程 (ZMAX.code-workspace 存在) 且排在最后一个参数",
    _cmd[-1] == _ws and os.path.isfile(os.path.join(ROOT, "ZMAX.code-workspace")),
    os.path.relpath(_ws, ROOT))
chk("②c 命令第一段是 code 可执行文件", os.path.basename(_cmd[0]) == "code" or _cmd[0].endswith("/code"), _cmd[0])

print("\n=== ③ 单线程口径 ===")
_env_b = VL.launch_env("550B")
_bad = {k: (v, _env_b.get(k)) for k, v in VL.SINGLE_THREAD_ENV.items() if _env_b.get(k) != v}
chk("③a 550B 环境 = SINGLE_THREAD_ENV 逐键相等 (OMP/MKL/OPENBLAS/NumExpr/VECLIB/Torch = 1)",
    not _bad, "不一致: %s" % (_bad or "无") )
chk("③b 550B 明确标注调试模式", _env_b.get("ZMAX_DEBUG_MODE") == "1" and _env_b.get("ZMAX_PRODUCT") == "550B",
    "ZMAX_DEBUG_MODE=%s ZMAX_PRODUCT=%s" % (_env_b.get("ZMAX_DEBUG_MODE"), _env_b.get("ZMAX_PRODUCT")))
_env_a = VL.launch_env("550A", base={"OMP_NUM_THREADS": "6"})
chk("③c 非标定档不改写线程口径 (550A 保持原值 6)", _env_a.get("OMP_NUM_THREADS") == "6"
    and _env_a.get("ZMAX_DEBUG_MODE") is None, "OMP=%s DEBUG=%s" % (_env_a.get("OMP_NUM_THREADS"), _env_a.get("ZMAX_DEBUG_MODE")))

print("\n=== ④ 独立 scope (关控制台不带走 VSCode) ===")
_w = VL.wrap_isolated(["code", "--reuse-window"])
chk("④ systemd-run --user --scope 包一层", _w[:3] == ["systemd-run", "--user", "--scope"]
    and any(x.startswith("--unit=zmax-vscode-") for x in _w), " ".join(_w[:5]))

print("\n=== ⑤ 真调用链 (注入 spawn 替身, 不真起进程) ===")
_n0 = _code_procs()
_seen = {}


def _fake(argv, env=None):
    _seen["argv"] = list(argv)
    _seen["env"] = dict(env or {})
    return True


_r1 = VL.autostart(force_product="550B", spawn=_fake)
chk("⑤a 550B → 真调 spawn 一次, argv 末段是工程, env 单线程",
    _r1.get("ok") and _seen.get("argv", [])[-1] == _ws
    and _seen.get("env", {}).get("OMP_NUM_THREADS") == "1",
    "argv=%s" % (" ".join(_seen.get("argv", [])[:6]) + " … " + str((_seen.get("argv") or ["?"])[-1])))
_seen.clear()
_r2 = VL.autostart(force_product="550C", spawn=_fake)
chk("⑤b 550C → 跳过且一次都不调 spawn", _r2.get("skipped") and not _seen, "why=%s" % _r2.get("why"))
_r3 = VL.autostart(force_product="550B", spawn=_fake, dry_run=True)
chk("⑤c --dry-run 只算不启 (ok=True 但 spawn 未调)", _r3.get("ok") and _r3.get("dry_run") and not _seen, "")
_n1 = _code_procs()
chk("⑤d 全程没有真起 VSCode 进程 (pgrep 前后一致)", _n0 == _n1, "%s → %s" % (_n0, _n1))

print("\n=== ⑥ studio.py 两条打开路径都接了钩子 ===")
_src = open(os.path.join(ROOT, "tools", "gui", "studio.py"), encoding="utf-8").read()
_h1 = '_vscode_autostart_after_open("打开总工程")' in _src
_h2 = '_vscode_autostart_after_open("加载工程文件")' in _src
_h3 = "def _vscode_autostart_after_open" in _src
chk("⑥ 打开总工程 + 加载工程文件 两处调用 + 方法定义", _h1 and _h2 and _h3,
    "打开总工程=%s 加载工程文件=%s 定义=%s" % (_h1, _h2, _h3))

print("\n=== ⑥b 真调 studio 的那个方法 (不是只看源码里有没有这行) ===")
try:
    import importlib.util as _iu
    import vscode_launch as _VL2
    _spec = _iu.spec_from_file_location("zmax_studio_probe", os.path.join(ROOT, "tools", "gui", "studio.py"))
    _sm = _iu.module_from_spec(_spec)
    _spec.loader.exec_module(_sm)
    _calls = {}


    class _Stub:                                  # 只给方法需要的最小面: repo_path + 两个输出
        repo_path = ROOT

        def _ui_msg(self, t):
            _calls.setdefault("ui", []).append(str(t))

        def statusBar(self):
            class _SB:
                def showMessage(self, t, ms=0):
                    _calls["sb"] = str(t)
            return _SB()

    _orig = _VL2.autostart
    _VL2.autostart = lambda root=None, **kw: {"ok": True, "skipped": False, "why": "标定档 550B → 自动起",
                                              "product": "550B", "cmd": ["code"], "isolated": True}
    try:
        _sm.StudioMainWindow._vscode_autostart_after_open(_Stub(), "判据")
    finally:
        _VL2.autostart = _orig
    _hit = (_calls.get("ui") and "VSCode 已启动" in _calls["ui"][-1]) and "复用窗口" in _calls.get("sb", "")
    chk("⑥b 调方法 → 真走 autostart 并如实回报 (状态栏 + 信息窗各一行)", _hit,
        "ui=%s | sb=%s" % ((_calls.get("ui") or [""])[-1][:90], _calls.get("sb", "")[:60]))
except Exception as e:                                                       # noqa: BLE001
    chk("⑥b 调方法 → 真走 autostart 并如实回报 (状态栏 + 信息窗各一行)", False, "异常: %r" % (e,))

print("\n=== ⑦ launch.json 的 550B 单线程配置 ===")
_lj = _jsonc(os.path.join(ROOT, ".vscode", "launch.json"))
_cfg = next((c for c in _lj.get("configurations", []) if "550B 标定版" in str(c.get("name"))), None)
chk("⑦a 配置存在且名称为「🅱 550B 标定版 · 单线程 debug (状态空间工程)」",
    _cfg is not None and "单线程 debug" in _cfg.get("name", ""), (_cfg or {}).get("name", "缺"))
_p = (_cfg or {}).get("program", "")
chk("⑦b 调试入口 = 状态空间工程画布 (tools/gui/simulink_module.py 真存在)",
    _p.endswith("tools/gui/simulink_module.py") and os.path.isfile(_p), _p)
_eb = (_cfg or {}).get("env") or {}
_bad2 = {k: (v, _eb.get(k)) for k, v in VL.SINGLE_THREAD_ENV.items() if _eb.get(k) != v}
chk("⑦c 配置 env == SINGLE_THREAD_ENV (与启动器同源)", not _bad2, "不一致: %s" % (_bad2 or "无"))

print("\n=== ⑧ 模板同源 (右键打开 VSCode 不会抹掉这条) ===")
try:
    import simulink_module as SM                                             # noqa: E402
    _tpl = SM._vscode_launch_cfg(ROOT)
    _tcfg = next((c for c in _tpl.get("configurations", []) if "550B 标定版" in str(c.get("name"))), None)
    _tbad = {k: (v, (_tcfg or {}).get("env", {}).get(k)) for k, v in VL.SINGLE_THREAD_ENV.items()
             if (_tcfg or {}).get("env", {}).get(k) != v}
    chk("⑧ 模板里有同一条配置且 env 一致", _tcfg is not None and not _tbad,
        "模板配置=%s · 不一致=%s" % ((_tcfg or {}).get("name", "缺"), _tbad or "无"))
except Exception as e:                                                       # noqa: BLE001
    chk("⑧ 模板里有同一条配置且 env 一致", False, "导入 simulink_module 失败: %r" % (e,))

print("\n=== ⑨ 工作区资源开关 ===")
_st = _jsonc(os.path.join(ROOT, ".vscode", "settings.json"))
_want = {"python.analysis.diagnosticMode": "openFilesOnly", "python.analysis.indexing": False,
         "editor.minimap.enabled": False, "git.autorefresh": False, "update.mode": "none",
         "extensions.autoUpdate": False, "search.followSymlinks": False,
         "telemetry.telemetryLevel": "off"}
_bad3 = {k: (_st.get(k), v) for k, v in _want.items() if _st.get(k) != v}
_we = _st.get("files.watcherExclude") or {}
chk("⑨a 索引/minimap/git 轮询/自动更新/遥测 全关", not _bad3, "不一致: %s" % (_bad3 or "无"))
chk("⑨b 文件监视排掉重目录 (gui-venv311 / external / outputs / zmax_data)",
    all(k in _we for k in ("**/gui-venv311/**", "**/external/**", "**/outputs/**", "**/zmax_data/**")),
    "命中 %d/%d" % (sum(k in _we for k in ("**/gui-venv311/**", "**/external/**", "**/outputs/**", "**/zmax_data/**")), 4))

print("\n=== ⑩ 自证日志 ===")
_log = os.path.join(os.path.expanduser("~"), ".cache", "zmax", "vscode_autostart.log")
_has = os.path.isfile(_log)
_last = open(_log, encoding="utf-8").read().strip().splitlines()[-1] if _has else ""
chk("⑩ 日志有本次 fail/skip/dry-run 记录", _has and ("550C" in _last or "SKIP" in _last or "DRY-RUN" in _last),
    _last[:160])

_ok = sum(1 for _, c, _ in CHECKS if c)
print("\n%s %d/%d" % ("✅ PASS" if _ok == len(CHECKS) else "❌ FAIL", _ok, len(CHECKS)))
sys.exit(0 if _ok == len(CHECKS) else 1)
