# 画布 HUD / 文字标签的坑（/ar3d 这类自绘三维页）

> 本文件尚无 SKILL.md 指针：该技能 SKILL.md 已达 100k 字符硬上限，无法再添一行。
> 合并/拆分 SKILL.md 时请把 `canvas-hud-and-labels` 加回 refs 列表。

## 「黑条挡视线」= 文字标签的深色底框被长文案撑成横带

用户说「屏幕上那条黑的是什么？删掉，挡视线」时，那不是遮罩、不是渲染 bug，
而是给标签画的底色块（`fillRect` · `rgba(0,0,0,.78)`）被一段几十字的 label 拉满画布宽度。

判据（一条 JS 就能定案）：

```js
const c = document.createElement('canvas').getContext('2d');
c.font = 'bold 13px monospace';
c.measureText(标签文本).width;      // 与画布宽比
```

实测：一条 70 多字的航路标签量出 **900+ px / 画布 980 px** —— 底框就是一条横贯画面的黑带；
把标签缩成「名称 · 点数 · 行程」后 **227 px**，黑条消失。

## 定式：两端都限

1. **服务端别把说明文字拼进 label**：`plan_label = "<名称> · <点数> · <行程>"` 足够；
   `note`（一句完整说明）不要拼进去 —— 它只该进 tooltip / 详情接口。
2. **页面侧画之前再截断**：超过 ~30 字截断加 `…`，并对底色块宽度设上限（如 ≤ 画布宽 40%）。
3. 只改一边不够：同一页面别的入口（另一套 plan、另一种轨迹、另一个按钮）会拼出另一种长文，
   所以服务端与绘制函数都要有上限。

## 先确认浏览器真在那页上，再改 DOM

导航之后先读 `location.href` / `document.title`：出现 `about:blank` 时 `getElementById` 全 null、
页面全局量（`VR` / `TRAJ` 这类）全 undefined —— 那是**浏览器会话丢了页**，不是页面缺元素。
据此去删/改 DOM 会白改一整轮；抓到空元素先看一眼 `location.href`。

## 标签改短之后的验收

- `measureText` 宽度回到一两百 px；
- 画布上同一条轨迹线还在（青/黄像素数不掉），只是底框短了；
- 刷新后不再出现横贯画面的黑带。
