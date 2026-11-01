# AR 指令流契约 (`ar_cmd.json` / `ar_exec.json`)

供回答「AR 场景给机器人输出的是什么 / 发的是什么信号 / 走了几成是什么」这类问题时用。
先看本文再答，别现场翻字段。

## 0. 先把这条流的权限判清楚：它不驱动真机

判一条输出流是否下发真机，**去功能注册表读 `real_cmd` / `real_auth`，不要用"它写了坐标"推断**。
Z-MAX 的注册表把这个写死了：

```python
grep -n 'real_cmd\|真机零指令\|real_auth' tools/ar300_config.py \
    src/lerobot/engineering/nodes/plan_long_impl.py
# ar300_config.py  →  {"scene": "AR 仿真双臂", "real_cmd": False}
#                 →  「只写渲染指令 ar_cmd.json, 真机零指令」
# plan_long_impl  →  副作用注释: 「AR 渲染指令, 真机零指令」
```

消费方只有三个，全是"看"：`tcp_ar_server.py`(`GET /api/ar/cmd`) · `ar_mujoco_scene.py` · 备份脚本。
**没有任何一条进 `bridge` / `zmax-l2-daemon` / Orin 39061 / 珞石控制器。**

真机指令走的是另一条链，吃的是 L2 收口的 `u`（4 维速度+夹爪）：
```
L2 收口闸 → zmax-l2-daemon(4060) → 39071 → Orin 39061 → 珞石控制器
```

⇒ 报节拍时必须写成「**计划节拍**」，不能写「产线出了 N 件」。两件事在 KPI 上是分开的。

## 1. 两个写入口（有优先级，别只查一个）

| 写入方 | 文件 | 接口 | 优先级 |
|---|---|---|---|
| 执行器节点 `ssact`（画布 ssplan.out1 → ssact.in1）| `zmax_data/ss_live/ar_exec.json` | `GET /api/ar/exec` | **高** |
| `ss_plan_long` / `uph_tact`（`ZMAX_UPH_AR_PUB=1`）| `zmax_data/ss_live/ar_cmd.json` | `GET /api/ar/cmd` | 回落 |

页面 10Hz 轮询，`AR_CMD_FRESH_S = 3.0` 超时静默回落——**不报错**。要判它还在不在跟，
看顶部横幅驱动源与 `age_s`/`fresh`，别以为没动就是坏了。

## 2. 字段契约：只有三个数是动作

| 字段 | 含义 |
|---|---|
| `a` | 段起点，笛卡尔 mm |
| `b` | 段终点，笛卡尔 mm |
| `u` | 段内进度，**0~1 比例**（见 §3，曾长期是秒）|
| `kind` / `label` | 段类型 / 人话描述（`move` / `down` / `up` …）|
| `seq` / `mod` / `batch` | 第几段 / 第几件 / 第几批（轮次）|
| `mt_id` / `mt_name` / `mt_i` / `mt_n` | 元任务归属与进度 |
| `t_seg` / `t_left` / `elapsed_s` | 本段时长 / 本段剩余 / 整体已用（秒）|
| `vision.src_kind` | 视觉点来源，`sim` = 仿真算的，不是实拍 |

前端 `arCmdSolve()` 三步：`tm = a + (b−a)·u` → `ikTool1(tm/1000, q)` 逆解 6 关节角 → Three.js 摆臂。
**关节角不是下发来的，是浏览器每帧自己 IK 解的。**

## 3. 🔴 `u` 的单位坑：曾把「秒」当「几成」发出去

`plan_long_impl._pub_ar(o1, u, seg_t, el)` 的调用点是 `_pub_ar(o1, el - seg_t0, seg_t, el)`，
即传进去的是**本段已过秒数**；函数内只有 `min(1.0, max(0.0, u))` 砍边界，**没有除以 `seg_t`**。
段时长中位数 0.3s ⇒ 页面把 0.15 当 15% 画，实际已走 50%，**虚拟臂每段只走约 30% 就跳到下一段起点**，
看上去一顿一顿。

判别式（一条就够，不需要读代码）：**`u + t_left ≈ t_seg` ⇒ `u` 是秒；`u ≈ (t_seg − t_left)/t_seg` ⇒ `u` 是比例。**
实测对照：`u=0.0823, t_left=0.418, t_seg=0.5`（0.0823+0.418=0.5 ⇒ 秒）；修后 `u=0.7929`
与 `(0.3−0.062)/0.3=0.793` 误差 0.000。

修复形态（`t_in_seg / seg_t`，`seg_t` 为 0 时取 1.0）：
```python
_pub_ar(o1, el - seg_t0, seg_t, el)
# def _pub_ar(o1, u, seg_t, el):
#     u = (u / seg_t) if seg_t > 1e-9 else 1.0      # ← 这一步原本缺
#     ... "u": round(min(1.0, max(0.0, u)), 4)
```

🔴 **同一文件名/函数名的两份实现要互相对账**：`uph_tact_impl._pub_ar` 早已归一化，
`plan_long_impl._pub_ar` 没有 —— 两个都在写同一个 `ar_cmd.json`，只有当前生效的那个才暴露问题。
改/读任一份前先 `grep -rn '_pub_ar(' src/lerobot/engineering/nodes/` 两份一起看，否则会以为"代码是对的"。

改完这类循环服务重启一次 `zmax-ss-canvas-loop` 即生效，然后**回读 `u` 与 `(t_seg−t_left)/t_seg` 的差**才算验完。

## 4. 已知空槽 / 隐式约定（答问题时不要当成有值）

- **`q` / `q_l` 恒为 `null`**：payload 留了关节角槽位，但全仓库没有任何节点写它，`tcp_ar_server` 只透传。
  现在纯靠前端 IK。别在回答里把它说成"下发了关节角"。
- **指令里没有臂别字段**：臂别只能从 `mt_name` 前缀解析（`右臂 ·` / `左臂 ·` / `双手 ·`）。
  改动 mt_name 文案会让臂别解析静默失效——这是隐患，不是设计。
- **起停靠人点**：代码明确禁止页面自己 `plantStart()`，必须手动点「🏭 全流程 UPH」。

## 5. 怎么答这类问题（用户明确要求过「说人话」）

被问「发的是什么 / 走了几成是什么 / 给机器人输出的是什么」时：

1. **先一句人话结论**，再决定要不要给字段表。例：
   > 服务器每 0.1 秒告诉页面三个数：从哪走到哪、现在走了几成。就这三样。
2. **不要一上来甩 JSON / 字段表 / IK / 笛卡尔这些词**。用户为此打断过：
   「你到底发的是啥啊，说人话」。字段表放在他追问细节之后。
3. **该说的实话必须留**：不驱动真机、`q` 是 null、视觉是 `sim`。这些是结论的一部分，
   不是"技术细节可以省略"。省略了就是在暗示真机在动。
4. 讲进度这类量，**给一个可复算的等式**（`u + t_left = t_seg`）比给形容词有效。
