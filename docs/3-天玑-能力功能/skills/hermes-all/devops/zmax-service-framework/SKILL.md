---
name: zmax-service-framework
description: Use when 把散落的多个服务收成一套框架(注册/门户/健康/反代), 或问"哪个端口是什么"。
---

# 把散服务收成框架 (契约 + 网关 + 分层门户)

触发: 用户说「把这些服务做成框架服务」「统一入口」「哪个端口是什么」, 或现场实施要来一份服务清单。

## 骨架 (三个文件, 不算网关代码就这三样)

```
services/
├── registry.json          # 唯一真源: name/port/layer/title/desc/health/capabilities/unit
├── framework_gateway.py   # :8788 四个端点, 不含任何服务名硬编码
├── zmax-framework.service # systemd 常驻
└── README.md              # 分层表 + 加服务三步 + 已有坑
```

四个端点分工要清:
| 端点 | 给谁用 |
|---|---|
| `GET /` | 人 —— 按层分组卡片, 绿灯 + 端口 + 延迟 + 元数据 |
| `GET /api/services` | 机器 —— 完整清单, 可 curl 可导监控 |
| `GET /api/health` | 看门狗 —— 聚合, 全在线才算 ok |
| `ANY /go/<name>/…` | 反代 —— 同源访问, 不用记端口 |

## 分层照「算法与业务分离」切, 别照端口顺序切

L5 场景理解(感知) / L4 流形引擎(物理护盾) / L3 流程编排(状态机) / L2 精细操作(原子技能) / OPS 交付观测(看板/视频/版本)。
**判据: 每层能一句话说清"不懂什么"** (L4 不关心摆盘还是插拔, L3 不写控制代码)。说不清的层就是分错了。

## 两个探测纪律 (都是踩出来的, 不照做门户就是一片假红灯)

1. **health 404 必须自动退到 `/`**。实测 8793/8797/8799/8815 只实现根路由, 照声明探 `/health` 全 404 →
   门户显示"全部离线", 比不显示更误导。写法: 拿到 `HTTPError` 且 `code in (404,405,501)` 就 `continue` 试下一个路径。
2. **超时只给 2 秒**。8816(3DGS 走 Intel 隧道) 在训练占 XPU 时会 timeout;
   如实标 `timeout` 好过拖死整页 (页面每 8 秒轮询一次, 一次卡 30 秒就废了)。

## 总索引页: 缩略图 + 热改 + 自探测递归 (2026-11-25 落地)

用户说「改成产品服务 / 点开先看到所有服务的总索引 + 缩略图 + 介绍 / 各服务都 link 起来」= 要的是
**门户本身变成一级入口**, 每张卡能直接进原服务。三条硬经验:

1. **页面抽成外部文件, 网关按 mtime 热读** (`services/web/portal.html`)。把 HTML 留在 .py 的 PAGE 常量里,
   每改一句文案都要重启常驻网关 —— 现场就是「改完用户还看到旧版」。热读后改版零重启, 只 `py_compile` 网关不动作。
2. **缩略图必须真截, 而且要控等待**: `chromium --headless --screenshot` 在 snap 版上**写不进** `$HOME/zmax`
   (snap 只能写 `~/snap/<pkg>/common`), 且带 `--virtual-time-budget` 时对有 `setInterval` 的页面**永不落盘**。
   可用做法 = CDP: 起 `--remote-debugging-port`, 手写最小 WebSocket (stdlib 即可, 不用装 websockets),
   `Page.navigate` → `sleep 7~15s`(3D/视频/图表要时间) → `Page.captureScreenshot`。
   点击率高的图 (ar3d/cy-slice/phase) 一次就好看; 视频页在 headless 下常黑 (浏览器同主机 6 连接被占),
   别硬截, 宁可用该服务的**单帧端点** (如 8802 `/frame.png`、8898 `/arm_yolo.jpg`) 存成同名 png。
3. 🔴 **网关不要探自己**: 若把自己也写进 registry 并让 health 指向 `/api/services`, 探活会再次触发
   `probe_all` ⇒ **无限递归/死锁** (缓存为空时尤其致命, `_lock` 是普通 Lock)。判据是 health 一请求就挂、
   进程 CPU 0。修法: 条目加 `"self": true`, `_probe` 里直接短路 `up=True`。
4. **分层之外要有 CLIENT 层**: 像「Simulink 画布」这种没有端口的入口, 给 `"port": null, "kind": "client",
   "open_hint": "控制台 → 首页「Simulink模式」"`, 不参与在线统计 (否则它永远算一个离线项, 统计永远不绿)。
5. 每条加 `kind`(page/api/client) 与 `path`(打开时拼在 `/go/<name>` 后面)。**station 要 `/station`**,
   只写端口会打开 8793 的旁路流首页, 不是工位总览 —— 用户点的和你给的不是同一个页面。
6. 离线文案要带真因: 有 `tunnel` 字段的显示「隧道未起 · 127.0.0.1:8816 -> intel:8816」,
   不要把 `ConnectionRefusedError` 原样丢在卡上。

验收 (缺一条不算完): `curl :8788/` 200 且 HTML 含标题; `curl :8788/thumb/<name>.png` 200 且几万字节;
`curl :8788/go/<name><path>` 拿到**底层原文** (如 station 188KB 页面); `/api/health` 的 down 只剩真断的隧道。

## 控制台里点「产品服务」没反应 = 外挂浏览器起不来 (必读)

**症状**: 点卡片后用户眼前零变化; 进程表里既无 firefox 也无 chromium, `ui_error.log` 无异常,
启动日志也没有任何打开记录 —— 看起来像"点击事件没绑"。

**根因**: 本机默认浏览器是 **snap 版 chromium**。① 从 studio 的 cgroup 里拉起会被 snapd 拒
(`...is not a snap cgroup for tag snap.chromium.chromium`), 静默 exit 1; ② `xdg-open` 只会把 URL
塞进**已有窗口的标签页** ⇒ 零可见变化。所以 `webbrowser.open()` 返回 True 也不能算成功。
判据: `ps -eo lstart,cmd | grep -E '[f]irefox|[c]hromium'` 点击前后无新进程。

**修法**: 与 8810 切面页同一套 —— 应用内 `QWebEngineView` 开 `QDialog`(NonModal, 1400x900),
再点一次只 `raise_()+reload()` 复用; 内嵌失败才回退 xdg-open。前提: `PyQt5.QtWebEngineWidgets`
必须在 QApplication **之前** import (studio.py 已在头部做了)。

**最大化按钮灰/点了没用**: `QDialog` 默认带 `Qt.Dialog` 位 ⇒ `_NET_WM_WINDOW_TYPE_DIALOG`,
GNOME 对 dialog 不给最大化能力。取证: `xprop -id <wid> _NET_WM_ALLOWED_ACTIONS | grep -i maximize`
—— 有值才能点; 没有就是窗口类型问题, 不是按钮画错了。修法: `setWindowFlags(Qt.Window |
WindowTitleHint | WindowSystemMenuHint | WindowMinMaxButtonsHint | WindowCloseButtonHint)`。
验收: 同上 xprop 出现 MAXIMIZE_HORZ/VERT + `wmctrl -i -r <wid> -b add,maximized_vert,maximized_horz`
后 `xwininfo` 尺寸真的变大 (实测 1420x900 → 1854x1131), 再抓图确认网格自适应不变形。

**自测不盲点坐标**: 命令通道 `/tmp/zmax_nav_cmd` 加一条 `portal`, `_oneshot(self,300,lambda: _open_portal_in_app(self))`;
`echo portal > /tmp/zmax_nav_cmd` 后等 6~8s, `wmctrl -l | grep 总索引` 看到窗口标题, 再用
`xwd -silent -id <wid> -out /tmp/w.xwd` + ffmpeg 转 png 抓图确认不是白页。**这才是"真点开了"的证据**,
"代码里调了 webbrowser.open" 不算。

## 收口坑

- **`kill <pid>` 只杀 bash 包装, python 子进程还活着** → 端口被占, systemd 起不来报
  `OSError: [Errno 98] Address already in use`, 而 `systemctl is-active` 显示 `activating` / `MainPID=0`。
  判据: `ss -ltnp | grep :8788` 看**端口主人**的真 pid, 杀它; 或直接 `systemctl restart` 前先确认端口空了。
- **`pkill -f <脚本名>` 会匹配到自己这条命令** → shell 被 SIGTERM (exit -15)。用精确 pid 或 `pgrep -f` 先看一眼再杀。
- systemd 起来后要**反代自证**: `curl :8788/go/<name>/health` 拿到底层服务真返回, 不是 200 就算过。

## 验证清单 (缺一条不算完)

```bash
python3 services/framework_gateway.py --selftest   # 逐服务打印 ✅/❌ + 原因
curl -s :8788/api/health                            # n_up / n_total / down 名单
curl -s :8788/go/cy-slice/health                    # 反代透传底层 JSON
systemctl is-active zmax-framework                  # active 且 MainPID 非 0
journalctl -u zmax-framework -n 20                  # 无 bind 失败
```

## 报告口径

离线项必须带**真因**, 不能只说"离线": "gs3d timeout = Intel 侧渲染进程未起", "aoi-surface 500 = AOI 侧服务未起"。
把"框架没问题、是下游没起"和"框架自己坏了"分开讲 —— 否则用户会以为框架不可靠。
