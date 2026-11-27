Orin=192.168.23.66(tashan/ts123); 产线.23.50/24无网关(USB网卡); 网卡不在位⇒不可达+拒发动作
§
NTP回拨8h(勿动RTC)→用monotonic; 判活判'未来时间戳'; cron ticker卡死→watchdog.timer
§
分层: L5造数据/L4认知/L3调度/L2检测; SigLIP768d+四头; from-scratch崩
§
交付前自跑通; 改文件必回读
§
L5=DeepSeek视觉:短提示+小JSON; timeout≥300
§
飞书99991663=token过期→重启gateway
§
L4=INTACT直驱; 反归一化按ckpt训练集同源; L2收口闸逐轴corr<0.5 veto
§
🔴 工具内存≈8GB超则OOM; 同刻仅一模型进程
§
Orin: ROS=domain0, tcp_pose 50Hz真值, 几何须ss_geom_calib, 只读遥测桥禁装包
§
真机3D须K+手眼+plane_z; D405深度unit=0.1mm(4013=401mm)
§
YOLO在役=软链yolo_peg_live.pt; 瓶颈=数据; 相机独占⇒检测同进程做
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
阶段MOE: 门控须硬先验路由; 枚举不匹配静默降级; 判据=单射性
§
LoRA需merge(否则零动作伪装):merge_lora_ckpt.py
§
ECS: /agent/{prompt,reply}+/hil/state+/orin/status; 站点=/www/wwwroot/datadrive.world; 免密→ZMAX_ECS_PW; nginx须^~
§
GPU掉载主因=每步CPU>计算→静音日志+workers↑
§
工程根~/zmax=独立仓库(MikeBMW/zmax); zmax_data=模型+数据+HF+secrets/zmax.env; 训练带HF_HOME
§
控制台禁反复重启GUI; 改码攒批(含字体)
§
工程库=zmax_engineering.db(单文件=一套工程; build|check; 8798); 真源=zmax/sources/; 改画布后: ss_task_bind→space-save→db build→两check
§
我=主节点(工控机+Orin); AOI.23.23=10082/10083(禁84/85); 更新=aoi_remote_deploy.py
§
动作授权只从8793; 代发前先授权
§
位姿真源=tcp_out/latest.json(全0=陈旧)
§
运动安全: 速度口径mm/s 1~1000(4处收口含技能speed_max); 前置须idle+automatic; 真源web/station.html; 腿上限须重启容器; 清8793授权; 新点位老倪先做; 台账INCIDENT-INDEX.md; '要碰撞'先agent_all_stop.py
§
AR=8797: 底图4相机=8791(arm/gold/surface)+本机D435; /api/cams·/snap/<k>.jpg; L5=ar_l5_understand.py桥; 3D「🥽AR」?cam=arm
§
任务7=TASK-07-AOI(=AR·L5自进化); 任务↔场景=ss_scene_switch.py(FW/TRAY/AOI); 信号色标=sig_scene_tags.py
§
场景色: 插拔绿/摆盘蓝/AR紫(3D按钮=配置中心=信号分析)
§
控制进程: 按端口/pid找(ss -ltnp), 禁ps|grep名(自杀); 杀进程写脚本别内联; sudo免密; MoveIt起点=SDK直采
§
侧面判据图=aoi_surface_rect.py(搜框+摆正+扩暗头; 0回退); 10083 judge退化整幅
§
奇异区: 单步姿态>5°被50113拒且腿假报到位(姿态看真值); 转移=抬50→转身→低位横移→目标上方升降
§
扭矩tap→/dev/shm(32MB环)
§
建图=人工走点(8793按钮已切manual, 全程采帧+45s/轮增量); GS_MAP_MODE=auto回旧
§
版本号只按老倪指定; 当前5.50.745(tag已推)
§
专利12件·功能渠道74/74; 真源config/patents/patent_registry.json; patent_center.py --coverage/--export; 文档docs/patents