# SE(3) 分支接进引擎: 接线骨架 + 验收数字

主 SKILL.md 给规则, 本文件给可直接抄的骨架与实测基线。所有数字都来自真机 TCP 位姿 + `tools/web/real_traj_joints.json` 215 点真值表。

## 1. se3 分支的骨架 (`ss_mani_eng` 实现层)
```python
from lerobot.manifold.se3_chain import (read_pose_truth, se3_log, se3_exp,
                                        T_from_rot_t, quat_to_R, potential, R_to_rpy)

pt = read_pose_truth(_REPO_ROOT          # 真机 TCP 真值; None ⇒ 不出数, 不编
                     )
T  = pt.T                                   # 4x4
p12 = np.concatenate([T[:3, :3].ravel(), T[:3, 3]])

# 🔴 绕开 encoder: eng.project() 会先 encode 到 16 维潜空间, 位姿被洗成 I+0
_p, _resid, _meta = eng.projector.project(p12)      # SVD 正交化 + det 修正
assert _resid < 1e-12 and np.allclose(_p[9:12], p12[9:12])

Tg = T_from_rot_t(quat_to_R(frames[i]['q']), np.asarray(frames[i]['p'], float))
xi = se3_log(np.linalg.inv(T) @ Tg)          # 当前→目标 (体坐标), 配 T·exp(ξ·dt)
phi, grad_w = potential(T, Tg, w=np.array([1000]*3 + [1]*3))
p_next = eng.navigator.step(_p, np.concatenate([xi[3:], xi[:3]]), dt=0.01)  # 重排成 [φ;ρ]
```

验收 (缺一不算通):
- `residual` ≤1e-12, `drift`=0, `det(R)`=1.0, `p[9:12]` 与输入 t 逐位相同
- 连续 8 步 `‖t − t_goal‖` **单调下降**: 实测 18.131→17.224→16.363→15.545→14.768→14.029→13.328→12.661→12.028 mm
- 净位移方向与 `t_goal − t` 同号: 实测 `[0.792, 0.858, 1.790]` mm vs 期望 `(+2.3, +2.5, +5.3)`
- **se3 模式不许 `eng.load(models/manifold_engine.npz)`**: 该 npz 存着 `manifold_type=su2`, load 会重建
  projector/navigator 把引擎改回 S³ (project 12→4 维, 螺旋变 sphere ⇒ `ValueError: (4,) (6,)`)。
  跳过 load, 并把"不加载 su2 标定"写进 `calib_note`。
- **算完必须真交出去**: `se3_out` 只写 `_SS_STATE` 不够 —— 节点 `_ret()` 是白名单组装, 新块要显式并进
  返回, 否则画布五个端口拿到的还是旧的 su2 块(日志全绿、端口看不见)。

## 2. 语义 (L5) 引导引擎: 确定性映射, 不产动作
上游 `ar_l5_understand.py::_publish_scene_vec` 已把检测框转成 `vec=[dx,-dy,0]·conf` (相机系)。
`manifold/l5_guide.py` 把它翻成引擎能吃的东西:

```
阶段 (接近/对位/下降/抓取/抬起/转移/插入/完成)
    → 215 点表该区间出口点 = T_goal
    → 实测: 接近 idx26 / 抓取 idx107 / 插入 idx187 / 完成 idx214
    → 跨阶段目标差 755.5mm (接近↔插入) ⇒ 语义真的换目标, 不是挂常数
conf 0.40~1.00 → k_l5 0.5~1.0 (势场 ×(1+k)); conf<0.40 ⇒ k=0, 退回默认目标并标 traj_default
```

- 阶段区间是**均分假设** (`range_src="均分假设(未标定)"`) —— 215 点表只有 p/q/关节, 没有 stage 列; 要精确得补 stage 列或按 z 高度+夹爪开合反推。
- 取语义的优先级: 显式传参 > `port:in5` (ss_moe 阶段先验, 八阶段 one-hot) > `port:in3` (sscalib, 载荷含 stage/speed/contact_p) > `port:in4` (sslat) > `port:in1` (VLM 语义 dict) > 文件。
- 🔴 **实测 `ss_moe` 三个出口全 None**: 只认 in5 会永远返回"无阶段语义"。真正能给 stage 的是
  `sscalib.out2` 与 `sslat.out1`(两者载荷同形, 都含 stage/speed/contact_p) —— 所以 in3/in4 必须排在 in1 前面。
- **纯潜向量不许当语义**: in1 只有 16/640 维 z 时 `_parse_port` 返回 `{}` 并跳过, 不 argmax 猜 stage。
- `fresh=False` 的总线包装直接拒绝, 不拿旧值冒充新判读。

## 3. 双通道 provider (语义/几何解耦)
| 通道 | 类 | 注意 |
|---|---|---|
| 几何 | `HJEPAManifoldProvider(state_fn=, mode="weak")` | `state_fn()` → state7; 输出 ξ(6)/v_n(3)/n_pred(3)/d_se3/d_normal/eta; 无 torch 时退纯几何诊断 |
| 语义 | `HJEPAStateProvider(root, state_fn=, frame_path=)` | 返回 dict{z1,z2,z3,energy} 与 `_hjepa_read` 对齐 |

- 🔴 **别用 `HJEPALiveProvider`**: 它 `__call__` 返回裸 ndarray, 引擎 `_hjepa_read` 的 `if not out:` 会抛 `truth value of an array is ambiguous`。
- state7 = `[x,y,z(m), rx,ry,rz(rad), grip]`。分量来源分级 (各自真源, 不混报):
  `pos ← 画布 in1 的 obs43[0:3]`, `grip ← obs43[3]`, `rot ← TCP 真值 rpy` (43D 里没有姿态), 都没就 0 并写进 `src`。
- provider 进程内缓存, `state_fn` 每拍读模块级 `_CUR_CTX` ⇒ 画布 in1 被**真消费**而不是注册一次就冻住。
- 实测: 语义 `z_dim=640` (256+256+128), `‖z1‖=55.5/‖z2‖=31.4/‖z3‖=11.3`; 几何 `ξ=[-0.128,0.041,-0.104,0.018,0.007,0.058]`, `n_pred=[0.170,0.074,0.983]` (装配面朝 +z, 合理)。
- 图像支路近似常数 ⇒ 无帧时用零图并在描述里写"图像=零输入", 不假装有视觉。
- `w_phi` 默认 0 = 只观测不进 Φ; 会改动作的档位默认关。

## 4. 标定 (in3 ← sscalib) 映射到势场
真源 `calibration_layer.py`: `ATTRACTION_CALIB{Kp=1.2, u_clip=±0.5, safety_limit=0.6}` · `MANIFOLD_CALIB{M}`。
```
Kp            → 势场尺度 ×clamp(Kp/1.2, 0.2, 3.0)      (限幅防标定异常拉爆)
safety_limit  → 单步平移钳制: ρ 超过就按比例缩         (实测 0.30m 被 0.15m 边界钳成 0.15)
M (等效惯量)  → 步长尺度 1/clamp(M, 0.3, 3.0)          (a=F/M 的直觉)
```
解析器要能吃三种形态: 扁平 dict / 嵌套 `{attr:{...}, manifold:{...}}` / 标量(=M); 解析不出返回 `{}` 并标"标定未提供", 不拿默认值冒充标定。

## 5. 端口消费表 (回答"连接一致吗"的唯一依据)
把每条入边的归属打进输出, 而不是只在文档里写:
```python
rec["ports"] = {
  "in1": {"used": True,  "what": "43D[0:3]→state7 位置, [3]→夹爪; stage→L5Guide", "src": {...}},
  "in2": {"used": True,  "what": "SU(2) q vs T 的 R → 姿态一致性夹角 (>5° 记 log, 不驱动 p)"},
  "in3": {"used": True,  "what": "Kp→势场尺度, safety_limit→单步钳制"},
  "in4": {"used": True,  "what": "sslat.out1 (原接 out2 是空口) → stage 供 L5Guide; contact_p 作接触诊断, 不改 p"},
  "in5": {"used": True,  "what": "阶段先验 → 215 点区间 → T_goal + k_l5"},
  "in6": {"used": True,  "what": "M 等效惯量 → 步长尺度"},
}
```
`used:false` 必须带 `why`, 且 why 要说明"是模式差异还是缺标定", 不许留空。
