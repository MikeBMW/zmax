# -*- coding: utf-8 -*-
"""🔴 命令行单步调试入口 (不依赖 VSCode 的 UI 断点)。

老倪 2026-10-29: 「无法进入断点」。VSCode 的 UI 断点依赖 debugpy 把"文件:行"绑到已加载的
模块上, 对按路径动态加载的模块 (execution.py 等) 未必绑得住。pdb 走的是另一条路: 直接按
co_filename + 行号在解释器里挂 trace —— 同一份代码, 一定能停。

用法 (在 ~/zmax 下):
  1) 手工单步 (推荐, 停下来自己敲命令)
     ./gui-venv311/bin/python -m pdb tools/dbg_actuator.py
     进去后:
       (Pdb) b /home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/execution.py:111
                ↑ 必须绝对路径: 相对名 `b execution.py:59` 会报 'execution.py' not found from sys.path
                  原因: 该文件是按绝对路径动态加载的, 不在 sys.path 里
                ↑ 行号 109 是 `def execute(self, u):` 本身(停下时 u 还没绑定, p u 会 NameError)
                  111 是函数体第一行 `a = np.asarray(u, dtype=float).ravel()` —— 打这行
       (Pdb) c                      ← 跑起来, 会停在那里
       (Pdb) l                      ← 看附近源码
       (Pdb) p u                    ← 看进来的指令
       (Pdb) p self.last_check      ← 看校验结论
       (Pdb) n / s / r / q          ← 单步/步入/返回/退出

  2) 一条命令直接停到那里并打印现场 (不看交互)
     ./gui-venv311/bin/python -m pdb -c "b /home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/execution.py:111" -c c -c l -c "p u" -c "p self.last_check" -c q tools/dbg_actuator.py

  3) 断在节点入口 (robot_actuator_impl.run)
     ./gui-venv311/bin/python -m pdb -c "b robot_actuator_impl.py:18" -c c -c l -c "p ctx.keys()" -c q tools/dbg_actuator.py

换节点: 改下面 NODES 里要跑哪个。
"""
import os
import sys


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "src"))
    os.environ.setdefault("ZMAX_SINGLE_THREAD", "1")      # 单线程, 断了不会跳到别的线程
    from lerobot.middleware import load_project           # noqa: PLC0415

    prj = load_project()
    nodes = sys.argv[1].split(",") if len(sys.argv) > 1 else ["sslimit", "ssact"]
    # 🔴 2026-10-30: 允许喂一条真实指令, 否则 u_sat 恒 0, 停在 execute 里看到的是全零 (看不出变化率
    #   校验在干什么)。用法: ZMAX_DBG_U="0.1,0.2,0.3,0.4" 或第二次跑给更大的值看 over_rate。
    _u = os.environ.get("ZMAX_DBG_U", "").strip()
    if _u:
        import numpy as _np
        from lerobot.engineering.nodes.library import _SS_STATE
        _SS_STATE["u_sat"] = _np.asarray([float(x) for x in _u.split(",")], dtype=float)
        print("▶ 注入指令 u_sat =", _SS_STATE["u_sat"].tolist(), flush=True)
    print("▶ 单步调试: 节点 %s" % nodes, flush=True)
    traces = prj.step(only=nodes)
    for t in traces:
        out = (t.get("out") or {}).get("out1")
        print("[%s] %s → %s" % (t["id"], t.get("status"),
                                (str(out)[:110] + "...") if out is not None else "None"))
    print("✅ 跑完 (若上面没有停在断点, 说明断点行号/文件路径不匹配)", flush=True)


if __name__ == "__main__":
    main()
