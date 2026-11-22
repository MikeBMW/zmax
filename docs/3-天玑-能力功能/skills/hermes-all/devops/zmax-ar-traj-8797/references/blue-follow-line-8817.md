# 「轨迹清了又回来 / 画面有条关不掉的青蓝长线」(2026-11-21 实测)

## 症状
- 服务端 `/api/traj/clear` 清过、围栏条目也删了, 用户仍说「没清空」「这蓝色轨迹都是啥, 删掉」。
- 每次换页/刷新又出现。

## 真因
页面 `pull()` 每 ~5s 拉 `http://HOST:8817/session.json` (会话轨迹, 实测 17764 点 / 累计 269m),
拿到就执行:

```js
NAMED['follow']=pts; NAMED_ON['follow']=true; SHOW=true;
NAMED_COL['follow']='#22d3ee';   // 青蓝
```

**无条件挂进三维**, 没有开关 ⇒ 服务端清一次它回来一次。

## 排查法 (别猜颜色)
在 console 里包一层 `ctx.stroke/fill`, 命中蓝色系时打 `new Error().stack` 并按函数名聚合:

```js
g.stroke=function(...a){ if(isBlue(g.strokeStyle)) rec(g.strokeStyle); return os(...a); };
```

一次就能看出是 `drawNamedVR`(轨迹) 还是 `drawFlatModule`(模块)。判据: `2 万+ 次 stroke` ≈ 某条几万点的轨迹被逐段画。

## 修法
只备数据、不自动显示: `NAMED_ON['follow']` 默认 false, 去掉 `SHOW=true`; 要看得显式打开。

## 别误删
页面里的蓝色块 `#60a5fa` 是料盘/槽里的光模块 (`drawTrayModules` / `drawFlatModule`), 是物体不是轨迹。

## 同源症状: 「服务端改了, 页面没变」
页面只在**首次加载**读一次 `/api/fence`, 没有轮询 ⇒ 服务端禁/删/清之后, 已经开着的那个 tab 还画旧图元,
用户看到的就是「没有清空」「删不掉」。定式(已落地): 每 5s 取一次 `/api/fence`, 用
`items.map(i=>i.id+':'+(i.enabled?1:0)).join(',')` 做指纹, **只有指纹变了才重新 `loadFences()`**
(无条件重载会连带 `vrFitBox` 把视角拽走)。
实测: 改开→关→开, 橙像素 698→1092→698, 全程不刷新也跟得上。

## 像素取证口径 (别数错画布)
| 画布 id | 尺寸 | 是什么 |
|---|---|---|
| `#vr` | 980×577 | **三维视图 —— 所有图元都在这里** |
| `#vid` | 1280×720 | 相机视频帧 (颜色随机, 数它只会得到 0 或噪声) |
| `#ov` / `#loupe` | 640×480 / 176×176 | 叠加层 / 放大镜 |

- 🔴 用「最大的那个 canvas」取图 = 取到 `#vid`, 再数颜色永远是 0 —— 会误判成「没画上」。一律 `getElementById('vr')`。
- 验证一个 points 图元真画上了, 三条一起看(缺一条就会被“看着有/看着没”骗):
  `FENCES.filter(x=>x.type==='points')` 里 `enabled===true` 且 `pts.length===期望值` ·
  `window.__FENCE_PTS_DRAWN__` 在涨(每刷新一帧 +N, 实测 717 = 239×3, 同一套点被 drawVR 重画三遍, 不算 bug) ·
  该颜色的像素包围盒落在画布内(如橙 `#ff9f1c` bbox 311×198)。
- 🔴 **靠逐个点开关按钮反推"这个颜色是谁"不可靠**: `🧊 管状通道` / `🫥 全部隐藏` / `🔩 光模块` 实测点下去
  像素一个不变(状态是服务端口径或另一层在画), 会把你带向错误结论。要定性就用上面的 `ctx` 钩子 + 调用栈聚合,
  一次就看得到 `drawNamedVR` / `drawFlatModule` / `drawUrdf` 哪个在画。
- 数“青色”和数“蓝色”会重叠(`#3db0ff` 类同时命中两个阈值) —— 报数时给具体 hex 或给调用函数名, 不要只说“蓝的”。

