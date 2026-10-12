---
name: ar-multicam-scene-tagging
description: Use when AR 换底图源/多相机/L5理解/信号场景色标与排序。
version: 1.0.0
author: Hermes (Z-MAX)
license: proprietary
metadata:
  hermes:
    tags: [ar, camera, vlm, signal-analysis, zmax]
    related_skills: [fixed-camera-ar-overlay, zmax-console, state-space-canvas-engineering]
---

# AR 场景多相机底图 + 信号场景色标

## When to Use
老倪要换 AR/3D 场景的**底图数据源**、把多台相机接进 AR、让 **L5(VLM) 理解**当前画面,
或要给**信号分析**的信号打场景色标/按色排序时, 用本技能。

## 触发
- 「AR/3D 场景的背景真实图像应该是 XX 数据源」/「这几台相机都照同一个场景」/「L5 的 VLM 能理解么」。
- 「信号分析里的信号属于哪个场景, 要标记出来」/「按 绿/蓝/紫/白 排序, 白=全部显示」。

## 1. 底图源 = **已有视频源, 不要另起相机**
Z-MAX 的「视频数据源」单一真源是 `tools/cam_live_stream.py`(8791 推流 / 8793 工位总览同源)，
AR 服务 `tools/tcp_ar_server.py`(8797) 只**订阅**: `CAMS[key] = {w,h,label,mjpg:'/<name>.mjpg',src:'sstate'|'usb',stats_key}`。
- 每台必须登记**实际分辨率**(标定点是像素量纲, 混用必错); AOI 路在 8791 `/stats` 里的键是 `aoi_*` ⇒ 用 `stats_key` 映射。
- 端点: `GET /api/cams`(来源/分辨率/在线/帧龄/fps/标定) · `GET /api/ss_stats` · `GET /snap/<key>.jpg`(rs 走本机 pipeline, 其余走 8791 快照) · `/cam.mjpg?c=<key>`(MJPEG 透传)。
- 帧龄/在线**只从真源读**(8791 `/stats`), 不在 AR 侧重算; 哪路停就照实显示(实测遇过 USB 内置相机停 10h)。
- 3D 场景「🥽 AR」按钮开 `?cam=<default>`, 别写死某一台; 开关前先探 `/api/cams` 并报「在线 N/M」。

## 2. L5(VLM) 理解 = **子进程桥**, 别在常驻服务里 import 引擎
引擎 `src/lerobot/policies/left_right/state_space/scene_vlm.py :: SceneVLM.ask(jpg, prompt, max_tokens)` 会拉 torch(GB 级);
AR 服务是常驻轻进程 ⇒ 进程内 import 会顶内存红线(本机同刻只允许一个模型进程)。
做法: `tools/ar_l5_understand.py --jpg <f> --w --h [--hint]` 打印单行 JSON, 服务侧 `subprocess.run(..., timeout=380)` 解析;
提示词/解析复用 `tools/gen_overlay_from_vlm.py` 的 `PROMPT/parse_json`(口径一致)。
- 引擎路径是 `src/lerobot/**policies**/left_right/state_space/scene_vlm.py`(漏 `policies` 会 "找不到 scene_vlm.py")。
- key 走 `DEEPSEEK_API_KEY`(env 或 `~/.hermes/.env`)→ 默认 `https://api.deepseek.com`, model `deepseek-flash`。
- **400 "unsupported image" = 喂进去的不是真 JPEG**。上游报错时 `/snap/<k>.jpg` 会返回 JSON 错误体; 服务侧必须校验魔数 `\xff\xd8` 再调模型。

## 3. 信号 → 场景 标签(色标 + 排序)
- 颜色/任务映射**只能有一份**: `tools/ss_scene_switch.py`(插拔 `#2e8b57` / 摆盘 `#1f6feb` / AR `#8957e5`), 3D 按钮、配置中心场景列、信号分析全从它取。
- 标签真源 `tools/sig_scene_tags.py` → `config/topics/scene_tags.json`; 打标证据: AR/AOI 注册表 + **任务启用节点的名字前缀**(信号名约定 `节点名.字段`, 节点名要剥 emoji/括号)+ 运行产物 + 人工 overrides。
- UI(`tools/gui/canoe_graphic.py`): 目录项加 `● `(场景色)/`○ `(未分类白); 排序行四钮 ⚪全部/🟢/🔵/🟣, 选色=该色置顶(其余压暗仍显示), 白=不排序全显示; 标题行报当前数据源场景 + 各色计数。
- **没证据的分类就不要编**: 宁可留在白色(未分类)并在标题行报数, 也别猜。
- 统计实时 store 时要 `list(bufs.keys())` 快照 —— 源线程同时在加键, 直接迭代会 `RuntimeError: dictionary changed size during iteration`。

## 3.1 造修过的三个真坑 (2026-10-12 老倪目检发现的)
- **整组信号看不到**: 信号目录里某一段被套在 `if not only3d:` 里, 而窗口默认「数据范围」=3D 场景实时数据
  ⇒ 那一整组(AOI/AR 176 条)被挡在门外。用户只会说「那些信号也没有啊」。
  教训: 用户点名的信号组 **不要与“数据范围”开关耦合** —— 一律列出。加组前先问: 默认开关下他能不能看到?
- **颜色不生效**: 标签真源里只打上了一部分场景(AR 176 条, 插拔/摆盘 0 条), 其余 UI 再对也是白。
  开工前先 `SST.summary()` 看各场景条数, 0 条就说明“分类依据”还没拿到。
- **`_walk_keys(obj, acc, ...)` 收的是 dict(`acc.setdefault`), 传 set 会被 except 吞掉**
  ⇒ universe 静默为空, 打标 0 条却看不到任何报错。收集键时用 `dict` 再 `set(acc)`。

## 3.2 场景专属关键词表(当节点集分不开两场景时)
先查两任务的 `enabled_nodes`: 本项目 TASK-01-FW / TASK-06-TRAY **都是同一套 52 个节点**
(同一管线), 所以「按节点名分场景」必然 0 条 —— 别在这条路上浪费时间。
改用 **场景定义原文(scenes_5jobs.json 的 name/desc/objects/steps)** 里的专属词建表:
插拔=孔/插入/力控/夹持/接触/对位/固件; 摆盘=真空/吸盘/周转盘/料盘/槽位/放置/取件; AR=光学/判决/金手指/表面/缺陷/取像。
- 只命中**一个**场景才上色; 两边都沾的(夹爪/光模块)留白。**别把“光模块”当一票否决** ——「光模块头到孔_mm」
  是插拔专属(孔), 一否决就被错留白。
- 共用词清单要小且明确; 宁可白也不要错色(老倪零容忍)。
- UI 键常带来源前缀(`ar.`/`sstrace.`/`host.`) ⇒ `tag()` 要**逐层剥前缀**再查表。
- 表建好后 `--build` 生成真源, 并把各场景条数打印出来(「插拔 4 / 摆盘 3 / AR 176」这种数字就是交付证据)。

## 4. 活跃配置 → 场景/数据源 联动
- 真源 `tools/ss_scene_switch.py`: 写画布数据源节点(`ssdata`).`params.src_state`(经 `flows.load_canvas/save_canvas`, 不手改 .db), 并回读校验。
- 新增一态(如「AR场景」)必须同时: `SRC_CYCLE/SRC_DESC/SRC_SCENE_ID` + `_src_norm` + **把所有 `== "真机"` 收口到一个判据**(如 `_src_is_real()`), 否则新态会悄悄走仿真算路。
- 挂钩点选**唯一激活路径**(`tools/ss_task_bind.py --activate`)并用 try/except 包住: 切场景失败只提示, 不能拦激活。
- 改画布后的顺序: `ss_task_bind` → `project_archive space-save` → `engineering_db build` → 两 check(顺序反了会报 drift)。

## 5. HTML/JS 页面的隐形杀手
一张内联 JS 的页面, **一行孤立残片**(如 `$('x').textContent='…'; });`)就让整段 script 解析失败 —— 页面上**所有**按钮失效,
浏览器只留一条空 exception。改完必须 `node --check`(抽出 `<script>` 内容): 若 HEAD 与新版报同一个错, 那就是历史遗留的真 bug, 顺手修掉。

## 6. 进程控制脚本
按**端口/pid**找进程(`ss -ltnp`), 绝不 `ps|grep <脚本名>` —— 脚本名出现在你自己的命令行里就会自杀(实测 exit -15)。
起服务前等端口真释放, 否则 `Address already in use`。参考 `tools/ar_server_ctl.sh`。
