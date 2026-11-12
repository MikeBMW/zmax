# 真机位姿全程录制 → AR 三维同步

用户说「我一会跑一遍流程，你记录所有的位姿，然后要同步 AR 场景」时的完整做法。

## 工具（都在 ~/zmax/tools/）

| 工具 | 作用 | 解释器 |
|---|---|---|
| `pose_record.py start/status/stop/list` | 逐拍读 `zmax_data/rokae_sdk/tcp_out/latest.json`，写 `zmax_data/pose_records/rec_<ts>/poses.jsonl`（每拍一行：xyz/rxryrz/quat/joint/src/speed_mm_s/moving） | `.venv-aoi310/bin/python` |
| `pose_to_ar.py [--per-run\|--per-seg\|--tol] [--dry]` | 录制 → 8797 `POST /api/fence/add {type:"points"}`，写后回读 `/api/fence` 对账 n | `.venv-aoi310/bin/python` |
| `pose_map.py [--with-scene]` | 俯视轨迹图 + 高度剖面 + 3D 等轴测 + `coverage.json`（20mm 覆盖栅格） | **`./gui-venv311/bin/python`**（matplotlib 只装在这个 venv） |

`stop` 会顺带写 `summary.json`（段/航点 RDP 2mm/路程/时长/断拍）。录制进程用
`terminal(background=true, persist_on_release=true)` 起，别用 nohup/setsid（工具会拒）；
中途用 `pose_record.py status` 报「拍数 / 时长 / 是否在动 / 真值龄」，用户每问一次「又跑了」就给增量。

## 顺序

1. **先起录制**（他还没动之前）。确认 `truth_age_s < 0.5`，否则先修位姿链（见 `robot-pose-truth-chain`）。
2. 他跑期间：`status` 报拍数/段数，**别停录制**；需要图就 `pose_map.py`（读的是正在追加的 jsonl，安全）。
3. 他说停 → `pose_record.py stop` → 读 `summary.json`。
4. `pose_to_ar.py --rec latest --per-run`（按空闲 >4s 分轮、跳过 <50mm 抖动轮，每轮一条）；
   `segments` 有 20+ 段时不要 `--per-seg`，左栏会被几十条按钮淹没。
5. 回读 `/api/fence` 核 `enabled/n` 与下发逐位一致，再报 id。
6. `pose_map.py --rec latest --with-scene` 出图，报 bbox/段/路程/覆盖格数 + 文件绝对路径。

## 坑（都实测踩过）

- **真值源原生只有 5Hz（200ms）**，不是 50Hz：`latest.json` 的 `ts` 相邻差中位数 0.200s。
  汇报必须写实际帧率；快速拐角 300mm/s × 0.2s = 60mm/拍，形状会切角 —— 要更细只能换源，别声称「记录了 50Hz」。
- **latest.json 有两个写者交替**：`src=rokae_xcoresdk/endInRef (direct, no DDS)`（多数，joint 12 位、带毫秒）与
  `src=orin_sdk_bridge/endInRef (relay, no DDS)`（少数，joint 只 6 位、`t` 显示成本地 18:xx 格式）。
  值是同一个 `endInRef`，**按 `ts` 排序/去重即可，别当成重复样本或跳变删掉**；汇报里按 src 分组给条数最省事。
- **同名函数两套结构**：`pose_record.segments()` 返回 `(i0,i1)` 元组，`pose_to_ar.segments()` 返回
  `{"i0":..,"i1":..}` 字典。从一处抄到另一处会 `TypeError: tuple indices must be integers` / `KeyError: 0`。
- **写 AR 用 `type=points`**：`fence_store.add` 里 points 只显示、`check_point` 显式跳过 ⇒ 不会把自己要走的路堵死。
  用 box/line 顶替会污染净空判定。
- **AR 页像素判据在这件事上不可用**：轨迹色 `#22d3ee` 与料盘同色、`#f59e0b` 与第二个料盘同色；
  而且一开轨迹会触发重新取景，非背景像素数**反而下降**（实测 49193 → 48331），按像素增减判「画没画」必假。
  判据换成：左栏「轨迹点」行文本为 `▣ 名字`（显示中）+ 服务端 `enabled=true` 且 `n` 与下发点数相等。
- **`browser_click(ref)` 可能不触发按钮的 onclick**（点了 class 仍 `sm`、像素不变）；
  验按钮行为用 DOM：`document.querySelectorAll('button')` 里按文本找到元素后调 `b.onclick()`，
  下一拍再读 `className`（`fenceToggle` 是异步 POST，同步读会读到旧 class）。
- **`pose_map.py` 必须用 `gui-venv311`**：`.venv-aoi310` 没有 matplotlib（Pyright 也会报 import 找不到，属正常）。
  图里中文会变方块，标签一律 ASCII（START/END/段号 S1..），要中文说明写在汇报里。
- 用户问「可以建图么」时给两种口径：**位姿图**（本工具，立即可出）与 **场景点云/3DGS**（要沿路径重新采 D405 深度，
  不是录位姿能顺手得到的）。别把位姿图说成场景地图。
