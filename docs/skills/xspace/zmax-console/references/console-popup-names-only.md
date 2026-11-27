# 控制台“打开工程/加载配置”弹窗：只列配置名称（2026-10-14 老倪）

老倪原话：「状态空间工程打开的时候，弹出来的文本清单，简单一些，只是列出所有加载的配置的名称即可。你写了那么多数字字符串，不是给人看的。别的都删掉」。

## 规则
- 弹窗正文 = 工程名 + **已加载配置名称清单**，就这样。
- 数字/哈希/结构计数/备份路径/时间戳/控制台版本/漂移计数/ok 标志 —— **一律不进弹窗**；需要查的细节只进控制台日志与台账。
- 名称清单的**真源 = 工程文件本身**（`json.load(工程文件)` 的段键 → 中文名），不许硬编、不许把文件里没有的段列上：
  `tools/gui/studio.py` 的 `_PROJ_SECTION_NAMES` + `_pj_loaded_names(path)`（已给 10 个段的中文名）；
  真实工程段的例子：`canvas/run_cfg/ui/panel/task_binding/tasks/calibration/master_param/measure/debug_state`。
- **同类弹窗一改到底**，同一流程里两个入口都要改（否则用户换个入口又看到数字）：
  ① `_load_project_file()` → 「📂 加载工程文件」（原带了 `json.dumps(stats)`）；
  ② `_open_space_file()` → 「🗂 状态空间工程已打开」（原带了 ok + lines + 漂移 + saved_at + version）。
  统一弹窗名：都写「已加载配置:」然后逐行 `  · 名称`。

## 判据（必跑）
`tools/verify_proj_load_summary.py` — 8 项：真源清单一致 / 正文零阿拉伯数字 / 旧字段痕迹清零 / 中文名而非键名 /
两处旧写法防回退 / 两处走同一份名称清单。改完 = 8/8 PASS。

## 千真万确的取证坑（本人踩过）
- 本机**没装 ImageMagick**：`import -window …` 静默失败（命令找不到但外层 `&&` 看着“成功”），
  我曾据此说“已截图”，实际那张图不存在 ⇒ **截图一律用 `scrot -u out.png`（或 `xwd`）**，写完 `ls -la` 核字节数。
- 验证真弹窗：`xdotool key ctrl+alt+o`（打开总工程）后 `wmctrl -l | grep 状态空间工程已打开`，
  `xdotool search --name …` 拿到 id 再 `scrot -u`；弹窗是模态，验完记得 `xdotool key Return` 关掉（不关掉会阻塞命令通道）。
- 巨集窗口最大化验证：先用 `_NET_WM_PID` 对准**当前控制台 pid** 的窗口（同名窗口可能有多个/旧的），
  再看 `_NET_WM_ALLOWED_ACTIONS` 是否含 MAXIMIZE_* + 几何真的变。
