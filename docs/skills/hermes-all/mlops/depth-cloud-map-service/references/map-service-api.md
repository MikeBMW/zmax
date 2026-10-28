# 地图服务端点契约 · 栅格渲染 · 可跑代码

配套 `depth-cloud-map-service`。这是「建好的图怎么变成服务」那一层的定式。

## 1. 端点契约(给远端/页面)

| 端点 | 返回 | 说明 |
|---|---|---|
| `GET /` | HTML 查看器 | 单页, 俯视+侧视两格, 3s 轮询 |
| `GET /map/status` | JSON | `ready/state/msg/meta/updated/age_secs` —— 查看器只轮这一个 |
| `GET /map/meta` | JSON | 当前地图元数据(坐标系/单位/内参/手眼/来源/bbox) |
| `GET /map/points.bin` | 二进制 | `struct.pack("<II", n, 0)` 头 + `float32` xyz 平铺 |
| `GET /map/points.json` | JSON | 小图/调试用; **>20 万点自动降采样**并标 `downsampled` |
| `GET /map/topdown.png` | PNG | XY 俯视栅格 |
| `GET /map/side.png` | PNG | XZ 侧视栅格 |

要点:
- 🔴 **点云别走 JSON**: 24 万点 JSON 有几十 MB; 二进制 `n + float32 xyz` 是 2.9MB, WebGL 能直接灌 buffer。
- 统一加 `Access-Control-Allow-Origin: *` + `Cache-Control: no-store`(地图会重建, 缓存旧图会让用户看到过期结果)。
- 未就绪返回 **503 + `{error, state}`**, 不要返 200 带空数据(前端分不清"没建好"和"建出来是空的")。
- 单写者/多读者: 建图线程写、HTTP 线程读, 用一个字典包 `threading.Lock()`, 请求里**先取快照再序列化**(别持锁做 PNG 编码)。

## 2. 查看器骨架(4060 那种「打开即看」)

```html
<header><span id="st"></span><span id="meta"></span></header>
<main><img id="td"><img id="sd"></main>
<script>
async function tick(){
  const s = await (await fetch('/map/status',{cache:'no-store'})).json();
  st.textContent = s.state + ' · ' + s.msg;
  if (s.meta?.n_points) meta.innerHTML = s.meta.n_points.toLocaleString() + ' 点 · ' +
      s.meta.source + ' · 建图 ' + s.meta.build_secs + 's @ ' + s.meta.built_at;
  const t = Date.now();                       // 破缓存, 否则重建了也看到旧图
  td.src = '/map/topdown.png?t=' + t; sd.src = '/map/side.png?t=' + t;
}
tick(); setInterval(tick, 3000);
</script>
```

- 元数据(点数/来源/建图耗时/时间)必须**显示在页面上**, 不要只放 JSON —— 用户会把画面当结论, 画面自己得带状态。
- 端点挂了要把状态字改成「服务无响应」并变红, 不要静默停在一个旧成功态。

## 3. 栅格化(俯视/侧视)

```python
def rasterize(P, axis_a=0, axis_b=1, px=900, flip_b=True, dilate_below=400000):
    a, b = P[:, axis_a], P[:, axis_b]
    c = P[:, 3 - axis_a - axis_b]                       # 第三轴当高度着色
    amin, amax, bmin, bmax = a.min(), a.max(), b.min(), b.max()
    span = max(amax - amin, bmax - bmin, 1e-6)          # ⚠ 短轴只用到部分画布
    ia = np.clip(((a - amin) / span * (px - 1)).astype(np.int32), 0, px - 1)
    ib = np.clip(((b - bmin) / span * (px - 1)).astype(np.int32), 0, px - 1)
    if flip_b: ib = (px - 1) - ib

    img = np.zeros((px, px, 3), np.float32); cnt = np.zeros((px, px), np.float32)
    cmin, cmax = np.percentile(c, 2), np.percentile(c, 98)   # 用分位, 防极值压平色阶
    t = np.clip((c - cmin) / max(cmax - cmin, 1e-6), 0, 1)
    col = np.stack([t, 1 - np.abs(t - 0.5) * 2, 1 - t], axis=1)   # 低蓝 中绿 高红
    np.add.at(img, (ib, ia), col); np.add.at(cnt, (ib, ia), 1)

    empty = (cnt <= 0)                                  # 🔴 归一化之前存
    img = img / np.where(cnt == 0, 1.0, cnt)[:, :, None]
    rgb = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    if len(P) < dilate_below:                           # 稀疏点 3x3 膨胀
        pad = np.pad(rgb, ((1,1),(1,1),(0,0)), mode="edge")
        grown = np.zeros(rgb.shape[:2], bool)
        for ch in range(3):
            mx = np.zeros(rgb.shape[:2], np.uint8)
            for dy in (0,1,2):
                for dx in (0,1,2):
                    mx = np.maximum(mx, pad[dy:dy+px, dx:dx+px, ch])
            rgb[..., ch] = np.where(rgb[..., ch] == 0, mx, rgb[..., ch])
    rgb[empty] = (18, 21, 26)                           # 深灰底, 不是纯黑
    return rgb
```

## 4. 三处 bug 的机制(都实测踩过)

| bug | 机制 | 数 |
|---|---|---|
| 背景纯黑 | 先 `cnt[cnt==0]=1` 再判 `empty` ⇒ `empty` 永远 False, 深灰底没生效 | 整图亮度 **3.1** → 修后 **123.5** |
| bbox 翻倍 | 有效阈值取 `z>0` 而非真源的 `z>0.05m`, 近距飞点被反投影 | `Z[-3322,1158]` → 修后 `Z[-1539,1131]`mm |
| 图看着空 | 24 万点铺 900×900, 大量重叠成单像素 | 覆盖 **2.55%**; 3×3 膨胀后可见 |

## 5. 实测数值(单帧 480×640 深度图, 手眼 TSAI 闭环 1.74mm)

| 量 | 值 |
|---|---|
| 有效像素 | 257,172 |
| SOR 后 | 244,854(剔除 4.79%) |
| bbox | X[122.6, 2449.8] Y[-814.4, 228.6] Z[-1539.1, 1131.5] mm |
| 建图耗时 | 0.88s(不含 SOR 时 0.13s) |
| 端点 | status 200/1KB · topdown.png 200/54KB · side.png 200/64KB · points.bin 200/2.9MB |
| 点云覆盖 | 俯视 **2.55%**(单视角深度表面的固有结果) |

对照口径: 同源 `stats.json` 报 **7,163 点 / Z[-1224, 337]mm** —— 那是过完滤的**单件主物体**,
与「整场景全部有效像素」是两个口径。报数必须带口径名, 不要试图让两个数字相等。
