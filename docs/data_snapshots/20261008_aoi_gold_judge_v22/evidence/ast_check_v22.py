#!/usr/bin/env python3
"""AST 权威核对: v21 → v22 到底改了哪些函数(逐字), 证明"模型吃的那条路"没被动过。"""
import ast, sys, difflib, hashlib
A = "/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v21.py"
B = "/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v22.py"

def src(path):
    return open(path, encoding="utf-8").read().split("\n")

def funcs(path, lines):
    t = ast.parse("\n".join(lines))
    out = {}
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(n.name, (n.lineno, n.end_lineno, "\n".join(lines[n.lineno - 1:n.end_lineno])))
    return out

la, lb = src(A), src(B)
fa, fb = funcs(A, la), funcs(B, lb)
added = sorted(set(fb) - set(fa))
removed = sorted(set(fa) - set(fb))
changed = sorted(k for k in set(fa) & set(fb)
                 if hashlib.md5(fa[k][2].encode()).hexdigest() != hashlib.md5(fb[k][2].encode()).hexdigest())
print("函数总数 v21=%d v22=%d" % (len(fa), len(fb)))
print("新增: %s" % (added or "无"))
print("删除: %s" % (removed or "无"))
print("改动的函数: %s" % (changed or "无"))
print()
for k in changed:
    d = list(difflib.unified_diff(fa[k][2].split("\n"), fb[k][2].split("\n"), lineterm="", n=0))
    add = sum(1 for x in d if x.startswith("+") and not x.startswith("+++"))
    dele = sum(1 for x in d if x.startswith("-") and not x.startswith("---"))
    print("  · %s: +%d/-%d 行" % (k, add, dele))
print()
# 模型输入路径的关键函数必须逐字一致
for fn in ("crop_goldfinger_regular", "warp_goldfinger_topview", "get_cropper",
           "_region_payload", "GrabAndSaveImage"):
    same = hashlib.md5(fa[fn][2].encode()).hexdigest() == hashlib.md5(fb[fn][2].encode()).hexdigest()
    print("  %-26s 逐字一致=%s" % (fn, same))
print()
print("=== GrabAndSaveImage 的真实改动(应该只有判据失败那一支) ===")
for x in difflib.unified_diff(fa["GrabAndSaveImage"][2].split("\n"),
                              fb["GrabAndSaveImage"][2].split("\n"), lineterm="", n=2):
    print(x)
print()
print("=== 核心渲染函数: 老 _v21_render(213行) → 新 _v21_render_core 的改动 ===")
d = list(difflib.unified_diff(fa["_v21_render"][2].split("\n"), fb["_v21_render_core"][2].split("\n"),
                              lineterm="", n=1))
for x in d:
    print(x)
print()
print("=== 模块级赋值(常量)改动 ===")
def assigns(path):
    t = ast.parse(open(path, encoding="utf-8").read())
    d = {}
    for n in t.body:
        if isinstance(n, ast.Assign):
            for tg in n.targets:
                if isinstance(tg, ast.Name):
                    d[tg.id] = ast.dump(n.value)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            d[n.target.id] = ast.dump(n.value) if n.value else ""
    return d
aa, ab = assigns(A), assigns(B)
ca = sorted(k for k in set(aa) & set(ab) if aa[k] != ab[k])
print("  新增常量: %s" % (sorted(set(ab) - set(aa)) or "无"))
print("  删除常量: %s" % (sorted(set(aa) - set(ab)) or "无"))
print("  改值的常量: %s" % (ca or "无(一个都没改)"))
