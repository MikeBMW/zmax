# 成像/检测服务「好使」的验收清单（逐路由 · 异步两段 · 并发最坏值）

适用：AOI 一类常驻检测服务（本项目 10082 金手指 / 10083 表面），或任何“HTTP 在听就算好使”会被骗的服务。

## 1. 路由清点（缺路由 = 跑的是旧版程序）

```bash
for u in storage param crop_info region last_result exposure; do
  printf "%-12s " "/$u"; curl -s -m 6 -o /tmp/o.json -w "HTTP %{http_code} %{size_download}B %{time_total}s" \
    "http://<host>:<port>/$u"; echo " | $(head -c 80 /tmp/o.json | tr -d '\n')"
done
curl -s -m 5 -X OPTIONS -D - -o /dev/null "http://<host>:<port>/picture" | grep -i '^allow'   # 写方法声明
```

实测两路差异：金手指有 `/param` `/crop_info` `/region` `/preview.jpg`；表面只有 `/storage` `/exposure` `/last_result`
`/picture` `/capture_detect`，且 `GET /capture_detect` 回 **405**（只收 POST）—— **405/404 也是合格反馈**，挂住才不合格。
静态口正常 4~11ms，`/picture?kind=origin` 7~11ms，`?grab=1` 0.28~0.72s，`/preview.jpg` ≈155ms（现抓）。

## 2. 异步检测：受理与出结果要分两段报

```bash
curl -s -m 60 -X POST "http://<host>:<port>/capture_detect"     # {"code":200} = 已受理
# 之后轮询 /last_result 看 ts 变新 + verdict/count/ms
```
- 表面：推理 **8.7s** 后 `/last_result` 落 `verdict/count/ms/detect_type=housing`。
- 金手指：1.5s 级落 `detect_type=gf`，同时 `/crop_info` 给 `judge.state / n_keys / pitch / score`。
- 只报“HTTP 200”会把“受理了但没出结果”当成成功；只报判决不同时报判据结论（检测 0 缺陷 ≠ 键排已定位）。

## 3. 并发最坏值

“每次请求都有反馈”的真正考验是另一请求占着相机时。实测：推理中 `/storage` 9ms、`?kind=origin&grab=1` 0.39s、
`?kind=crop&grab=1` 0.42s；但多轮混合时 `crop&grab=1` 最长 **7.2s**（仍返回）⇒ 客户端 5s 超时会先断；
第二个 `POST /capture_detect` 串行等 **7.4s** 后回 200（不是 409 busy）。
⇒ 要么服务端忙时秒回 503+原因（重启服务前先点名），要么客户端整轮总时长硬闸，不能只给 socket timeout。

## 4. 「服务通」之后还要证「取像有效」

```python
import cv2, numpy as np
im = cv2.imread('/tmp/f.png', cv2.IMREAD_GRAYSCALE)
print(im.mean(), im.std(), len(np.unique(im)), np.abs(cv2.Sobel(im, cv2.CV_32F, 1, 0, 3)).mean())
# 空场/灯未开: mean≈66  std≈2.1  唯一灰度值≈21  梯度≈3.5
# 档位被改坏的全黑: mean<8  max≤12
```
判据抑制（`state=suppressed_19gate`、`why=no key-row window (needs >= 6 bright groups, pitch 25..140)`、`score` 0.03 级 vs 正常件 0.95+）
是**安全行为，不是服务挂** —— 别据此说“AOI 坏了”。

🔴 同一套 `/param` 口径（`exposure/gain/gamma`）被两路相机共用时，把一方的档写进另一方**不报错、`applied` 非空、还落盘**，
重启后依旧。金手指产线档 **20000us/8dB**（p50≈68），表面 **80000us/1.8dB**；写成 5000us/2dB 会让金手指全黑而服务一切正常。
⇒ 判“忽然全黑/全灰”先回读两路 `now` 值比各自产线档，再看像素，最后才谈判据。

## 5. 汇报格式

先一句人话结论（已启动 / 服务通但视图无效），再逐路给数（路由码+耗时 · 推理 ms · 判据 state/score · 像素统计），
末行写**需要现场做什么**（摆件/开灯）或**需要他批准的动作**（重启服务约 10s）。不列选项让用户猜。
