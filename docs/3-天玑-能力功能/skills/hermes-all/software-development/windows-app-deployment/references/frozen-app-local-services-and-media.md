# 冻结包里的“小服务”与页面媒体接线

冻结包只带 GUI，不带按钮指向的那些小服务；页面则可能按“原始部署”的端口写死媒体地址。
两类症状都是“点了没反应 / 画面全黑”，而服务端自检是好的。

## 1. 按钮打不开：服务没被打包

证据在代码注释里就能找到：负责“本机微型服务”的模块（`local_services` 一类）通常直接写明
“这两个服务在产线上是常驻进程，冻结包里没有它们”。

修法：启动器里“端口没听就拉起”，用程序自带的 exe 当解释器（PyInstaller onedir 的
`app.exe <script.py>` argv dispatch），不依赖机器上装 Python：

```powershell
function Start-LocalSvc {
    param([int]$Port, [string]$Script, [string]$Extra)
    try {
        $up = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).Count
        if ($up -gt 0) { return }                        # 已在跑，别起第二份
        $sp = Join-Path $root $Script
        if (-not (Test-Path $sp)) { return }
        $argStr = '"' + $sp + '"'
        if ($Extra) { $argStr = $argStr + ' ' + $Extra }
        Start-Process -FilePath $exe -ArgumentList $argStr -WorkingDirectory $root -WindowStyle Hidden
    } catch { }
}
Start-LocalSvc -Port 8799 -Script 'tools\dashboard_server.py' -Extra ''
Start-LocalSvc -Port 8797 -Script 'tools\tcp_ar_server.py'    -Extra '--port 8797'
```

要点：

- **从 `tools\` 那份启动，不要用 `_internal\tools\`**。这类脚本用 `os.path.dirname(__file__)`
  找同目录资源（`web/<page>.html`、模板、fixture），`_internal\tools\` 下往往没有这些；
  报错只有一句“页面不存在”，进程直接退出、端口也不听。两个副本都要用时就都补齐资源。
- **加载重依赖（cv2 等）的服务要 15~25 秒才响应 HTTP**。端口先监听、请求先超时是正常的；
  验收要等够（分两次探测，别把“还在初始化”当成起不来而重启）。
- 只在端口没听时起，否则每次点图标都叠一个重复服务抢同一端口。
- 端口检查放在启动器**最前面**（含“已在运行”提前 return 的分支之前），否则第二次点图标时
  什么都补不上。

## 2. 页面能开、图全黑：媒体地址指到没人听的端口

1. 浏览器里数图：`Array.from(document.querySelectorAll('img')).map(i=>[i.id,i.src,i.naturalWidth])`
   —— 全为 0 就是没取到。
2. 找媒体基址助手（常见 `_mb()` / `mediaBase()` / `API2`）：常写死“主端口 + 第二端口”
   （同一进程双端口的设计），本部署只起一个端口 ⇒ 全部落到关闭端口。改成同端口相对路径
   （`const _mb=()=>''`），服务端本来就在同一端口提供同样的流。
3. 硬编码的外部叠加源（`http://127.0.0.1:8898/xxx.jpg`）在对应服务没跑时也是 404；
   改回本服务自己的快照端点（`/snapshot/...`）。
4. 叠加层端点 `/snapshot/overlay_<cam>.jpg` 在没启用叠加 worker 时返回 503：
   在 snapshot 处理里做降级——叠加帧没有就返回原图，页面不用改：

```python
def _snapshot(self, name):
    jpg, seq, *_ = _get(name)
    if (not jpg) and name.startswith("ov_"):     # overlay 槽空 → 回落原图
        jpg, seq, *_ = _get(name[3:])
```

## 3. 改了页面不生效：外部页面静默覆盖内嵌页面

服务端常见两种取页方式：先看 `web/<page>.html`（按 mtime 热读），没有才用代码里内嵌的字符串。
把一批页面复制进 helper 所在目录，会**静默**把生效页面换成那份外部文件——之前针对内嵌页做的 URL
修复全部失效，症状是“刚修好的相机又黑了”。

判据：

```bash
grep -n 'web/.*\.html' <helper>.py                                  # 它怎么解析页面路径
curl -s http://127.0.0.1:<port>/<page> | grep -c '<你改的那行>'      # 服务出去的到底是哪一版
```

改页面时把两份都改（源码目录 + `_internal` 下的副本），或只留一份并确认服务读的就是它。

## 4. 验收清单

- 每格图的 `naturalWidth` > 0，或快照是 `ffd8` 开头的真实 JPEG——不是服务的 `online:true`
- 按钮指向的端口 `Get-NetTCPConnection -LocalPort <p> -State Listen` 有进程，且父进程是新起的 GUI
- 页面里的媒体 URL 与 `Get-NetTCPConnection` 的实际监听端口一致（没有指向第二个端口）
- 重启一次（按用户真实方式：双击快捷方式）后上述各项仍成立，才算修好
