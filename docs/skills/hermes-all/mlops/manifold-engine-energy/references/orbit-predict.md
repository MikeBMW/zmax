# 对称轨道预测（预测 = 沿对称群轨道做等距离推演）

命题：可预测的根是**对称性**。群 G 不变 ⇒ x 与 g·x 在同一轨道、物理等价 ⇒ 沿轨道「等距走一步」就是把已知平移成未知。
「等距」= **群参数上的等长步**，不是空间距离。落到流形引擎（p∈S³）：轨道 = 大圆，等距步 = 恒定弧长的测地线步。

## 实现（`src/lerobot/manifold/orbit_predict.py`）

```
U_i     = log_{p_i}(p_{i+1})          # 一步切向量，挂在 p_i
V_host  = PT_{p_{n-1}→p_n}(U_{n-1})   # 把上一步速度沿轨道搬到当前点
p̂_{n+k} = 反复 exp / PT 推进 k 步      # k=1 精确；k>1 逐步搬移
```

- 只用 `manifold/sphere.py` 原语（`log_map`/`exp_map`/`parallel_transport`/`distance`），不写第二套 exp/log。
- `OrbitPredictor.observe(p, phi=Φ)` → `{pred{h}, valid, break_reason, drift, accel, bend, phi_drift, err_rad, hit_rate}`。
- 引擎侧 `step()` 每拍喂一拍 → `rec["orbit"]`；常驻回路平铺成 `orbit_valid/orbit_speed_rad/orbit_err_rad/orbit_break/orbit_pred_1`。
- 关闭：`ZMAX_ORBIT_PREDICT=0`（必须逐位回到旧行为，见下「零回归」）。

## 四条破缺判据（任一超阈 → valid=False，只报原因，不外推）

| 量 | 含义 | 默认阈值 |
|---|---|---|
| `drift` = std(‖U‖)/mean(‖U‖) | 弧长不再等距 ⇒ 外力矩/势扭曲轨道 | 1.0 |
| `accel` = |‖U_last‖−‖U_prev‖|/mean | 这一步速度突变（接触/指令/碰撞） | 0.6 |
| `bend` = 上一步残差/步长 | 轨道假设的实际违反量（滞后一拍，如实如此） | 0.5 |
| `phi_drift` = |ΔΦ|/mean(‖U‖) | 势沿轨道变化 ⇒ 该方向对称被势破坏 | 0.5 |

阈值不是拍的：在 400 帧真 episode 上扫「覆盖×精度」选点（覆盖 71%、valid 拍误差 = 保持基线的 17%）。

## 实测数字（可复现，`tools/verify_orbit_prediction.py`，12/12 通过）

- 理想轨道：等距 CV `2.5e-14`；一步外推误差 `2.0e-8` rad = **exp∘log 数值地板**（A4 同量级）⇒ 公式本身精确。
- 真 episode（400 帧真机 obs43 → project → p）：轨道 `1.159e-3` vs 保持 `2.113e-3` rad ⇒ **+45.1%**，胜率 82.9%。
- 常驻 live 700 拍：整体 +78.7%；**valid 拍 +91.5%**；invalid 拍只 +9.7%（⇒ 门控抓的是真失效区），invalid/valid 误差比 10.0x。
- 引擎闭环：多视界误差 k=1 `5e-5` → k=10 `2.4e-3` rad（势场在变，推得越远越差）。

## 坑（都实测踩过）

- **切空间必须统一**：`u_last∈T_{p_{n-1}}`，`V_host∈T_{p_n}`。直接比大小/夹角会凭空多出一个步长（实测 bend 假报 1.0、外推偏 3.75e-5 rad）。先 `parallel_transport` 再比。
- **`<3 点就别给预测`**：没有速度就没有轨道；此时也别把预测记进误差账（否则第一条误差 = 一整步，把 RMSE 拉爆）。
- **静止阈值用遥测抖动地板**：`STATIC_EPS=1e-6` rad/步（真机实测抖动 4e-7/帧）；`1e-9` 会把「已停」判成在动，收敛段永远不 static。
- **缓慢减速不算破缺**：每拍相对变化小 ⇒ drift/accel 都不超阈。破缺判的是突变/离散/残差/势。要判「推不动了」看 `static`，不是看 `valid`。
- **弦线外推 ≈ 轨道推演**（小步长下一阶等同，实测两者误差逐位相同）；要对比就跟「保持不动」比，那才是没有预测的基线。

## 零回归闸（上常驻前必做）

同一 60 拍序列，`ZMAX_ORBIT_PREDICT=1` vs `=0`：动作 `max|Δ|=0`、p `max|Δ|=0`、`array_equal=True`；引擎 `--selftest` 全部通过。
观测量可以随时加，但**不许改 p、不许改动作** —— 这是能进常驻的唯一理由。

## 三个「指导运行」接点 (实测结论，别重复踩)

| 接点 | 做法 | 实测 | 结论 |
|---|---|---|---|
| 时延补偿 | valid 时用 p̂ 解码动作 | 动作误差 0.002129→0.000759 (+64.4%) | ✅ 进常驻 `ZMAX_ORBIT_LOOKAHEAD=1` |
| 编排门控 | 破缺才重规划 | 节拍5 省 3%; 节拍20 多跑190% (破缺率29%) | ❌ 不默认开：买的是时机不是钱 |
| L4 门控 | valid 时跳 INTACT 前向 | 影子 |Δz| valid/break=0.36 | 🟡 具备前提，未改行为 |

- 直接改动作的「向轨道增量靠拢」是**负结果**：jerk 0.26e-3→0.34/0.43/0.70e-3，Φ 无改善 ⇒ 默认关。
- 对称性不含目标：它能约束/延续，不能决定去哪。用错位置就会把速度噪声注入执行端。

## 部署到边缘机 + 接入自主进化

- 边缘机不需要整套 lerobot：只拷 `manifold/{__init__,sphere,orbit_predict,manifold_engine}.py` + `verify_orbit_prediction.py` + `models/manifold_engine.npz` + `ss_traj_last.json`，用它的 train_venv 直接跑判据（实测 15/15）。
- 进化是**一维退化**：目标只有 mAP50 ⇒ 时间平移对称 = 等改进量推演；推演破缺或 pred<best−margin ⇒ `escalate`（强制大变异+加算力），否则 `keep`。
- 换脚本必须**等 `phase=cooldown`** 再重启，别打断正在跑的代：轮询 `/health` 的 phase + setsid 后台脚本。

## 复现

```
cd ~/zmax
./gui-venv311/bin/python src/lerobot/manifold/orbit_predict.py --selftest
./gui-venv311/bin/python tools/verify_orbit_prediction.py
systemctl restart zmax-ss-engine-loop && sleep 30
python3 -c "import json;d=json.load(open('zmax_data/ss_live/engine_latest.json'));print(d['orbit_valid'],d['orbit_pred_1'])"
```
