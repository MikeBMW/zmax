#!/usr/bin/env python3
"""判据: 快反射层(vl_safety_fast)对「全黑(设备级无信号)」与「真遮挡」分得开。

背景(2026-10-12 老倪): 「⛔ 被拒: (本地检测, 亚秒级) 又是怎么回事?」
  笔记本内置相机镜头全黑(实测 mean=4.8 · uniform=1.000 · lap=0.3) ⇒ 快层判「遮挡/糊化」
  ⇒ L2 执行器 fail-closed **拒发任何动作**, 现场所有按钮都下不去(卡死)。
  一张全黑帧没有任何安全信息(分不出"手挡住镜头"和"屋里没光") ⇒ 单列 no_signal(降级), 不参与否决;
  但**所有**相机都无信息时仍然 fail-closed(不留盲区)。真遮挡(有画面但同质/糊)照旧拦。

判据(不靠嘴, 全跑真码):
  ① 全黑帧          → no_signal=True,  unsafe=False(降级)
  ② 真遮挡(灰同质)  → blocked=True,   unsafe=True (仍然拦!)
  ③ 正常纹理帧      → unsafe=False
  ④ 从严开关 STRICT_DARK=1 时全黑 → unsafe=True(恢复旧口径, 开关有效)
  ⑤ 现场实况(真读 /snapshot): arm 正常 + local 全黑 ⇒ 裁决文件 safe=True · degraded_cams=['local'] · why 写明
  ⑥ 全盲 fail-closed: ZMAX_VL_FAST_CAMS=local --once ⇒ safe=False(只剩一路且它全黑 ⇒ 拒发)
  ⑦ 页面/控制台能看见降级: 裁决文件里有 degraded_cams 且 why 含「不参与否决」
"""
import json, os, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
sys.path.insert(0, os.path.join(ROOT, "tools"))
P = F = 0


def ok(c, m):
    global P, F
    if c:
        P += 1; print("  ✅ %s" % m)
    else:
        F += 1; print("  ❌ %s" % m)


import importlib.util
spec = importlib.util.spec_from_file_location("vlf", os.path.join(ROOT, "tools", "vl_safety_fast.py"))
vlf = importlib.util.module_from_spec(spec); spec.loader.exec_module(vlf)
import numpy as np

print("=== ① 全黑帧(设备级无信号) ===")
black = np.zeros((480, 640, 3), np.uint8)
j = vlf.judge(black)
ok(j["no_signal"] is True and j["unsafe"] is False,
   "全黑 ⇒ no_signal=True · unsafe=False(降级不否决) 实测=%s" % {k: j[k] for k in ("mean", "uniform_frac", "lap_var", "no_signal", "unsafe")})

print("\n=== ② 真遮挡(有画面但同质/糊)仍要拦 ===")
occ = np.full((480, 640, 3), 128, np.uint8)
j2 = vlf.judge(occ)
ok(j2["unsafe"] is True and j2["blocked"] is True and j2["no_signal"] is False,
   "灰同质(遮挡) ⇒ unsafe=True 仍然拦 实测=%s" % {k: j2[k] for k in ("mean", "uniform_frac", "lap_var", "blocked", "no_signal", "unsafe")})

print("\n=== ③ 正常纹理帧 ===")
rng = np.random.default_rng(7)
norm = rng.integers(40, 200, (480, 640, 3), dtype=np.uint8)
j3 = vlf.judge(norm)
ok(j3["unsafe"] is False, "正常纹理 ⇒ unsafe=False 实测 lap=%.0f uniform=%.2f" % (j3["lap_var"], j3["uniform_frac"]))

print("\n=== ④ 从严开关(恢复旧口径) ===")
f = os.path.join(ROOT, "tools", "vl_safety_fast.py")
code = open(f, encoding="utf-8").read()
saved = os.environ.get("ZMAX_VL_FAST_STRICT_DARK")
os.environ["ZMAX_VL_FAST_STRICT_DARK"] = "1"
spec2 = importlib.util.spec_from_file_location("vlf2", f)
v2 = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(v2)
j4 = v2.judge(black)
ok(j4["unsafe"] is True, "STRICT_DARK=1 时全黑 ⇒ unsafe=True(开关有效) 实测 no_signal=%s unsafe=%s" % (j4["no_signal"], j4["unsafe"]))
if saved is None:
    os.environ.pop("ZMAX_VL_FAST_STRICT_DARK", None)

print("\n=== ⑤ 现场实况(真读两路单帧 + 真裁决文件) ===")
frames = {}
for c in ("arm", "local"):
    try:
        b = urllib.request.urlopen("http://127.0.0.1:8791/snapshot/%s.jpg?_=%d" % (c, int(time.time())), timeout=6).read()
        import cv2
        frames[c] = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
    except Exception as e:
        print("   (%s 取帧失败: %s)" % (c, repr(e)[:60]))
for c, im in frames.items():
    jx = vlf.judge(im)
    print("   %-6s mean=%.1f uniform=%.3f lap=%.1f ⇒ no_signal=%s unsafe=%s" % (c, jx["mean"], jx["uniform_frac"], jx["lap_var"], jx["no_signal"], jx["unsafe"]))
vf = os.path.join(ROOT, "zmax_data", "vl_safety_fast.json")
d = json.load(open(vf, encoding="utf-8"))
age = time.time() - os.path.getmtime(vf)
print("   裁决文件: 龄 %.1fs · safe=%s · unsafe_cams=%s · degraded_cams=%s" % (age, d.get("safe"), d.get("unsafe_cams"), d.get("degraded_cams")))
ok(age < 20, "裁决文件在时效内(%.1fs < 20s) —— 生产者带着新码在跑" % age)
if frames.get("arm") is not None and vlf.judge(frames["arm"])["unsafe"] is False:
    ok(d.get("safe") is True and d.get("unsafe_cams") == [], "臂上画面正常 ⇒ 裁决 safe=True · 不拦(实测 safe=%s)" % d.get("safe"))
    ok("local" in (d.get("degraded_cams") or []), "全黑那路记进 degraded_cams(审计留痕, 不是偷偷放行)")
    ok("不参与否决" in str(d.get("why")), "why 里写明「不参与否决」⇒ 控制台/日志看得见")
    ok("无信号" in str(d.get("why")) or "全黑" in str(d.get("why")), "why 里写明是「无信号/全黑」而不是「遮挡」(分得开)")

print("\n=== ⑥ 全盲 fail-closed(只剩一路且它全黑 ⇒ 必须拒) ===")
env = dict(os.environ); env["ZMAX_VL_FAST_CAMS"] = "local"
env.pop("ZMAX_VL_FAST_NO_WRITE", None)
r = subprocess.run([PY, os.path.join(ROOT, "tools", "vl_safety_fast.py"), "--once", "--show"],
                   capture_output=True, text=True, timeout=90, cwd=ROOT, env=dict(env, ZMAX_VL_FAST_NO_WRITE="1"))
tail = [l for l in r.stdout.splitlines() if l.strip().startswith("{")]
verdict = {}
for l in tail:
    try:
        verdict = json.loads(l)
    except Exception:
        pass
print("   单路(local)全黑 --once ⇒ safe=%s why=%s" % (verdict.get("safe"), str(verdict.get("why"))[:110]))
ok(verdict.get("safe") is False, "全部相机都没信息 ⇒ safe=False(不留无信息盲区)")

print("\n=== ⑦ 页面/控制台可见性(裁决文件字段) ===")
ok("degraded_cams" in d and "unsafe_cams" in d, "裁决文件自带 degraded_cams 字段 ⇒ 任何读它的页面都能显示")

print("\n=== 汇总: PASS %d · FAIL %d ===" % (P, F))
sys.exit(1 if F else 0)
