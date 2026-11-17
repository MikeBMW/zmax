# D405 高分辨率采集（1280×720）—— pyrealsense 接管 + 内参按分辨率重取

用途: 3DGS 建图 / 检测要更高清源图, 而现役链是 cv2 UVC 640×480 时。
**核心事实: cv2 + V4L2 在 D405 上开不到 640×480 以上**（见下）, 只有 SDK 能。

## 1. 先证「cv2 这条路的上限」, 别只改环境变量
把宽高做成环境变量后重启服务, 表现极具欺骗性: `enc=direct`、`fps 30`、`err` 空 —— 而帧仍是 640×480。
判据只有**回读实际帧尺寸**:
```bash
curl -s -o /tmp/f.jpg http://<host>:8792/frame.jpg
python3 -c "from PIL import Image; print(Image.open('/tmp/f.jpg').size)"   # 仍 (640,480) ⇒ 设置被静默忽略
```
⇒ 该机从此换成 SDK 取流。别在 `CAP_PROP_FRAME_WIDTH/HEIGHT` 上继续试。

## 2. 枚举设备真正支持的 profile（不需要开流，相机被别人占着也能读）
```python
import pyrealsense2 as rs
dev = list(rs.context().query_devices())[0]
for s in dev.sensors:
    for p in s.get_stream_profiles():
        if p.stream_type() != rs.stream.color:
            continue
        v = p.as_video_stream_profile()
        print(v.width(), v.height(), v.fps(), v.format())
```
- `dev.profiles` **不存在**（老 API 才有）⇒ 必须走 `dev.sensors → get_stream_profiles()`。
- 实测 D405 彩色: 1280×720@{5,15,30} / 848×480@{5,15,30,60,90} / 640×480@{5,15,30,60,90}, 格式 yuyv·rgb8·bgr8·y8 等。

## 3. 内参必须按分辨率重取 —— 各档 **FOV 不同, 不是缩放**
实测同一台 D405: `1280×720 fx=655.065 fy=654.084 cx=637.413 cy=357.770` ·
`848×480 fx=436.710` · `640×480 fx=394.062`。
640 的 fx×2 = 788, 与真的 655 差 **+20%** ⇒ **拿 640 的标定文件等比缩放去渲 720p 的 3DGS,
重投影一定对不上、整图发虚**, 而且训练侧只会表现为"指标偏低", 极难归因。
```python
v = profile.as_video_stream_profile()
i = v.get_intrinsics()          # fx fy ppx ppy coeffs, 与 fps 档无关
```
规范化做法: 相机服务暴露 `GET /intrinsics` 返回 `{ok,w,h,fps,fx,fy,cx,cy,coeffs}`, 下游**优先用它**,
只有拿不到时才退回"标定文件等比缩放"那条老路, 并在 `cameras.json` 的 `K_src` 里写明是哪一种。
⚠️ 手眼外参 `T_cam2tool` 与分辨率**无关**, 换分辨率不必重标外参 —— 只换 K。

## 4. SDK 取流的三个 API 坑
| 坑 | 现象 | 正解 |
|---|---|---|
| `cfg.enable_stream(type,w,h,fmt,fps)` 五参 | `TypeError: incompatible function arguments` | 用**六参** `enable_stream(type, index, w, h, format, fps)` |
| `cfg.enable_stream(profile_obj)` | 同上 | 同上, 从 profile 取 `stream_index()/format()` |
| 只按尺寸+帧率挑 profile | 挑到 y8/y16 单通道 16 位 ⇒ JPEG **纯白** | 按格式优先序 `bgr8 > rgb8 > yuyv > y8` 现挑 + 编码前归一化 |

## 5. SDK 独占设备 ⇒ 必须把 cv2 消费者全部停用
D405 的 UVC 节点只能有一个进程开着。有 cv2 读者在跑时, pyrealsense 直接
`xioctl(VIDIOC_S_FMT) failed, errno=16 Device or resource busy`。
- 先找全占用者: `for d in /dev/video*; do fuser $d; done` + `systemctl list-units | grep -iE 'rs-|d405'`
  + `systemctl --user list-units | grep -i 8794`（8794 那类 relay 常是**用户级** unit，系统级里看不到）。
- 停的时候 `systemctl stop` 可能被 `Restart=always` 立刻拉起 ⇒ `stop` 后**逐个 kill -9 残留**,
  趁端口空着立刻起新服务; 顺序错了就一直 `Device busy`。
- 新服务**同时监听旧的两个端口**(如 8792+8794), 下游零改动 —— 比改下游 URL 稳得多。

## 6. 带宽: 720p@30 开不动, 15fps 才稳
`1280×720 YUYV@30 ≈ 55 MB/s` > USB2 实侧 ~40 MB/s ⇒ `Frame didn't arrive within 4000`。
降到 **15fps（≈27 MB/s）** 正常；这时**再加 848×480 深度也会超**（实测直接 `Frame didn't arrive`）⇒
建图只要彩色时把深度关掉(`RS_DEPTH=0`), 下游深度 URL 置空, 别让它吃旧 depth。

## 7. systemd drop-in 排序会把你的参数吃掉
`/etc/systemd/system/<unit>.service.d/*.conf` 按**文件名字典序**合并, 后合入的胜。
实测已有的 `zz-direct.conf` 里写着 `Environment=D405_FPS=30`, 新加的 `hd.conf` 里写 15 ⇒ 生效值是 **30**
(于是带宽超限, 又变成"改了没生效")。
- 定式: 自己的 drop-in 命名 **`zzz-*.conf`**, 或者直接改那条已存在的 `zz-*.conf`。
- 改完必须回读: `systemctl show <unit> -p Environment | tr ' ' '\n' | grep <KEY>`,
  以及 `tr '\0' '\n' </proc/<pid>/environ | grep <KEY>` 两处都对上才叫生效。

## 8. 验收五件（缺一不算通）
```
① 服务自己报: color 1280x720@15 format.bgr8 · fps>10 · err 空
② /intrinsics 的 w/h 与帧尺寸一致, fx 是 SDK 真值(不是 640 标定×2)
③ 连取三张 /frame.jpg 的 md5 全不同       ← 排除冻结/重复
④ 解码 mean 150~210 · std 70~90           ← 排除纯白/纯黑
⑤ 下游 HTTP 层回读: 8791 /snapshot/arm.jpg 也是同一尺寸且 stalled=false
```

## 9. 落地后要主动交底的两件事
- 下游页面/算法如果**假设 640×480**(按像素坐标算框、按固定比缩放), 换 720p 后会整体偏 —— 要么一起改, 要么显式告知。
- 深度那一路若被关, 页面上"深度图"那格会变空; 要说清是主动关的, 别让现场当成新故障。
