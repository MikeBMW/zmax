# YOLO 输出 → 统一状态空间 SU(2): 入口图与验证探针

回答「现在的 YOLO 输出怎么进统一状态空间」时, 先按下面四条对号。四条性质不同, 混着说就会把
「环境真值」说成「检测结果」, 或把「静默单位元」说成「已映射」。

## 入口图 (逐行可核)

| # | 入口 | 代码 | 吃什么 | 群元素怎么来 |
|---|---|---|---|---|
| ① | 画布 L2 块 | `su2.py:272 encode_obs43` ← `encode_layer("L2")` ← `SU2UnifiedState.push` ← `node_ss_su2`(library.py:3038) | 43D obs | `e = 光模块头([4:7] + z 0.030) − 孔位([36:39])` (su2.py:256) → `ω = π·tanh(2‖e‖)·ê` → `exp(−iωσ/2)` |
| ② | 真机/AR 链 | `tools/ss_station_engine.py:189 obs43` → `tick_plan` → `ManifoldEngine.project` (manifold_engine.py:999 → 309-318) | 43D **工位**张量 (另一套口径) | 编码器得潜向量 `z` → `z[:3]` → `bounded_rotvec(gain=2)` → `from_rotvec` |
| ③ | 节点级 | `su2.py:508 encode_nodes` + `NODE_SPECS` | 每个节点 io_trace 的真实 out | `node_vector` 按语义规则取 3 维 → 有界映射 |
| ④ | 场景态 | `compose_scene` (su2.py:343) | ①/③ 的群元素 | `U = U_L2 ⊗ U_L3 ⊗ U_L4 ⊗ U_L5` (不可交换) |

### 两套 43D 不能互相套用
- 画布/metaworld 口 (①②里的 canvas 支): `[0:3] hand · [3] grip · [4:7] peg · [7:11] quat ·
  [18:21] prev_hand · [22:25] prev_peg · [36:39] hole` + `[39:43]` 触觉 4D。
- 工位口 (`ss_station_engine.obs43`): `[0:3] TCP · [3] 夹爪标量 · [4:7] 光模块 3D · [7:10] 相对位移 ·
  [10:12] 两指开度 · [12:18] 关节角 · [18:24] 关节速 · [24:33] TCP 旋转 · [33:36] 环境目标 · [36:39] 孔口 ·
  [39:43] 恒 0 触觉(本场景无触觉传感器, 明标不冒充)`。
  拿工位口的槽位去读 `su2.obs43_geometry` 会算出完全不同的 e —— 报数前先确认是哪一份。

### YOLO 实际落在哪一格
- **YOLO 节点** `node_ss_yolo`(library.py:3809): `detect_3d` + 同帧 2D conf → 写
  `zmax_data/ss_live/vision_points.json`(`units=mm`, `points → 光模块·当前 / hole / hand`), 这是给
  plan / `📐 2D→3D 解算`(library.py:2042, 读 `det2d` 框自监督解算) 的**唯一交界**。
- 真机源 (`ZMAX_L2_SRC=real`) 只出 `vision_points`, **不产 obs39** —— 所以真机链的 43D 由工位构建器给, 不是对齐器给。
- 仿真源才走 `aligner.align()` → `_YOLO_CACHE["aligned39"]`, 而它**无消费者**(全仓库 grep 只有写入点) ⇒
  画布 43D/L2 块吃的仍是 `env._get_obs()`。

## 已断的那一格: 节点级映射 (实测)

`NODE_SPECS["🎯 YOLO 目标检测"] = ("diff", "peg 检测框", "hole 检测框")` 是旧 io_trace 写死伪装的标签;
节点改成发 vision_points 契约后标签没了 ⇒ `_pick` 取空 → `SU2Element.identity()`, 且**不报错**。
`encode_nodes(frame, detail={})` 会把节点名塞进 `detail["no_numeric_output"]` —— 这是唯一可见线索。

复现/判据 (只用 numpy, 不加载 YOLO):
```bash
cd ~/zmax && python3 -c "
import json,sys
sys.path.insert(0,'src/lerobot/policies/left_right/state_space')
import su2
d=json.load(open('zmax_data/ss_live/vision_points.json'))
det={}
nodes=su2.encode_nodes({'🎯 YOLO 目标检测':{'out':[('out1',d)]}}, detail=det)
for k,u in nodes.items(): print(k, u.describe())
print('no_numeric_output:', det.get('no_numeric_output'))
"
# θ≠0 ⇒ 映射在; θ=0 且该节点出现在 no_numeric_output ⇒ 标签口径对不上
```
实测: `θ=0.0000 rad · |w|=1.0000 · no_numeric_output=['🎯 YOLO 目标检测']`。

## 接通的两条路 (未落役, 改前先说清"改的是哪一格")
1. **节点级**: 让 spec 读现契约 —— `points.光模块·当前.pos_mm` 与 `points.hole.pos_mm` 做差 (注意 mm vs m),
   或直接给该节点一个专用取值函数, 别靠 `NODE_SPECS` 的通用 `_pick`。改完必须重跑上面探针, 断言 θ≠0 且
   `no_numeric_output` 不含该节点。
2. **L2 块吃检测**: 在 `_ss_ensure_obs43` 里优先 `_YOLO_CACHE["aligned39"]`(新鲜度门槛同 SAM3 掩膜的做法),
   取不到才回落 env 真值并**在日志里写明回落**。不做新鲜度门 = 拿上一帧检测套这一帧 = 假数据。

## 汇报口径
- 「检测进了状态空间么」必须分两答: **控制/规划路径**(vision_points → plan/SK 目标) 与 **43D 观测数组**
  (画布 sim = env 真值; 工位链 = 检测坐标) —— 后者才是 SU(2) L2 块的输入。
- 说群元素前报清是哪一格 (①几何误差 / ②潜空间投影 / ③节点语义向量), 三者的 θ 语义完全不同。
- 节点级没接上就直说"映射每帧落单位元", 不要用「已覆盖 17 节点」的清单当证据。
