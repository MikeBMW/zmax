# 🧭/⚖ 拆分回归判据: 新 InertiaLimiter 与拆分前(HEAD)逐位相同 + 两条闸每拍都被真调
import importlib.util, os, sys, json
import numpy as np

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m)
    return m

OLD = load("pc_old", "/tmp/pcref/physics_constraints_old.py")
NEW = load("pc_new", "/home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/physics_constraints.py")

stages = list(OLD.PHYS) + ["未知段"]
rng = np.random.default_rng(20261031)
n_cmp = n_bad = 0
lim_old = OLD.InertiaLimiter(dt=0.1)
lim_new = NEW.InertiaLimiter(dt=0.1)
vp = ap = None
for i in range(600):
    st = stages[i % len(stages)]
    u = np.concatenate([rng.normal(0, 0.25, 3), [rng.integers(0, 2)]])
    m = None if i % 7 else round(float(rng.uniform(1.1, 1.6)), 3)
    dmdt = None if i % 5 else round(float(rng.uniform(0.0, 0.6)), 3)
    ro = lim_old.limit(st, u, v_prev=vp, a_prev=ap, m=m, dmdt=dmdt)
    rn = lim_new.limit(st, u, v_prev=vp, a_prev=ap, m=m, dmdt=dmdt)
    n_cmp += 1
    same = (np.array_equal(ro["u"], rn["u"]) and np.array_equal(ro["err"], rn["err"])
            and ro["err_norm"] == rn["err_norm"] and ro["why"] == rn["why"]
            and ro["big"] == rn["big"] and ro["s_travel"] == rn["s_travel"]
            and ro["over_travel"] == rn["over_travel"]
            and json.dumps(ro["phys"], sort_keys=True) == json.dumps(rn["phys"], sort_keys=True))
    if not same:
        n_bad += 1
        if n_bad <= 3:
            print("❌ 差异", i, st, "\n old", ro["u"], ro["why"], "\n new", rn["u"], rn["why"])
    vp, ap = rn["u"][:3], (np.asarray(rn["u"][:3]) - np.asarray(vp if vp is not None else np.zeros(3))) / 0.1

print("[1] 逐位回归: %d 拍比对 · 差异 %d 拍" % (n_cmp, n_bad))
print("[2] 统计口径一致: old.n=%d new.n=%d · n_cut 相等=%s" % (lim_old.n, lim_new.n, lim_old.n_cut == lim_new.n_cut))
print("[3] 两条闸真调次数: 运动学 n=%d · 动力学 n=%d (== 总拍 %d)" %
      (lim_new.kin.n, lim_new.dyn.n, lim_new.n))
print("[4] 分闸削因: 运动学 %s · 动力学 %s" % (lim_new.kin.n_cut, lim_new.dyn.n_cut))
# ⑤ 位移: 运动学闸内单独计
print("[5] stats: %s" % json.dumps(lim_new.stats(), ensure_ascii=False)[:300])
sys.exit(1 if (n_bad or lim_new.kin.n != lim_new.n or lim_new.dyn.n != lim_new.n
               or lim_old.n_cut != lim_new.n_cut) else 0)
