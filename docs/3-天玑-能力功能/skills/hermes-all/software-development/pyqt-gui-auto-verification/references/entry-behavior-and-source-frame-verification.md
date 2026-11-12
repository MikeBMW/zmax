# 取证模式: "入口行为/状态同步" 与 "替代数据源真出帧" 怎么验 (2026-09-17 实测)

两类改动**不能用同一种证据**, 混用会得到假 PASS:

## ① 行为级 (入口按状态取参 / 单例窗口复用对齐) — 真函数体 + 假窗口对象

被测对象是"读应用状态 → 决定参数 → 同步窗口"的逻辑, 不必真开 GUI:
- 用**磁盘上真函数体** (import 真模块取方法), 只把窗口/屏幕对象换成桩 (`FakeWin` / `FakeCb` 记录
  `setCurrentIndex` 调用次数), 屏幕用假 `QRect` 列表注入 (PyQt 类属性不让改 → 换掉模块命名空间里的 `QtWidgets`)。
- 覆盖三个方向: 旧状态≠新状态 (必须切) × 2 方向 + 两边一致 (不许乱切, 断言调用次数 0)。
- ⚠️ **桩绑定 `@staticmethod` 必须 `staticmethod(...)` 包一层**, 否则被当实例方法绑 self → TypeError 被
  被测代码的 `except Exception: pass` 吞掉 → **"不许动"的 case 全部假 PASS**。
  排查口诀: 若某个**本该发生动作**的 case 也 `moved/switched=False`, 先怀疑异常被吞, 不是逻辑对
  (诊断: 临时把 `except Exception: pass` 换 `traceback.print_exc()` 跑一遍, 定位后还原)。
- 真窗口级 A/B 台架见 pyqt5-gui-development `scripts/multiscreen_clamp_probe.py`
  (老实现从 `git show HEAD:<file>` 抠出来跑同一台架 — 同台架 old❌/new✅ 才算证据)。

## ② 数据源级 (换了源, 真的出帧了吗) — 直接起真采集器收 N 帧

"窗口不报错 / 日志说已启动"**不是**数据源可用的证据 (同族教训: 影子臂 `calls>0` 实为空转)。
做法: 绕过窗口, 直接实例化真采集器 (`g = _SimGrabber(q, False); g.start()`), 限时收 ≥3 帧, 逐项断言
**形状 + 来源标识 + 设备身份**:
```
帧1: shape=(480, 480, 3)  src=sim:metaworld corner2  device=mujoco 渲染 (非真机相机)
```
对真机源同理: 断言 `device` 里的 VID:PID/序列号 + `age_s`/`seq` 递增 (别只看"有帧")。

## ③ 报告口径 (老倪)

- 他问"为什么" → 先**根因 + 证据** (现场复现数字 / 代码文件:行号 / 真跑输出), 别先给方案列表。
- 说清"改了什么"(哪些文件/行为变化) + 需要他做什么 (重启 GUI / 重开窗口)。

## ④ 跨进程“模型真正吃的那一帧”取证通道 (窗口里那帧 = 输入帧, 不是另渲染一张)

引擎/常驻循环跑在**另一个进程**时, GUI 读不到它的内存帧槽 (`SS_LIVE_FRAME` 这类同进程共享变量对窗口进程等于空)。
用户问"我看到的是不是实际喂给模型的图"时, 唯一站得住的答法是三件套:

1. **写侧**: 在 `predict()` **之前**把真正送进去的那个数组落盘 `/dev/shm/<name>.png` + 同名 `.json`
   (`t / mono / shape / md5_px / md5_rgb / md5_file / src / pid`)。必须 **tmp 文件 + `os.replace`** 原子替换,
   否则窗口会读到半张图 (解码失败 → 窗口空, 看着像"源没帧")。
2. **读侧**: 窗口先读 shm 这帧 (带帧龄上限, 超时就弃用并如实标注), 再回退同进程实况槽, 再回退静态帧+横幅。
   状态栏写 `同源 md5 <x> · 帧龄 <t>s · pid <p>` —— 用户要的就是这一行。
3. **取证**: 下面两条硬判据, 缺一条都不算证完。

- 🔴 **JPEG 会毁掉同源判据**: JPEG 有损 ⇒ 解出来的像素 md5 与模型入参不同 ⇒ 只能比文件 md5, 一改成比像素就假红。
  落盘用 **PNG (`IMWRITE_PNG_COMPRESSION=1`)** : 480×480 ≈184KB, 解码后与 `predict` 入参**逐字节相同**。
- 🔴 **通道序不一致 ⇒ md5 "看着一样但比较为 False"**: 模型入参是 BGR, 窗口解码成 RGB, 同一张图两种字节序。
  sidecar 同时存 `md5_px`(BGR=模型入参) 与 `md5_rgb`(显示口径), 判据比 `md5_rgb`。实测形态: 打出的两个 16 位
  md5 明明相同, 判据仍报 False —— 因为比的是另一个字段。
- **取证不许拖慢主链**: 写盘节流 (monotonic ≥0.15s 一次) + 全程 `try/except: pass` + 环境开关 (`ZMAX_<X>_DUMP=0` 关掉)。
  让取证代码拖慢或抛异常, 就是本末倒置。
- **截图内容断言 (无 vision 也证得动)**: 多尺度 `cv2.matchTemplate(screenshot, resize(dump, s), TM_CCOEFF_NORMED)`,
  s 从 180 步进 20 到窗口宽, 取最大相关 ≥0.9 (实测 0.939 @420px) = 窗口确实把那帧缩放上屏; 再加"解码后像素 md5 相等"
  = 同源 + 上屏两条独立证据。只截图或只 md5 都缺一条。
- **窗口级验证不必抬真窗口**: `QT_QPA_PLATFORM=offscreen` → 直接实例化 grabber 调 `_grab_once()` 断言 info
  (`src/shape/md5/pid`) → 再 `open_*viewer()` + `win.grab().save()` 存证。mujoco/EGL 栈在解释器退出时
  可能 abort (与结论无关), 断言全部打印在 abort 之前即可, 探针结尾可 `os._exit(0)`。
- **这类"看输入"入口的正确接法 (PyQt 画布右键菜单)**: 条件按 node params 判 (`params.viz_kind == 'bypass'` 之类)
  → `a_x = menu.addAction(...)` → `exec_()` 之后用 `elif a_x is not None and chosen == a_x:` 分派 → 调应用自己的
  `open_*()` 单例入口 (窗口源要跟随画布当前数据源)。改完 GUI **必须重启才见**, 重启是用户的动作:
  交付时写"菜单已就位, 重启 GUI 生效", 并同时说明当前有没有活的生产者 (常驻循环没跑 ⇒ 窗口只会显示静态帧)。
