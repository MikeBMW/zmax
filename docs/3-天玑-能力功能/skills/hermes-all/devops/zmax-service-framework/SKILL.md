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
