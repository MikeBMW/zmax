"""SE(3) 安全策略的闸门测试: 证明该拦的真会拦, 不该拦的不误拦。

四类用例(全部离线, 不碰真机):
  1. 正常在轨      → 必须放行
  2. 横向偏轨 30mm → 必须拦(超管半径)
  3. 真值帧龄 3s   → 必须拦(无真值不出位姿)
  4. 相位倒车请求  → 必须拦/夹到 0(不许沿轨迹倒退)
"""
import json, math, sys
import numpy as np
sys.path.insert(0, "/home/ubuntu/zmax/tools")
import se3_safe_policy as P

fr, ph, net, ck = P.load_all()
ok_all = True

def show(name, out, expect_ok):
    global ok_all
    good = (out["ok"] == expect_ok)
    ok_all &= good
    print("%-16s 期望 %-5s 实际 %-5s %s  %s" % (name, "放行" if expect_ok else "拦截",
          "放行" if out["ok"] else "拦截", "✅" if good else "❌",
          "" if out["ok"] else out["why"][:60]))
    return out

i = 100
p_now, q_now = P.fr_p(fr[i]), P.fr_q(fr[i])

# 1 正常
o = P.safe_target(fr, ph, net, ck, i, np.zeros(3), pose_now=p_now, q_now=q_now, age_s=0.05, ds_force=0.00127)
show("正常在轨", o, True)

# 2 横向偏轨 30mm(沿工具 Y 方向推开)
off = p_now + np.array([0, 30.0, 0])
o = P.safe_target(fr, ph, net, ck, i, np.zeros(3), pose_now=off, q_now=q_now, age_s=0.05, ds_force=0.00127)
o2 = show("偏轨30mm", o, False)
print("              gate: lateral=%.1fmm  r_tube=%.1fmm" % (o2["gate"].get("lateral_mm", -1), o2["gate"].get("r_tube_mm", -1)))

# 3 真值陈旧
o = P.safe_target(fr, ph, net, ck, i, np.zeros(3), pose_now=p_now, q_now=q_now, age_s=3.0, ds_force=0.00127)
show("真值帧龄3s", o, False)

# 4 相位倒车: 强制 ds 负
o = P.safe_target(fr, ph, net, ck, i, np.zeros(3), pose_now=p_now, q_now=q_now, age_s=0.05, ds_force=-0.002)
o4 = show("相位倒车", o, False)  # 期望拦: 单拍姿态/位移 或 方向不符
print("              cmd.s=%s  s_now=%s" % (o4.get("cmd", {}).get("s"), o4["gate"].get("s_now")))

# 5 大跳变: 相位猛推 0.02(=157mm)
o = P.safe_target(fr, ph, net, ck, i, np.zeros(3), pose_now=p_now, q_now=q_now, age_s=0.05, ds_force=0.02)
o5 = show("单拍157mm", o, False)
print("              gate: dp=%smm" % o5["gate"].get("dp_mm"))

print("\n汇总:", "全部符合预期 ✅" if ok_all else "有用例不符合预期 ❌")
sys.exit(0 if ok_all else 1)
