# -*- coding: utf-8 -*-
"""判据: 闭环总装真身必须在 src/ 下, tools/gui 只许留别名 shim, 且零 Qt 依赖。

老倪 2026-10-17: 「RealStateSpaceSim 是 Z-MAX 的核心物理仿真主循环, 但是这么多核心代码,
却在 gui 文件夹里, 不合理啊」

跑法: ./gui-venv311/bin/python tools/verify_engine_location.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = os.path.join(ROOT, "src", "lerobot", "engine", "runtime.py")
SHIM = os.path.join(ROOT, "tools", "gui", "state_space_sim_real.py")

ok = 0
bad = []


def chk(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print(f"✅ {name}{(' · ' + extra) if extra else ''}")
    else:
        bad.append(name)
        print(f"❌ {name}{(' · ' + extra) if extra else ''}")


# ① 真身位置
chk("真身在 src/lerobot/engine/runtime.py", os.path.isfile(REAL),
    f"{os.path.getsize(REAL) // 1024} KB" if os.path.isfile(REAL) else "缺失")

# ② tools/gui 只剩 shim (不超过 40 行, 且不含 class RealStateSpaceSim)
shim_lines = len(open(SHIM, encoding="utf-8").read().splitlines()) if os.path.isfile(SHIM) else -1
shim_txt = open(SHIM, encoding="utf-8").read() if os.path.isfile(SHIM) else ""
chk("tools/gui 只剩别名 shim", 0 < shim_lines <= 40, f"{shim_lines} 行")
chk("shim 里没有实现体", "class RealStateSpaceSim" not in shim_txt)

# ③ 真身零 Qt 依赖 (核心逻辑不许绑 GUI)
real_txt = open(REAL, encoding="utf-8").read()
qt_hits = [m for m in ("PyQt5", "pyqtgraph", "pyqtSignal", "QWidget") if m in real_txt]
chk("真身零 Qt 依赖", not qt_hits, f"命中 {qt_hits}" if qt_hits else "仅 stdlib + numpy")

# ④ 两条 import 路径拿到同一个模块对象 + 类身份一致
probe = (
    "import sys; sys.path[:0]=['tools/gui','src']\n"
    "import state_space_sim_real as A\n"
    "from lerobot.engine import runtime as B\n"
    "print(A is B, A.RealStateSpaceSim is B.RealStateSpaceSim, A._repo_root())\n"
)
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=ROOT)
parts = (r.stdout or "").split()
chk("import 两条路同一对象", parts[:2] == ["True", "True"], (r.stdout or r.stderr).strip()[:80])
chk("_repo_root() 解析正确", len(parts) > 2 and os.path.abspath(parts[2]) == ROOT)

# ⑤ 仓库级资源定位 (归位后预先固定 dirname×3 会失效的正是这类)
probe2 = (
    "import sys; sys.path[:0]=['tools/gui','src']\n"
    "import state_space_sim_real as A\n"
    "print(A._tool_path('gen_l4_demo_video.py') != '', A._SS_DIR.endswith('state_space'))\n"
)
r2 = subprocess.run([sys.executable, "-c", probe2], capture_output=True, text=True, cwd=ROOT)
chk("tools/ 与六层源码目录定位正常", (r2.stdout or "").split() == ["True", "True"],
    (r2.stdout or r2.stderr).strip()[:80])

print()
if bad:
    print(f"❌ 失败: {bad}")
    sys.exit(1)
print(f"✅ 全部通过 ({ok} 项)")
