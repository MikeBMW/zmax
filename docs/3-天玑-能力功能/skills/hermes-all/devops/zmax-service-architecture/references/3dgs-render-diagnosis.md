# 3DGS 渲染诊断阶梯 (gsplat · Intel XPU)

按顺序查，每步都有明确判据，不要跳步。

## 0. 先读状态端点，别从现象推

渲染服务通常给一个 JSON：

```json
{"ok": true, "gaussians": 219829, "fps": 5.4, "src": "arm",
 "pose_age_s": 0.156, "err": ""}
```

- `ok:false` 且 `err` 非空 ⇒ 直接读 `err`，它是真实异常的第一手证据
- `fps: 0` 且 `src: "tour"` ⇒ 在跑兜底路径（环绕示例），**没有跟随实时位姿**
- `pose_age_s: null` ⇒ 位姿没喂进来，**未必是渲染本身的问题**

## 1. 分清"位姿没进来"和"渲染崩了"

两个对照跑一遍：

```bash
--sync off                  # 完全不用位姿
--sync on --path-mode cam   # 用采集时的位姿回放
```

- **两个都崩** ⇒ 跟位姿无关，别再查 relay / 手眼
- 只有一个崩 ⇒ 查那条链

这一步能把排查面砍掉一半，做之前不要动任何配置。

## 1.5 两种对照都全黑（不是崩）⇒ 查归一化口径

崩溃会报错，全黑不会。这时 `/health` 一切正常（`ok:true`、`fps` 有、`src` 甚至已是
`arm`、`pose_age_s` 很小），但抓下来的帧只有 8~9 KB 且纯黑。

根因：`cameras.json` 的 `frames[]` 可能被后处理过，带 `_normalized: true` ——
里面的 `T_cam2world` 平移**已经是归一化坐标**（围绕 0、量级 ±1）。
而渲染器按 `train_report.json` 的 `normalize.center / S` 又算了一次
`S * (t - center)`，相机被推到离点云十几米的位置，画面自然全黑。
同一份 report 里的点云侧变换是对的，错的只有相机那一半。

一条命令拆分两种口径：

```bash
python3 - <<'PY'
import json
d = json.load(open(".../cameras.json"))
print("flag:", d["frames"][0].get("_normalized"))
print("center:", json.load(open(".../train_report.json"))["normalize"])
print("pos0:", d["frames"][0]["T_cam2world"][0][3], d["frames"][0]["T_cam2world"][1][3])
PY
```

判据：`flag=True` 且 `pos0` 围绕 0、量级 <±1 ⇒ 相机侧**不要再归一化**
（`S_cam=1, center=0`），点云侧保持 `S*(P-center)` 不变。
修完在启动日志里打一行确认，不要让它静默生效。

**同类的两个"画面还是老的"开关**：

- `gs_force_out.conf`：渲染壳脚本读它，只要那一行存在就**永远锁死在那份资产**，
  今天新采新训的结果完全不会被采用。查"为什么画面没变"先看它。
- 资产选择会按 `psnr_holdout` 和"最近 48 小时"过滤；老 job 是别的场景/别的标定，
  看起来 PSNR 高也不是这个工位。

## 2. gsplat 的 packed 陷阱

```
opacities = opacities.view(B, N)[batch_ids, gaussian_ids]
IndexError: shape mismatch: indexing tensors could not be broadcast
            together with shapes [0], [0, 2]
```

`nnz = 0`（没有任何高斯通过视锥 / 不透明度剔除）时 SYCL kernel 返回空批次，
上层索引形状对不上。**改 `packed=False`**。

`GS_RENDER_DEV=cpu` **不是退路**：XPU 版 gsplat 只编了 SYCL kernel，
CPU 路径在 `fully_fused_projection` 就抛错；而且 `import gsplat` 时已经打印
`Using SYCL XPU backend`，说明设备根本换不掉。

## 3. 崩之前先验资产，否则修好也是白雾

```python
rgb = 0.5 + 0.28209479177387814 * f_dc   # PLY 的 f_dc_0 / f_dc_1 / f_dc_2 → RGB
```

- 均值 ≈ 0.5 且 std < 0.1 ⇒ **高斯还是初始化灰色，模型没收敛**
- 交叉验证 `train_report.json` 的 `psnr_holdout` / `steps`（几百步的多半没收敛，
  而且可能压根没有 psnr 字段）

训练没收敛时，正确结论是"要重采图 + 重训"，不是继续调渲染参数。
把"渲染管线已修好"和"模型是灰的"分开报，别混成一句"3DGS 修好了"。

## 4. 位姿链

- 中继服务的**默认源**必须指向真实存在的机器。默认值写死一台已下线 IP，
  服务会一直"进程在跑但写不出文件"，日志只有笼统的失败行。
- `age_s == 0.0` 是**最新鲜**的值；用 `or` 兜底会把它当缺失 → 误报"过旧"。
- 判据：位姿文件的 `ts` 是否在刷新 —— `stat -c %y` 看 mtime，或连读两次比对 `ts`。
  不刷新而进程还活着 ⇒ 循环卡住或写的是别的路径。

## 4.5 整机饥饿：load 高 + 内存贴底时先降载，别修渲染

画面黑 / 掉帧未必是渲染器的问题 —— 先把整机状态读一遍：

```bash
uptime; free -m | sed -n 2p
ps -eo pcpu,rss,comm --sort=-pcpu --no-headers | head -8
sudo journalctl -k --since "-1h" | grep -iE "out of memory|oom-kill|blocked for more than"
```

判据：

- **内核日志里既没有 OOM 也没有 `blocked for more than` ⇒ 不是内存耗尽杀进程，
  是 direct reclaim（内存贴底线时每次分配都要同步回收页缓存）+ CPU 超配造成的调度饥饿。**
  它比 OOM 隐蔽：不留任何内核痕迹，只有 load 与 free 的数字能看出来。
- 典型数字：15 核机器 load 24~42、`free` 剩 200~400MB、`available` 2~9GB、swap = 0。
- 外部症状：`ping` 通、`22` 端口 TCP 能 CONNECTED，但 HTTP 全超时、SSH 拿不到 banner；
  连接队列打满后表现还会从 `TimeoutError` 变成 `URLError`（内核直接拒）。
- 这种状态下**先降载再谈渲染**。降载前先记一份 `systemctl is-enabled` 清单。

可停的只读旁路（不影响产线与采集）：

```bash
sudo systemctl disable --now zmax-550c-shadow zmax-evolve-intel zmax-symmetry-evolve
```

实测释放：`available` 154MB → 14GB，load 37 → 15.8（1 分钟均值；5/15 分钟均值滞后下降，
判效果要看 1 分钟那一格）。只 `stop` 不 `disable` 的话重启后原样复活。

同源结论：训练慢（3000 步跑一小时）多半也是这一条 —— 资源空出来后同样的活儿快得多，
不必先去怀疑数据集或超参。

**最常被忽视的触发源：训练队列并行。** 两个 3000 步 job 同时在一台 550C 上跑，
各占一个 `python` 100% CPU，叠在采集 + 渲染 + 中继之上就把 load 推到 40+，
而两个 job 自己也都推不动（进度停滞）—— 看起来像“训练坏了”，实际是互相抢。
判据：`ps -eo pcpu,comm | grep python` 里同时挂着 2 条以上训练进程。
修法：**训练队列一次只跑一个**，后面的队着（或错峰），别并发。

**过载期的 `last_error: 位姿陈旧 age=497s` 是下游症状，不是 relay 坏了。**
CPU 被抢到调度不上时，中继线程跑不动，位姿自然“陈旧”；先降载，再回头看 `age` 是否归零。
不要先去翻 relay 代码或改默认源 —— 降载后会自动好转。

## 5. 服务由 systemd 管时

`pkill` 后 systemd 用**默认配置**重启，命令行前缀的环境变量全丢。
改脚本里的默认值 → `systemctl restart <unit>`。
验证：`tr '\0' '\n' < /proc/<pid>/environ | grep KEY`。

另外有人会挂一个 `while true; timeout N python ...` 的守护循环自动重启渲染器，
所以 `pkill` 之后几秒看到新 PID 不代表你的新命令生效了 —— 先
`systemctl list-units | grep <关键词>` 确认归属，再决定改服务还是改循环脚本。
