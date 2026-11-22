# play_points.py 分段回放(点表直发, 不经 8797)

用于「按点表一站一站走给现场看」：一条命令跑 `I0..I1-1` 一段，到位停,报账,等下一站。
与 `arm_step_traj.py`(走 8797/step_traj/flow 档)是**两条不同的腿**，别混:
play_points 是**一次性把整段 MoveAbsJ 分块 append**、同一个进程跑完就退出，不写 `traj_step_state.json`、
不触发夹爪/AOI 事件。用户说「去抓取点 / 去工作点 / 去废料点」时用这条。

## 命令契约
```bash
cd ~/zmax && \
ZMAX_PP_TRAJ=/sdk/real_traj_joints_v2.json \
ZMAX_PP_STOPS=/sdk/point_stops_v2.json \
ZMAX_PP_I0=<起> ZMAX_PP_I1=<起+1> \
ZMAX_PP_SPEED=100 ZMAX_PP_DWELL=1000 ZMAX_PP_CHUNK=24 \
ZMAX_PP_SLOW="91-133:15" \
bash tools/rokae_sdk_run.sh --script play_points.py
```
- 🔴 **`I1` 是排他的**: `I0=0 I1=33` 走 `#0..#32`(end_i=32)。想到 `#99` 就 `I1=100`，不是 `I1=99`。
  报点数时说清「239 个点 = 索引 0~238」，用户口径的「238 点」是**间隔数**，照抄会差一个。
- 起点 `I0` 会先对齐一次(`start` 行的 `jump_to_i0_deg`)：臂已停在上一段末点时应 <1°，
  若报几度到几十度 = 臂不在你以为的位置，**先查真值再跑**，别让它用关节直跳跨过去。
- `ZMAX_PP_SLOW="a-b:15"` 只治**接触段**(插入/对位，本轨迹 91~133)；不起作用时日志 `slow_zones` 行不会出现你的区间。
  另有两条**默认慢区** `21-35 / 93-108`，所以从 #33 起跑会先在 33~35 爬行，属正常。
- 单点块(相邻点被分到 1 点时)在日志里是 `speed: 15.0`，实测 ≈2.4 s/点；
  这是「接触段慢走」的表现，不是速度参数没生效。

## 监视: 别用 pgrep 判活
```bash
ps -eo args | grep -c '[p]lay_points.py'     # 0=已退出; 别写 pgrep -f play_points.py
```
`pgrep -f play_points.py` 会把**执行这条命令的 shell 自己**匹配进去(命令行里含同一串) ⇒ 永远返回"alive"，
于是一直傻等一个早就跑完的段。同理 `pkill -f` 会自杀。
实时位置看 `curl -s 127.0.0.1:8797/api/tcp`(x/y/z 米 + age_s)，比读日志快。

## 报账: 读 process-results, 不看 tail
```bash
python3 - <<'EOF'
import json
d=json.load(open('/home/ubuntu/.hermes/logs/process-results/<proc_id>.json'))
recs=[json.loads(l) for l in d['output'].splitlines() if l.startswith('{')]
print([r for r in recs if r.get('step')=='done'])          # ok/end_i/elapsed_s/n_chunk/n_hold/joints_deg
print([(r['i'],r.get('name')) for r in recs if r.get('step')=='dwell'])   # 实际停过哪些点
errs=[r['err_deg'] for r in recs if r.get('step')=='chunk' and 'err_deg' in r]
print(min(errs), max(errs))
EOF
```
- 后台命令若是 `... | tail -30`，结果文件里也就只剩 30 行 ⇒ **dwell 行会被截掉**，
  只看到 1 个停点而 `n_hold=3`。要么别加 tail，要么以 `n_hold` 为准去对号。
- 到位判据用 **关节误差**(全段 0.084~0.130°)；TCP 毫米值与表值有 ~3.9mm **系统性口径偏置**
  (表里 `p_mm` 与实时 `endInRef` 的算法差, 整条轨迹同源)，拿毫米差当"没到位"会误判返工。

## 分段基线(239 点表, SPEED=100, DWELL=1000, CHUNK=24, 接触段 15)
| 段 | 点数 | 实测 | 停点 |
|---|---|---|---|
| #0→#32 抓取点 | 33 | 49.9 s | 抓取点·槽7 |
| #33→#64 扫码点 | 32 | 33.3 s | 抬升 / 扫码点 |
| #65→#128 | 64 | 109.4 s | 对位点 / 对位微进 / 插入 |
| #129→#154 离开 | 26 | 25.4 s | 离开 |
| #129→#199 废料点 | 71 | 73.7 s | 工作点 / 离开 / 废料点 |
| #200→#238 终点 | 39 | 40.5 s | 回程 / 初始点 |
| #0→#99 一趟到工作点 | 100 | 101.4 s | 6 个 |
| #100→#238 收尾 | 139 | 183.1 s | 5 个 |
| 全程一次 | 239 | **288.6 s**(288.57 实测) | 11 个 |
分段接力合计 284~306 s，比一次跑完多/少几秒(每段起点重锚 + 段首停点重复 1s)—— 被问"分着跑慢多少"给这个区间。

## 跑之前的三件事
1. **同一时刻只允许一个回放进程**：先 `ps -eo args | grep -c '[p]lay_points.py'` 为 0。
2. **确认臂站在上一段末点**：`/api/tcp` 与表里 `p_mm[I0-1]` 比，差在几毫米内才起跑。
3. **别在跑的时候改 `point_stops_v2.json`**：脚本在启动时读一次停点表，中途改文件不会生效，
   还会让下一次跑的停点与这次报的账对不上。改表 → 重算 8815 → 再跑(见 `zmax-ar-traj-8797` 的 point-naming-ui 参考件)。
