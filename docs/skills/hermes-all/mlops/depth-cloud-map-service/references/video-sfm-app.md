# 视频建图 → 手机 Web App → 公网子路径

配套 SKILL.md 律 4/律 5。适用于「拍一段视频就要出点云、手机上能看不装 App」这类需求。

## 为什么是 Web App, 不做 APK

手机浏览器原生 `<input type="file" accept="video/*" capture="environment">` 直接调后置摄像头录像,
拿到的是**真视频文件**(不是 blob 流), 一次上传即可建图。
对比 APK: 免签名/免打包/免应用商店, iOS 与安卓同一份代码, **改完刷新就生效**。
只有当 HTML 必须打进包内 `assets/` 时才需要重打包 —— 这个场景不需要。

## 架构

```
手机浏览器
  └─ POST /upload (multipart)  ──→ 落到 job 目录 input.mp4
                                     ↓ 后台线程
                                   ffmpeg 抽帧 2fps
                                     ↓
                                   mono_sfm.py --frames <dir> --out <job>/map
                                     ↓
              points.ply → points.json / trajectory.tum → trajectory.json
                                     ↓
手机轮询 GET /job?id=  ←── job.json (状态/帧数/点数/耗时)
  └─ GET /points?id= → Float32Array → 原生 WebGL 渲染 (不引 3D 库)
```

## 后端骨架 (stdlib, 零第三方依赖)

`http.server.ThreadingHTTPServer` 足够; **不要为这个引 Flask/FastAPI** —— 目标机可能只装了 numpy/cv2,
零依赖才真正可跨机部署。

```python
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"              # 允许 keep-alive
    def log_message(self, *a): pass            # 静音, 日志自己写文件

    def do_POST(self):
        # 从 Content-Type 头取 boundary, 不要 import cgi (py3.13 已移除)
        boundary = self.headers["Content-Type"].split("boundary=")[1].strip().strip('"').encode()
        body = self.rfile.read(int(self.headers["Content-Length"]))
        for part in body.split(b"--" + boundary):
            if b'name="video"' in part and b"filename=" in part:
                idx = part.find(b"\r\n\r\n")
                vdata = part[idx + 4:].rstrip(b"\r\n-")
```

要点:
- `client_max_body_size` 必须配到足够大(nginx 默认 1m 会 413)。
- 上传限额在应用层也挡一次(如 800MB), 别只靠 nginx。
- 后台线程跑建图, 请求立即返回 `job id`; 前端轮询。

## 抽帧参数

```bash
ffmpeg -i input.mp4 -vf fps=2 -qscale:v 3 frames/f_%04d.jpg
```
- **2fps 是折中**: 手机 30fps 全用没必要, 2fps 视差够且三角化快。
- 抽完若超 `--max-frames`, **均匀抽稀**(保时间覆盖), 不要截断前 N 帧 —— 截断会丢掉后半段位姿。
- 抽帧目录建成即删, 别长期占盘。

## 任务状态必须落盘

内存里的任务表在服务重启后全丢 ⇒ 历史图无法打开、分享链接失效。
每个 job 写 `job.json`, 读接口先查内存再回退读盘:

```python
def _load(jid):
    with LOCK:
        if jid in TASKS: return TASKS[jid]
    p = os.path.join(_job_dir(jid), "job.json")
    if os.path.exists(p):
        d = json.load(open(p)); TASKS[jid] = d; return d
    return None
```

状态机固定为 `queued → extract → sfm → done | failed`, 失败把 `err` 原文返回 ——
用户看到「失败: 视频太短或抽不到帧」比看转圈强。

## 前端要点

- 🔴 **别引 Three.js**。画点云+轨迹线只要 ~150 行原生 WebGL, 而 three.module.js 是 **1.27MB**。
  实测这条公网链路(ECS 出口约 **0.57 Mbps**): 1.27MB 直连隧道 **25s 超时**,
  本地托管后 18.3s, gzip 到 311KB 仍要 5.8s; **全改原生 WebGL 后整页 11KB / 0.33s**。
  换算惯例: **每 100KB ≈ 2 秒**, 页面总重超 100KB 就该怀疑。
  只引库不换架构(先做 CDN→本地托管)是**缓解不是修复** —— 本地托管只解决「内网没外网白屏」, 不解决传输时间。
- 渲染所需: `mat4mul` / `perspective` / `lookAt` 三个矩阵函数 + 一个 `gl.POINTS` 管线;
  顶点属性 `aPos`+`aCol`, 轨迹用 `gl.LINE_STRIP` 单独一个 buffer, 用 `vertexAttrib3f` 喂固定橙色。
- 点云归一化到单位球再灌 `Float32Array`(质心平移 + 半径缩放),
  否则 mono_sfm 的归一化尺度五花八门, 手机上一开就在视野外。
- 触屏: `touchstart/touchmove` 扭 `rot`, 双指 `hypot` 扭 `dist`; `touch-action: none` 必须加。
- `?id=xxx` 支持直接打开已有任务 —— 这才叫「发给我一下」, 否则对方打开是空白上传页。

## 🔴 渲染验收: `readPixels` 全 0 **不等于**画布黑

WebGL 默认 `preserveDrawingBuffer: false`, 帧外调 `gl.readPixels` 读到的是**已清空的缓冲**,
恒为全 0。据此判「渲染坏了」会白排一轮根本不存在的 bug。两个可靠口径:

1. 建上下文时开 `preserveDrawingBuffer: true`, 之后随时 `readPixels` 判「亮点占比 + maxVal」。
   本例 `litPct 2.46% / maxVal 255` = 真画出来了; 全 0 且 `maxVal 0` 才是真空。
2. 页面里挂 `window.__zmap = {n: 点数, gl}` 调试钩子, 外部直接查点数/缓冲。

判定顺序: **先查点数灌进去了没有**(`__zmap.n`), 再查像素。两者都过才算渲染通。
反过来「状态栏显示 5690 点」不能当渲染证据 —— 那个数字来自 `job` 接口, 与画布无关。

## 公网接入 (律 5 的展开)

```
手机 → ECS 80 /map/ → nginx ^~ /map/ → 127.0.0.1:18794
     → SSH 反向隧道 (工位机中转) → <目标机>:880x
```

反向隧道用 systemd `Type=simple` + `ssh -NT -R`, 密码走 `EnvironmentFile` + `sshpass -e`
(**不要把密码明文写进 unit**)。worker 机不需要能让 ECS 主动连入, 反转隧道方向即可。

nginx:

```nginx
location = /map { return 301 /map/; }
location ^~ /map/ {
    proxy_pass http://127.0.0.1:18794/;      # 尾斜杠会把 /map/x 去前缀成 /x
    client_max_body_size 800m;
    proxy_request_buffering off;              # 大视频别先攒全再转发
    proxy_read_timeout 1800s;                 # 建图是长任务, 默认 60s 必超时
}
```

## 验收清单

| 项 | 判据 |
|---|---|
| 页面 | `/map/` 200, 大小与源文件一致, **打开耗时 < 1s** |
| 页面总重 | **< 100KB**(超了先怀疑引了 3D 库) —— 别只测 200 |
| 渲染 | `__zmap.n` == 点数, 且 `readPixels` 亮点占比 > 0 / maxVal 255 |
| 公网上传 | 真传一个视频, 返回 `bytes` 与本地文件大小相同 |
| 建图 | `job` 转 `done`, 报 `points` 和 `reproj_err_med_px`(律 4) |
| 重启恢复 | 重启服务后旧 `?id=` 仍能打开(读的是 job.json) |

🔴 **全部接口 `failed to fetch` 但单独 `curl` 每个端点都是 200** ⇒ 不是接口坏, 是**首屏资源超时**:
`<script type="module">` 里 `import` 失败会让**整个模块脚本**崩, 之后所有 `fetch` 都报这个错。
定位法: 量**体积最大的那个静态资源**的 `time_total`, 而不是挨个测接口。

若确实还有大文件, gzip 后 300KB 左右是正常的(解压后应等于源文件大小, `gunzip -c | wc -c` 核),
别看到 300KB 就以为被截断 —— 但「压缩正确」不等于「够快」, 见上面每 100KB≈2 秒的预算。
