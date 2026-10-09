Orin=192.168.23.66(tashan/ts123); 产线.23.50/24无网关(USB网卡); 网卡不在位⇒不可达+拒发动作
§
NTP回拨8h(勿动RTC)→节拍用monotonic,负帧龄拒用
§
分层: L5定方向造数据/L4认知/L3调度/L2检测; 主干=SigLIP768d+四头; from-scratch崩
§
交付前自跑通; GPU不空转; 改文件必回读核验; 新脚本须真导入真跑
§
长命令/杀进程一律写脚本(内联会杀自己shell); sudo免密; 网络优化=zmax-net-optimize
§
L5=DeepSeek视觉:短提示+小JSON; timeout≥300
§
飞书99991663=token过期→重启gateway
§
引擎tr['obs']39D≠h5原生o[:39]; L3须env原生obs+128图
§
L4=INTACT直驱; 反归一化按ckpt训练集同源; L2收口闸逐轴corr<0.5全veto; 真模型默认生效
§
守卫: 模型参与>30%掉分; insert_depth=0.002
§
🔴 工具内存≈8GB: 超则OOM杀; 同刻仅一模型进程
§
评估: 口径训练同源零回退; loss低≠有效→留出集+平凡基线
§
Orin: ROS=domain0, tcp_pose 50Hz真值, 几何须ss_geom_calib, 政策宽(只读遥测桥禁装包), 动作默认speed=8
§
真机3D须K+手眼+plane_z; D405深度unit=0.1mm(4013=401mm)
§
YOLO在役=软链yolo_peg_live.pt; 瓶颈是数据
§
真机画面报方向说'朝画面中心'
§
真机: rt后必下电; move_*不下电; 30s超时勿重发; collision_detection=False
§
记忆五层: L2/L3/L4+总装Qwen(SS_MACRO); 势场喂obs[0:3]
§
真源calib.json→zmax_params.py; 全系统训练=joint_train_all.py --only L4,L3,L2; LoRA=lora_inject.py
§
L5规划器/safety=left_right/state_space/{planner,safety}.py; INTACT稳态101ms冷6.7s→须常驻
§
阶段MOE: 门控必硬先验路由; 枚举不匹配会静默降级吞阶段; 判据=单射性
§
LoRA需merge(否则零动作伪装没提升):merge_lora_ckpt.py
§
ECS relay: /agent/{prompt,reply}+/hil/state+/orin/status; 站点根=/www/wwwroot/datadrive.world; 新网页挂首页入口; 免密不通→ZMAX_ECS_PW; 公网只读/ov+/st, nginx须^~
§
遥测DDS仅测试/标定用(量产关; 开关env>文件~/.zmax_telemetry_mode; 守护zmax-dds-ss.service)
§
GPU掉载主因=每步CPU开销>计算(非数据/显存)→静音日志+workers↑
§
工程根~/zmax=独立仓库(MikeBMW/zmax public); 数据/venv/外部仓库都在zmax内(zmax/zmax_data=模型+数据+HF+secrets/zmax.env), 老名全删; 训练带HF_HOME=zmax_data/hf_cache; ld.so.conf指~/zmax/gui-venv311/.../nvidia/*/lib(免libcusparseLt报错); 入库=代码+docs/skills/hermes-all+docs/memory(守卫repo_guard+secret_scan)
§
控制台: 禁反复重启GUI(投诉过;改码攒批+先问); 字体一次到位
§
场景叠加: overlay_spec按origin存框; 手眼TSAI闭环1.74mm
§
我=主节点: 工控机+Orin全归我; AOI(.23.23)用10082/10083(禁10084/10085); 更新=aoi_remote_deploy.py; 通道=agent_hub(8794,~/zmax_data/agent_hub)+station_cmd.py
§
动作授权只从8793; 代发前先授权
§
位姿真源=zmax_data/rokae_sdk/tcp_out/latest.json(全0=会话陈旧⇒restart容器); 8793页真源=tools/web/station.html
§
运动安全: 抬升闸已放开(老倪10-09现场口授: 现场安全已检查过⇒取消"需要上升⇒整单拒发", 勿再拿10-08旧令限制; 仍须慢速+警报在先); 空间点1~7=同一平面 z=0.1727(11:34重记)⇒点间纯横移; 腿速上限150mm/s(页面2000档, 实测≈15mm/s); MoveJ自愈默认关; 危险点/新点位老倪先做; 台账INCIDENT-INDEX.md; 听"要碰撞"先agent_all_stop.py