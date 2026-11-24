# 画布接线 · 「运行」语义 · 节点可观察性

新增/改动节点后，从「JSON 里有」到「画布上看得见、跑得出值」还差四步。每一步都有实测坑。

## 1. 接线要落到 GUI 真正读的那份

- studio 打开状态空间工程时读 `flows/state_space_obs.json`（见 `simulink_module._flows_path()` / `open_state_space`），
  它通常软链或复制自 `data/database/zmax/sources/canvas/state_space_obs.json`。**两份都写**，只改一份会出现
  「脚本查到了、界面没有」或反之。
- 两份都在数据空间（`.gitignore` 命中），`git add` 静默什么都不加。仓库里提交的是**幂等接线脚本**
  （如 `tools/wire_<feature>_canvas.py`），画布内容本身不进库。
- 写盘前 `json.load` 校验一遍，并留 `path + ".bak_<hhmmss>"`；改完立刻跑完备性判据。
- **「画布里有几个节点」的口径 = 运行中的 studio 打印的节点数**，不是某个 JSON 文件的行数。
  `data/database/…/canvas/` 那份会被 studio 回写而漂移（实测两份 100 vs 97，拿它判会得出"节点丢了"的假结论）；
  漂了就重跑幂等接线脚本，别手改回去。

## 2. 幂等 upsert：重复执行不叠节点/连线

```python
LK = {"id": "lkw_<feature>_<port>", "f": "src_node", "t": "dst_node",
      "f_port": "out1", "t_port": "in1", "label": "43D 状态 → X10"}
ids = {l.get("id") for l in d["links"]}
if LK["id"] not in ids:
    d["links"].append(LK)
```

- 节点与连线都必须带**稳定 id**；按 `(f,t,port)` 去重会在改端口时留下幽灵连线。
- `label` 写**数据含义**（`意图 Δ → 十维意图`），不写 `a→b`；用户是照 label 判读链路的。
- 新节点若需要输入才有意义，别忘了把上游接上：只接出线 ⇒ 运行一拍也只会返回 `ok=False`。

## 3. 完备性判据的硬约束（`tools/canvas_completeness_check.py`）

- **断头**：节点有入无出（或有出无入）即失败。新节点必须两端都有线，或者进 `SOURCES` 白名单（数据源）。
- **行带归属按节点中心 `cy`**：中心落在两条行带之间的缝里就判错位 ⇒ 挪节点让中心回到带内，不要改行带。
- **坐标必须是整数**：改 JSON 时 `int(round(v))`。
- 全绿之前先接**既有**断头（只进不出的终端节点接下游），否则老问题和新问题混在一起，看不出因果。
- 判据看**退出码**，不看日志措辞；报数用「节点 N / 连线 M / 断头 K（K 全为合法终端）」这种可复核口径。

## 4. 「▶ 运行」不保证跑节点图：先判数据源

- `studio.py::_run_ss_cmd → start_sim`：画布数据源是「AR场景」时，运行只写 `ar_play.json` 开关 AR 播放，然后 return，
  **节点图一拍都不跑**。
- 症状：点了运行、状态栏有字、模型也加载了，但目标节点零输出、落盘文件不出现、日志里搜不到节点名。
- 判断顺序：① 读 `_canvas_src_state()` 看数据源；② 追 `start_sim` 的分支；③ 确认不跑节点图后，
  用**同一注册入口**真跑一拍拿数据：`registry.NODE_LOGIC[key]["fn"](ctx)`（ctx 按 `{"in1": {"value": ...}}` 组织，
  输入取真值文件，如 `zmax_data/rokae_sdk/tcp_out/latest.json`）；或把数据源切「仿真/真机」后再点运行。
- 汇报口径必须分清：**「点了运行」与「节点级真跑了同一函数」是两件事**，别把后者说成前者。
- 要从界面侧触发某个节点（验证双击行为、不必找像素）：命令通道加按名子串定位——
  `echo "ss_node <关键字>" > /tmp/zmax_nav_cmd` → 找节点 → `scene.on_node_activated(node)`（与真双击同路径）；
  未命中先 `_open_ss_canvas_cmd()` 再 2.5s 重试，命中/未命中都**打印节点总数**，否则分不清"没这个节点"和"画布没加载"。
- 双击节点的自定义行为都挂在 `SimCanvas.on_node_activated` 的**前置分支**（按 `node["name"]` 认，GUI 内存节点不带 id），
  排在 `source`/`verif`/`viz` 这些会抢先拦截的分支之前；典型用法是双击开内嵌网页窗口，
  实现与 snap 浏览器坑见 `zmax-console/references/studio-opening-web-pages.md`。

## 5. 新节点必须自己落盘，否则用户「看不见」

节点输出只走内存总线，不落库也不落文件 ⇒ 画布真跑起来也查不到值。在 node fn 里加观察落盘：

```python
_LIVE_TS = {}

def _live(obj, name, payload, hz=2.0):
    """原子 + 节流写 zmax_data/ss_live/<name>；只做观察，异常全吞。"""
    now = time.time()
    if now - _LIVE_TS.get(name, 0.0) < 1.0 / max(hz, 0.1):
        return
    _LIVE_TS[name] = now
    tmp = "%s.tmp.%d" % (path, os.getpid())
    json.dump({"t": round(now, 3), "node": node_id, **payload}, open(tmp, "w"), default=str)
    os.replace(tmp, path)
```

- 2Hz 节流（节点可能 10Hz 跑）；`tmp + os.replace` 原子，避免读到半个 JSON。
- 观察路径绝不能影响控制路径：整段 `try/except` 吞掉，写盘失败也要正常 `return out`。
- 落盘字段挑能自证的：`V`、`V_traj`、`steps_to_tol`、`monotone`、`viol_max`、`action6`、`gate`、`src_engine`。

## 6. 重启 studio 的正确姿势

- 入口 `tools/gui/restart_studio.sh`。它必须**先判 unit 在不在**：
  `systemctl --user list-unit-files | grep -q '^zmax-studio.service'`，不在就回落 `launch_studio.sh`；
  直接 `systemctl --user start` 会在杀完旧进程后报 `Unit not found`，窗口直接消失（用户会把黑屏当成你的错）。
- 回落启动写成 `setsid nohup bash launch_studio.sh </dev/null >>log 2>&1 &`。少了 `</dev/null`，
  调用方用管道接这个脚本（`... | tail`）会一直等，因为后台子进程继承了管道的写端。
- 旧实例不响应停止请求，脚本要等满约 30s 再 pkill；窗口约 15s 恢复。
- 验收是**窗口**，不是进程：`wmctrl -l | grep -c "XSpace ZMAX"` + geometry 是否在屏内（越界会截断按钮）。
- 别用 `pgrep -f studio.py` 当判据：会匹配到自己的 shell；用
  `pgrep -af "^[^ ]*gui-venv[0-9]*/bin/python studio\.py$"`。
- 重启后画布是空的，`open_state_space()` 需要重新加载；先 `ss_canvas` 再 `ss_run`，中间留 ~10s。

## 7. 显存共驻：8G 卡装不下整画布

- L2 YOLO + L3 SmolVLA + L4 INTACT + SAM3 同时驻留 >8G ⇒ `CUDA error: out of memory`，
  崩点在 ultralytics 预处理（`im.half()` / `im.float()`）而不是模型加载，容易误判成权重坏了。
- 先认清是谁：`nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv,noheader`，
  再逐个 `tr '\0' ' ' < /proc/<pid>/cmdline`。
- 只验证节点逻辑时用 CPU 起 GUI：`CUDA_VISIBLE_DEVICES= bash tools/gui/restart_studio.sh`（子进程继承，YOLO 落 CPU），
  不必去抢显存、也不必停别人的服务。
- 真要停服务腾显存：**只停不擅自重启**，报出停的是哪个 pid/unit、腾出多少 MiB、以及恢复命令，让用户点头。
