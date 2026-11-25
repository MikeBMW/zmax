# IndexError: shapes [0], [0, 2] — 从“后端退化”分到“内参错”

症状（gsplat 1.5.3+pt210xpu / SYCL XPU）：

```
File "gsplat/rendering.py", line 516, in rasterization
    opacities = opacities.view(B, N)[batch_ids, gaussian_ids]  # [nnz]
IndexError: shape mismatch: indexing tensors could not be broadcast together
with shapes [0], [0, 2]
```

含义：**nnz = 0**，一个高斯都没投到画面里。两种原因报同一个错，必须分开。

## 第 0 步：拿到完整 traceback

渲染服务把异常压成 `str(e)` 塞进 `/health` 的 `err`，**栈全丢**。在缓存那行前插打印：

```python
STATE["err"] = "%s: %s" % (type(e).__name__, str(e)[:120])
# ↑ 这行前面加：
#   traceback.print_exc()
```

改完重启服务、请求一次 `/frame.jpg`，`/tmp/<log>` 里就有完整栈。
（注入脚本要处理 `sudo`；文件常是 root 所有。）

## 第 1 步：交叉实验（15 分钟，四个组合）

| 组合 | ply | cameras | 若挂说明 |
|---|---|---|---|
| A | 老（已知能渲） | 老 | 基线坏了 —— 先别查业务 |
| B | 新 | 新 | 待定 |
| C | **新** | **老** | **C 挂 D 通 ⇒ ply / 位姿问题** |
| D | **老** | **新** | **D 挂 ⇒ cameras 解析问题** |

实测结论是 **A ✅ / B ❌ / C ❌ / D ✅** ⇒ 问题在 ply 所依赖的位姿，不在 cameras 解析。

每组合起一个**独立端口**（8841/8842/…），轮一次 `/health` 再杀，别占用生产端口 8816。

## 第 2 步：先量 ply 数值健康度（排除 NaN/Inf/坏四元数）

```python
# 逐属性统计 nan/inf、四元数模长、exp(scale)、位置范围
```

实测两个 ply 都健康（0 NaN / 0 Inf / 四元数模长恒 1.000000 / exp(scale) 中位 1e-2）
⇒ **不是数据损坏**，别在这条上继续。

同一个脚本顺带看位置范围 —— 这一步是后面定位内参的关键：

```
141621(能渲) 位置范围 [-0.326~0.002, -0.675~-0.349, -0.441~-0.2]
merged_3k(挂) 位置范围 [ 0.285~1.279, -0.535~0.649, -0.001~0.663]
```

## 第 3 步：直接调 gsplat 抓最小复现（关键分水岭）

**绕开渲染服务**，自己在 venv 里加载 ply + 调 `gsplat.rasterization`。

这一步的意义：如果**两个 ply 都能渲**，问题就在服务代码路径（K/W/H 的推导），不在数据。
（实测就是这么跳出来的：两个都 `✅ 渲染成功 img shape (1,480,640,3)`。）

## 第 4 步：读渲染服务怎么推 W/H 和 K

```python
cj = json.load(open(a.cameras))
W0, H0 = int(cj["width"]), int(cj["height"])       # ← 从 cameras.json 顶层读
W, H = (a.width, int(a.width * H0 / W0)) if a.width else (W0, H0)
K = np.array(cj["K"], dtype=float)
if W != W0:
    K[0] *= W / W0
    K[1] *= H / H0
```

看 `/health` 回显的 `w/h` 反推 `W0/H0`：

```
141621   -> 960 x 543   =>  W0/H0 = 848 x 480
merged_3k -> 960 x 720   =>  W0/H0 = 640 x 480   ← 可疑
```

## 第 5 步：核 cameras.json 声明 vs 图片真实像素

```python
for n, p in [('141621', ...), ('merged', ...)]:
    d = json.load(open(p))
    print(n, d['width'], d['height'], d['K'])
```

```
141621 848x480  K = [[513.21, 0, 422.49], [0, 387.42, 238.30], [0,0,1]]
merged 640x480  K = [[387.93, 0, 319.35], [0, 388.24, 238.80], [0,0,1]]
```

**同时量图片真实尺寸**（不要信 meta / cameras 的声明）：

```python
from PIL import Image
Image.open('<ds>/images/' + os.listdir('<ds>/images')[0]).size   # -> (848, 480)
```

⇒ 声明 640×480、实际 848×480。`cx=319.35 ≈ 640/2` 也印证了 K 是 640 口径标的。

## 修复

```python
sx = W_img / W0          # 848/640 = 1.325
sy = H_img / H0          # 480/480 = 1.000
K[0] *= sx; K[1] *= sy
d['width'], d['height'] = W_img, H_img
# 备份 d + '.bak_640fix'
```

修完的 fx=514.00 / cx=423.14，与能跑那份的 513.21 / 422.49 **几乎重合** —— 这是最有力的交叉验证。

## 最后一步：必须重训

旧 ply 是“为了拟合错误内参下的图像”优化出来的，高斯位置本身就是错的 ⇒ 换 K 也渲不出来。
用 **500 步 / 50k** 快速验证（约 5 分钟），判据：

```
/health -> {"ok": true, "gaussians": 50000, "w": 960, "h": 543, "fps": 5.0, "err": ""}
/frame.jpg -> 16 KB（不是 18 字节的 "still initializing"）
```

过了再开长训。

## 顺带两个环境坑

1. **训练与渲染抢同一块 XPU，20 万高斯级会卡在设备上传**（进程 31 线程全在 `poll_schedule_timeout`、
   `/frame.jpg` 长期回 18 字节 `still initializing`）。要切资产就得先把 XPU 腾出来。
   给渲染器加 `GS_RENDER_DEV=cpu` 也救不了：这套 gsplat 核是 SYCL 编的，CPU 模式直接报
   `RuntimeError: means must be a XPU tensor`。
2. **`pkill -f gs_render_stream_intel` 杀不干净 `setsid`/`nohup` 起的孤儿**，而新进程 bind 失败是**静默的** ——
   你明明用新 ply 起了一遍，`/health` 一直报旧高斯数。判据只看端口主人：
   `sudo ss -ltnp | grep :8816` 取 pid → `tr '\0' ' ' < /proc/<pid>/cmdline` 读它的 `--ply`。
3. **`date.today()` 过滤会在过零点后把昨晚训的资产全滤掉** ⇒ pick 回落到次优。用最近 48 小时窗口。
4. **自动挑资产的壳会抢生产端口**: 修好资产后若 `gs_render_loop.sh` 还在跑, 它按 PSNR 重挑时可能又把你手动起的进程挤掉(或反过来你的 bind 失败)。
   手动接管 8816 前**先 `pkill -f gs_render_loop.sh`**, 再按端口取 pid 杀旧进程, 最后才 diff `/health` 的 `gaussians` 与目标 ply。

## 修好内参后仍然不清晰/报错的两个岔路

### 岔路 A: 实时视角满屏尖刺(holdout 视角却很清楚)

先分清"同一个模型、两个视角":

```
holdout_00.png (训练视角渲染)  → 31.06 dB, 结构完整
/frame.jpg    (arm 实时位姿)   → 放射状尖刺
```

⇒ 不是模型坏, 是**该视角没被覆盖**。判据(一条命令算完):

```python
d = json.load(open('/tmp/arm_tcp_pose.json')); tcp = np.array(d['t'])
X = np.array(json.load(open('<handeye>'))['T_cam2tool'])
Tb = eye(4); Tb[:3,:3] = q2R(d['q']); Tb[:3,3] = tcp
Tcw = inv(Tb @ X); c = Tcw[:3,3]                      # 相机中心
cj = json.load(open('<ds>/cameras.json'))
T = np.array([np.array(f['T_cam2world'])[:3,3] for f in cj['frames']])
for ax,i in (('x',0),('y',1),('z',2)):
    print(ax, c[i].round(3), T.min(0)[i].round(3), T.max(0)[i].round(3), lo<=c[i]<=hi)
```

实测 `y=-0.792` vs 训练 `-0.401~0.551` ⇒ 越界 391mm; x/z 都在内。**只看一个轴越界就足以整片尖刺。**

处置二选一:
- 把臂沿越界那一轴移回覆盖区(需要授权, 实测约 400mm);
- 给渲染器加 `--path-mode cam`: 按 `cameras.json` **原序**回放采集位姿, 不排序不插值 ⇒ 每一帧都是训练过的视角,
  `/health` 的 `src` 报 `cam`(与 `arm`/`tour` 区分), fps 正常。适合"臂不动但页面必须有清晰画面"。

### 岔路 B: 想靠"给实时位姿补一套归一化参数"修错位 —— 别加

先读 `train_report.json` 的 `normalize`。**恒等(`center=[0,0,0] S=1.0`)= 正常**, 说明 `cameras.json` 的 `T` 已在 ply 空间里,
渲染端那句 `t = S*(t0-center)` 就是恒等变换, 直接喂实时位姿没错。此时再加 `--live-norm-center/--live-norm-s`
(哪怕是训练前的原始 center/S)会**双重归一化** ⇒ 相机被打到视野外, 同样报 `shapes [0], [0, 2]`。
判据: 加参数前后各取一次 `/health` 的 `ok`; 加了更差就立刻去掉, 别沿着这条继续调。

### 反例: 别用"截取 ply 前 N 个高斯"二分找阈值

```
N=50000    ❌    N=100000 ❌    N=200000 ❌    N=400000 ✅(1.8fps)    N=640999 ✅(1.7fps)
```

完整模型能渲而前缀截断全挂 ⇒ 前缀里主要是飞点/背景, 截断等于把场景删掉。**这条二分法给出的"高斯数阈值"是假的**, 别据此降高斯数。
