# Z-MAX 框架服务 (services/)

把散在 8791~8898 二十多个端口上的服务收成**一套框架**：一份契约、一个入口、
一次探测看全 —— 而不是靠人记"哪个端口是什么"。

## 一句话用法

```bash
# 看全部门户（分层 L5/L4/L3/L2/OPS + 实时健康灯）
http://10.163.146.76:8788/

# 机器可读清单（可 curl / 可导给外部监控）
curl -s :8788/api/services

# 聚合健康（给看门狗/CI，全在线才 200）
curl -s :8788/api/health

# 反代访问（同源，不用记端口）
http://10.163.146.76:8788/go/cy-slice/
http://10.163.146.76:8788/go/ar3d/
```

## 为什么这样分（对应「算法与业务分离」）

| 层 | 职责 | 不负责 | 现役服务 |
|---|---|---|---|
| **L5 场景理解** | 只懂数学与物理，不懂客户 | 不关心模块去哪、臂怎么动 | se3-board 8815 · ar-render 8802 · gs3d 8816 · gs-models 8796 · aoi-gold 10082 · aoi-surface 10083 |
| **L4 流形引擎** | 物理护盾：10D 相空间 / 辛几何 / 黎曼约束 | 不关心摆盘还是插拔 | cy-slice 8810 · ar3d 8797 |
| **L3 流程编排** | 只懂流程不懂力学 | 不写底层控制 | ar-station 8804 · phase 8805 |
| **L2 精细操作** | 灵巧双手：原子技能 + 末端控制 | 不决定抓哪颗、放哪槽 | station 8793 |
| **OPS 交付观测** | 只懂参数不懂代码 | — | dashboard 8799 · video-overview 8791 · platform 8798 · agent-hub 8794 |

## 加一个新服务（三步，不改网关代码）

1. 在 `registry.json` 的 `services[]` 里加一条：
   ```json
   {"name":"my-svc","port":8899,"layer":"L3","title":"我的服务",
    "desc":"一句话说清它干什么","health":"/health",
    "capabilities":["flow.my"],"unit":"my.service"}
   ```
2. （可选）给你的服务加 `/health` 返回 `{"ok":true,...}`。
   **没有也没关系** —— 网关会自动退到 `/` 探测，靠 HTTP 状态码判断存活。
3. `sudo systemctl restart zmax-framework`

契约即清单：`registry.json` 是唯一真源，网关不含任何服务名硬编码。

## 两条探测纪律（都是踩出来的）

1. **health 端点 404 时自动退到 `/`**。实测 8793/8797/8799/8815 只实现 `/`，
   照 `health` 声明去探会全报 404 → 门户一片红灯，"假的全部离线"比不显示更误导。
2. **延迟只设 2 秒**。8816（3DGS，走 Intel 隧道）在训练占 XPU 时会 timeout，
   如实显示 `timeout` 比让它拖死整页更好。

## 运维

```bash
systemctl status zmax-framework      # 状态
sudo systemctl restart zmax-framework
journalctl -u zmax-framework -n 50   # 日志（常驻静音，只留 journal）
```

`/api/health` 语义：`n_up == n_total` 才 `ok:true`；
`n_up > 0` 就回 HTTP 200（部分可用不算全挂），全挂才 503。

## 已知离线项（不是框架的错）

| 服务 | 现象 | 真因 |
|---|---|---|
| gs3d :8816 | timeout | Intel 侧渲染进程未起（训练/切资产时会停），需在 Intel 上重启 |
| aoi-gold :10082 | 404 @/ | 隧道只转发了特定路径，没有根路由 |
| aoi-surface :10083 | 500 @/health | AOI 侧服务未起（返回 000 的历史问题） |
