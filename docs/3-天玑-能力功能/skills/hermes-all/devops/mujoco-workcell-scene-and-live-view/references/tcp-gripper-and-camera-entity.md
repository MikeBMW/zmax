# TCP 锚点 / 夹爪几何 / 场景相机实体

8802 场景里「末端」和「相机」最容易在两处错: 一是**锚点被删**, 二是**姿态角叠加**。两份数值都是本工位实测, 换产品时重新量, 但**量法**照抄。

## 1. TCP 锚点契约

`tools/ar_scene_render_server.py` 里有两处按名字找模型元素:

| 用途 | 查找 | 名字 |
|---|---|---|
| FK / 现位姿 | `mj_name2id(model, mjtObj.mjOBJ_SITE, "%s_tcp")` | `<side>_tcp` (**site**) |
| IK 目标 | `mj_name2id(model, mjtObj.mjOBJ_GEOM, "%s_tcp")` | `<side>_tcp` (**geom**) |

⇒ 两个对象必须同时存在、且都落在**真 TCP**: 本工位是 URDF `joint_tool1` 原点 (= 夹住的光模块头部中心)。

安全写法(挂在工作件所在的 tool1 body 里, 不污染画面):

```xml
<site name="R_tcp" pos="0 0 0" size="0.004" rgba="1 0.2 0.2 1"/>
<geom name="R_tcp" type="sphere" size="0.004" pos="0 0 0" group="5"
      contype="0" conaffinity="0" rgba="0 0 0 0"/>
```

`group="5"` (index 4) 恒关; 用 group 3 会被非顶视机位重新打开变成可见小球。

失败症状: IK 每拍 `找不到 <side>_tcp` → `_ar_cmd_ctrl` 返回 None → `mode` 一直是 `idle` → 双臂停在最后一帧,
而料盘/工件/相机照常渲染。**只看画面会误判成“相机或浏览器卡了”。**

## 2. 夹爪几何 (无夹爪 URDF 时自建)

真值: `joint_tool1` 相对 `joint_tool0` = `xyz (-0.0159, 0.0183, 0.2587)`, `rpy (0.0370252, 0.6751676, 2.3752487)` rad
= `(2.12°, 38.68°, 136.09°)`, 即 TCP 在法兰前方 258.7mm。

关键测量: **tool1 的 Z 轴与法兰 +Z 夹角 33.6°**（用 `R = Rz(y)@Ry(p)@Rx(r)` 求 `R[:,2]`，与 `(tool0−tool1)` 归一化向量点乘）。
⇒ 夹爪(法兰盘/执行器/两指)画在**法兰系**; 只有工件挂在 tool1 系。搞反 = 整组歪出腕口, 视觉上“悬空脱开”。

法兰系 z 排布(实测贴合):

| 件 | z (mm) | 尺寸 (mm) |
|---|---|---|
| 法兰盘 | 0–24 | Ø60 × 24 |
| 执行器 | 24–126 | 52 × 44 × 102 |
| 两指 | 123–265 | 20 × 10 × 142 (半长 71) |
| 光模块 | 208–265 | 8.5 × 13.4 × 56.5 (中心 z≈237) |

指的位置按**工件在法兰系的投影包围盒**定, 不是按工件自身半宽: 模块转 33.6° 后 AABB y = −14.7…+25.3mm、x = −23…+15.2mm。
两指内侧面正好贴 AABB 两侧。

MuJoCo 四元数坑: `mju_mat2Quat(q, mat)` 要 **column-major** —— 传 `np.asfortranarray(R).flatten()`。
传行主序会得到一个“看着像个姿态、其实偏几十度”的旋转, 表现为夹爪悬空。

验收三条(全给数):

```python
mujoco.mj_geomDistance(m, d, gid("R_fga"), gid("R_mod"), 1.0, None)   # ≈ 0.0000
mujoco.mj_geomDistance(m, d, gid("R_t1_body"), gid("R_fga"), 1.0, None) # ≈ 0.0033 (相邻)
# 到腕心 R_link6 世界位置的距离: 12 / 75 / 205 / 237 mm 单调递增且首尾相接
```

负值 = 指插进工件; 几十 mm = 断手; 两者在斜视特写里都只表现为“金色一小块 + 一根白条”。

## 3. 场景相机实体 (立柱 + D435 这类)

- 与 AR 页同源时要照抄 `tcp-ar.html` 的 `TCAM`(位置/半径/俯角/fov), 不要自造吊装方块。
- **姿态角是叠乘的**: `<body euler="0 35 0">` 内的 `<camera euler="0 -90 0">` 合成后才是世界朝向。
  写之前先算: 期望视轴(如 35° 俯视朝 +X = `(0.819, 0, -0.574)`), 再反推 child euler; 符号反了会变成
  朝上看。`body euler` 用 MuJoCo 角序易混, 直接给 `quat` 更稳。
- 验证不读参数, 读结果:
  ```python
  mujoco.mj_forward(m, d)
  # 视轴 = cam_xmat 的第三列取反 (camera 沿自身 -z 看)
  axis = -d.cam_xmat[cid].reshape(3,3)[:, 2]
  dist, gid_hit = mujoco.mj_ray(m, d, d.cam_xpos[cid], axis, None, 1, -1, None)
  ```
  中央射线应命中预期物体(如料盘壁 `pan0_w2` @0.355m), 不是 0.57m 外的横梁。
- **镜头不能贴着自己的顶盖**: 顶盖 Ø144、镜头只高 2.3cm + 35° 俯角 ⇒ 盖沿在光轴上方 15°, 画面下部六成是盖子。
  修法: 盖半径收到 62mm、机身沿 +X 外移 72mm(加悬臂), 使镜头在盖外 34mm。
- 机位从 −X 侧看时只看得到机身背面(深色贴在黑料盘上 ≈26×8px, 认不出是相机) ⇒ 加一块浅灰尾板 + 白标条,
  不要为了“露出蓝色镜头”去改真源俯角。

## 4. 观测点 (改完一定要能自证)

`/status.json` 现含 `mode`, `ac_err`, `ac_tgt`, `n`, `mean`, `gold_px`, `views`。
拿不出这几个数就说明改动没落地; 缺 `ac_err` 时先确认跑的是新代码(Windows 上尤其)。
