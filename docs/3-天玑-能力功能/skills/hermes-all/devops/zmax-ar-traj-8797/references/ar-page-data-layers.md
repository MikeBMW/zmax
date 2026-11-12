# 8797 AR 页的臂从哪来: 三层数据源与各自闸门

页面上的“机器人”不是一个东西, 是三层叠加��**排查“没有臂 / 臂不动”必须先定位是哪一层**:

| 层 | 数据源 | 接口 | 何时有 |
|---|---|---|---|
| 真机臂 | 真机 TCP 位姿 | `/api/tcp` | 只有接真机时 `ok=true` |
| 仿真双臂 | 8802 骨骼真值 | `/api/sim_bones`(8797 代理 `/bones.json`) | 8802 在跑且已出 ENV |
| 动作帧 | 画布 Plan 节点写盘 | `zmax_data/ss_live/ar_cmd.json` | `ZMAX_UPH_AR_PUB=1` 才写 |

## 排查顺序

1. `curl /api/tcp` → `ok=false` 说明这台机器没有真机位姿, “真机臂”层永远空, 不是 bug。
2. `curl /api/sim_bones` → 看 `ok`、`n`、`L`/`R` 各自连杆数。`ok=false` 就去查 8802。
3. 两层都有了但画面还是空 ⇒ 页面层(开关/渲染/主刷新链), 见下。

## 仿真臂不生: 8802 的 GL 依赖

`ar_scene_render_server.py` 在无桌面会话(Windows 服务/会话 0/无 GL)里 `mujoco.Renderer(...)`
建不出来。如果这个构造写在 `env.reset()` 同一个 try 里并直接抛, 整个循环每 2-3 秒重试一次,
ENV 永远不就位 ⇒ `/bones.json` 一直“未生成”。

规则: `Renderer` 单独包 try/except —— 失败就降级成“只跑物理 + 只出骨骼”, 照样把 `arms_cmd.json`
和 `/bones.json` 供出去; 页面只要骨骼, 不需要渲染帧。

## 双臂不动而画布在动: `ZMAX_UPH_AR_PUB` 闸门

三维双臂只跟 `ar_cmd.json` 的执行帧走。写它的是画布 Plan 节点(`plan_long_impl.py`),
入口处 `_AR_PUB = (ZMAX_UPH_AR_PUB == "1")`, 未设 ⇒ 一字节不写 ⇒ 页面就停在初始姿态。

- 启动入口要 `os.environ.setdefault("ZMAX_UPH_AR_PUB", "1")`;
- 生产机 systemd 里显式写 `0` 的不会冲突(`setdefault` 不覆盖已有值)。

## 页面默认什么都不显示: 自动开层

没接真机的机器上, “真机臂”空 + SIM 骨骼层默认关 ⇒ 画面一条臂都没有, 用户会报“没有机器人”。
规则: 页面要判**位姿是否新鲜**, 不是判 `ok` —— `ok=true` 只说明文件读到了, 位姿可以陈旧到几天
(`/api/tcp` 同时给 `age_s` 与 `stale:true`, 实测 250037s / stale)。自动开层的条件写成
`!(TCP && TCP.ok && TCP.age_s <= 8 && !TCP.stale)`; 只判 `ok` 的版本会让断链机器永远停在
“一条臂都没有”, 而且页面看起来一切正常。接真机且位姿新鲜时这段不触发。

## 「只有光模块, 也不动」: 四条源逐个量年龄, 不要先改页面

三维里只剩静态几何(典型: 光模块)、一帧不动 ⇒ 没有一条驱动源是新鲜的。四条各有一份真值, 按顺序量,
**每条都报年龄/hz, 不要只报 ok**:

| 源 | 判据 | 过期口径 |
|---|---|---|
| 真机位姿 `/api/tcp` | `age_s` / `stale` | ≤8s 且非 stale; 回 `stale:true` 就是断链 |
| 动作帧 `/api/ar/cmd` | `age_s` / `fresh` / `src` | ≤3s(`AR_CMD_FRESH_S`); 过期页面回落到自身播放 |
| 相机 `/api/cams` | 每路 `online` / `age_s` / `fps` | `online=false, age_s=-1, fps=0` = 没有底图 |
| 仿真骨骼 `/api/sim_bones` | `L`/`R` 两次采样求最大位移 | 见下条: `n` 在涨 ≠ 臂在动 |

一键探针: `scripts/ar_feed_probe.py`(只读, 打印四条源 + verdict)。

- 🔴 **`/bones.json` 的 `n` 是物理/帧计数, 不是位移**: 停机实测 `n` 每秒稳定 +50 左右, 而 L/R 各 8 段
  逐坐标最大位移恒为 `0.0000m`。判“仿真臂在不在动”必须**隔 1s 采两次、逐段比 L/R 坐标**;
  看 `n` 递增或 `ts` 在刷新都会得出“仿真在跑”的反结论。
- 🔴 **四条同时过期先查网络, 再查页面**: 本机没有到产线网(`192.168.23.x`)的路由时, `l2_daemon` 每 5s
  打一条 ssh 失败、`/api/cams` 全 offline、位姿停在几天前 —— 这三样同时出现就是“这台机器已经不在产线网”,
  页面怎么改都画不出真机臂。判据: `ip -br link`(是否只剩 wlan)· `ss -ltnp | grep 39071`(位姿桥)·
  `/api/tcp` 的 `age_s`。
- 不重启服务能做的: `tools/web/tcp-ar.html` 是 mtime 热读, 改判新鲜度/横幅当场生效; 服务端
  (`tcp_ar_server.py`)的改动必须重启, 而重启要用户点头 —— 汇报时把这两类分开说, 别承诺“改完就好”。

## 页面卡死的真图: 可选接口 500

`refresh()` 第一句 `await fetch('/api/traj')` 无 `scene.json` 时 500 ⇒ 异常跳 catch ⇒ 后面读 TCP、
开图层、拉骨骼全不执行。修法两条一起上:

- 服务端 `_traj()` 取不到 `scene.json` 就返回 `{"ok":false, "trace":[], ...}`, 不抛;
- 页面把“没真机就开 SIM”的兜底放进**独立 `setInterval`**, 不依赖 `refresh()` 是否走完。

## 验证口径(不要只看 200)

1. `curl -s /api/sim_bones` → `ok=true, n>0, L=8, R=8`。
2. 用代理自己的浏览器打开同一个 `/ar3d` URL, 读页面全局(`SIMON`、`SIMB.ok/n`)。
3. 枚举 canvas, 只取 **3D 那个**(通常 `#vr`, 不是视频 canvas), 数青色/橙色像素;
   青=左臂、橙=右臂, 末梢标 `SIM L` / `SIM R`, 像素数 >100 即已画出。
4. 改页面后让用户用带版本号的 URL(如 `/ar3d?v=NNNN`)或 Ctrl+Shift+R, 否则浏览器用旧页,
   你会得到“改了没用”的假回复。
