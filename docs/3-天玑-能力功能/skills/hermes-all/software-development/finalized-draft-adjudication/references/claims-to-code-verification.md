# 逐条声明 → 代码 → 实测 的核对配方

用途：交付前证明「文档里写的每一条都真在代码里跑」。适用于权利要求、技术协议条款、方案指标。

## 骨架

每条声明三项：**落点存在**（符号真有）+ **行为实测**（真跑出数）+ **判定**。

```python
import inspect, sys, os
sys.path.insert(0, os.path.join(ROOT, "src"))
from <pkg> import <module> as M

PASS, FAIL = [], []
def ck(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  ✓ " if ok else "  ✗ ") + name + (("   " + detail) if detail else ""))

# ① 落点存在
ck("权1a 度规构造存在", callable(getattr(M, "anisotropic_metric", None)))

# ② 行为实测（断言来自独立推导，不来自被检文档）
Mx = M.anisotropic_metric(axis, sigma_t=0.30, sigma_n=6.00)
ck("权1c M 对称正定", np.allclose(Mx, Mx.T) and np.all(np.linalg.eigvalsh(Mx) > 0))

# ③ 架构性声明 → 结构检查
sig = inspect.signature(M.correct)
ck("权9a 无 model/net/weights 参数",
   not any(k in sig.parameters for k in ("model", "net", "weights", "policy")),
   "参数=%s" % list(sig.parameters))
ck("权9b 模块不依赖训练框架", "import torch" not in inspect.getsource(M))

print("汇总: PASS=%d FAIL=%d" % (len(PASS), len(FAIL)))
sys.exit(0 if not FAIL else 1)
```

退出码非 0 ⇒ 有声明落空，**不能交付**。

## 断言怎么写才有用

| 声明类型 | 有效断言 | 无效断言 |
|---|---|---|
| 存在 | `callable(getattr(m, sym))` | 读源码里出现字符串 |
| 数值关系 | 手推的精确值 `abs(x-400) < 1.0` | 「大概在几百」 |
| 方向/符号 | 受控输入下的符号断言（`F=+5 ⇒ Δξ 的 x 分量 <0`） | 「方向合理」 |
| 一致性 | 同一输入两种路径结果逐位相等 | 两次都非零就算过 |
| 零回退 | 关闭/缺失时输出**逐位不变** | 「不报错」 |
| 架构 | 签名/依赖/导入检查 | 注释里写了「无需重训」 |

**反例优先**：每条正向断言旁边放一条负向场景，证明它真的会红。
例如「两路皆缺 ⇒ 不构造梯度」比「两路都有 ⇒ 有梯度」更能暴露实现缺陷。

## 常见落空方式（都是静默的）

1. **符号名对但签名不对**：`f(a, axis)` vs `f(a, contact=None, axis=None)` ⇒ 位置参数错位，
   传进去的 axis 变成 contact，函数不报错但行为全错。先 `inspect.signature` 打印再调用。
2. **参数名写成不存在**：`force_guard(f_max=40)` 而实际是 `force_guard(force_norm, cfg=None)` ⇒
   `TypeError` 或静默走默认值。核对脚本要通过 IDE/LSP 的 `No parameter named` 提示自查。
3. **返回结构猜错**：`info["s"]` vs `info["scale"]`、`out[0]` vs `out["manifold"]`。
   先跑一次打印 keys，再把断言写死。
4. **真源键不存在**：参数在 `metric` 段而你去 `inject` 段取 ⇒ `.get()` 返回 None，不报错。
   读配置时断言 `key in dict`，不要只用 `.get(k) or default`。
5. **把「返回 None」当失败**：函数在「没有有效输入时不构造结果」是正确行为
   （纯轴向力被径向投影剔除 ⇒ 返回 None）。断言写 `x is None or np.allclose(x, 0)`。

## 与真源联动

核对脚本里的参数值应**从真源读**，不要写死：

```python
TRUE_CFG = json.load(open("data/.../zmax_manifold.json"))["inject"]
ck("c_min 在真源", TRUE_CFG.get("cap_min_mm") == 0.30)
```

这样「文档写的参数」与「代码实际用的参数」被同一个数绑住；改真源而不改文档时会立刻红。
