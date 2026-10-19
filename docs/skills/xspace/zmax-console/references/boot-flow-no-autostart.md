# 启动流程硬规矩: 双击图标 → 只落主控制台 home, **不自动开任何窗口**

老倪 2026-10-12 定规矩（原话）:
> 点开启动图标后，3D场景不要自动启动，我要先检查任务配置，然后启动工程

## 规矩
1. 双击桌面图标（= `tools/gui/launch_studio.sh`）后:**只**把控制台落到**配置中心**
   (2026-10-19 起 `ZMAX_BOOT_PAGE=home` = 主控制台; 10-12~10-18 期间是 `config`); **不**开 3D 场景 / 实时监控 / 状态空间画布; **不**自动跑仿真。
2. 开窗的唯一入口 = 老倪自己看完任务配置后点右下角「🚀 启动工程 · 信号 · 场景」
   (= `tools/zmax_open.py step2` 同一执行体)。
3. 已有实例在跑时, 双击图标 = 写 `config` 命令 + 激活窗口, **绝不**起第二个进程。

## 实现要点(踩过的坑)
- **`/tmp/zmax_nav_cmd` 残留 = 假"自动启动"**: 新控制台进程的去重表是空的, 若该文件里还留着上一轮
  写的 `open_all` / `ss_3d`, 界面一建好(0.3s)就把 3D/信号窗全开出来, 看起来就是"自己开的"。
  ⇒ `launch_studio.sh` **启动前 `: > /tmp/zmax_nav_cmd`**, 并 `unset ZMAX_AUTO_RUN ZMAX_AUTO_SS
  ZMAX_AUTO_SS_RUN ZMAX_AUTO_SS_3D ZMAX_AUTO_TEST`。
- 所有自动开窗钩子(studio.py 启动段 `_oneshot(... _auto_*)`)必须**只在显式 env 下**触发,
  正常启动路径一个都不走。
- 助理自己不要为了取证往命令通道写 `open_all`/`ss_3d` 后不说 —— 老倪会把它当成开机自动启动。
  取证请走 `verify_no_autostart.py`(它自己清现场)。

## 判据
`tools/verify_no_autostart.py`: 先塞一条旧命令模拟残留 → 走 `launch_studio.sh` 启动 →
核 ① 控制台起来 ② 日志有「开机默认页: config」 ③ 45s 内无标题含「3D场景/实时监控」的窗口
④ 启动后命令文件为空。任一条不过 = FAIL。
