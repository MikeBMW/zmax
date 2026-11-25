# 把外部相位轨迹（带 AOI 检测）搬进 ar3d

用途：把一条**带工艺相位标注**的真实轨迹（抓取→扫码→插入→等待检测→金手指检测 1/2→侧面点 1~4→下料）
渲染到 `/ar3d` 并能仿真回放。真机不动。

## 真源：`192.168.23.50:8815/api/geo`

```
{ok, set, n:251, len_mm:5888, states:[{i0,i1,name}...26 段],
 frames:[{i, p:[mm,mm,mm], n:[法向], phi, q:[w,x,y,z], dn, dphi, spd, s, s_mm}]}
```
`states` 是相位表，`name` 不含「移动」的是停留相位（检测/抓取/插入）。这是判断
「这条轨迹到底含不含 AOI 检测」的唯一依据 —— 看 `金手指检测1/2` + `侧面点1~4` 在不在里面。

同类看板还有 `/api/se3`（实时 TCP + 最近点 + phi）、`/api/ver`。**没有** `/api/traj`、`/api/phase`。

## 两个落地通道（都不用重启 8797）

8797 是 systemd 起的，禁止自行重启 ⇒ 只能走已有的文件/接口通道。

| 目的 | 通道 | 做法 |
|---|---|---|
| **只在三维里看见这条线** | `map` key 读 `zmax_data/ss_live/explore_traj_fenced.json` | 把 frames 的 p 转米写进该文件的 `pts`，页面点「轨迹3 建图」即可（先 `cp -a` 备份原建图轨迹） |
| **让仿真右臂沿它走** | `/api/orbit_frames` 读 `zmax_data/capture_plan/{port_sweep,port_orbit}_joints.json`（取 mtime 最新） | 把 frames IK 成 `{p,q,j,t}` 写进 `port_orbit_joints.json`，页面 `fetch` 后 `rtrajPlayJoints(d)` |

`map` 通道的 label 会照旧叫「建图(自主探索)」——在 `loadNamed()` 里按 `note` 认出来改名，
否则页面写着「建图」而画的是一条带 4 个 AOI 检测位的工艺闭环，看的人会误解。

## 三个致命单位/格式坑

1. 🔴 **`q` 是 `[w,x,y,z]`，不是 `[x,y,z,w]`**。
   拿真机当前位姿反推验证：按 wxyz 解出的工具 z 轴与真机差 **5.2°**，按 xyzw 差 **140.5°**。
   顺序搞错 ⇒ IK 从 66% 收敛掉到… 实测首轮 84/251 点 ik_err>5mm，看着像「轨迹本身不可达」，实际是姿态全错。
   **换新数据源先做这一步反推验证，别直接信字段名。**
2. 🔴 **`t` 必须是秒**。frames 里自带的 `s` 是弧长归一化(0~0.93)，直接当 `t` 用 ⇒ `dur=0.93s`，
   一整条轨迹一闪而过，看起来像「播放器坏了」。`t = i / 25.0`（25fps）。
3. `p` 是 mm，服务端 `pts` 要米；`j` 是弧度。`real_traj_joints.json` 的 `unit` 字段明写 `j: rad / p: m`。

## IK 连续性：解支跳变比不收敛更毁画面

`tools/phase_traj_ik2.py` 的做法（可直接复用）：
- TCP → 法兰：`flange = tcp - R[:,2] * TOOL_LEN`（0.2587m）；
- 每步**限幅** `max_step=0.06 rad`，不限幅会在解支间跳（实测出现单帧 180°、J6 冲到 −394°）；
- 不收敛**沿用上一帧关节角**（画面停一下），绝不插值到未来解 —— 插值会把两个不同解支直接连起来；
- 收尾做 ±2π unwrap；
- 仍 >15° 的帧对，**插入关节空间过渡帧**（每帧 ≤6°，位置同步线性插值）。

验收口径：`max_joint_step_deg ≤ 15` 才可播。否则用户会看到手腕凭空翻一下。

修完仍会有 10~20% 帧是「沿用上一帧」—— 这是数据本身超出可达域，
要在交付说明里讲清「播到那几处会停一下」，不要说成「平滑回放」。

## 渲染侧：让这条线一打开就在

`loadNamed('map')` 默认全部轨迹关闭 ⇒ 用户打开页面看不到，会直接说「没有啊」。
交付「渲染上去」= 打开即见：在 `window load` 里延时 ~1.2s 自动 `loadNamed('map')`，
并把按钮文字改成准确的（如「轨迹6 相位·AOI」）—— 只改 label 不改按钮名，用户照样找不到。

## 验证口径（缺一不可）

- `NAMED_ON['map'] === true` 且 `NAMED['map'].length === n`；
- `window.__NAMED_VIS__['map'] === {ok:n, total:n}`（全部在视锥内，不是画到视角外）；
- 回放：`RTRAJ.playing === true` 且 `RTRAJ.fi` 在前几秒内递增（`dur` 等于秒数而不是 ~0.9）；
- 真机零变化：`zmax_data/rokae_sdk/tcp_out/latest.json` 的 x/y/z 前后逐位相同 + `op=idle` + 无 `arm_step_traj` 容器。
