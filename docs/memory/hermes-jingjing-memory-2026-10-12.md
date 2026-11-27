Orin=192.168.23.66(tashan/ts123); 产线.23.50/24无网关(USB网卡); 网卡不在位⇒不可达+拒发动作
§
NTP回拨8h(勿动RTC)→节拍用monotonic,负帧龄拒用
§
分层: L5造数据/L4认知/L3调度/L2检测; 主干SigLIP768d+四头; from-scratch崩
§
交付前自跑通; GPU不空转; 改文件必回读; 新脚本须真跑
§
长命令/杀进程一律写脚本(内联会杀自己shell); sudo免密
§
L5=DeepSeek视觉:短提示+小JSON; timeout≥300
§
飞书99991663=token过期→重启gateway
§
L4=INTACT直驱; 反归一化按ckpt训练集同源; L2收口闸逐轴corr<0.5 veto
§
🔴 工具内存≈8GB超则OOM; 同刻仅一模型进程
§
Orin: ROS=domain0, tcp_pose 50Hz真值, 几何须ss_geom_calib, 只读遥测桥禁装包, 动作默认speed=8
§
真机3D须K+手眼+plane_z; D405深度unit=0.1mm(4013=401mm)
§
YOLO在役=软链yolo_peg_live.pt; 瓶颈是数据; 相机独占⇒检测须在持有进程内做
§
真机画面报方向说'朝画面中心'
§
真机: rt后必下电; move_*不下电; 30s超时勿重发; collision=False
§
记忆五层: L2/L3/L4+总装Qwen(SS_MACRO); 势场喂obs[0:3]
§
真源calib.json→zmax_params.py; 训练=joint_train_all.py --only L4,L3,L2
§
L5规划器/safety=left_right/state_space/{planner,safety}.py; INTACT须常驻
§
阶段MOE: 门控须硬先验路由; 枚举不匹配静默降级吞阶段; 判据=单射性
§
LoRA需merge(否则零动作伪装):merge_lora_ckpt.py
§
ECS: /agent/{prompt,reply}+/hil/state+/orin/status; 站点=/www/wwwroot/datadrive.world; 免密→ZMAX_ECS_PW; 公网只读/ov+/st;nginx须^~
§
GPU掉载主因=每步CPU开销>计算→静音日志+workers↑
§
工程根~/zmax=独立仓库(MikeBMW/zmax); zmax_data=模型+数据+HF+secrets/zmax.env; 训练带HF_HOME; 入库=代码+docs/skills+docs/memory(repo_guard+secret_scan)
§
控制台: 禁反复重启GUI(投诉过); 改码攒批一次到位(含字体)
§
工程库=data/database/zmax/zmax_engineering.db(单文件=一套工程; build|check; 8798); 真源=zmax/sources/(画布+feature.dbc链); 改画布后顺序: ss_task_bind→space-save→db build→两check
§
我=主节点: 工控机+Orin全归我; AOI(.23.23)=10082/10083(禁10084/85); 更新=aoi_remote_deploy.py; 通道=agent_hub+station_cmd.py
§
动作授权只从8793; 代发前先授权
§
位姿真源=tcp_out/latest.json(全0=陈旧); 8793页=station.html
§
运动安全: 抬升闸已放开(慢速+警报在先); 点1~7同面z=0.1727; 腿速≈名义/10(要快给1000); 新点位老倪先做; 台账INCIDENT-INDEX.md; '要碰撞'先agent_all_stop.py
§
MoveIt起点=SDK直采(latest.json.joint); 清进程脚本按名匹配⇒命令文本别带进程名
§
AR=8797: 底图源4相机=状态空间工程视频源8791(cam_live_stream; arm/gold/surface)+本机USB D435; /api/cams·/snap/<k>.jpg; L5理解=ar_l5_understand.py子进程桥(勿在常驻服务import引擎); 3D「🥽AR」开?cam=arm
§
任务7=TASK-07-AOI(场景SCN-07-AOI=AR·模型L5自主进化程序); 节点名🔍光学质量检测; 任务↔场景真源=ss_scene_switch.py(写画布ssdata.src_state; FW→插拔/TRAY→摆盘/AOI→AR); 信号色标真源=sig_scene_tags.py
§
场景色: 插拔#2e8b57绿/摆盘#1f6feb蓝/AR#8957e5紫 (3D按钮=配置中心场景列=信号分析同色)
§
控制进程脚本一律按端口/pid找(ss -ltnp), 禁ps|grep 名 — 命令行含名就自杀(exit -15)