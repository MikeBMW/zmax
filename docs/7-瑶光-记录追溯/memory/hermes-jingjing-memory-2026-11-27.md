远程: 直连Orin.66/工控.23/intel.70; 拔⇒wifi(.43)经Orin跳; bridge39071; 小芳cli_aac4912eb6389bc2@550C
§
分层: L5造数据/L4认知/L3调度/L2检测; SigLIP768d+四头; from-scratch崩
§
交付前自跑通;改文件回读;答≤两行;常驻静音
§
L5=DeepSeek短提示+小JSON(timeout≥300); L4=INTACT直驱, 反归一化按ckpt训练集; L2收口闸逐轴corr<0.5 veto
§
🔴工具内存≈8G超OOM;同刻仅一模型进程
§
Orin: ROS=domain0, tcp_pose 50Hz真值, 几何须ss_geom_calib, 只读遥测桥禁装包
§
真机3D须K+手眼+plane_z; D405深度unit0.1mm(4013=401mm)
§
YOLO=软链yolo_peg_live.pt; 瓶颈=数据; 相机独占⇒同进程
§
真机: rt后必下电; move_*不下电; 30s勿重发; collision=False; 腿=bridge(4060→39071→Orin39061); 段表须带abs_mm; 550C不在执行链
§
引擎五层L2/L3/L4+Qwen,势场喂obs[0:3]; H-JEPA-MR+SE3阻抗(u=+Kξ−Bξ̇+F_d); A~E五流形=se3_layers(C=S³归一)
§
真源calib.json→zmax_params.py; 训练=joint_train_all.py --only L4,L3,L2; L5规划器/safety=ss/{planner,safety}.py; INTACT须常驻
§
LoRA需merge(否则零动作):merge_lora_ckpt.py
§
双系统C=p3/D=p4共用(挂/mnt/wD)/Ubu=p5; Win控制台=D:\ZMAX双击启动控制台.bat; 回灌sync_from_dzmax.sh; 根_zmax_root_dir禁dirname³; 场景色插拔绿摆盘蓝AR紫
§
GPU掉载=每步CPU>计算→静音日志+workers↑
§
~/zmax=仓库MikeBMW/zmax; zmax_data=数据+HF+secrets(软链); 训练带HF_HOME
§
禁自重启GUI/服务(只可停);重启须点名;禁抢光标/代跑前台
§
我=主节点(工控+Orin);AOI=10082/10083(禁84/85);更新=aoi_remote_deploy.py
§
动作授权只从8793; 代发前先授权
§
位姿真源=tcp_out/latest.json(全0陈旧;崩则pose-relay搬)
§
运动安全: 速度1~1000mm/s;前置idle+automatic; 腿上限须重容器; 清79免授权;新点位老倪先做;碰撞先agent_all_stop; 插入力SFP18/QSFP60/DD90N; 台账INCIDENT-INDEX.md; 两腿:轨迹MoveAbsJ/笛卡尔move_rel
§
AR=8797(systemd;8793与Intel8816皆裸进程无自启);轨迹cursor=N+1⇔frames[N]⇔页#N;底图8791+D435@Orin8794;AOI位姿8793/guide_move→8797/move_rel;k勿用pitch换算;规整图裁剪跟随看不出移动
§
任务7=AR·L5进化;场景=ss_scene_switch.py;色标=sig_scene_tags.py
§
控制进程: 按端口/pid找(ss -ltnp),禁ps|grep名;杀进程写脚本;sudo免密
§
判据图=aoi_surface_rect;10083曝光<20k无信号(3k=4/5k=11/7k抖/40k可)现7k;点记录后必跑verify_points_consistency
§
奇异区: 姿态>5°被50113拒且腿假报到位; 转移=抬50→转身→低位横移→上方升降
§
版本号只听老倪;仓VERSION.md为准;MoveIt起点须SDK直采
§
tool0读heartbeat.pose.flange(禁手推R,y差251mm);precheck扣连杆半径(肘r78)+<20mm FAIL
§
intel出口=.23.66走Orin NAT(zmax-nat-intel;Orin sudo ts123)
§
新版必跑canvas_selfheal; 打包红线=软链解引用(cp -L)否则Win画布崩; Win补丁每版同步
§
状态空间100D=55+45缓冲; 段表11.28s/件=319UPH; 900需AOI并行
§
调试断点:decide每拍advance+meta;fsm:181必过,252需证据;n_feature仿真须关
§
8797僵尸pid⇒busy;flow游标跟align回退;段在容器⇒CHUNK=1
§
action=真值pose+u·dt(重锚)+u[3]夹爪;无真值不出位姿;Intel非git⇒rsync
§
7任务=reports/fullflow7/<ts>/;专利20件