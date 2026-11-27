# 控制台生命周期: 谁可以重启 · 关窗不能崩 · 复用窗口要重读配置

## 1. 不要自作主张重启用户的控制台

用户正在用的控制台是**他自己**启动的 (VSCode F5 / launch_studio.sh)。改完代码需要生效时:

- 先问，或直接给出启动命令 `bash /home/ubuntu/zmax/tools/gui/launch_studio.sh`，让他自己按；
- 自己拉起来的那个实例，发现他另有实例在跑时要**停掉自己那个** (按 pid 精确 kill，不要 `pkill -f studio.py`
  扫全量)；
- 反复“改了→自动重启→再改→再重启”会打断他手上的操作，是最容易惹火的一条。

例外只有一个: 用户明确说“你重启吧”。

## 2. 关窗口不能崩 (QThread Destroyed → Aborted)

症状: 关主窗口后 `/tmp/studio_launch.log` 尾部出现
`QThread: Destroyed while thread is still running` + `Fatal Python error: Aborted`，进程退出码 -6 并落 core。

根因: `sys.exit(app.exec_())` 让解释器进入 finalize, 信号页回放/3D/DDS/看门狗这些 QThread
还没 join 就被 QObject 析构 → Qt qFatal。

修法 (studio.py `main()` 末尾):

```python
_rc = app.exec_()
try:
    sys.stdout.flush(); sys.stderr.flush()
except Exception:
    pass
os._exit(int(_rc) if isinstance(_rc, int) else 0)   # 跳过 finalize, 与 SIGTERM 通道同款处置
```

判据 (真开窗→真关窗, 不看感觉):

```bash
B=$(grep -c 'Fatal Python error' /tmp/studio_launch.log)   # 基线
DISPLAY=:0 wmctrl -ic $(DISPLAY=:0 wmctrl -l | grep 'XSpace ZMAX' | awk '{print $1}')
sleep 8
grep -c 'Fatal Python error' /tmp/studio_launch.log        # 必须等于基线
```

离屏平台 (`QT_QPA_PLATFORM=offscreen`) **不能**用来验这条: 离屏启动会在 pyqtgraph/GL 处自己段错,
与关窗路径无关, 会把你带进假故障。

## 3. 配置窗口是复用的 → 配置改了要重读

症状: 用户改 json 数值后“改了没生效”。两种真因都要一起排:

1. **代码把用户填的数又夹回去了**: 例如下限写成 170, 他填 120/100 当然没变化。夹值范围要和文档一致。
2. **窗口对象复用**: 配置中心不新开第二个 page, 宽度/尺寸只在**构造**时读一次文件 ⇒ 再点开还是旧值。
   修法: 在既有 `showEvent` 里挂一次 `QTimer.singleShot(0, self._reapply_*)`, 并且只在
   (内容需求 / 配置值 / pin) 指纹变了时才落 —— 否则会把用户手拖的结果冲掉。

另外: 同一类里**重复定义 `showEvent`** 会被后一个定义覆盖 (Pyright 只报 obscured,
运行时不报错但你的代码永远不跑); 改前先 `grep -n "def showEvent"`。

## 4. 背景进程完成通知

每次 `launch_studio.sh` 后台启动都会在稍后回一条 exit-code 通知; 若那是已被自己 kill 的旧实例,
一句话说明即可, 不要把通知当成新故障去重新排查一遍。
