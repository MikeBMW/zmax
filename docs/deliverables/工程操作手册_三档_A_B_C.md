# 工程操作手册 (Working Instruction) —— 按性能等级 A / B / C

> 唯一依据 `tools/spec/eng_profiles.json` · 版本 `zmax-eng-profiles/1.0` · 生成工具 `tools/export_wi_doc.py`

> 三档与《性能配置》一一对应: **A 基本性能 (L2) / B 精细操作性能 (L2+L3) / C 专业性能 (L2+L3+L4 含 L5)**。档位只加不换: B 含 A 的全部, C 含 B 的全部。


## 0. 通用约定

| 项 | 约定 |
|---|---|
| 工作目录 | `/home/ubuntu/zmax` (所有命令都在这里执行) |
| 命令 = 判据 | 每条命令都能直接粘, 期望输出写在同一行; 对不上就是没做完 |
| 不做假动作 | 参数/权重/标定只能来自唯一依据文件, 界面看不到的东西不许手填 |
| 失败先停 | 任何一步 FAIL 都停下来按「失败处理」修, 不许带着问题往下走 |
| 凭据 | 手册只核对凭据**键名**, 任何步骤都不打印密钥值 |

---

## A 档 · 基本性能 · L2 单任务

**对应性能**: 基本性能 (L2) · 11.42s/件 · 316.1UPH


### A.1 硬件清单

| # | 设备 | 规格 | 数量 | 为什么 |
|---|---|---|---|---|
| 1 | 工控机 (550C 级) | x86_64 · ≥16G · Ubuntu 22.04 · 单机跑 8791/8793/8794/8797/8799 | 1 | 五路本机服务常驻 |
| 2 | 关节臂 + 控制器 | 珞石 (xCore) · SDK 直连 · 力控可用 | 1 | L2 技能执行本体 |
| 3 | 腕部相机 | Intel RealSense D405 (深度 unit 0.1mm) | 1 | 插拔/对位视觉 |
| 4 | 侧视相机 | Intel RealSense D435 | 1 | 第二视角/AR 底图 |
| 5 | AOI 检测服务主机 | 192.168.23.23 · 10082 金手指 / 10083 表面 | 1 | 五点检测判据 |
| 6 | 产线网卡 + 千兆交换 | 与 192.168.23.x 同段 | 1 | AOI/Orin 直连 |

### A.2 软件栈 (服务/权重)

| 服务/资产 | 端口 | 起法/位置 |
|---|---|---|
| 状态空间引擎 (画布/任务) | 8793 | `systemd zmax-* 或 tools/restart_traj_ar.sh` |
| AR / 实时流页面 | 8797 | `tools/restart_traj_ar.sh` |
| 大屏/遥测 | 8791 | `随主程序` |
| 工位服务 | 8794 | `随主程序` |
| 任务/元任务服务 | 8799 | `随主程序` |
| L2 技能库 | — | `data/skills/l2_muscle/光模块_抓放循环_v1.json` |

### A.3 标定项 (不达标就停)

| 标定项 | 唯一依据 | 容差/判据 |
|---|---|---|
| 相机内参 K | `config/calib/zmax_calib.json#camera` | fx 394.06 / fy 393.47 / cx 318.44 / cy 238.66 (±2%) |
| 手眼 T_base_cam | `config/calib/zmax_calib.json#T_base_cam` | 平移 <2mm · 旋转 <1° |
| 台面高度 plane_z | `config/calib/zmax_calib.json#plane_z` | ⚠ 当前 value=null 未标定 ⇒ 3D 换算被拒, 必须先标 |
| 深度尺度 depth_scale | `config/calib/zmax_calib.json#depth_scale` | D405 = 0.1mm/单位 |

### A.4 安全要求

- 速度 1~1000 mm/s, 分段限速; 插入段力 ≤40N
- safety.py 收口: VEL_LIMIT 1.0 · FORCE_LIMIT 5.0N · POS_LIMIT 0.6 (越限饱和/拒发)
- rt 类指令执行后必须下电; move_* 不下电; 30s 内勿重发
- 姿态 >5° 会被 50113 拒且腿可能假报到位 ⇒ 以真值 tcp_out/latest.json 为准

### A.5 操作步骤 (Working Instruction)

| 步骤 | 做什么 | 在哪做 | 命令 / 操作 | 期望 | 失败处理 |
|---|---|---|---|---|---|
| **A1** | 五路服务在位自检 | 本机 (可直接跑) | `ss -ltnp | grep -E ':(8791|8793|8794|8797|8799)' | wc -l` | `5` | 少于 5 ⇒ 起服务: bash tools/restart_traj_ar.sh (8797/8793), 其余随 zmax 主程序 |
| **A2** | AR 页面可用 | 本机 (可直接跑) | `curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8797/ar3d` | `200` | 非 200 ⇒ 看 8797 日志 (tools/restart_traj_ar.sh 重启) |
| **A3** | 相机内参在位 | 本机 (可直接跑) | `python3 -c "import json;c=json.load(open('config/calib/zmax_calib.json'))['camera'];print(round(c['fx'],2),round(c['fy'],2))"` | `394.06 393.47` | 缺内参 ⇒ 先跑标定靶标流程, 不要手填 |
| **A4** | 台面 plane_z 标定 (当前未标定 ⇒ 必做) | 现场 (需设备/产线) | `python3 -c "import json;print(json.load(open('config/calib/zmax_calib.json'))['plane_z'])"` | `'value': None` | 看到 None ⇒ 用夹爪尖轻触台面读 tcp z, 三次取均值写入 calib (写入后本步期望值变为数值) |
| **A5** | 位姿真值新鲜 (帧龄 <2s) | Orin/执行腿可达 | `python3 -c "import json,time,datetime as D;d=json.load(open('zmax_data/rokae_sdk/tcp_out/latest.json'));t=D.datetime.strptime(d['ts'],'%Y-%m-%d %H:%M:%S.%f');print('帧龄s',round(time.time()-t.timestamp(),1))"` | `帧龄s 0~2` | 帧龄大 ⇒ 采样器崩/链路断: 在 dobot/Orin 侧重启采样, 或 zmax-pose-relay 保障; 全 0 也视为陈旧 |
| **A6** | L2 技能库在位 | 本机 (可直接跑) | `test -f data/skills/l2_muscle/光模块_抓放循环_v1.json && echo SKILL_OK` | `SKILL_OK` | 缺 ⇒ 用示教流程重新生成标杆 (human-in-the-loop 示教), 不要手写 JSON |
| **A7** | AOI 服务连通 | 现场 (需设备/产线) | `curl -s -m 3 -o /dev/null -w '%{http_code}' http://192.168.23.23:10082/` | `200/404 都算通 (端口有响应)` | 000 ⇒ 检查产线网卡是否插上 (本机当前未插), AOI 主机是否起服务 |
| **A8** | 单件试跑 (节拍验收) | 现场 (需设备/产线) | `在 8793 页面点 1 件 → 记录 start/end 时间戳` | `单件 ≤11.42s, 无急停/无越限日志` | 超节拍 ⇒ 查段表 abs_mm 与速度档; 撞到围栏 ⇒ 先 agent_all_stop 再查围栏 |
| **A9** | 配置一致性验收 | 本机 (可直接跑) | `python3 tools/verify_config_active_task.py > /tmp/v.log 2>&1; tail -1 /tmp/v.log` | `0 FAIL` | 有 FAIL ⇒ 按 FAIL 行给出的唯一依据路径逐条修, 不要跳过 |

### A.6 交付验收 (全过才算实现)

- [ ] A1~A9 全过
- [ ] 单件节拍 ≤11.42s
- [ ] plane_z 已标定 (非 null)
- [ ] 首件 AOI 五点判据通过

---

## B 档 · 精细操作性能 · L2+L3 多任务编排

**对应性能**: 精细操作性能 (L2+L3) · 双臂 供料4.70/交接8.70/件周期11.40


### B.1 硬件清单

| # | 设备 | 规格 | 数量 | 为什么 |
|---|---|---|---|---|
| 1 | A 档全部 | — | 1 | 底座 |
| 2 | 推理 GPU 主机 (550A) | RTX 4060 8G · CUDA 12 | 1 | SmolVLA 500M 推理 |
| 3 | 训练数据采集位 | 同构工位 + 采集脚本 | 1 | 每技能 ≥50 episode |

### B.2 软件栈 (服务/权重)

| 服务/资产 | 端口 | 起法/位置 |
|---|---|---|
| L3 策略权重 | — | `outputs/train/smolvla_lew_v10_1h/checkpoints/004000 (1289MB)` |
| LoRA 合并 | — | `python3 tools/merge_lora_ckpt.py (不 merge 会零动作伪装)` |
| 训练入口 | — | `python3 joint_train_all.py --only L3 (带 HF_HOME)` |
| 双臂时序编排 | — | `python3 tools/ss_meta_task_ar.py` |

### B.3 标定项 (不达标就停)

| 标定项 | 唯一依据 | 容差/判据 |
|---|---|---|
| A 档全部标定 | `config/calib/zmax_calib.json` | 同 A |
| 动作空间映射 (action 4 维) | `ckpt config.json#output_features` | dx/dy/dz/gripper 顺序必须与训练一致 |
| 观测维度对齐 (state 39) | `ckpt config.json#input_features` | 少一维就整段跑飞 |

### B.4 安全要求

- A 档全部安全项
- 序列级校验: 每段动作过 safety 收口再下发
- 双臂并行: 同一槽同一时刻只有一只手 (交接点 8.70s)

### B.5 操作步骤 (Working Instruction)

| 步骤 | 做什么 | 在哪做 | 命令 / 操作 | 期望 | 失败处理 |
|---|---|---|---|---|---|
| **B1** | GPU 在位 | 本机 (可直接跑) | `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader` | `4060` | 无输出 ⇒ 驱动/显卡未就绪, L3 推理未起 (可降级跑 A 档) |
| **B2** | L3 权重在位 (含大小) | 本机 (可直接跑) | `python3 -c "import os;p='outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model';s=sum(os.path.getsize(os.path.join(dp,f)) for dp,_,fs in os.walk(p) for f in fs)//2**20;print('OK' if s>=1000 else 'SMALL',s)"` | `OK` | 偏小 ⇒ 权重不完整, 重下/重训 |
| **B3** | LoRA 已合并 (否则零动作) | 本机 (可直接跑) | `python3 -c "import json;d=json.load(open('outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model/config.json'));print('lora' in json.dumps(d).lower())"` | `False` | True ⇒ 先 python3 tools/merge_lora_ckpt.py 再部署 |
| **B4** | 输入/输出域对齐 | 本机 (可直接跑) | `python3 -c "import json;d=json.load(open('outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model/config.json'));print(d['chunk_size'],d['output_features']['action']['shape'])"` | `7 [4]` | 不匹配 ⇒ 与训练配置同源重建, 不要改推理侧将就 |
| **B5** | 数据量达标 (每技能 ≥50 episode) | 本机 (可直接跑) | `python3 -c "import glob;n=len(glob.glob('zmax_data/datasets/**/*.parquet',recursive=True))//max(1,len(glob.glob('zmax_data/datasets/*/')));print('DATA_OK' if n>=50 else 'DATA_LOW', 'episodes≈'+str(n))"` | `DATA_OK` | 看到 DATA_LOW ⇒ 数据量不足 (L3 掉点主因): 按 human-in-the-loop 示教采每技能 ≥50 episode, 并在数据集里补 LeRobot meta/info.json |
| **B6** | 双臂时序复算 | 本机 (可直接跑) | `python3 tools/ss_meta_task_ar.py 2>&1 | grep -E '件周期|交接' | head -2` | `11.4` | 对不上 ⇒ 先查 tasks.json steps 时长, 再查 build_lanes |
| **B7** | 序列试跑 3 件 (编排验收) | 现场 (需设备/产线) | `8793 页面选 TASK-07-AOI → 跑 3 件, 记录每件 start/end` | `3 件节拍均 ≤11.42s, 无碰撞/无急停` | 有碰撞 ⇒ agent_all_stop, 查围栏与段间过渡 (抬50→转身→低位横移) |
| **B8** | 双臂并行判据 | 本机 (可直接跑) | `gui-venv311/bin/python tools/verify_ar_meta_parallel.py 2>&1 | grep -E 'PASS|FAIL' | tail -1` | `PASS` | FAIL ⇒ 看左右手 lane 采样点, 是编排还是渲染问题 |

### B.6 交付验收 (全过才算实现)

- [ ] A 档全过
- [ ] B1~B8 全过
- [ ] 双臂交接 8.70s 稳定
- [ ] 3 件连续跑无人工干预

---

## C 档 · 专业性能 · L2+L3+L4 (含 L5) 安全分级自主

**对应性能**: 专业性能 (L2+L3+L4含L5) · 意图101ms · 目标 PL d


### C.1 硬件清单

| # | 设备 | 规格 | 数量 | 为什么 |
|---|---|---|---|---|
| 1 | A/B 档全部 | — | 1 | 底座 |
| 2 | L4 训练 GPU (或云端) | ≥16G 显存, 训练 INTACT-JEPA 224×224×3帧 | 1 | L4 权重训练/合并 |
| 3 | L5 运行资源 | 本地 3B VLM 需 ≥16G 显存 / 或云端 API | 1 | 场景理解与任务规划 |
| 4 | 安全验证台架 | 急停/安全门/光栅 + 记录仪 | 1 | ISO 13849 验证 |

### C.2 软件栈 (服务/权重)

| 服务/资产 | 端口 | 起法/位置 |
|---|---|---|
| L4 权重 | — | `zmax_data/stable-wm-cache/checkpoints/intact_l4_current (84MB + LoRA 需 merge)` |
| L4 决策/规划 | — | `src/lerobot/policies/left_right/state_space/{planner,safety}.py · INTACT 须常驻` |
| L5 配置 | — | `zmax_data/secrets/zmax.env (只核对键名, 不打印值)` |
| 动作授权 | 8793 | `授权只从 8793 代发, 其余入口一律拒` |

### C.3 标定项 (不达标就停)

| 标定项 | 唯一依据 | 容差/判据 |
|---|---|---|
| A/B 档全部标定 | `config/calib/zmax_calib.json` | 同 A/B |
| skill 24 维映射 | `intact config.json#intent_actor` | 技能表顺序必须与训练一致 |
| 安全距离/围栏 | `config/calib/zmax_calib.json#robot` | 预检扣连杆半径 (肘 r78) 后 <20mm ⇒ FAIL |

### C.4 安全要求

- A/B 档全部安全项
- 目标安全等级 PL d (ISO 13849): 当前未认证 ⇒ 不得对外宣称达标
- 认证前必须完成: 急停链验证 / 安全门互锁 / 危险动作授权 / 异常演练各 1 次并留证
- 危险动作前 agent_all_stop 保障; 台账写 docs/incidents/INCIDENT-INDEX.md

### C.5 操作步骤 (Working Instruction)

| 步骤 | 做什么 | 在哪做 | 命令 / 操作 | 期望 | 失败处理 |
|---|---|---|---|---|---|
| **C1** | L4 权重在位 | 本机 (可直接跑) | `ls -l zmax_data/stable-wm-cache/checkpoints/intact_l4_current/config.json | wc -l` | `1` | 0 ⇒ 权重未就位, L4 不可用 (可降级 B 档) |
| **C2** | L4 未残留 LoRA 标记 | 本机 (可直接跑) | `python3 -c "import json;d=json.load(open('zmax_data/stable-wm-cache/checkpoints/intact_l4_current/config.json'));print('lora' in json.dumps(d).lower())"` | `False` | True ⇒ 先 merge, 否则零动作伪装 |
| **C3** | L5 凭据键在位 (不打印值) | 本机 (可直接跑) | `python3 -c "import re;t=open('zmax_data/secrets/zmax.env').read();print(sorted(set(re.findall(r'^([A-Z0-9_]+)=',t,re.M)))[:6])"` | `[` | 空/文件缺 ⇒ L5 不可用, 走 _plan_rules 降级 (功能不受影响, 仅无自主规划) |
| **C4** | 授权链只认 8793 | 本机 (可直接跑) | `grep -n '8793' src/lerobot/policies/left_right/state_space/hil_bridge.py | head -2` | `8793` | 找不到 ⇒ 授权入口散落, 先收口再谈安全等级 |
| **C5** | 否决链阈值在位 | 本机 (可直接跑) | `grep -n 'max_veto' src/lerobot/policies/left_right/state_space/planner.py` | `max_veto` | 无 ⇒ 分层否决未生效, 禁止上自主模式 |
| **C6** | 急停/异常演练 (1 次留证) | 现场 (需设备/产线) | `运行中按急停 → 记录恢复时间与复位步骤; 截图/录像存档` | `停机 ≤1s, 复位后可继续; 台账登记` | 无响应 ⇒ 立即下电, 安全链整改前不得再上电自动化 |
| **C7** | 安全等级证据清单 | 现场 (需设备/产线) | `cat docs/incidents/INCIDENT-INDEX.md | head -20` | `有台账条目` | 空 ⇒ 认证无从谈起; 目标 PL d 只能写「目标」不能写「已达」 |
| **C8** | 全量判据验收 | 本机 (可直接跑) | `python3 tools/verify_config_active_task.py > /tmp/vc.log 2>&1; tail -1 /tmp/vc.log` | `0 FAIL` | 有 FAIL ⇒ 逐条修, 不带病交付 |

### C.6 交付验收 (全过才算实现)

- [ ] A/B 档全过
- [ ] C1~C8 全过
- [ ] 急停/异常演练留证
- [ ] 安全等级只宣称「目标 PL d」直至认证完成

---

## 附: 三档对比 (选档依据)

| | A 基本性能 | B 精细操作性能 | C 专业性能 |
|---|---|---|---|
| 模型 | L2 | L2+L3 | L2+L3+L4(+L5) |
| 节拍 | 11.42s/件 · 316.1UPH | 同 A + 双臂并行 供料4.70/交接8.70 | 同 B + 意图决策 101ms |
| 多任务编排 | ✗ | ✓ 技能序列可组合 | ✓ + 自主重规划 |
| 异常自主恢复 | ✗ | ✗ 只能按预案分支 | ✓ max_veto=3 转异常 |
| 安全等级 | 单机限幅 | + 序列级校验 | 目标 PL d (认证未做) |
| 成本项 | 工控机+相机+AOI | +推理GPU+数据采集+LoRA | +L4训练+API/3B显存+安全认证 |

> 选档规则: 只做单产品单工位节拍 ⇒ A; 要换产品/多工位靠序列 ⇒ B; 要自主判断异常并担安全等级 ⇒ C。**降档可以, 跳档不行** (B 必须含 A 的全部验收)。

