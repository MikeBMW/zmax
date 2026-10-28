---
name: gnome-desktop-launchers
description: Use when GNOME .desktop 快捷方式叉号/未信任/双击没反应/启动两次。
---

# GNOME 桌面 .desktop 快捷方式维护 (Ubuntu 24.04 + DING)

## 触发场景
- 桌面 .desktop 快捷方式图标带叉号(未信任徽章), 或双击提示 "untrusted desktop file" / 无法启动
- 新建桌面快捷方式后图标不对/无法打开
- 系统克隆/rsync 迁移后桌面快捷方式失效 (E盘迁移后 09-06 复现过)
- 双击图标「第一次没反应 / 要点两次才开」/ 启动后几十秒才有窗口

## 叉号 = 什么
Ubuntu 24.04 (GNOME 46) 桌面图标由扩展 **Desktop Icons NG (ding@rastersoft.com)** 渲染。
.desktop 图标上的叉号 = DING 判定该启动器**未信任 (untrusted launcher)** = "不可运行"状态标记, 不是文件损坏、不是资源缺失。

## 信任判定三条件 (先查文件, 再动扩展)
1. 执行位: `ls -l ~/Desktop/*.desktop` → 须含 x (如 -rwxr-xr-x)
2. Exec / Icon 目标真实存在:
   - `ls -la <Exec路径>` — 脚本须存在且有 +x
   - Icon 可为主题图标名(utilities-terminal) 或绝对路径文件
3. trusted 元数据: `gio info ~/Desktop/X.desktop | grep trusted` → 须见 `xattr::metadata::trusted: true`

## 核心坑: DING 信任缓存不刷新
- DING 在文件创建/变更时缓存 `_trusted=false`; 事后 `gio set metadata::trusted true` **只写 xattr, 不触发 inotify**, 扩展不会重读 → 叉号不退 (08-23 首犯, 09-06 克隆后复发)
- 克隆/rsync 迁移后 xattr 丢失或缓存陈旧都会让叉号重现

## 目录改名/家目录整合后: 快捷方式**静默失效**(零反应、不报错)

2026-10-08 实测(老倪报"控制台怎么无法打开了"): 家目录整合(仓库 `zmax_rel/` → `zmax/`)后,
`~/Desktop/XSpace-Studio.desktop` 里 `Exec=/home/ubuntu/zmax_rel/tools/gui/launch_studio.sh`、
`Icon=/home/ubuntu/lerobot-smolvla-lew/tools/gui/logo.png` —— 两个目录都已不存在 ⇒ **双击毫无反应, 不弹窗不报错**
(不像"叉号"那样有视觉提示)。
- 判据: 先看 `Exec=`/`Icon=` 指向是否**真实存在且可执行**(`[ -e ] && [ -x ]`), 再判信任。**路径失效与信任是两回事**。
- 修法: 改成新绝对路径 → 重装 `~/Desktop/` + `~/.local/share/applications/` → `touch`+`gio set metadata::trusted true` →
  重启 DING 扩展。脚本化:`install -m755` + `desktop-file-validate`(能抓到 `Exec=bash -lc '...$HOME...;'` 这类引号非法写法)。
- **唯一依据入库**: 把三个 .desktop 放进仓库 `tools/desktop/`, 附 `install_launchers.sh`(不带参数=安装修复,
  `--check`=只核验) ⇒ 以后再改路径不会丢图标。
- 别只修桌面那份: `~/.local/share/applications/` 里常有一份**同名副本**(应用菜单用), 两份都要改, 否则"菜单里点还是无法打开"。
- 修完的实测证据: 他双击后 `studio.py` 进程真的起来了(记录 pid/时间), 不是"应该能开"。

## 「第一次没反应 / 总是启动两次」= 慢启动 + 零反馈 + 单实例闸静默

症状成套出现: 双击后桌面**几十秒没有任何反馈** ⇒ 人以为没点到, 再双击一次 ⇒ 第二次也“没反应”,
最后窗口自己冒出来 ⇒ 主观结论“要点两次才开”。**多数情况只有一次进程启动**, 先别去查“起了两个进程”。
三段根因, 逐段核:

1. **慢启动**: 重应用常把「重模型权重/大数据加载」放在主窗口 `show()` **之前** ⇒ 进程 pid 早就有了,
   主窗口要等几十秒才 map。量法(别猜): `pgrep -f '<锚定正则>'` 有 pid, 而同时
   `DISPLAY=:0 xdotool search --onlyvisible --name '<窗口标题>'` 搜不到 ⇒ 就是“进程在、窗口没出来”的启动窗口期。
   报时间用启动脚本的实测口径 (如“第 N 秒窗口 1 个”), 不要凭感觉说“大概几秒”。
2. **`StartupNotify=true` 缺 `StartupWMClass`**: 桌面图标不显示“正在启动”的忙碌态、启动请求也永远收不到完成信号 ⇒ 零反馈。
   **WM_CLASS 必须用 `xprop -id <win> WM_CLASS` 实测** —— 它常等于**脚本名**, 不等同于 `Name=` 或窗口标题; 照猜写 `StartupWMClass` 等于没写。
3. **第二次点击被单实例闸静默吞掉**: 启动包装脚本命中 `pgrep` 后写命令通道 + 激活已有窗口,
   而 `xdotool search --onlyvisible` 在窗口未 map 时**找不到** ⇒ 原实现直接 `exit 0`(零反馈)。
   修: 找不到窗口时也 `notify-send`「正在启动中(约 N 秒), 请勿重复双击」; 新实例启动前同样先发一条。

判“到底起没起两个进程”: ① `pgrep` 必须**锚定整条 cmdline** (`^[^ ]*<venv>/bin/python <app>\.py$`) ——
子串匹配会把你自己刚敲的 `pgrep -af '...'` 当成实例; ② `systemctl --user status <unit>` 看 **Main PID** ——
只有一个 ⇒ 就是“两次点击、一次启动”, 别写“启动两次”这种误导结论。

别忘**第二条入口**: `systemctl --user cat <unit>` + `ls ~/.config/autostart/`。用户级自启单元
(`WantedBy=default.target`) 的 `ExecStart` 往往就是**同一个** launch 脚本 ⇒ 桌面图标实际只做“确保在跑 + 激活窗口”,
两路不是竞态。查启动延迟时也要去看那个单元的 `Environment=DISPLAY=:0 / XAUTHORITY=...` 是否齐全(服务起的实例没有桌面环境)。

改 .desktop 必须改**三份**(桌面 / `~/.local/share/applications/` / 仓库唯一依据), 改完走信任序列
(`touch` + `gio set metadata::trusted true` + 重启 DING 扩展), 再 `desktop-file-validate` 收口。

治本(单独一版做, 别和别的改动同批): 把模型/大数据加载从 `show()` 之前挪到之后 (`QTimer.singleShot`),
窗口 2~3 秒出来, 剩余加载在界面里显示进度 —— 慢启动造成的“没反应”从根上消失。

## 修复序列 (08-23 与 09-06 两次实测有效)
```
touch ~/Desktop/X.desktop                       # 触发 IN_MODIFY 让扩展重载
gio set ~/Desktop/X.desktop metadata::trusted true   # 幂等重写
gnome-extensions disable ding@rastersoft.com && sleep 1 && gnome-extensions enable ding@rastersoft.com
```
只重启 DING 扩展即可; **勿重启 gnome-shell**(整屏闪、丢用户 GUI 状态)。

## 给「打开某个工程/工作区」做快捷方式 (文件型入口不需要包装脚本)

`.code-workspace` / `.zmaxproj` 这类**文件型入口**, 双击由文件关联直接打开 —— 不需要写包装脚本:
可先放一个软链到桌面试 (`ln -s /home/ubuntu/zmax/ZMAX.code-workspace ~/Desktop/`),
实测双击即开 VSCode 工作区, 重复双击只聚焦已有窗口、不会起第二个实例。
要中文名/带图标就写 .desktop(与其它快捷方式同一套安装+信任序列):

```ini
[Desktop Entry]
Type=Application
Name=Z-MAX 工程
Exec=/usr/bin/code /home/ubuntu/zmax/ZMAX.code-workspace
Icon=/usr/share/code/resources/app/resources/linux/code.png
Terminal=false
Categories=Development;IDE;
StartupNotify=true
StartupWMClass=code
```

`StartupWMClass` 同样要用 `xprop` 实测(这里的窗口 WM_CLASS 是 `code`); 图标不存在就退成主题图标名。
验证执行链别再造一个:`timeout 20 /usr/bin/code <工作区文件>` 跑一次 —— 窗口应仍在(单例聚焦), 不是又开一个。

## 环境专属知识 (老倪这台 E盘 Ubuntu)
- LiveUSB 迁移残留: `ubuntu-desktop-bootstrap*.desktop` = "Install Ubuntu" 安装向导入口。它在桌面上带叉号属正常(本来就不是日常应用), 误点会启动安装向导; 处理 = 改名 `.bak` 隐藏保留(老倪铁律: 删东西先改名, 不真删)
- 标准桌面配套: .desktop 的 Exec 指向仓库内启动脚本(如 `tools/gui/launch_studio.sh`), 脚本硬编码 venv python 并防重复启动 — 相关 GUI 工程细节见 zmax-console 技能
- Desktop 目录健康检查辅助: 确认 Exec 里 Terminal=true/false 语义正确(不影响信任判定, 只影响是否弹终端)
