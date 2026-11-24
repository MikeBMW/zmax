---
name: calabi-yau-slice-service
description: Use when 做六维/卡拉比-丘流形切面可视化(孔洞/亏格), 或要把它固化成标准服务网页与画布入口 (8810)。
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [manifold, visualization, webgl, web-service, systemd, zmax]
    related_skills: [canvas-3d-scene-page, manifold-potential-field-design, zmax-release-versioning, live-service-change-discipline]
---

# 六维卡拉比-丘流形切面 → 标准服务网页 (孔洞 = 亏格)

## When to Use

- 老倪说「增加六维卡拉比丘流形的切面、表达出孔洞」「做成网页服务」或要在画布/看板里点开看。
- 任何「抽象数学对象 → 可交互网页」且要求**看着真、能量化**的场合（流形、亏格、拓扑、势场切面）。
- 要把一次性脚本升级成**标准服务**（systemd + /health + 版本 + 服务清单 + 应用内入口）。

不适用: 普通工艺卡/设备三维页 → `canvas-3d-scene-page`; 纯数学自证无页面 → `manifold-engine-math-verify`。

## 1. 数学口径先定死（这是能不能交差的地基）

十维引擎隐藏部分 M6 是复三维(实六维) ⇒ **直接画不了**，取**标准复二维切面**:

```
Q : z₁⁵+…+z₅⁵ = 0 ⊂ CP⁴  ⇒  仿射切片 C : x⁵ + y⁵ = 1
亏格(Riemann–Hurwitz): 2g−2 = n(2g_b−2) + Σ(e_p−1) = 5(−2) + 5·(5−1) = 10 ⇒ g = 6
```

- **孔洞数不是画出来的**，是算出来的：g=6。汇报时先说这句，再给图。
- **逐点自证**：每个采样点代回 `|x⁵+y⁵−1|`，实测 ≤ 3.6e-15，把残差打到页面上（和面数并列）。
- 采样参数 `x = r e^{iθ}`，`y_k = ω^k·(1−x⁵)^{1/5}`，k=0..4（5 个分支/5 张片）。
- 🔴 `r_max` 取 **1.0（分歧圆上）**：5 张片在 `|x|=1` 的 5 个分歧点收拢成环，瓣间空隙就是孔洞；
  取 1.5+ 会变成“五片带硬边的叶子”，用户看不出孔洞。
- 导出 `/slice.obj` 让人能拖进 Blender 复核 —— 自称数学对象就必须可复算。

## 2. 渲染选型：上万三角面一律 WebGL，别用 2D 画家算法

| 方案 | 实测结果 |
|---|---|
| 2D canvas 画家算法（几千面以内可用） | 1.3 万面时每面描边在掠射角叠成**竖条纹**；关描边仍因无深度缓冲互相穿插而脏 |
| WebGL（本地 three.module.js） | 一次就干净，深度缓冲自动解遮挡 |

- 边缘/产线不能引 CDN ⇒ 服务端加一条热读路由把仓库里的 `tools/three.module.js` 吐出去：
  `if p == "/three.module.js": open(THREE_JS,'rb')`，页面用 `<script type="module">import * as THREE from '/three.module.js'`。
- **几何轴要映射**：曲面“瓣轴”是数学 z，摆进 three 的 y：`pos.push(v[0], v[2], v[1])`，否则默认视角正对轴看成一只实心圆盘。
- 材质 `MeshStandardMaterial{vertexColors, side:DoubleSide, flatShading:true}` + 三向光（主白/冷蓝/暖橙），5 个分支各一色。
- 交互只给四条：拖拽旋转 / 滚轮缩放 / `W` 线框 / `R` 复位。
- 🔴 `resize()` 要按 `stage.clientWidth/Height` 取尺寸并在 build 之后调一次；页面和窗口尺寸都由 CSS grid 决定。

## 3. 服务要“标准”，不是“能开就行”

固定四件套（缺一件就会被问“这算服务吗”）:

1. **`/health`** 带自证量：`{ok, service, port, version, tag, uptime_s, genus, verts, tris, resid_max}`。
2. **`/version.json`**：版本**热读**仓库 `VERSION.md`，改号不用重启。
   🔴 解析必须先 `txt.split("## 版本历史")` 再抓 `\*\*v(\d+\.\d+\.\d+)\*\*`：
   全文找第一个 `v5.` 会抓到表头正文里的历史号（实测把 5.50.783 读成 5.50.771）。
3. **`/services.json`**：本机服务清单逐端口 TCP 探活（0.25s 超时、5s 缓存），页面右下角「本机服务」卡
   用 ●/○ 显示 8791/8793/8797/8810/8898/8796/8789 —— 一眼看出谁挂了，比挨个 curl 强。
4. **systemd unit**（`deploy/systemd/zmax-cy-slice.service` + `/etc/systemd/system/` 同名），
   `enable --now`；页脚写 `Z-MAX v<ver> · 8810 · up <s> · g=6 · <tris> 面 · 只读可视化，不下发任何动作`。

## 4. 画布入口：双击节点开窗，但**别指望外挂浏览器**

`on_node_activated` 里加分支（按**名字**匹配，GUI 内存节点不带 id）:

```python
_cy_name = str(node.get("name","")) or str(node.get("id",""))
if "十维流形引擎" in _cy_name or "十维黎曼梯度流" in _cy_name or _cy_name in ("ss_mani10","ss_mani_flow"):
    self._open_cy_slice(node); return     # 必须放在 source/verif 分支之前
```

🔴 **外挂浏览器三条路在本机全部失败**（三次实测，别再试）:

| 试法 | 结果 |
|---|---|
| `xdg-open URL` | 只往已有 Chromium 塞一个标签页 ⇒ 用户眼前无变化，说“双击没反应” |
| `chromium --app=… --user-data-dir=~/.hidden` | snap 版**禁止访问 $HOME 隐藏目录** ⇒ SingletonLock 权限拒绝后静默退出 |
| `chromium …` / `systemd-run --user --scope chromium …` | `...is not a snap cgroup for tag snap.chromium.chromium` ⇒ 被 snapd 拒 |

⇒ 用 **PyQt5 QtWebEngine 在应用内开窗**（gui-venv 里现成可 import，WebGL 正常）：
`QDialog(NonModal, 1180×780)` + `QWebEngineView.load(QUrl(url))`；窗口存 `self._cy_win`，
**再双击 = raise_ + activateWindow + reload**（不叠窗）。开窗前先 `urlopen(url+'health',2)`，不通就明说并给
`sudo systemctl start zmax-cy-slice`。

**取证明令通道**（免找像素）: `echo "ss_node 十维流形引擎" > /tmp/zmax_nav_cmd` —— 按名字找节点再调
`on_node_activated`。节点列表为空（画布还没加载）时先 `_open_ss_canvas_cmd()` 再 2.5s 重试，
**不要静默返回**（实测第一版没日志，看起来像命令没生效）。

## 5. 验收数字（照这组报，不要形容词）

```
数学: 残差 3.63e-15 · 分歧点 5 个 · g=6 · 7200 顶点/13680 面
服务: /health {version 5.50.783, uptime_s, genus 6, tris 13680} · /services.json 7 项 (6 ● / 1 ○)
页面: 五瓣+孔洞 · 隐藏 6 维现场值 + gate(fource/conf) · 帧龄
入口: 窗口「🧿 六维卡拉比-丘切面 — 孔洞 = 亏格 g=6」1180×780, 内嵌 WebGL 正常
```

## 6. 发版与归档

走 `zmax-release-versioning`。两个本技能专属的坑:

- 🔴 **sha256 清单必须在归档目录内用相对路径生成**：
  `( cd "$DST" && find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt )`。
  在仓库根 `find zmax_data/release_… | sha256sum` 生成的清单带前缀路径，`sha256sum -c` 在归档目录里解 = 全部 FAIL。
- 归档的 `data/` 手工列清单：画布真源 `data/database/zmax/sources/canvas/state_space_obs.json`、
  `flows/state_space_obs.json`、`config/ss_task_binding.json`、`deploy/systemd/*.service`、
  `zmax_data/ss_live/mani*_live.json` —— 这些全在 .gitignore 里，commit 保存不了。

## 7. 已落地位置 (v5.50.783)

```
数学核  src/lerobot/manifold/core/calabi_yau.py     (selftest: 亏格/残差/网格/分支不重合)
服务    tools/cy_slice_server.py                    (8810, 只读)
unit    deploy/systemd/zmax-cy-slice.service        (enabled, /var/log/zmax-cy-slice.log)
入口    tools/gui/simulink_module.py::_open_cy_slice (QtWebEngine 内嵌窗)
归档    zmax_data/release_5.50.783_<ts>/           (code/data/logs/evidence + sha256)
```
