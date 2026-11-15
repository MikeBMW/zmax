# SE(3) 引擎接通 + 双通道 provider 实操

配 `SKILL.md` §0/§2/§4 用。这里只放接线清单、可复现实测数字、以及选判据的坑。

## 1. `Navigator.step` 的 se3 分支改造清单

```python
if t == "se3":
    if p.size < 12:
        raise ValueError("se3: p 必须 12 维 [R(9); t(3)]")   # 不许静默 p+v*dt
    from .se3_chain import se3_exp, T_from_rot_t
    T  = T_from_rot_t(p[:9].reshape(3, 3), p[9:12])
    xi = np.concatenate([np.asarray(v[3:6], float) * dt,      # ρ ← v 的后 3
                         np.asarray(v[:3], float) * dt])     # φ ← v 的前 3
    T2 = T @ se3_exp(xi)                                     # 螺旋, 不是 slerp+lerp
    return np.concatenate([T2[:3, :3].ravel(), T2[:3, 3]])
```

三组判据都要跑, 只测前两组发现不了近似:

| 情形 | slerp+lerp vs 真螺旋 |
|---|---|
| 小角度 (0.01 rad) | 0 |
| ρ∥φ (1.0 rad) | 0 (`V(φ)ρ = ρ`) |
| ρ∦φ + 1.2 rad | **163 mm / 10.1°** |

## 2. 位姿 → 引擎 p 的通路

```python
from lerobot.manifold.se3_chain import read_pose_truth
pt = read_pose_truth(REPO)          # tcp_out/latest.json, 自带 >2s 年龄闸
T  = pt.T
p12 = np.concatenate([T[:3, :3].ravel(), T[:3, 3]])
_p, _resid, _meta = eng.projector.project(p12)     # ← 不是 eng.project(p12)
# _resid ≈ 1e-16, _meta["drift"] == 0.0
```

`eng.project()` 走 `encoder.encode` ⇒ 位姿被 PCA 洗成 `I + 0`, 且不报错。

## 3. 目标与收敛验收

```python
xi      = se3_log(np.linalg.inv(T) @ Tg)     # 当前→目标 (体坐标)
descent = np.concatenate([xi[3:], xi[:3]])   # Navigator 要 [φ;ρ]
p_next  = eng.navigator.step(_p, descent, dt=0.05)
```

实测 (dt=0.05, 8 步): 18.131 → 17.224 → 16.363 → 15.545 → 14.768 → 14.029 → 13.328 → 12.661 → 12.028 mm,
8 步全单调, 净位移 `[0.79, 0.86, 1.79] mm` 与 `Tg−T = [+2.3, +2.5, +5.3]` 同号, `det(R)=1.000000000`。

## 4. 双通道 provider 接线

```python
# 几何: state7 → ξ∈se(3) + v∈TS² + 接触/性能流形诊断
from lerobot.manifold.hjepa_manifold_provider import HJEPAManifoldProvider
mr = HJEPAManifoldProvider(state_fn=_state7, mode="weak")
ok, why = mr.start()
eng.set_hjepa_mr_provider(mr, note="...")

# 语义: state7 → z1/z2/z3 三层潜 (必须是返回 dict 的那个类)
from lerobot.manifold.hjepa_state import HJEPAStateProvider
sem = HJEPAStateProvider(root=REPO, state_fn=_state7, frame_path=fp_or_empty, every=1)
ok, why = sem.start()
eng.set_hjepa_provider(sem, note="...")

# 每拍读 (se3 分支自己维护 p, 不会自动触发 step 内的 poll)
rec_sem = eng._hjepa_read()
rec_geo = eng._hjepa_mr_read()
```

实测同一拍两通道都有值:
```
几何  ok=True  ξ=[-0.1278, 0.0407, -0.1035, 0.0175, 0.0067, 0.0578]
      v_n=[0.1714, 0.0746, -0.0532]  n_pred=[0.1704, 0.0742, 0.9826]  d_se3=2.7685  d_normal=0.187
语义  ok=True  z_dim=640  ‖z1‖=55.52 ‖z2‖=31.39 ‖z3‖=11.30  energy=[-8.633,-0.709,-0.324]
```

`n_pred` 应接近装配面法线 (如 `+z`); 若接近随机值说明 state7 源不对。
`w_phi` 默认 0 = 只观测不进 Φ, 要动动作必须另过闸。

### state7 口径
`[x, y, z (m), rx, ry, rz (rad), grip]`, 与 `hjepa_manifold_provider._rpy_to_T` 的 `Rz@Ry@Rx` 互逆。
真机位姿给四元数 ⇒ 用 `se3_chain.R_to_rpy` 反解 (ZYX, 万向锁单分支)。

**分量来源必须分开取、分开标源** —— 43D obs 里没有姿态:
```
obs43 布局: [0:3]手位置(m) [3]夹爪 [4:7]光模块位置 [7:11]光模块四元数
            [11:18]pad×7 [18:36]上一帧18D [36:39]孔位 [39:43]触觉
```
所以 `state7` 的位置/夹爪取 `in1` 的 `obs[0:3]` / `obs[3]`, **姿态只能取 `tcp_out` 真值**。
输出里逐分量记来源 (`{"pos":"画布 in1 43D[0:3]","rot":"TCP 真值 rpy","grip":"画布 in1 43D[3]"}`),
否则事后无法判断某个不收敛是位姿源错还是语义源错。缺 `in1` 时整条退回 TCP 并标 `"pos":"TCP 真值"`。

## 5. 判据要选在物理层, 不要在参数层

验 `R_to_rpy` 时第一版判据是「欧拉角数值相等」: 200 组里 88 组不一致。
但这 88 组全是 `ry` 超出 ±π/2 后的**等价角**, 不是错误 —— 判据本身错了。

| 判据 | 结果 |
|---|---|
| 欧拉角数值差 <1e-9 | 247/500 不一致 ← 等价角, 误判 |
| **旋转矩阵往返** `‖R1 − R(rpy(R1))‖` | **0/500, worst 1e-14** ✅ |

同一形状的坑: 未训练网络上的 `d_se3` 单调性 (§4)、用 `p.hole_pos` 而非原点算欧氏对照。
写判据前问一句「这个量是有多解/多参数化的吗」。

## 6. 权重路径解析: 回退到 hub 名 = 离线静默失败

本地快照只在一个缓存根里时, 硬编码单根会把 `DEFAULT_MODEL` 解析成裸 hub id
(`Qwen/Qwen2.5-VL-3B-Instruct`), 离线模式下加载失败, 而节点只是持续输出空值 ——
从外面看像「模型没训好」而不是「路径没命中」。

定式: 按序探测多根 (`hf_cache` → `hf_home` → `~/.cache/huggingface`), 只认含 `config.json` 的快照;
解析结果必须落在绝对路径上, 落在裸 hub id 就当启动错误报出来。

## 7. 🔴 `eng.load(ck)` 会把流形类型改回 npz 里存的那个

`ManifoldEngine(manifold_type="se3")` 创建后三处都正确 (`manifold_type` / `projector.type` /
`navigator.type` 全是 `se3`, `project` 出 12 维), 但紧接着 `eng.load("models/manifold_engine.npz")`
之后 **三者全部变回 `su2`** —— npz 里存了 `manifold_type="su2"`, load 拿它覆盖了构造参数。
症状链: `project` 从 12 维掉到 4 维 → `navigator` 走 sphere 分支的
`unit(p*cos(a)+u*sin(a))` → `ValueError: operands could not be broadcast together with shapes (4,) (6,)`,
栈顶落在引擎里, 看着像引擎 bug。

定式: **SE(3) 模式不加载 su2 标定**, 并在 `calib_note` 里写明理由;
或 load 后立刻断言 `eng.manifold_type == 想要的值` 并重设 projector/navigator。
验收一行:
```python
print(e.manifold_type, e.projector.type, e.navigator.type)   # 三处必须一致且等于目标类型
```

## 8. 势场度量 w_m 的自动标定 (别用硬编码比例)

`w_m=[1000,1000,1000,1,1,1]` 这种硬编码等价于 `平移:旋转 = 1000:1` (因为 m↔rad 差三个量级),
实测结果是**旋转几乎不参与收敛**, 且 Φ 被 1000 倍权重撑成虚高值 (42594.75)。

真机数据就能标定, 零新增动作:
```python
dP = ‖diff(points_p)‖         # 215 点真值表逐段平移 (m)
dR = 2·arccos|⟨q_i, q_i+1⟩|   # 逐段转角 (rad)
t_s, r_s = median(dP), median(dR)
w_m = concat([1/t_s]*3, [1/r_s]*3); w_m /= w_m.min()   # 归一化到最小分量=1
```
产物写 `zmax_data/calib/se3_metric_calib.json` (带 `t_scale_m` / `r_scale_rad` / `method`),
引擎每次热读, 读不到才退回硬编码并在 `metric.src` 里写明"无标定文件"。

实测 (215 点 / 214 段): `t_s=29.284mm`, `r_s=2.532°` ⇒ `w_m=[1.509,1.509,1.509,1,1,1]`,
即 `平移:旋转 = 1.5:1`; Φ 从 42594.75 降到 0.180569。
判据: 标定后 `metric.src` 必须带出 `t=/r=/比例`, 且 Φ 量级与"典型步长"同阶 ——
Φ 上万而步长只有几十 mm 就说明权重还在被量纲放大。