# 把「实时建图」装进「📡 融合定位建图」节点

## 落点三件套
| 层 | 文件 | 职责 |
|---|---|---|
| 节点实现 | `src/lerobot/engineering/nodes/library.py::node_ss_s1` | 每拍仅：`ensure()` 守护活着 + `line()` 写一行日志(节流 30s) |
| 节点模块 | `src/lerobot/policies/left_right/state_space/realtime_map.py` | `ensure()/status()/line()`，`_ss_import` 只认这个目录(不是 manifold) |
| 重活守护 | `~/zmax_map/tools/gs_realtime_map.py` (+ systemd `zmax-gs-realtime-map`) | 攒帧 / 裁滚动窗口 / `gs_train.py --init-ply` 增量训 / 发布 `gs_assets/rt_live` |

## 六个必踩的坑

**① 建图块必须放在节点函数最前面，且与 metaworld 解耦**
产线机(550C)没有 `metaworld` ⇒ `_ss_env_obs()` 抛 `No module named 'metaworld'`，整函数早退。
建图块写在融合之后 = **永远不会执行**（看着代码在、行为零效果）。放在 `log = ctx.get("log")` 之后、`try:` 之前，
再给融合失败的日志加 60s 节流（10Hz 循环否则 10 条/秒刷屏）。

**② 常驻循环不再读 `ZMAX_CANVAS_ONLY`（写进 drop-in 是无效功）**
`ss_canvas_loop.py` 已改成「每拍跑核心链 CORE_IDS，每 `ZMAX_FULL_EVERY`(默认30) 拍跑一次全量」。
判据不是白名单，而是：`canvas_loop.json` 的 `traces[]` 里有没有该节点 id，以及 `/tmp/ss_canvas_loop.log` 里
有没有它的 `[<id>]` 行。加白名单 drop-in 看起来"配置生效了"(`systemctl show -p Environment` 有)，实际一点作用没有。

**③ 采集会话有两种形态，只认一种就炸**
- 今天的会话(`gs_autocap/sessions/<id>`) = `images/ + cameras.json + session_meta.json` ⇒ **已经是数据集**，
  只需按窗口裁最后 N 帧（`os.link` 硬链接零拷贝）。
- 老会话只有帧+位姿 ⇒ 才走 `gs_dataset.py`（内部读 `frames.jsonl`）。
  踩过的报错：`FileNotFoundError: .../frames.jsonl`（把新会话喂给了旧构建器）。
- **采集中不是错误**：采集守护还在写帧时 `cameras.json` 尚未落盘，`has_ds()` 为假 ⇒ 会掉进旧构建器连报
  `frames.jsonl` 不存在。正确处置是 `return False, "会话还在采, 本轮先不建"`（下一拍再来），不是打 error、不是重试风暴。
  实测该形态会连续报 5 次，30 秒后会话收口自动就成功——把它当故障会让人去改本来没错的代码。

**④ 守护会双起：节点 ensure() 与 systemd 同时拉起**
现象极像"配置没生效"：状态文件里 `steps` 一会儿 600 一会儿 400、`phase` 来回跳。
修法：守护入口 `fcntl.flock(LOCK_EX|LOCK_NB)` 单实例闸；拉起侧 `ensure()` 先看状态是否新鲜，新鲜就不 spawn。

**⑤ 换会话必须清零训练基线，标记位不能用被覆盖的键**
采集守护每段跑完就开新会话、帧数从 0 重数；基线若还停在上一段的 900 帧，`pending = n - last_n` 永远 ≤0
⇒ 状态看着是 `phase=collect`、`pending=0`、`n_rounds` 卡住不动，现场表现就是"建图停了"。
修法：`if state["sess_marker"] != sess: state["sess_marker"] = sess; state["last_trained_frames"] = 0`。
🔴 **标记位必须是 `state.update()` 里没有被写过的键**：若先 `state.update({"session": sess, ...})` 再比
`state.get("session") != sess`，两边永远相等 ⇒ 清零分支永不进入（第一版就这么写的，白查一轮）。

**⑥ `cameras.json` 只在会话收口时落盘 ⇒ 长跑一趟全程训不了**
采集中的会话目录**只有 `images/`**，`cameras.json`/`session_meta.json` 要等收口（够帧数 / 位姿摊够跨度 /
静止 >20s 且 ≥MIN_FRAMES）才出现。跑二十分钟的连续轨迹期间实时建图一直拿不到数据集，只能等走完。
修法（已上线）：采集守护在追加帧处**每 40 帧落一次 `cameras.json`**（`len(cur["frames"]) % 40 == 0`），
守护就能用滚动窗口边动边训。
🔴 副作用要记住：**重启 `zmax-gs-autocap` 会丢掉内存里未收口的那一段**——目录里只剩 `images/`、永远没有
`cameras.json`，那段帧对建图不可用（实测丢了 102 帧）。重启采集守护前先确认当前会话已收口。

## 训练预算口径（实测）
- 冷启 3000 步 ≈ 1557s；冷启 400 步 ≈ 334s（与批量队列**共卡**时）；冷启 150 步 ≈ 155s。
- **warm start 便宜得多**：`--init-ply 上一轮 gs.ply` + 400 步 ≈ **91.5s**（同一台 550C、同卡共跑）。
  所以"实时"的可行档是 400~600 步 warm start，而不是每轮冷启。
- 冷启 400 步 / 300~400 帧窗口 ⇒ PSNR 留出 **10.55 dB**（150 步 8.73 dB）；同参数 warm start 第 2 轮 ⇒ **13.22 dB**。
  仍属"能出图"量级，不是可用重建(≥18dB)。想要质量靠**多轮 warm start + 臂持续走动扩覆盖**，不是单轮加步数。
- 与 8814 批量队列共卡用 `RT_IGNORE_BUSY=1`（实时是产品要求，不因排队饿死）；纯让路就不设，代价是长队列期间实时建图会被饿死、状态一直是 `wait_trainer`。

## 验收四证（缺一条就是"看着像好了"）
1. `systemctl is-active zmax-gs-realtime-map` + `/proc/<MainPID>/environ` 里的 `RT_*` 真值；
2. `~/zmax_data/gs_map/realtime.json` 里 `phase/n_rounds/psnr_holdout_db/asset` 有真数；
3. `gs_assets/rt_live/gs.splat` 的 mtime 与本轮完成时间一致；
4. `/tmp/ss_canvas_loop.log` 里出现 `[sssensor] 🗺 实时建图(3DGS): ...` —— 证明**节点**这一拍真的读到了它。

判 `phase` 别只看有没有 error：`collect`(帧不够) / `wait_ds`(会话还在采，正常) / `wait_trainer`(8814 在排)
/ `train` / `done`。把 `wait_ds` 写成 `error` 会让下一次会话把正常等待当故障去修。
