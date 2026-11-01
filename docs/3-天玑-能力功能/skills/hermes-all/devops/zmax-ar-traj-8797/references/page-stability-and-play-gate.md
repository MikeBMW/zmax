# live 3D 页面的稳定性与播放闸口 (ar3d 类页面通用)

适用: `tcp-ar.html` 这类"长驻一整天 + 每帧重绘 + 跟随外部执行信号"的页面。
用户抱怨的都不是功能缺失, 而是**画面自己在动**: "图像总是上下漂浮" / "左侧按钮上下跳" / "没点运行怎么就跑"。

## 1. 图像整体上下漂浮 = 每帧自动取景

症状: 双臂在动, 但**背景/坐标架/整幅图一起上下移动**, 像镜头在呼吸。

真因: `drawVR()` 开头 `if(VR.auto) vrFitBox();` —— `vrFitBox` 按**包围盒**重算 `VR.tgt`/`VR.dist`,
而包围盒里包含**会动的臂点云/URDF 点** ⇒ 臂一上一下, 相机目标点跟着漂。

修法: 自动取景**只做一次**, 之后相机锁死 (只有人拖/点「对准」才重取景):

```js
// 自动取景只做一次; 连续取景会把"会动的工件/臂"算进包围盒 ⇒ 整幅图漂浮
if(VR.auto){ VR.auto=false; vrFitBox(); }
```

判据 (真页面 `browser_console` 采样, 别靠肉眼说"好了"): 跟随中连续 3s 两次读
`{tgt: VR.tgt.map(×), dist: VR.dist, seq: PREV.ssSeq}` ⇒ `tgt`/`dist` **逐位不变** 且 `seq` 在推进。

## 2. 侧栏随状态文字长高 ⇒ 所有按钮上下跳

症状: 用户看不到具体文字, 只看到「左边那排按钮老是上下跳」。

真因: 侧栏里插入**动态行** (状态提示/帧龄/seq 摘要), 有内容/无内容高度不同 ⇒ 下面所有控件位移。

规矩:
- 侧栏**只放固定高度的控件**; 一切"会变的文字"上**顶部横幅** (固定位置, 不参与侧栏布局)。
- 动作按钮与它的开关**放同一行** (`flex-wrap:nowrap; white-space:nowrap`), 不另起一行。
- 删掉的那行对应的绘制函数要**改成 no-op** (`function ssHintPaint(){ return; }`), 否则下次改别的分支又把它写回来。

判据 (四态各量一次): 关键控件 `getBoundingClientRect().y` 与侧栏总高 `offsetHeight` **完全相同**。
例如改前/改后都应是 `预览动作 y = 275/275/275/275`、侧栏高 `577/577/577/577`。

## 3. 复制了开关状态却不拷 `play` 字段 ⇒ 画面板「▶ 运行」推不动页面

症状: 画布点「运行」、日志说已写播放意图文件, 页面却纹丝不动 (开关开着也不动)。

真因: `/api/ar/cmd` 的 payload **从来没有 `play` 字段** ⇒ 页面永远收不到"有人点了运行"。

落法: 服务端 `_ar_cmd_payload()` 里挂 `out["play"] = _ar_play_payload()` (同时挂 `/api/ar/mode`),
返回 `{action, ts, by, src, task, age_s, fresh}`; `fresh = age_s <= 120`。
判据: `curl -s /api/ar/cmd | python -m json.tool | grep -c play` ≥1, 且 `play.fresh` 随写入变 true。

## 4. 页面加载时刻不能当"命令太旧"的分界

症状: 人**刚点过**运行, 页面自动跟版刷新一次后却不动了 (开关开、`plant=0`)。

真因: 页面 `PLANT._lastPlayTs` 初值 = **加载时刻**, 而 `ar_play.json` 的 `ts` 是刷新前写的 ⇒ 被当成"旧命令"。

修法: 初值取 `Date.now()/1000 - 120`, 与服务端 `play.fresh`(≤120s) **同一口径**:
刚点过的运行不会因刷新失效, 超过 2 分钟的老命令仍然不许自己拉起。

配套: 改完这层要紧跟一条**新鲜的 start 写入**再让用户刷新 —— 否则他会看到"还是不动"再报一轮。

## 5. 交付口径 (用户把这页当结果看)

- 页面必须**自报状态**: 顶部横幅写清 拨杆=开/关 · 是否跟随 · `seq` · 帧龄; 用户读不出就等于没状态。
- 报告时给**能复现的判据**, 不要"改好了"三个字: 相机 `tgt/dist` 不变 + `seq` 推进 + 侧栏 y 恒定 + 侧栏高不变。

## 6. 切换驱动源必须"字段对等": 动作对、状态全丢

同一套动作在这页上有**两个播放器**:
- 本地时钟 `plantAt(PLANT.simT)` —— 「全流程 UPH」「🔁 插拔全流程」用;
- 服务端信号 `plantAtAR()` —— 左栏「状态空间」拨杆 + `▶ 跟随` 用。

`plantAtAR()` 只写 `PREV.q / PREV.M`（臂怎么动），**不碰 `INSP.*`**；而手里那颗模块、源盘剩余、孔占用、
`📷 检测` 标注、良品/NG 落盘全在 `INSP.*` 里，且**只有** `inspStep()`（全流程播放器）会写。
⇒ 现场原话是「开状态空间以后右臂就把光模块掉了 / 看着有动作但手里没东西」。
判据: 跟随模式 `INSP.carry` 恒 false、`INSP.si` 不动 —— 这就是空手走轨迹。

定式三处一起改, 少一处仍然空手:
1. `plantAtAR()` 里按 `a/b` 端点匹配段表, 写 `INSP.carry = (u<0.5 ? carry_from : carry_to)`,
   并补 `INSP.si / holeOcc / holeT / pickedK / doneK / curCheck`（真源 = 段表自带的 `carry_from/carry_to/check`,
   与全流程读的是同一份 `sim_insert`)。
2. 绘制闸从 `if(INSP.on)` 放宽到 `(INSP.on || SSMODE.on)` —— 模块/孔/分拣那一整块都在这道闸里。
3. 拨开关与点 `▶ 跟随` 时调 `inspEnsure()`: **只 fetch `/api/sim_insert` + `inspPrepare()`, 不 `inspPlay()`**。
   新标签页没点过「全流程 UPH」时 `INSP.plan` 是空数组, 光有状态同步代码也取不到真源。

🔴 同一段动作在一批 14 件里**重复出现** ⇒ 端点会撞多个候选。定位"第几件"必须用服务端 `elapsed_s` 落在
哪一段累计时间 (`cum[i-1] <= el < cum[i]`); 只按端点取第一个匹配会拿到别的件的孔占用/手上有货状态。

自验 (真浏览器 `browser_console`, 不要离屏截图): 拨杆 → `▶ 跟随` → `setInterval(250ms)` 采样
`{carry, si, kind, u, x: PREV.M['tool1'].t[0]}` 存 `window.__CS`, 读回后断言三件事:
`carry` 出现 0→1→0 的切换、`si` 递增、`tool1` 位移 >100mm。实测 30s/119 采样: carry=1 占 90、段 46→117、
x 扫 454mm、孔占用 3→2 —— 只报"改好了"不算过。
同时把 `carry / ssi / hold` 加进 `/api/ar_diag` 的自报字段, 以后现场"手里有没有货"直接看数。

## 7. 双臂问题要按"层"回答: 编排层并行, 命令流单臂

被问「左右臂是 plan 节点规划的吗」时, 先分清四件事再答:
- `plan_long_impl.py`（`ssplan`）**只发段、不发关节角**: payload 的 `a/b/u/elapsed_s/mt_id/mt_i/batch`,
  `q`/`q_l` 恒 null。关节角是页面 `arCmdSolve()` 用 `a+b*u` 插值再 `ikTool1` 逆解出来的 ⇒
  "规划"发生在浏览器侧; 要让服务端出 q 得在 `_pub_ar` 里加 IK。
- 它**也不算几何**: 段坐标来自 `sim_insert.json`(392 段 / 159.43s)，节点自算与磁盘表逐段一致才算"真执行",
  不一致就回退磁盘表并把差异写进 status。
- **左臂根本不在 plan 的命令流里**: `plan_long_impl.py` 搜 `MT-06|lane|left|transport` 零命中; 左臂播的是
  `sim_transport.json`（离线一次性生成, 3.0 s/件），由页面本地时钟 `transPlay()` 驱动, 与 `ar_cmd` 无关。
  payload 里 `q_l`（`tcp_ar_server` 透传）永远是 null = 双臂钩子留了没实现。
- **但编排层知道左手**: `ar_meta_tasks.json` 有 `MT-06 左臂供料` / `MT-07 双手交接`, `/api/ar/meta` 的 lanes
  也画了左右手两条轨道 ⇒ 结论必须说成"**元任务层并行、命令流单臂, 断在 plan_long 这一层**",
  不要说成"没做双臂"。
