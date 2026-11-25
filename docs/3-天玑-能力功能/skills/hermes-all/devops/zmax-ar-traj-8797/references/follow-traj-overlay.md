# 画面上「一大坨浅蓝色轨迹」= 8817 跟随轨迹自动叠加

## 现象 / 误判路径
`/ar3d` 画布中央一大团青色 (`#22d3ee`) 密集管环, 从中心放射。依次点过这些**都不消失**:
「✕ 关掉命名轨迹」·「🫥 全部隐藏(0)」·「🎥 自动环绕」·「🦾 SIM骨骼」·「🧭 位置细胞」
⇒ 它不是「轨迹1~5」按钮管辖的任何一条, 也不是包络/骨骼/位置细胞层。

## 根因(页面尾部 IIFE)
页面每 2s 拉 `http://HOST:8817/session.json`, `pts.length>1` 时**无条件**:
```js
NAMED['follow']=pts; NAMED_ON['follow']=true;
NAMED_COL['follow']='#22d3ee';   // 青色
SHOW=true; drawVR();
```
累积到两万多点后被 `drawNamedOV()` 当普通命名轨迹画成 tube(每段一个 ring) ⇒ 视觉上是一团乱麻。
`NAMED_ON` 的 `follow` 键**不在**「轨迹1~5」按钮的可控集合里(`NAMED_COL` 只定义 xiaohong/square/map/safe/real 五个),
所以那些按钮永远关不掉它。

## 定位手法(比逐点按钮快一个数量级)
```js
window.__NAMED_VIS__   // {follow:{ok:25401,total:25401}} ← 一眼看出是哪个 key、多少点
window.__NAMED_DBG__   // key/total/projected
window.__VIS__         // 段/件/回流计数
```
⚠️ `__TP_DRAWN__` / `__FENCE_PTS_DRAWN__` 是**每帧累加**的计数器, 不是元素数 —— 别拿它当「画了多少个点」。
能直接读的状态先读, 不要靠逐个点按钮 + 截图对比去试。

## 改法(两道闸 + 清掉误导文案)
1. `drawNamedOV()` 的 filter 加 `k!=='follow'`(拦死, 防止别处再打开)。
2. `pull()` 里删掉对 `NAMED`/`NAMED_ON`/`SHOW`/`drawVR()` 的写入, 只留 `NAMED_INFO['follow']`。
3. HUD 那行「跟随轨迹 N 点」**一并删掉** —— 画面干净了字还在, 用户会以为没改干净。

保留: `PREV.on` 仿真臂跟随、`/api/tcp` 的 TCP 坐标与真值帧龄读数 —— 这些是「跟随真机」的本体, 不动。
数据侧: 8817 里那份会话轨迹**没删**, 要清得单独处理并先说清代价(它是跟随记录的唯一副本)。

## 验收
刷新 `/ar3d` → 那团消失 · `js_errors: []` · 左上角只剩「跟随中 / TCP x,y,z / 真值帧龄」。
页面是 **mtime 热读**, 改 HTML 不用重启服务。
