# 给 Ubuntu 侧：怎么找到小红（Hermes Agent）

> 写于 2026-11-27 · 由 Windows 侧的 Hermes Agent（用户叫我「小红」）留下
> 目的：**跨平台迁移**。你（Ubuntu 上的我）读到这份，就等于接上了 Windows 侧的全部上下文。

---

## 一、我是谁

- 名字：**小红**（用户起的，希望以此称呼）
- 跑在：Hermes Agent（Nous Research），profile = `default`
- 用户：倪莹祥 / Mike.Ni（产线现场，苏州智蜂创元）
- 语言：**始终用中文回复**
- 禁忌：**不许替用户点开 GUI 窗口 / 抢焦点**（用户原话「别抢鼠标」）；不许刷屏式进度通知

## 二、这个目录里有什么

```
D:\ZMAX\.hermes\
  ├─ README.md              ← 你正在读的这份（总入口）
  ├─ memories/
  │    ├─ MEMORY.md         ← 环境/坑/约定（每次会话都加载）
  │    └─ USER.md           ← 用户是谁、偏好、禁忌
  ├─ skills/                ← 全部技能（按分类目录）
  ├─ SERVICES.md            ← 服务清单：端口 / 启动方式 / 自愈
  └─ HANDOFF-20261127.md    ← 本次会话做了什么（最近一次交接）
```

**接入方式**：把 `memories/MEMORY.md`、`memories/USER.md` 拷到 Hermes 的 `memories/`，
把 `skills/` 拷到 Hermes 的 `skills/`，然后读 `HANDOFF-20261127.md`——上下文就接上了。

## 三、550C 上已有完整镜像（可直接跑）

```
/home/intel/hermes_mirror/
  ├─ skills/        13 个分类（含 zmax-gold-geometry / zmax-gold-window）
  ├─ memories/      MEMORY.md + USER.md
  └─ config.yaml
```

**访问 550C**（两个地址，看你在哪个网）：

| 网络 | 地址 | 备注 |
|---|---|---|
| corp guest（10.163.x） | `10.163.149.123` | SSH 通，走这里最稳 |
| 产线（192.168.23.x） | `192.168.23.70` | USB 网卡掉线就整段断 |

账号：`intel` / `intel`

## 四、Windows 侧的服务（远程控制入口）

```
http://10.163.148.87:8793/station    工位总览（21 个手动按钮 + 6 路相机 + AOI）
       10.163.148.87:8793            ← Windows 这台机在 guest 网里的地址
```

从 550C 的 8888 索引页 `http://10.163.149.123:8888/` 顶部有蓝色入口直达。

## 五、两条铁律（改动前必读）

1. **节点不许有检测/判据/阈值逻辑** —— `src/lerobot/middleware/nodes/impl/ss_aoi.py` 只是薄壳，
   算法真身在 `src/lerobot/policies/aoi/`（gold.py / gold_yolo.py / gold_geometry.py / quality.py / surface.py）。
   往节点里塞算法 = 破坏分层。
2. **规整图规格固定 1341×206、19 根完整** —— 改动要同步三处：
   代码 `GOLD_SPEC`、技能 `zmax-gold-window`、`docs/0-总纲/ARCH-L2-L5.md`。
   禁止纵向拉伸（用户三次否决过「拉长」）。

## 六、真机移动必须授权

- 页面点「🔓 授权真动(现场确认无人)」
- 8797 `/api/arm/move_rel` 要求「8793 已授权」，fail-closed
- 参数是 **`dx/dy/dz`（mm）**，不是 `axis/mm`
- 限幅：服务端 8mm / `sdk_ctl.py` 5mm / 速度 5mm/s
- 移动通道 `~/zmax/zmax_data/move_transport.json` 必须写 `{"transport":"sdk"}`
  （缺这个文件会默认 `ros`，Windows 没 ROS ⇒ 永远不动）

---

写这份是为了让迁移不断线。你改完记得回来更新它。
