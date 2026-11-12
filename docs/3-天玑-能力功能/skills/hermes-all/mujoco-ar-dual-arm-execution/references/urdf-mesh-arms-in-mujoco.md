# 把真 URDF 机械臂搬进 MuJoCo 场景 (外形 + 运动学同源)

用途: AR 画布里的臂是 URDF 网格(FK 出来的真六轴), 而 MuJoCo 渲染出来是“光秃秃一根棍子”、
动作也不一致。这里是把两边做成**同一几何 + 同一运动学 + 同一组关节角**的完整做法与判据。
判据: 同一组关节角, MuJoCo 正解 TCP 与页面正解 TCP 差 <1mm; 实时残差 <30mm。

## 1. 为什么是棍子 / 为什么动作不一致 (两个独立病因)

- 外形: 手写 MJCF 常用 `<geom type="capsule" size="0.022">` 拼 6 段缩尺链 ⇒ 渲染只有光棍。
  URDF 里每节 link 有真实 STL, 曲面/法兰/关节壳都在。
- 动作: 缩尺链的**链长**(自定义 0.06/0.18/… ) 与真机 URDF (0.328/0.4/0.4) 不同,
  同一个 TCP 目标由两个不同运动学各解一次 ⇒ 关节角完全不同。这是模型问题, 不是延迟/帧率。

## 2. MuJoCo 直接编译 URDF (先验证可行性)

`mujoco.MjModel.from_xml_path("x.urdf")` 在 MuJoCo 3.3 可用; 成功标志:
`nbody/ngeom/nmesh/njnt` 与 URDF 的 link/visual/joint 数对得上 (实测 7/7/7/6)。

常见失败只有一个, 且与内容无关:
- `Error opening file '.../XMS5-R800-W4G3B4C_base.stl': No such file or directory`
  ⇒ URDF 里 `filename` 只有**文件名**, MuJoCo 按 URDF 所在目录解析, 而 STL 在 `meshes/.../` 子目录且**大小写不同**。
  处理: 生成 MJCF 时写**绝对路径**到真实文件; 只做编译验证时可在临时目录把 STL 铺平并补大小写别名。
- `Geom with duplicate name ''` 是 URDF→MJCF 的常态告警, 不影响编译。

不要指望 `MjSpec.from_file(urdf)` 再 `to_xml()`: 它按 MJCF 解析, 报 `Only compiled model can be written`。
要拼进自己的场景, 就自己按 URDF 的 link/joint 生成 MJCF body 树 (下面)。

## 3. URDF → MJCF 映射 (最容易写错的一处)

URDF 结构是 `base(fixed to world) → joint_1(origin 0 0 0.328, axis z) → link1 → joint_2 …`。
正确映射:

```
<body name="R_link0" pos="bx by bz">          <!-- 基座: 只放 base 的 mesh, 不挂 joint -->
  <geom type="mesh" mesh="R_m_base"/>
  <body name="R_link1" pos="0 0 0.328">       <!-- joint_1 的 origin 落在 body pos 上 -->
    <joint name="R_j0" axis="0 0 1"/>        <!-- joint_1 名 j0 -->
    <body name="R_link2" pos="0 0 0">
      <joint name="R_j1" axis="0 1 0"/>      <!-- joint_2 -->
      …
```

🔴 **基座上不能再挂一个 j0**。多挂一个绕 z 的基座 joint, 会让 `R_j0..R_j5` 相对 URDF
`joint_1..joint_6` **整体错位一格**: 模型里实测变成 `R_j1 axis=[0,0,1]`、`R_j3 axis=[0,-1,0]`,
而 URDF 是 `joint_2=y`、`joint_4=z`。后果是两边喂同一组角、末端差到 200mm 级,
画面上就是“动作完全不一致”, 而且 IK/PD/同步通道全都“看起来正常”。

自检命令 (每次改完必跑):

```python
for k in range(6):
    j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "R_j%d" % k)
    print(k, m.jnt_axis[j])      # 必须与 URDF joint_{k+1} 的 axis 逐一相同
# 再用页面/URDF 侧的 q 做正解, 比 TCP:
#   MuJoCo [0.4822, 0.2011, 0.3688] vs 页面 [0.4822, 0.2012, 0.3689]  ⇒ 0.1mm 合格
```

其它对齐项: mesh `scale="0.001 0.001 0.001"` (URDF 常是 mm); 关节名换成 `%s_j%d` 但**下游
(ik_solve/`_apply_ctrl`/bones) 本来就按 `%s_j%d`+`%s_act%d` 找**, 名字保持一致就不用改下游。
`%s_tcp` 放 link6 原点 (tool0), site `endEffector` 放右臂末端。

## 4. 缺 mesh 必须软回退, 不能崩

冻包/CI 里 `config/.../urdf/meshes` 常是空占位。生成前先 `meshes_ok()`, 缺 STL 就回退旧简化链
并照样出图; 否则渲染线程抛异常 ⇒ 端口活着但不出帧 (假活)。留 `ZMAX_AR_MJCF=simple` 一键回滚。

## 5. 姿态一致性: 别用 position actuator 跟画布

真 URDF 链自重大 (每节 2~5kg), position actuator 有明显静差:
实测 kp=300/kv=20 → j0/j1 各差 **15.9°**、末端差 57~217mm; kp 提到 1500/80 仍不到位。

AR 叠加要的是“同一组角 = 同一姿态”, 不是伺服精度。做法 (kinematic override):

```
每拍: mj_step × N  (物理照常跑光模块/工件)
      _apply_kin(): qpos[joint] = radians(页面给的角度); qvel[dof] = 0
      mj_forward()
```
实测残差从 217mm 降到 ~24mm, 肉眼不可分。只在“页面推角”这条通道上开, 不要用在需要真接触力的任务上。

## 6. 单一指令源: 页面直推关节角 (`POST /armq`)

两个 IK 求解器 (页面 JS / 服务端 Python) 对同一 TCP 目标会落**不同分支**(肘上/肘下),
几何一致也照样姿态不同。所以让**算的一方**是唯一来源:

```
页面 (画布每帧已算出 q, rad) --8Hz POST--> 8802 /armq {R:[deg×6], L:[deg×6], seq}
8802: 写 zmax_data/ss_live/ar_mj_q.json (原子 replace), 渲染循环读 (≤1.5s 新鲜)
      ⇒ 优先于 /control, 也不解 IK
```

- 页面无独立左臂位姿时, **左臂照抄右臂的角度** —— 画布本来就这么画; 不照抄就会出现
  “渲染里左臂停在 home、右臂在动”的不对称, 被误判成几何错。
- 页面只在**播放/预览**时才算出 q (空闲时 `PREV.q=null`), 空闲不推送是正常现象,
  别据此判“通道没接上”; 验证方法: 点一次预览动作, 15s 内看 `ar_mj_q.json` 的 `t/seq` 在变。
- 页面 HTML 是**热读**的 (改完 F5 即生效, 不用重启 8797 服务)。

## 7. 8802 页面/直播叠加的三个坑

- **直接改 `<img>.src` 换帧会闪黑帧**: 浏览器先清空再加载 ⇒ 画布“疯狂跳动”。
  双缓冲: `const pre=new Image(); pre.onload=()=>{ MJ.img.src=url }; pre.src=url;`
  判据: 连拍 2~3s, 画布区亮度应稳定 (实测 mean 50.4~50.6、亮像素 30.7% 恒定)。
- **拉图频率别超过 ~2Hz**: 每张要现场渲染 60~150ms, 画布 2.5fps + 直播窗 10fps + 50Hz 物理
  会把渲染线程打满 (ms 在 39~148 之间抖), 新帧到达不齐同样表现为“跳”。
- **相机参数有优先级**: 页面推的相机 (`POST /cam` → `ar3d_cam.json`) 优先于服务端预设;
  预设只影响没有页面时的 `?cam=` 直取。改预设不会影响画布叠底的对齐。

## 8. 取景与亮度 (目检合格线)

- **两臂会叠成一条轮廓**: 两臂基座在 y=0 / y=0.5 时, 视线沿 y (方位 -51°/-72°) 两台臂投影重合,
  近臂把远臂整个遮死。看两臂必须让方位**垂直于两臂连线** (方位 0°, 沿 x 看)。
- **纯黑背景不是曝光问题**: 是画面上半没有几何。加背板要放在**相机对侧** —— 方位 0° 时相机在 -x 侧,
  背板若也放 -x 会挡在相机与场景之间, 整幅糊成一块灰 (实测 frame.png 只有 13.8KB、全灰)。
- **亮度验收口径**: 料盘槽唇 vs 盘面差 ≥25 灰阶、全图 p90 ≥90 才算够目检 (初始只有 11 灰阶)。
  性价比最高的手段是 MuJoCo `<visual><headlight ambient="0.6" diffuse="0.7"/>` + 一盏料盘正上方补光,
  改灯光不动几何与标定。
- 换真臂后臂高变 1.2m (旧缩尺链 0.6m): 相机 lookat z 要跟着抬, 否则腕部/夹爪被上边界切掉。

## 9. 一次改动后的验收清单

1. `meshes_ok()` 为真, `build_mjcf()` 里 `type="mesh"` 数 = 2×7、`type="capsule"` = 0。
2. `jnt_axis` 六轴与 URDF 逐一相同; 同一组角 FK vs 页面 <1mm。
3. `/status.json` `ok:true`、`ms` 正常、`gold_px` 非 0。
4. `/frame.png?cam=ar3d` 200 且字节数正常 (全灰/极小字节 = 背板挡镜头)。
5. 页面播放时 `ar_mj_q.json` 的 `t/seq` 在变, `/bones.json` L/R TCP 与页面 FK 差 <30mm。
