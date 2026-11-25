# 全流程相位轨迹: 数据源 · 注入 ar3d · 四元数顺序

给 /ar3d 加一条「真机全流程轨迹（带工艺相位、含 AOI 检测位）」时走这三段。

## 1. 源: 8815 的 `/api/geo`（唯一带相位标注的轨迹源）

`http://192.168.23.50:8815/api/geo` → `{set, n, len_mm, states[], frames[]}`

- `frames[i] = {i, p[3] mm, q[4], n[3], phi, spd, s, s_mm}` —— 笛卡尔点位 + 法向 + 四元数 + 弧长
- `states[] = {i0, i1, name}` —— 相位段索引，名字里带「移动→」的是过渡段，其余是**停留相位**
  （实际更有用的就是停留相位：`槽2抓取 / 扫码 / 插入到底 / 等待检测 / 钩拉环解锁 /
  金手指检测1 / 金手指检测点2 / 侧面点1~4 / 下盘放料`）
- 同机另有 `/api/se3`（当前 TCP 的最近点 / phi / 轴向误差）与 `/api/ver`、`/api/stop`。
  探接口时别猜：抓首页 HTML 后 `grep -oE "/api/[a-z_/]+"` 拿到真实路由。

**四元数顺序是 `[w, x, y, z]`，不是 `[x, y, z, w]`。** 这条必须验不要假定：
把两种解释各转成旋转矩阵，跟真机 `latest.json` 的 `rx,ry,rz` 反推出的 R 比对 ——
实测 `[w,x,y,z]` 差 **5.2°**、`[x,y,z,w]` 差 **140.5°**。按错的顺序做 IK，工具 z 轴整体歪 140°，
251 点里 84 点解不出来（P95 误差 836mm）；改对后中位 0.18mm。

## 2. 注入 ar3d: 改数据文件, 不重启服务

`8797` 是 systemd 起的常驻服务, 改后端加 key 要重启 —— 不该为了画一条线重启它。
已有的读取通道够用: `GET /api/traj/named?k=map` 优先读
`zmax_data/ss_live/explore_traj_fenced.json` 的 `pts`(米制点列)。

```
1) 备份: cp -a explore_traj_fenced.json explore_traj_fenced.json.bak_<ts>
2) 写: {src, n, len_mm, pts[[x,y,z] 米], states, note}
   note 里必须写清"8815 全流程相位"+ 点位数 + 相位链, 前端要靠它在 UI 上认出来改名
3) 验证: curl -s ':8797/api/traj/named?k=map' → ok=true, n=251, note 带相位链
```

`pts` 只要 `[x,y,z]`；姿态(q)只有做 IK 回放时才需要，别往这里塞。

## 3. 前端三处热改（`tools/web/tcp-ar.html`，改完不用重启）

1. **按钮文字**: `<button id="t3">` 改成这条轨迹的真名（否则页面上仍写「建图」，看的人会误解）。
2. **按 note 改名**: `loadNamed()` 里 `NAMED[k]=d.pts;` 之前插一句
   `if(k==='map' && /<note 关键字>/.test(d.note||'')) d.label='<真名>';` ——
   服务端 `NAMED_TRAJ['map']` 是写死的旧名，不改后端只能用这招覆盖。
3. **自动显示**: `window.addEventListener('load')` 里加 `setTimeout(()=>loadNamed('map'), 1200)`。
   用户说"渲染上去"= 打开就能看见，不是"渲染好了要你自己找按钮点亮"。

验收（缺一条就是没真画上）: console 读 `NAMED_ON['map']===true` · `NAMED['map'].length` ·
`window.__NAMED_VIS__['map']` 的 `{ok,total}` 必须 **ok===total**（ok<total = 有点在视锥外）、
`document.getElementById('t3').className` 含 `on`（按钮变蓝）。

## 4. 要真机回放看画面前, 先做净空求交

`frames[i].p` 与**启用**的围栏盒逐个求交。实测该 215/251 点轨迹有 50 点落在「检测设备」盒内
(x711~844 / y−91~302 / z0~340)，直接下发会撞。
只想让三维模型动 ⇒ 用页面内 `rtrajPlayJoints(frames)`（只驱动模型 + 推 8802）；
`/api/arm/step_traj` 那条是真机 MoveAbsJ，闸门不查围栏。
