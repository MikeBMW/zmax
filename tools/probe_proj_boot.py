import importlib.util as ilu, json, os, re, shutil, sys
ROOT = "/home/ubuntu/zmax"
CV = os.path.join(ROOT, "flows", "state_space_obs.json")
def cur():
    for n in (json.load(open(CV, encoding="utf-8")).get("nodes") or []):
        p = n.get("params") or {}
        if p.get("src_state"):
            return p["src_state"]
    return ""
print("BOOT_BEFORE=" + cur())
# 模拟控制台重启把 src_state 写成真机
txt = open(CV, encoding="utf-8").read()
open(CV, "w", encoding="utf-8").write(re.sub(r'("src_state"\s*:\s*")[^"]*(")', lambda m: m.group(1) + "\u771f\u673a" + m.group(2), txt, count=1))
print("BOOT_CLOBBERED=" + cur())
s = ilu.spec_from_file_location("ps", os.path.join(ROOT, "tools", "proj_state.py"))
m = ilu.module_from_spec(s); s.loader.exec_module(m)
r = m.restore()
print("BOOT_AFTER=" + cur())
print("BOOT_ENV=" + (os.environ.get("ZMAX_SCENE_DIR") or "(unset)"))
print("BOOT_TASK=%s->%s" % (r.get("applied", {}).get("active_task_saved"), r.get("applied", {}).get("active_task_now")))
print("BOOT_BAK=" + str(os.path.exists(CV + ".bak_before_proj_restore")))
