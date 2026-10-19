# 借用生产端进程的检测器 (权重加密/本机没有时)

适用: 生产机上的检测器权重是加密的(`*.pt.enc`)且解密器只装在那台机器, 本机既无权重也无加载器;
但那台机器上有反向通道, 可以让它拿自己的解释器跑检测、再把结果读回来。

前置(必须先验证通道是活的, 别先写业务逻辑): 往队列写一条`Get-Date`之类无害命令 → 等十几秒 →
输出目录里出现新文件且内容正确, 才算通道可用。**通道死了和"检测失败"是两件事**, 别混。

## 1. 从跑着的服务里取解释器真路径

生产机 `python` 往往不在 PATH(裸 `python` 会报 "无法将 python 项识别")。从**正在跑服务的进程**里取:

```powershell
Get-CimInstance Win32_Process | Where-Object {$_.Name -like '*python*'} | ForEach-Object {
  $_.ProcessId.ToString() + ' :: ' + $_.ExecutablePath + ' :: ' + $_.CommandLine }
```

实测会看到两条(venv 一份 + 系统 Python 一份)—— 这本身就是"双实例抢相机"的常见来源,
但取路径时两个都要记下: venv 那份通常带着正确的工作目录。

## 2. 送图: 先看静态根在哪

反向通道的静态目录(`--dir` 参数)就是生产机 `iwr` 下载的根。把图写进去, 生产机侧:

```powershell
Invoke-WebRequest -Uri 'http://<本机IP>:<port>/<file>.png' -OutFile 'C:\Windows\TEMP\in.png' -UseBasicParsing
```

`-UseBasicParsing` 不能省(PS 5.1 不带它会卡在 IE 初始化), 加 `-TimeoutSec 20`。

## 3. 执行: base64 绕引号地狱

PowerShell 里内嵌 python `-c "..."` 的引号会互相打架。做法: 本机把 python 脚本 base64,
PowerShell 侧解码写文件再执行:

```python
b64 = base64.b64encode(code.encode("utf-8")).decode()
ps = ("[IO.File]::WriteAllText('C:\\Windows\\TEMP\\det.py', "
      "[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%s')), "
      "(New-Object Text.UTF8Encoding($false))); " % b64)
ps += ("& 'D:\\<app>\\venv\\Scripts\\python.exe' 'C:\\Windows\\TEMP\\det.py' 'C:\\Windows\\TEMP\\in.png' 2>&1")
```

python 脚本本体(路径按实际改):

```python
import sys, json
sys.path.insert(0, r'D:\<app>')            # 厂家模块所在
from yolo_detector import YoloDetector      # 其内部会加载加密权重
print('PY', sys.executable)
try:
    import torch; free, total = torch.cuda.mem_get_info()
    print('GPU free/total MB: %.0f / %.0f' % (free/1048576, total/1048576))
except Exception as e:
    print('gpu?', e)
d = YoloDetector()                          # 构造时预热, 实测 5~12s/模型
r = d.detect(sys.argv[1], detect_type='<model>')   # 接文件路径, 不是数组
print('RESULT_JSON ' + json.dumps(r, default=str, ensure_ascii=False))
```

注意 `detect()` 吃的是**文件路径**(框架内部落盘再读), 所以送图必须先落成文件, 不能传内存数组。

## 4. 取结果: 按 mtime 过滤(最容易踩)

```python
t_mark = max((os.path.getmtime(p) for p in glob.glob(out_dir + '/*.txt')), default=0.0)
# ...入队...
for _ in range(tries):
    time.sleep(gap)
    fresh = [p for p in glob.glob(out_dir + '/*.txt') if os.path.getmtime(p) > t_mark]
    for p in sorted(fresh, key=os.path.getmtime, reverse=True):
        for ln in open(p, encoding='utf-8', errors='replace').read().replace('\r','').splitlines():
            if ln.startswith('RESULT_JSON '):
                return json.loads(ln[len('RESULT_JSON '):])
```

**不做 mtime 过滤就会读到上一轮的结果**。实测: 拿到的 `saved_incoming` 时间戳比当前早 2 分钟,
判决数字看着合理, 但根本不是这一次的。判据: 结果里的落盘文件名/时间戳必须晚于本次入队时刻。

## 5. 结果字段与常见解读

实测返回形态:

```json
{"result": 1, "detect_count": 1,
 "detections": [{"xyxy": [x1,y1,x2,y2], "class_id": 0,
                 "class_name": "housing_pit", "confidence": 0.473}],
 "saved_incoming": "D:\\...\\incoming\\<ts>_001.png",
 "saved_pre_detect": "D:\\...\\pre_detect\\<ts>_002.png"}
```

- `saved_*` 是**证明这是新一次运行**的时间戳凭据, 别丢。
- `class_name` 暴露类别表上限: 只有 4 类的外壳模型**没有划痕类** —— 用户说"有划痕"而模型报 `pit`,
  那是类别缺失不是漏检。
- 坐标是**送进去那张图**的坐标系; 若你送的是整幅旋转图, 报给用户的框坐标也是整幅坐标,
  换算回原图的逆变换要一起给出, 否则用户无法核对。

## 6. 不要做的事

- 不往生产机装包、不起第二个服务实例(相机/GPU 是共享资源)。
- 不改生产程序(要用唯一合规部署路径, 见其他技能)。
- 不把 `detect_count=0` 当成"合格": 工件不在位时它也是 0。先看"在位"判据(几何/搜索是否成功)。
