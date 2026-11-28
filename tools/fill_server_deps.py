"""补齐 server/ 缺失的项目内依赖模块（tools/ 下有同名 .py 但 server/ 里没有的）。

背景: 建 server/ 时只复制了"服务脚本"本体, 它们 import 的兄弟模块没跟过来 ⇒
      tcp_ar_server.py 一跑就 ModuleNotFoundError: laptop_cam_solve。
      这里扫全部 server/*.py 的 import, 迭代补齐, 直到没有新增为止。
"""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(ROOT) in ("tools", "server"):
    ROOT = os.path.dirname(ROOT)          # 脚本放在 tools/ 或 server/ 下 ⇒ 上溯到仓库根
SRV = os.path.join(ROOT, "server")
TOOLS = os.path.join(ROOT, "tools")

IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([a-zA-Z_][\w]*)", re.M)


def mods_of(path):
    try:
        src = open(path, encoding="utf-8", errors="ignore").read()
    except Exception:
        return set()
    return set(IMPORT_RE.findall(src))


def main():
    copied = {}
    for round_no in range(1, 8):
        have = {os.path.splitext(f)[0] for f in os.listdir(SRV) if f.endswith(".py")}
        targets = [os.path.join(SRV, f) for f in os.listdir(SRV) if f.endswith(".py")]
        need = set()
        for t in targets:
            for m in mods_of(t):
                if m not in have:
                    need.add(m)

        added = 0
        for m in sorted(need):
            src = os.path.join(TOOLS, m + ".py")
            if os.path.isfile(src):
                dst = os.path.join(SRV, m + ".py")
                shutil.copy2(src, dst)
                copied[m] = os.path.getsize(dst)
                added += 1
        if added == 0:
            # 没有可补的了
            still = sorted(m for m in need
                           if not os.path.isfile(os.path.join(TOOLS, m + ".py")))
            print("第 %d 轮: 无新增。仍是外部依赖(不需要补或需 pip 装): %s"
                  % (round_no, ", ".join(still) if still else "无"))
            break
        print("第 %d 轮: 补了 %d 个 — %s" % (round_no, added, ", ".join(sorted(
            m for m in copied if m in need))))

    print()
    print("累计补齐 %d 个模块:" % len(copied))
    for k in sorted(copied):
        print("  %-26s %d 字节" % (k, copied[k]))
    print()
    print("server/ 现在共 %d 个 .py" % len([f for f in os.listdir(SRV) if f.endswith(".py")]))


if __name__ == "__main__":
    sys.exit(main())
