# 把真 URDF 臂搬进 MuJoCo (MJCF 片段生成 + 三大验收)

场景: 仿真场景里的机械臂是手写缩尺胶囊, 而交付/前端画的是真 URDF 网格 —— 要求"外观像 URDF、
动作和前端逐帧一致"。不要试图靠调相机/调增益凑, 必须换几何与运动学。

## 0. 先确认 URDF 能不能被 mujoco 直接吃

MuJoCo 3.x 支持直接编译 `.urdf` (纯 revolute/prismatic + STL/OBJ mesh):

```python
m = mujoco.MjModel.from_xml_path("config/.../xms5_r800_w4g3b4c.urdf")
print(m.nbody, m.ngeom, m.nmesh, m.njnt)      # 实测 7 / 7 / 7 / 6
```

两个常见报错:

- `Error opening file '.../XMS5-..._base.stl'` —— URDF 里 mesh `filename` 只写了 **basename**
  (或包名被剥掉), 解析器按 URDF 所在目录找。缺 `meshes/` 前缀时: 把 xml 和 stl 放同一层
  (或按实际前缀改 filename) 即可。**大小写敏感**: 真源里可能同时有大小写两套名字, 只拷了一套就会缺。
- `duplicate name ''` 警告可忽略 (URDF 的 geom 没名字, mujoco 会自动改名)。

⚠ 直接吃 URDF 只能验证"能编译"; 要和自己的场景 (台面/料盘/光模块/相机/执行器) 拼在一起, 仍然要
生成 MJCF 片段插进现有 `<worldbody>` —— mujoco 没有 URDF `<include>`。

## 1. 从 URDF 抽链: 只抽 revolute, 按 parent→child 顺序

```python
import xml.etree.ElementTree as ET
root = ET.parse(urdf).getroot()
for j in root.findall("joint"):
    o = j.find("origin"); a = j.find("axis")
    print(j.get("name"), j.get("type"),
          j.find("parent").get("link"), "->", j.find("child").get("link"),
          o.get("xyz") if o is not None else None, o.get("rpy") if o is not None else None,
          a.get("xyz") if a is not None else None)
```

典型 6 轴链 (珞石 R800 口径):

| # | parent→child | origin xyz | axis |
|---|---|---|---|
| joint_1 | base→link1 | 0 0 0.328 | 0 0 1 |
| joint_2 | link1→link2 | 0 0 0 | 0 1 0 |
| joint_3 | link2→link3 | 0.05 0 0.4 | 0 -1 0 |
| joint_4 | link3→link4 | -0.05 0 0.4 | 0 0 1 |
| joint_5 | link4→link5 | 0 0.136 0 | 0 -1 0 |
| joint_6 | link5→link6 | 0 0 0.1035 | 0 0 1 |

fixed joint (world→base, link6→tool0/tool1) 不产生 hinge; mesh 的 `scale="0.001 0.001 0.001"` 要在
`<asset><mesh>` 上原样保留 (mm→m)。

## 2. 生成 MJCF 片段 (可直接照抄的形状)

```
<body name="R_link0" pos="bx by bz">                        <!-- 基座: 只有 mesh, 无 joint -->
  <geom name="R_g0" type="mesh" mesh="R_m_base"/>
  <body name="R_link1" pos="0 0 0.328">                    <!-- joint_1 的 origin 挂在 link1 上 -->
    <joint name="R_j0" type="hinge" axis="0 0 1" range="-175 175"/>
    <geom name="R_g1" type="mesh" mesh="R_m_link1"/>
    <body name="R_link2" pos="0 0 0">
      <joint name="R_j1" type="hinge" axis="0 1 0"/>
      ...
```

要点:

- **第 k 个 hinge 名 `R_j{k}` 必须对应 URDF `joint_{k+1}`**, 且 origin 挂在它要驱动的那个 link body 上。
- 左右臂共用同一份 stl, `<mesh name="{side}_m_{link}" file=...>` 各注册一套即可。
- 原来代码里的 `<side>_tcp` geom、`endEffector` site、`<side>_act{k}` 执行器、`<side>_finger{a,b}`
  这些**名字必须保持不变** —— 下游 IK / runtime / 前端都按名字取。
- mesh geom 有体积 ⇒ 默认会参与碰撞; 若臂常常贴着台面/箱体, 会自己把自己弹开, 先跑一步验证静止姿态。

## 3. 三大验收 (缺一条就会"看着对、其实错")

1. **轴对拍**: `m.jnt_axis[jid]` vs URDF `axis`, 逐条。错位时能全部"看起来合理"但整体差一格。
2. **FK 对拍**: 同一组关节角, mujoco `geom_xpos[tcp]` vs 前端 tool0, 合格 <1mm。
   ```python
   for k in range(6):
       j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "R_j%d" % k)
       d.qpos[m.jnt_qposadr[j]] = np.radians(q_deg[k])   # ⚠ 用 jnt_qposadr, 不能直接 qpos[j]
   mujoco.mj_forward(m, d)
   ```
   `d.qpos[jid]` 是最常见的自坑 —— 会"静默无效果", 表现为"设了角但姿态没变"。
3. **静差**: 若靠 position actuator 收敛, 量稳态误差。真 6 轴链 kp=300 时 15.9°/57~217mm;
   镜像用途直接写 qpos (见 SKILL.md 同节), 不要靠加 kp 硬顶 (kp=1500 仍在 15°)。

## 4. 与前端对接: 谁算 IK 只能有一个

两个前端各解一次 IK ⇒ 目标相同、姿态不同 (肘上/肘下分支)。可用的结构:

- 前端 (画布) 算完把**关节角(度)** POST 到渲染服务 (`/armq`), 写 `zmax_data/ss_live/ar_mj_q.json`:
  `{t, R:[6], L:[6], seq}`; 渲染端读新鲜文件 (≤1.5s) 直接执行, **不再解 IK**。
- 前端某一侧没有独立位姿时, 要按画布自身的退化规则补 (如画布"左臂照抄右臂"), 否则渲染里那只臂
  停在 home, 看起来就是"两边动作不一致"。
- 渲染端仍要保留原来的 IK 兜底 (没人在推关节角时按目标点自解), 且把"数据源/年龄"打进
  `/state.json`, 否则调不出是谁在驱动。

## 5. 冻包/CI 注意

`config/*/urdf/meshes` 很容易没进包 (data 目录被 gitignore, CI 里又被建成空占位目录)。
部署后必须实测 `mesh_geoms = xml.count('type="mesh"')` 与 `capsules` 计数 —— 只看服务 `ok:true`
看不出退回了简化模型。
