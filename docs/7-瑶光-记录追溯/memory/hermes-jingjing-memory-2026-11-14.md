远程: 网卡→Orin.23.66+工控机.23.23+intel.23.70直连; 拔⇒wifi(.43)经Orin跳; bridge39071; 小芳=cli_aac4912eb6389bc2在550C默认profile
§
NTP回拨8h(勿动RTC)→monotonic; 判活判'将来时间戳'; cron卡死→watchdog.timer
§
分层: L5造数据/L4认知/L3调度/L2检测; SigLIP768d+四头; from-scratch崩
§
交付前自跑通; 改文件必回读
§
L5=DeepSeek:短提示+小JSON; timeout≥300
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
真机: rt后必下电; move_*不下电; 30s勿重发; collision=False; 执行腿=bridge(4060 l2_daemon→39071→Orin 39061); 段表须带abs_mm; 550C不在执行链
§
引擎记忆五层L2/L3/L4+Qwen,势场喂obs[0:3]; H-JEPA-MR几何分支+SE3阻抗
§
真源calib.json→zmax_params.py; 训练=joint_train_all.py --only L4,L3,L2
§
L5规划器/safety=left_right/state_space/{planner,safety}.py; INTACT须常驻
§
阶段MOE: 硬先验路由; 枚举不匹配静默降级; 判据=单射性
§
LoRA需merge(否则零动作伪装):merge_lora_ckpt.py
§
ECS=web入口; 站点搬550C(8081)切流待点头; 资产产线直连/U盘
§
GPU掉载主因=每步CPU>计算→静音日志+workers↑
§
工程根~/zmax=仓库(MikeBMW/zmax); zmax_data=数据+HF+secrets(软链); 训练带HF_HOME
§
禁自重启GUI/服务(只可停);重启须点名;禁抢用户终端光标,不代跑前台脚本
§
我=主节点(工控机+Orin); AOI=10082/10083(禁84/85); 更新=aoi_remote_deploy.py
§
动作授权只从8793; 代发前先授权
§
位姿真源=tcp_out/latest.json(全0=陈旧; 崩则zmax-pose-relay桥搬)
§
运动安全: 速度mm/s 1~1000; 前置idle+automatic; 腿上限须重启容器; 清79免授权; 新点位老倪先做; 台账INCIDENT-INDEX.md; 要碰撞先agent_all_stop; 插入力≤40N
§
AR=8797(8791底图+D435; L5=ar_l5_understand.py)
§
任务7=AR·L5进化; 场景=ss_scene_switch.py; 色标=sig_scene_tags.py
§
场景色: 插拔绿/摆盘蓝/AR紫(3D按钮=配置中心)
§
控制进程: 按端口/pid找(ss -ltnp), 禁ps|grep名(自杀); 杀进程写脚本别内联; sudo免密
§
判据图=aoi_surface_rect;曝光5000us
§
奇异区: 姿态>5°被50113拒且腿假报到位(看真值); 转移=抬50→转身→低位横移→上方升降
§
3DGS糊=视角超覆盖; 建图8793走点45s/轮; GS_MAP_MODE=auto
§
版本号只听老倪; 仓VERSION.md为准(现5.50.775)
§
tool0读heartbeat.pose.flange(禁手推R,y差251mm); precheck需扣连杆半径(肘r78)+<20mm FAIL; 手臂相机围栏无此项盲区
§
MoveIt起点须SDK直采(禁手推)
§
反刷屏:回答≤两行;常驻输出静音
§
intel出口=.23.66走Orin NAT(zmax-nat-intel;Orin sudo ts123)
§
新版必跑canvas_selfheal; 打包红线=软链必须解引用(cp -L), 否则Win画布加载失败; Win补丁每版同步新app
§
状态空间100D=前55+45级联缓冲; 段表11.5s/件=313UPH(实测200.6), 900需AOI并行
§
调试断点:decide每拍advance+meta; 用scheduler_fsm:181(每拍必过), 252需证据; n_feature每拍仿真须关; start.py自带调试env/离线护栏
§
8797僵尸pid算活⇒busy(已判Z); flow游标跟align回退; 段在容器⇒CHUNK=1