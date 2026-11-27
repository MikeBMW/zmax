# 画布节点右键 → “打开代码”落点 / “点了没反应” 分诊

什么时候看这个文件: 用户说「右键打开 node 没进到 node 的代码」「右键打开源代码跳错文件」
「点了没反应」「又开了一个 VSCode」。

## 1. 先读轨迹，再猜

节点右键每次落点都追加一行到 `~/.cache/zmax/rightclick.log`:

```
2026-10-17 12:31:03 target=node kind=- loc=…/state_space/cognition.py:254 spawn=isolated
2026-10-17 12:32:09 target=node kind=middleware-node loc=…/middleware/nodes/n_scheduler.py:31 spawn=isolated
```

- `kind=-` + `loc=` 指向实现源码 ⇒ **解析失败后退回 `params.source` 了**（这就是“没进 node”）。
- `kind=-` + `loc=-`      ⇒ 该节点既没有中间件模块、也没有 `params.source`（纯新建节点）。
- 连行都没有            ⇒ 跑的旧代码（控制台改完未重启）或点的不是那个菜单项。

定位失败再补 `err=模块: 原因`，用于区分“文件不在”和“import 失败”；
现场生成模块时写 `err=已现场生成 node 模块`。

## 2. 落点解析不许依赖 import

`from lerobot.middleware import resolve_open_target` 在 GUI 进程里会失败（sys.path 被占、同名包、调试器环境），
而失败一旦写成 `except: pass` 就静默退回 `params.source` —— 日志干干净净，用户只看到“没进 node”。

固定顺序：

1. **按文件名直查** `src/lerobot/middleware/nodes/n_<单词>.py`；单词来自
   `src/lerobot/middleware/node_names.json`（id → 一个英文单词，那个文件可直接编辑），
   与 `spec.module_name` 是**同一份真源**。GUI 里**读这个 JSON，不要 import lerobot.middleware**。
   节点没登记时: 名字里的英文 → 再不行用 id slug（`[^0-9a-zA-Z_]` → `_`）。
2. 行号 = 文件里第一条 `PORTS_IN` 行（文件头就是输入输出/连线/compute，正好是用户要看的）。
3. 直查命中后，resolve 结果**只允许补**「实现在 x:y」这一跳，不许覆盖已定落点。
4. 任何定位异常都要 `_log` 出类型+原因，不许 `pass`。

验收必须含“毒化 import”一档：`sys.modules['lerobot'] = types.ModuleType('lerobot')`（无 middleware）后，
落点仍必须是 node 文件 —— 这条才证明不依赖 import。

## 2.5 没有模块就现场生成，绝不允许“打开 node 却给了别的文件”

用户口径很硬：**「打开 node」必须进到 node 文件**，不管这个节点在不在 `flows/state_space_obs.json` 里。
直查 `nodes/n_<单词>.py` 不存在时，就地写一个再打开（`_mw_write_module`）：

```python
PORTS_IN  = 画布节点的 inputs 端口 id      # 没写端口就退 in1
PORTS_OUT = 画布节点的 outputs 端口 id     # 没写端口就退 out1
IMPL      = 节点 params.source
compute(ctx): 输入从 ctx 取, 输出按位透传, 不伪造数值
```

- 端口只能取**节点自己的** inputs/outputs（这时没有连线可推），不许凭空造一条连线路由。
- `PORTS_IN` 必须单独一行，`-g` 落点靠 `startswith("PORTS_IN")` 找它。
- 生成的模块是给“看输入输出”用的，**别指望它能进批量校验**：`gen_middleware_nodes.py --check` 只认
  工程 JSON 里的节点，现场生成的会被它忽略（不算漂移）。
- 节点没有 id 时不生成（文件名会是 `n_.py`），这时明确告诉他“这个节点没 id”。

验收: 造一个不存在的 id（如 `actmod_probe`，带 inputs/outputs/params.source）→ 调
`open_middleware_node` → 必须真的生成 `nodes/n_<单词>.py`（没登记就用 id slug，如 `n_actmod_probe.py`）、
VSCode 标题变成该文件、日志 `已定位 …:PORTS_IN 行号`；
**验完把生成的探针文件删掉**，别留在节点目录里。

## 2.6 模块文件名 = 一个英文单词（不是 id，也不是中文）

两条都踩过: 先是 `n_n1792212206921aaw`（id 像乱码），改成 `n_动作调制器`（中文）后又被否 ——
老倪要的是 **一个英文单词**，例如 `sssched → n_scheduler.py`、`ssff → n_feedforward.py`、
`ssyolo → n_yolo.py`、`sssk1…8 → n_skill1.py…n_skill8.py`。

- 真源 = `src/lerobot/middleware/node_names.json`（`id → 单词`，75 条，可直接编辑）。改单词后跑
  `python tools/gen_middleware_nodes.py`：它按新名重写模块、重建 `_index.py`、**自动删掉旧名文件**
  （id 名与中文名都会被清掉，实测「删 75」），别手工 mv。
- Python 3 **允许**中文标识符与中文模块名（实测 `import` 正常），所以“中文跑不了”是错的认识；
  用英文是**命名规范要求**，不是技术限制。
- `spec.module_name` 与 GUI 的 `_mw_module_path` 必须同规则（都查同一份 JSON）+ 按文件里的
  `NODE_ID = '<id>'` 反查兜底 —— 只改一边，右键和生成器就会指向不同文件。
- 验收: `gen --check` 75 个一致 · `verify_middleware.py` 10/10 · 节点目录里中文文件名残留 = 0。

## 3. 两个菜单项分工（别搞反）

| 菜单项 | target | 落点 |
|---|---|---|
| 打开源代码 (模块实现) | `impl` | `params.source` / 注册表符号行 |
| 打开 node (中间件 · 输入输出) | `node` | `middleware/nodes/n_<单词>.py` 的 `PORTS_IN` 行 |

`open_in_vscode(node, target=...)` **必须显式传 target**；默认值不当会让两个入口撞到同一行。

## 4. VSCode 起窗后要抢前台

`code` 是经 `systemd-run --user --scope` 起的（与控制台 cgroup 解耦，关控制台不会带走它），
窗口可能留在别的窗后面 ⇒ 用户看到的就是“没反应”。起窗 1.5s 后：

```bash
xdotool search --name <文件名>.py        # 拿 window id
xdotool windowactivate --sync <id>
```

## 5. 探针写法的三个已知坑

- 截 `QMenu.exec_` 拿菜单项做“菜单精简”验收（给 `*args`！`exec_` 被调成 `(self, pos)`）。
- 截 `subprocess.Popen` **抓不到** VSCode 启动命令（不是 Popen 起的）；以 `_log` 里的
  「已定位 path:line」或轨迹文件为准。
- 真开窗验收用真屏：`DISPLAY=:0` 调函数 → `wmctrl -l` 看 VSCode 窗口标题是否变成目标文件名。
  离屏 (`QT_QPA_PLATFORM=offscreen`) 跑完整 studio 带 3D/pyqtgraph 可能直接 SIGSEGV，不要拿它当真。

## 5.5 判“这次运行”只许看最后一段日志

`/tmp/studio_launch.log` 是**追加写**的：同一文件里躺着历史多次运行的
`Fatal Python error` / `Traceback` / 「N 趟回放」刷屏。直接 `grep -c Traceback` 会把上一次的崩溃
当成这次的回退（本次差点误报）。只认最后一条 `启动计时：控制台` 之后的行：

```bash
L=$(grep -n '启动计时：控制台' /tmp/studio_launch.log | tail -1 | cut -d: -f1)
awk -v n="$L" 'NR>=n' /tmp/studio_launch.log | grep -c 'Traceback\|RecursionError'
```

## 6. 交付纪律

改完这些代码需要重启控制台才生效，而**重启必须由用户自己做**（他明确制止过「你不要自己重启啊」）。
给命令 (`bash tools/gui/launch_studio.sh` 或 F5)，并告诉他重启后点一次，你读轨迹核对。
