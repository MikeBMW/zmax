# 远程看产线相机的三条路：Orin 反代 / 550C 隧道 / ECS 中转

本机（操作端）不在产线网时，每一路相机都得有一条别人替你转的路。三路并存、互不冲突，
按「离现场最近的优先」选。

## 1. 手臂相机（Orin 相机，D405）

- 设备侧：Orin 上 `tools/rs_fast_node.py` 起 HTTP `:8792/frame.jpg`（JPEG 单帧）。
- 本机侧：`zmax-orin-arm-fwd` = `ssh -NT -p <跳板口> -L 127.0.0.1:18792:127.0.0.1:8792 <user>@<跳板>`。
  注意 `-L` 的**远端**那一跳是在跳板机侧解析的 —— 真正落地是“跳板口后面那台设备”的 8792，
  不是跳板机自己的 8792。判据：`curl -s -o /tmp/a.jpg -w '%{http_code} %{size_download}'`
  得 200 + 几十 KB（实测 ~59KB/640x480）。

## 2. 中央相机（550C / Intel 的 USB 相机）

- 设备侧：`http://<intel>:8812/snap.jpg`。
- 本机侧：`zmax-intel-cam-tunnel` = `ssh -N -L 127.0.0.1:8812:127.0.0.1:8812 intel`（`intel` 走 ProxyJump 经跳板）。
- 喂页面的方式：`cam_live_stream.py --local2-url http://127.0.0.1:8812/snap.jpg --local2-label "🎥 中央相机" --local2-fps 10`。

## 3. ECS 中转（谁都能推，本机只读）

用于「本机与设备互相都直连不上、但两边都能出公网」的场合。

```bash
# 推：源侧（能拿到帧的那台机器）
curl -X POST --data-binary @frame.jpg -H 'Content-Type: image/jpeg' \
  "https://<domain>/api/relay/cam/push?cam=arm"
# 读：本机 / 页面
curl -s "https://<domain>/api/snapshot/arm" -o frame.jpg
```

- 服务端落 `cams/<cam>_<YYYYmmdd_HHMMSS>.jpg`，读的时候取该 cam 最新一张。
- **路径别猜**：`/api/relay/cam/<name>.jpg` 回 404 JSON；`/cam/latest.jpg`、`/api/relay/cam/latest.jpg`
  会优先回 **archive 里的历史快照**（几周前那种），永远 200 —— 用它当实时画面等于把旧图说成现场，
  必须看 `GET /api/relay/cam/status` 里的 `width/height/age_s/last` 才能判断有没有人在推。
- 端到端验证（唯一可信的）：推之前记 `md5sum`，推完 `GET /api/snapshot/<cam>` 再 `md5sum`，
  **两值必须一致且字节数相同**；只有这个能证明“推上去的确实是拿回来的”。
- 测完**必须清掉自己推的测试帧**（`rm -f <relay>/cams/<cam>*.jpg`），否则页面会把一张测试图
  当“实时”一直显示，`age_s` 还很小，肉眼分辨不出来。
- 中转端没有推帧进程是常态：设备上跑不跑推帧要看有没有 unit，`orin_uplink` 那类只推遥测的脚本
  **不推图**，不要因为遥测在线就以为相机也在推。

## 启动器选源顺序（写成代码，不要靠人记）

`tools/start_station_stream.sh` 的定式：

- 手臂：产线直连 `http://<orin>:8792/frame.jpg` → 本机隧道 `127.0.0.1:18792` → ECS 中转 `…/api/snapshot/arm`
- 中央相机：本机设备号存在就用设备 → 否则 550C 隧道 `127.0.0.1:8812` → 否则 ECS 中转 `…/api/snapshot/central`
- 每一跳探到/探不到都**打印一行**（“走 550C 隧道”/“产线与中转都没帧 ⇒ 这一格会是空”），静默起一个注定没画面的进程是可耻的。

## 验收（缺一不算通）

1. `8793/stats` 或 `8791/stats` 三格 `online=true`，间隔 8~10s 两次取 `frames_served` **都在涨**。
2. 每格取一张 `/snapshot/<name>.jpg`，`cv2.imread` 得尺寸 + `mean/std`：`std<5` 或全黑 = 假帧；
   实测参考：arm 640x480 mean≈23、local 1280x720 mean≈126、local2 mean≈66。
3. 帧率如实报（实测 arm≈3fps 来自 Orin 侧 JPEG 桥、local≈23~27fps、local2≈3.7fps 受源侧节拍限制）。
4. 用户给的旧地址无法打开时先查**本机当前 IP**（WiFi 换网段 DHCP 会给新地址，旧书签 curl 直接 000），
   再给一个不随 IP 变的入口（公网 `<domain>/st/station?k=<token>` 实测页面与 `/st/snapshot/<cam>.jpg` 都 200）。
