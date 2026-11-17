# 点位/配置值的覆盖识别与还原

## 1. 常见形态: 两套同名数据

| 库 | 谁写 |
|---|---|
| 传授/示教点库(`…/taught_points.json` 类) | 教点工具、脚本 |
| 页面「空间点」库(`…/space_points.json` 类) | 界面「记录/清除」按钮 |

解析时**同名以某一套为准**(常见: 传授库优先); **另一套缺失不报错** ⇒ 静默回落到
"演示学习轨迹点"(逐次运动自动攒的点) ⇒ 落点变成"某个历史时刻恰好在那里的位姿"。
两条都要看, 别只 grep 一个文件就下结论。

## 2. 症状 → 判据

- 现场说"这个点不是我写的点" ⇒ 查该条目的 `recorded_at` 与值:
  - `recorded_at` 很近, 且值与**当时**的真值文件逐位相同 ⇒ **被覆盖式写入**过(写的是当时状态, 不是人设的值)。
  - 名字在库里但落点等于"当时设备在哪" ⇒ 首选库被清空, 走了回落路径。
- 别用"看着差不多"当判据; **数字对不上就是被换过**, 拿数字说话。

## 3. 审计与备份(还原靠它们)

- `…/<store>_removed.jsonl` 类审计流水 —— 每次清除追加一行:
  `{ts, ts_str, name, removed:{pos/quat/值, desc, recorded_at, source, n_samples, spread_*}, by, backup}`
- `/tmp/<store>.cleared_<name>_<mmdd_HHMMSS>.json` —— 清除前的整库快照。
- 库自身的历史 `*.bak*`(可能更早, 用来交叉验证)。

## 4. 每个名字取"覆盖前最后一次"的原件(可跑)

```python
import json, os
AUD = os.path.expanduser("~/<store>_removed.jsonl")
rows = [json.loads(l) for l in open(AUD, encoding="utf-8") if l.strip()]
best = {}
for r in rows:
    nm, rm = r.get("name"), (r.get("removed") or {})
    if not nm or not rm.get("pos"):
        continue
    if nm not in best or str(rm.get("recorded_at") or "") > str(best[nm].get("recorded_at") or ""):
        best[nm] = rm
for k, v in sorted(best.items()):
    print("%-8s 值=%s 原件记录于 %s" % (k, [round(float(x), 4) for x in v["pos"]], v.get("recorded_at")))
```

写回流程: **先把将要写回的值列给现场确认**(不要自己挑一套他没要的) → 备份现库 → 写回 → 回读校验
→ 发一次 **dry(不下发)** 指令, 核对目标值与写回值逐位一致。

## 5. 纪律

- **现场正在手改这份数据(清+重记)时不要插手** —— 只报证据 + 给"可一键还原"选项, 由他选。
- 新增"记录/清除"入口时照抄**审计 + 备份两件套**, 否则覆盖不可追溯。
- 回报格式: 原值 / 现值 / 覆盖时间 / 原件在哪个文件 / 能否一键还原 —— 一行一条。

## 6. 写台账: 三件套 + 派生配置重建 + 端口径校验(改任何一个点位都要走)

真源与派生严格分开, 只改真源:

| 层 | 文件 | 谁写 |
|---|---|---|
| 真源 | `reports/aoi_points/<点名>.json` | 本节流程 / `aoi_teach_point.py` |
| 留痕 | `reports/aoi_points/<点名>.history.jsonl` | 同上, append-only |
| 派生 | `config/tasks/tasks.json`、`config/ss_task_binding.json` 的 `pt.*` / `pthist.*` | **只由 `tools/task_build.py` 从台账生成** |

顺序固定:

1. `cp <点名>.json <点名>.json.bak_$(date +%Y%m%d_%H%M%S)` —— 备份先做。
2. 写 `<点名>.json`(pos / quat / abc / 关节角), 原子替换(`.tmp` + `os.replace`)。
3. 追加 history.jsonl 一行, **schema 必须对**:
   - `old` 要是 **dict 且含 `pos`**(`{"pos": [...], ...}`)。写成 list 会让 `task_build.py` 抛
     `AttributeError: 'list' object has no attribute 'get'` 且 **rc=1**, 而派生配置**静默保持旧值**;
     这时校验只报"配置 ≠ 台账", 极容易被误读成"我的写入没落盘", 于是回头重写 json 白折腾一轮。
   - `new_pos` 必须是 3 元数值数组 —— 校验脚本与页面历史摘要都读它, 缺了摘要显示 `? → (新值)`。
4. `python3 tools/task_build.py`(rc 必须 0) → `python3 tools/verify_aoi_points_config.py`。
   验收 = 该点名三项全 ✅: 配置值 = 台账 pos · 配置带记录时间 · 更新次数 = jsonl 行数 + 最近 new 值一致。
   ⛔ **唯一允许的 FAIL 是「配置中心页起窗口」**(机器没装 PyQt5), 与本改无关; 其它任何 FAIL 都不算完成。
5. 回报: 点名 / 原值 → 新值 / 谁定的 / 派生配置回读值 / 备份在哪。

## 7. 「把 A 改成跟 B 一样」= 先分维度, 再决定要不要连姿态一起抄

- 三种口径别混: **只某轴**(x 对齐) / **整位姿**(pos + quat 全同) / **连同实测关节角**。
  同一现场会连着改口径(先"x 一样"再"位姿一样")⇒ 每次重读台账现状再改, 别把上一轮的 pos 当成已完成状态。
- 整位姿一律**连关节角一起抄 B 的实测值**(§8), 否则页面 pos 对了、真机走的是 IK 解出的另一组关节角。
- 🔴 **混合口径(位置取 B、姿态留 A 自己)只能解 IK**: 这种情形 B 的实测关节角**不能照抄**(它带的是 B 的姿态),
  必须按 `pos = B 的 pos` + `quat = A 自身` 解, 并报位置/姿态/各轴 Δ 三个数(实测位置 0.00mm · 姿态 0.00° ·
  各轴最大变 6.07°)。**判口径是否混合**只看两项: `pos` 与 B 逐位相同 **且** `quat` 与 A 原值逐位相同 ——
  两条同时成立才是混合, 只成立一条说明抄多了或抄少了。
- 改完主动说清后果: 两个点位同位姿后 **A 失去独立意义**; 若现场本意是两个不同工位, 要重录 B。
- 派生配置永远不手改: 手改的那一份下一次 `task_build` 就被覆盖 —— 这是"改了没生效"的头号来源。

## 8. 给点位定关节角: 实测 > URDF 数值 IK

- **优先复制实测关节角**: 回放轨迹帧的 `j_new_rad`、示教工具录下的 joints —— 那是真机走过/录过的位姿, 必达。
- IK 只在没有实测值时才用: scipy `least_squares`, 残差 = 位置 mm + 旋转向量×权重; 解完必须报
  **位置误差(mm) / 姿态误差(°) / 各轴 Δ(°)** 三个数, 任一超容差就不能说改好了。
- 🔴 **IK 多解**: 同一末位姿能解出大幅翻转的另一组解(实测同一点位解出 `j1` 差 55°、`j4` 差 133°),
  从当前姿态过去要大幅摆动、可能穿奇异区 ⇒ 报这种解时必须写明"这是 IK 解不是实测"。
- **FK 自检口径**(确认 URDF 与台账同一 tip/坐标系): 拿已有点位的 `joints_deg` 做 FK 与台账 `pos` 比;
  实测差 1.5~2.2mm、姿态 3.6° 属**既有标定偏差**(不是链路口径错), tip 是 **tool1 而非 tool0**。
- 欧拉口径: 台账 `abc = reversed(as_euler('ZYX'))` 即 `[e[2], e[1], e[0]]`, quat 是 **xyzw**;
  手写 ZYX 公式会 a/c 互换, 得出"欧拉与四元数不一致"的假结论。
