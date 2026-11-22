# 8815 看板切到新版点位表 (ZMAX_SE3_SET)

`tools/se3_geom_server.py` 现在支持两套点位表，环境变量 `ZMAX_SE3_SET` 切：
- `v2`（默认）：`real_traj_joints_v2.json` 239 点 / `point_stops_v2.json` / `traj_phase_v2.json` / `traj_hopf_v2.json` / `sectors_v2.json`
- `215`：老表 `real_traj_joints.json` + `point_stops.json`（相位图回到旧口径）

## 生成 v2 三件套
```bash
./gui-venv311/bin/python tools/make_v2_phase.py --chunks <play_points 日志>
```
- 相位 `s` = 沿 TCP 折线弧长 / 末帧；`s_mm` 累计毫米；hopf 由 `rpy → 四元数 → n/φ`
- `sectors_v2.json` 直接取那次真机跑批的 chunk(i0,i1,secs,speed)，节拍 sum ≈ 实测总秒
- 日志被截头时用 `--head-secs` 补起点块，否则环上 0 段是空的

## 状态清单口径（用户已确认）
- 清单每行 = 一个**停点/状态**，行区间 = `(上一个停点, 本停点]`，行名 = 该段落点状态
- 高亮 = **第一个 `i >= 当前帧` 的行**（不是"最近"、也不是"已走过的最下面"）；
  这样方框单调自上而下，且与画布上"现在 X"永远一致。改这条前先跑抽样断言
- 用户口述规则：**插入之后第一次到底 = 工作点**（中间 退出/再进/微调 不单列成状态）
- 同一动作的多次微调（退出/再进/孔内微调/退出准备）并进落点状态，**只留工艺节点**;
  他要“少而准”的行，不是把每个停顿都列出来。改完抽 4 帧（插入点/微调中/到底/离开）验单框命中

## 扇区补缝
chunk 的 `s0/s1` 只覆盖"点"，点与点之间的弧不属于任何块 ⇒ 环上出现几十道细缝、
标题"覆盖"只有 82%。把每块 `s1` 拉到下一块 `s0`（末块拉到 1.0）即可 100%，耗时不动。

## 🔴 页面里内嵌的“旧点位表快照”会与后端正表错位

页面 A/B/C/D 四个面板（位置 ℝ³ / 速度 / 姿态 / 相位）原来画的是 HTML 里内嵌的 `const D={frames:[…]}`
（旧 215 点）。服务端切到 v2 之后，相位环与右侧清单是新的、但位置面板那条轨迹仍是旧点 ——
用户看到的就是「轨迹没更新」。只改后端不够，前后端要认同一套表。

- 服务端加 `GET /api/geo`：返回**与内嵌 D 同形**的帧数组（`p` mm / `n` / `phi` / `q` 四元数 / `dn` / `dphi` /
  `spd` / `s` / `s_mm`），数据源就是当前 set 的 `real_traj_joints_*.json` + `traj_phase_*.json` + `traj_hopf_*.json`。
- 页面侧三处配合，缺一处就静默不生效：
  1. `const F/D.frames/N/S_END/PROG/PW` 一律改 `let`，把派生量包进 `deriveGeo()`（`PROG`、unwrap 后的 `PW`）；
  2. `loadGeo()`：`fetch('/api/geo')` → 若 `j.n !== N` 就 `F=j.frames; N=F.length; D.frames=F; deriveGeo();`，
     同步滑块 `sc.max=N-1`、夹住 `idx`，最后 `drawAll()`；
  3. 首载调一次 `loadGeo()`（`drawAll` 是函数声明，会提升，不用担心定义顺序）。
- 验收（页面 console）：`N===239` · `sc.max===238` · `F[0].p≈[663,-29,292]` · `F.at(-1).p≈[664,-29,294]` ·
  末点与首点差几 mm（闭环）· 页面 `idx` 与 `/api/se3` 的 `nearest.i` 同源一致。
- 🔴 **速度色标要包含表里真出现的档位**：`SPC={100,85,70,60}` 遇到接触段的 15 档会画成灰色，
  看着像“没着色/没数据”。实际档位集先 `set(speed)` 看一遍再定色标。

## 改服务端的固定顺序
```bash
./gui-venv311/bin/python -c "import ast;ast.parse(open('tools/se3_geom_server.py').read())" || exit 1
sudo systemctl restart zmax-se3-geom && sleep 3
curl -s http://127.0.0.1:8815/api/geo | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['ok'],d['set'],len(d['frames']))"
```
- 🔴 **先 `ast.parse` 再 restart**：多行 docstring/引号写坏时 `systemctl restart` 表现为“服务挂了”，
  日志里只有一行 SyntaxError，很容易被当成“端口被占/旧进程”。编译先过一遍比读日志快。
- 验收必须探**新加的端点**（`/api/geo`），只探 `/`200 证明不了新代码在跑。

## 自检
页面 console：`window.__curI = <帧号>; renderStops(SEC,0)` 后读 `#stopList .r.cur`，
断言"恰好一行命中且名称等于该帧所属 block.state"。
