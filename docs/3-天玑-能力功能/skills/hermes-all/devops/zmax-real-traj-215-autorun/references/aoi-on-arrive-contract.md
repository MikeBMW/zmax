# 到点触发 AOI: request 契约 (10082 金手指 / 10083 表面)

执行器里 `AOI_ON_ARRIVE = {帧号: (端口, 名称)}`, 每走完一帧命中就触发一次。这个表写错或请求写错, 效果是“轨迹跑完了、日志里也有图, 但检测从来没跑过”。

## 三个路由, 顺序不能换

| 步 | request | 作用 | 实测 |
|---|---|---|---|
| ① | `POST /capture_detect` body `{}` | **触发一次真检测** | `{"code":200,"msg":"success"}`, ≈1.9s, 超时给 25s |
| ② | `GET /last_result` | 取本次判决 | 检测本身 ≈1600ms |
| ③ | `GET /picture?grab=1` | 另取一帧 jpg | **只有 10082 有**; 10083 无 /picture, 失败不计错 |

`GET /picture?grab=1` **不是触发** —— 只取图, 服务端不跑推理, `/last_result` 永远停在旧结果。
只调 `/capture_detect` 不读 `/last_result`, 就是检测了但判决丢了。两件都要做。

## 地址不是 127.0.0.1

AOI 服务在产线另一台机上; 工控机**本机** 10082/10083 不监听(`curl 127.0.0.1:10082` → `000`)。
写成回环地址 = 每次到点都触发失败, 而且因为只打 warning, 没人会发现。Host 走 `ZMAX_AOI_HOST`。
执行器跑在容器里时确认 `rokae_sdk_run.sh` 用了 `docker run --network host`, 否则容器内到不了该地址。

## /last_result 关键字段

```json
{"code":200,"count":0,"defects":[],"detect_type":"gf",
 "judge":"...Finger_TopView_W900_H1660_No_13.png","ms":1615.7,"n":1,
 "origin":"...Finger_Image_W2448_H2048_No_13.png",
 "saved_incoming":"D:\\AOI_images\\gf\\incoming\\20261117_210334_001.png",
 "shadow":{"verdict":"OK","ms":1402.6,"count":0,"defects":[]}}
```

- `detect_type`: `gf` = 金手指; 表面是另一路
- **判 OK/NG 看 `count` 与 `shadow.verdict`**, 不是看 `code==200`; 有 `defects` 逐条读
- `saved_incoming` 是服务端留档路径, 事后复查原图从那里取; `ms` 进节拍账

## 触发点表怎么写

**两个金手指检测位各触发一次**(点1、点2 都发 10082), 表面点走 10083。
不要只留一个“总触发点” —— 会漏掉第二个拍照位, 而且旧单点帧号往往与真实检测位差几十帧。
改完用帧号对一下段表: 检测点应落在对应的“金手指检测 / 表面检测”段内, 不在就是帧号错了。

落盘字段带 `trigger / result / jpg / trigger_err / result_err`: 触发成功但 `result` 失败 = 判决丢了; 触发失败 = 检测根本没跑。

## 🔴 帧号是 0 基索引: 人话「第 126 点」= `frames[125]`

表里 key 与 `frames` 下标同基(0 起), 而现场说的点号是 1 起。写 `{126: 金手指}` 去等「第 126 点」,
那一轮拿到的 `i=125` ⇒ `AOI_ON_ARRIVE.get(125)` 是 None, `if _aoi and ok` 直接跳过,
**不打日志、不报错、HTTP 全 200**。写表一律先减 1: 126→125、152→151, 表面点同理。

## 怎么证明真的触发了(两步, 别拿真机节拍当测试)

1. `grep -o '"aoi".\{0,600\}' zmax_data/rokae_sdk/traj_step_out.log | tail -1` ——
   出现 `"i":125` + `detect_type:"gf"` 才算触发。
2. 日志里的 `_cap.aoi_on_arrive` 只证明**代码是活的**(表已加载), 不证明触发过。
   表是新的而 `"aoi"` 全场 0 命中 ⇒ 就是 get() 没命中, **先查 key 基别**, 不要去怀疑容器挂载或重启。
   (执行器 `docker run --network host -v ~/zmax:/repo`, 每轮新起容器 ⇒ 改 Python 无需重启任何服务, 下一轮自动生效。)

## 已经过了检测位还没触发 ⇒ 退游标重走, 不动轨迹

`zmax_data/rokae_sdk/traj_step_state.json` 的 `cursor` 只是计数: 改成 `目标帧 - 1` 再点一次单步,
真机物理上就在那位姿附近 ⇒ 这一步是原地保持, 安全。改前 `cp` 备份, 并在文件里记 `rewound_from`。
轨迹真源 `real_traj_joints.json` 一字节不动。

## 判决里没有逐根计数 —— 「19 根金手指」问不出来

`/last_result` 只有 `count`(缺陷数) / `defects[]` / `verdict`; 没有 `detections[]`, 没有逐根坐标或计数。
`/detect_detail /defects /config /version /result` 实测全 404。
⇒ `verdict:OK, count:0` 的语义是「没检出缺陷」, **不等于**「看到并通过了 19 根」。要答这类问题只能另开数据源,
别用 OK 反推模型看没看见。

`/picture?kind=topview|judge|960` 参数被忽略, 四种都回同一份文件(md5 相同) ⇒ 拿到的是原图;
真正的判据图 `Finger_TopView_W900_H1660_*.png` 只在服务端机器本地盘上, 接口不暴露。

## 黑帧不等于「没有金手指」

`/picture?grab=1` 的成像取决于抓的时刻: 不在检测位抓到的是暗且失焦的空视野
(实测 mean 20 / median 11 / Laplacian var 6.5 / Canny 边密度 0.15% / FFT 无周期峰)。
判「看不清」先分清是 ①时机不对 ②曝光/对焦 ③真没有 —— 前两者最常见。
真 19 根光栅应在列剖面或 FFT 出现 ≥2–3× 的周期尖峰; 实测只有 1.2–1.5× 就是根本没结构。

## 假成功识别

`code:200` 只代表 HTTP 成功, 不代表这次检测跑了。核对 `t` / `ms` / `saved_incoming` 时间戳是不是刚触发的那一次。
改完先单发一次 POST+GET 验证通路, 再等真机走到位 —— 不要拿真机节拍当测试。
