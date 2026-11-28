远程: 直连Orin.66/工控.23/intel.70(8888=总服务站); 拔⇒wifi(.43)经Orin跳; bridge39071; 小芳cli_aac4912eb6389bc2@550C
§
NTP回拨8h勿动RTC⇒monotonic;判活看将来ts;cron卡→watchdog.timer
§
分层: L5造数据/L4认知/L3调度/L2检测; SigLIP768d+四头; from-scratch崩
§
交付前自跑通;改文件回读;常驻静音
§
L5=DeepSeek短提示+小JSON(timeout≥300); L4=INTACT直驱, 反归一化按ckpt训练集; L2收口闸逐轴corr<0.5 veto
§
🔴工具内存≈8G超OOM;同刻仅一模型进程
§
Orin: ROS=domain0, tcp_pose 50Hz真值, 几何须ss_geom_calib, 只读遥测桥禁装包
§
真机3D须K+手眼+plane_z;D405深度unit0.1mm(4013=401mm)
§
YOLO=软链yolo_peg_live.pt;瓶颈=数据;相机独占⇒同进程
§
真机: rt后必下电; move_*不下电; 30s勿重发; collision=False; 腿=bridge(4060→39071→Orin39061); 段表须带abs_mm; 550C不在执行链
§
引擎五层L2/L3/L4+Qwen,势场喂obs[0:3]; H-JEPA-MR几何+SE3阻抗(u=+Kξ−Bξ̇+F_d; 序[ρ;ω])
§
阶段MOE:硬先验路由;枚举不匹配静默降级;判据=单射
§
LoRA需merge(否则零动作):merge_lora_ckpt.py
§
ECS=web入口;站点搬550C:8081待点头;资产直连/U盘
§
GPU掉载=每步CPU>计算→静音日志+workers↑
§
~/zmax=仓库MikeBMW/zmax; zmax_data=数据+HF+secrets(软链); 训练带HF_HOME
§
禁自重启GUI/服务(只可停);重启须点名;禁抢光标/代跑前台
§
我=主节点(工控机+Orin); AOI=10082/10083(禁84/85); 更新=aoi_remote_deploy.py
§
动作授权只从8793;代发前先授权
§
位姿真源=tcp_out/latest.json(全0陈旧;崩搬pose-relay)
§
运动安全: 速度1~1000mm/s;前置idle+automatic; 腿上限须重容器; 清79免授权;新点位老倪先做;碰撞先agent_all_stop; 插入力按封装SFP18/QSFP60/DD90N; 台账INCIDENT-INDEX.md
§
AR=8797;底图=8791(arm/gold/surface)+D435@Orin8794; L5=ar_l5_understand.py; AR3D r107 2孔z278/187.6
§
任务7=AR·L5进化;场景=ss_scene_switch.py;色标=sig_scene_tags.py
§
场景色:插拔绿/摆盘蓝/AR紫(3D=配置中心)
§
控制进程:按端口/pid找(ss -ltnp),禁ps|grep名;杀进程写脚本;sudo免密
§
判据图=aoi_surface_rect(贯穿列截断夹具+vertical兜底+扩暗头);曝光5000us
§
奇异区: 姿态>5°被50113拒且腿假报到位; 转移=抬50→转身→低位横移→上方升降
§
3DGS:基线17.22dB;24k=16.41未过闸; 建图8793走点45s/轮;GS_MAP_MODE=auto
§
版本号只听老倪;仓VERSION.md为准(现5.50.786);MoveIt起点须SDK直采
§
tool0读heartbeat.pose.flange(禁手推R,y差251mm);precheck扣连杆半径(肘r78)+<20mm FAIL
§
intel外网=corp10.163.149.123/23(wifi);.23.66 OrinNAT备;Orin sudo ts123
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
7任务=reports/fullflow7/<ts>/;缺口=仿真0轨迹·元任务‖T‖同值;专利20件
§
同步中枢=550C:8888(hub=/home/intel/zmax_sync_hub); Win跑zmax_sync.ps1 -Apply; skills只补缺+skills_update.txt强制覆盖