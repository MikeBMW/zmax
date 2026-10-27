# 场景段表 → 执行器 plan 序列（切分、补空走、节拍口径）

适用：一份「整盘/整流程」场景段表（几百段、多件、多批）要交给只有一个
「每次 1..8 段」载荷闸的执行器（550C 的 `plan_exec_550c.py` 或等价物）时。

工具：`tools/scene_550_planify.py`；产物目录 `zmax_data/runtime/traj/plan_550c/`。

## 1. 两种文件长什么样

**场景段表**（发布端输入，实测 `zmax_data/runtime/traj/sim_insert.json`）

```json
{"ok": true, "cycles": 8, "n_segs": 392, "total_t": 159.43,
 "ok_count": 12, "ng_count": 2, "uph_target": 300,
 "plan": [{"k": 1, "seq": 1, "kind": "move", "label": "→ 槽1 上方",
           "a": [490,499,240], "b": [490,499,218], "t": 0.3,
           "carry_from": false, "carry_to": false, "mod": 1}]}
```

- `k` = 批/循环号，`seq` = 段序号，`a`/`b` = 段起止（mm，base 世界系），`t` = 该段名义耗时。
- **件数 = `ok_count + ng_count`**（不是 `cycles`）：实测 12+2 = 14 件，`cycles=8` 是批次数，拿它算节拍会把 UPH 算高。

**执行器载荷**（消费端，闸门按这些字段校验）

```json
{"plan_id": "scene-000", "n_seg": 8, "speed_mm_s": 10.0,
 "auth_remaining_s": 900, "start_mm": [490,499,240],
 "abs_mm": [[490,499,218], ...], "dirs": ["move", "down", "grip", ...]}
```

闸门（任一不过即拒，且拒绝原因要落台账）：
`n_seg` 1..8 · `abs_mm` 每点 3 个数 · 授权剩余秒数 > 0 · 同 `plan_id` 只执行一次（幂等窗口）·
当前 TCP 与 `start_mm` ≤20mm · 每段到位 `|Δ|≤2mm` 且 `max|jointVel|<0.05`。

## 2. 必做的一步：补换槽空走

场景段表换槽时的写法是「下一段 `a` = 中转位」，不是上一段的 `b`：

```
上一段末 [814,228,340]   →  本段起 [490,499,240]   差 434mm
上一段末 [814,108,340]   →  本段起 [490,499,240]   差 518mm
```

这 27 处（占 392 段的 7%）如果照 `abs_mm` 直发，就是从料盘/槽位直接斜穿到中转位的直线——
穿过工装、也不经过任何安全高。补齐算法：

```
for s in segs:
    if out: gap = dist(s.a, out[-1].b)
    if gap > 0.5:
        insert {kind:"air", a: out[-1].b, b: s.a, t: gap / bridge_speed, bridge: true, gap_mm: gap}
    append s
```

- bridge 段标 `bridge=true` + `gap_mm`，便于事后审计「哪些段是补的」。
- 补齐后判据：段内 `a[i]==b[i-1]` 与 plan 间「上末点==下起点」都 ≤0.5mm。
- 只补平移不补抬升时，**要确认中转位的 z 本身就是安全高**（实测中转位 z=240，段内高位段 z 到 340），
  否则还得在 bridge 前插一段「抬到安全高」。

## 3. 节拍口径：三个数必须分开报

| 口径 | 时长 | UPH（14 件） | 含义 |
|---|---|---|---|
| 场景自报 `total_t` | 159.43s | 316 | **不含空走**，页面显示的那个数 |
| 补空走 @100mm/s | 308.31s | 163 | 空走 14,887mm 的保守速度 |
| 补空走 @300mm/s | 209.06s | 241 | 常规快走 |
| 补空走 @1000mm/s（运动安全上限） | 174.32s | 289 | 物理天花板，仍 < 300 |

结论模板：

- 报 UPH 必须同时写「空走速度 + 是否补齐 + 件数」。只写一个数字会被当成已验证。
- **空走顶到安全上限仍达不到目标 ⇒ 结论是靠并行工位**（另一条臂承担上下料/周转，把空走藏进对方节拍里），
  不是继续调速度或缩段。这句话要连对照表一起给。
- 同一条律也约束了「一进多出」类指标：**先算每件的预算秒数**（300UPH ⇒ 12s/件），再把感知+决策+下发开销逐项扣掉。

## 4. 下发次数也是节拍成本

419 段 / 每 plan 8 段 = 53 个 plan = 53 次下发，每次都要过授权 + 幂等 + 逐段真值对账。
按 200ms/次往返 ≈ **10.6s**，而 12s/件 的预算里还要装动作本身 ⇒ 必然超。
两条正路：① 让执行臂那条链只做插拔（段数极少），上下料/周转交给另一条臂；
② 放宽执行器的分段上限（这是安全闸，要人点头）。

## 5. 用法与判据

```bash
./gui-venv311/bin/python tools/scene_550_planify.py                      # 生成 + 全项判据
./gui-venv311/bin/python tools/scene_550_planify.py --no-bridge          # 对照: 段内连续性必 ❌
./gui-venv311/bin/python tools/scene_550_planify.py --bridge-speed 300   # 换速度看节拍
./gui-venv311/bin/python tools/scene_550_planify.py --json               # 只出 index.json(可管道)
```

退出码 = 有判据不过则非 0，可直接当 CI/交付闸。`index.json` 里 `gates[]` 逐项带 `ok/name/detail`，
`uph_scene_only` 与 `uph_theoretical` 并列给出两个口径，避免引用时只拿一个。

本工具**只做离线校验**：不下发、不发布、零运动。真实下发仍必须经执行器自己的授权+闸门+真值对账。
