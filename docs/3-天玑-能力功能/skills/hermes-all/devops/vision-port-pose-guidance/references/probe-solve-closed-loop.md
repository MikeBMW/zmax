# probe → solve 真跑一次(真机落地细节)

SKILL.md 的铁律 2 说"mm/px 与轴符号都不许猜, 先走 2mm 测"。这份是那一步真落地时的细节:
服务侧算法已经 OK, 坑全在**运动侧**和**验收口径**上。

## 顺序(一次跑完, 别拆成两轮人工)

```
① 读真值位姿(桥/控制器实时)        ← 不信缓存文件、不手推
② 授权 + 上电 + 模式 三道守卫
③ POST /guide_pose mode=probe      → pose_target(只变一个分量)
④ 下发单轴小步(speed 5mm/s)
⑤ 等"真值稳定"(不是等回执)
⑥ POST /guide_pose mode=solve      → 反算 k_mm_px + axis_sign, 落盘
⑦ 再调 auto → 若仍偏, 继续走终值直到 act=hold
```

先 `--dry` 跑一遍只算不发, 把 ③④ 的目标位姿打印出来核一眼, 再真跑。

## 运动侧守卫字段名是最容易白费一轮的地方

读控制器/桥的 status, 字段取值常是**枚举字符串**, 不是 `idle` 这种直觉词:

| 字段 | 实测取值 | 正确判法 |
|---|---|---|
| `operateMode` | `OperateMode.automatic` / `manual` | **要求 `automatic`**(自动态才收 SDK 下发)。⚠️ **不要拿 `idle` 判模式** —— idle 是"是否在运动中"(`operation_state`), 不是模式 |
| `powerState` | `PowerState.on` / `off` | `"on" in s.lower() and "off" not in s.lower()`。用 `s.lower() in ("on","1","true")` 会**永远为假** |

症状就是"守卫自己把自己挡住了": 打印出来明明是 `PowerState.on` / `OperateMode.automatic`, 脚本却报未上电/非自动, 一次都没动。
⇒ 先把 status 原样 dump 出来看取值, 再写判据; 判据写宽一点(子串包含)比写窄安全。

## 姿态: 原样回传, 用 rpy→quat 重建

- 很多控制器 status 只给 `endInRef = [x,y,z,rx,ry,rz]`(位置 m + rpy rad), **不给四元数**,
  而运动接口要 `q`。自己转, 别指望有现成的:

```python
def rpy2quat(rx, ry, rz):            # ZYX 欧拉 → (x,y,z,w)
    cx, cy, cz = math.cos(rx/2), math.cos(ry/2), math.cos(rz/2)
    sx, sy, sz = math.sin(rx/2), math.sin(ry/2), math.sin(rz/2)
    return [sx*cy*cz - cx*sy*sz,
            cx*sy*cz + sx*cy*sz,
            cx*cy*sz - sx*sy*cz,
            cx*cy*cz + sx*sy*sz]
```

- **姿态用起走前读到的 q0 原样回传**, 不要每步重读 —— 重读会把前一步的微小漂移累进目标, 而这类任务只该有 1 个自由度。
- 验收时**单独看姿态漂移**: 实测三步全程 ≤0.001°, 这才证明"只平移没带姿态"真的成立。

## 认真值, 不认回执

下发接口 `/move_pose {p,q,speed,dry}` 回 `ok:true` 只代表"受理", 不代表"到了"。

```
循环 up to ~25s:
    读真值 p_n
    if 相对起点位移 > 0.15mm: moved = True          # 真的动过
    if 与上一拍差 < 0.03mm(连续 3 拍): 判稳定, break
```

- 两个判据缺一不可: **moved**(防"回执成功但一位没变"的假到位) + **stable**(防"还没停就发下一条")。
- 实测正常一步: `Δ=+0.000/+2.001/+0.000 mm`, 误差 0.001mm ⇒ 报数时写这个实测 Δ, 不要重复回执里的目标值。
- `moved=False` 就直接**中止并报错, 不要写标定** —— 没动还写标定 = 把错误的 k 固化下来。

## solve 的产出怎么对账

```
probe_dpix = -176.32      # 走 2mm 让中心从 1567 → 1390 的像素差
k_mm_px    = 0.011343     # = 2 / 176.32
axis_sign  = +1
```

- `k` 要落在**先验估值带**里(按工件尺寸估的那条带), 落在带外先怀疑"动的不是你以为的那根轴"。
- 符号对账用**用户给的方向语义**("沿世界 Y 向屏幕左")核对: 走 +Y 后中心 px **变小** ⇒ +Y 就是屏幕左。
  符号反了不要改 `axis_sign` 去凑, 回头查轴的定义。
- 标定文件里**留着 `probe_dmm / probe_dpix`** —— 这是唯一能事后复算 k 的证据, 只存 k 就没法审计。

## 收尾: 走到 `act=hold` 才算闭环
只验证"solve 出了数"是不够的, 必须再走一次终值直到服务回 `act=hold`:

```
off_px  343.0 → 166.2 → -4.1   (tol 20px ⇒ hold)
Y       +0      +2.0    +4.0 mm
```

- 收到 `hold` 时把**实际总位移**和**最终 off_px** 一起报出来, 这是"居中"的唯一硬证据。
- `hold` 阈值别为了好看调小 —— 容差边缘会持续抖着发指令(见铁律 5)。

## 想退回来

试探步是 `d_mm`, 反向走 `-d_mm` 就回原位。脚本留 `--undo` 比事后手动挪靠谱:
手动挪会漏掉"姿态也要一起回填"这件事。
