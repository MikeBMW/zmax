#!/usr/bin/env bash
# 起后端状态空间 (单线程, 不驱动真机轨迹), 带 debugpy 监听 5678 供 VSCode 附着
cd /home/ubuntu/zmax || exit 1
export PYTHONPATH=/home/ubuntu/zmax/src:/home/ubuntu/zmax/tools
export PYTHONUNBUFFERED=1
export ZMAX_FSM=1 ZMAX_ORCH=1 ZMAX_SINGLE_THREAD=1
export ZMAX_AUTO_TRAJ=0            # 只跑状态空间, 不下发真机 215 点; 要跑真机就改 1
export ZMAX_TRAJ_CHUNK=1 ZMAX_TRAJ_SPEED=40 ZMAX_DISPATCH_INPROC=0
# 调试档: 关掉"外部 IO 节点"(单线程下会变同步阻塞), 只留状态空间链路
export ZMAX_AOI_OFF=1
# 调试档只跑核心调度链: 单线程下"整张画布(94 节点)"每拍要把 HTTP/RPC/大模型节点串一遍,
# 一拍几十秒 ⇒ 调度链(decide→advance→fsm.step)几乎轮不到。全量拍设成几乎不发生。
export ZMAX_CORE_IDS="ssobs,sssensor,ssff,ssest,sspred,ssinnov,sssched,sslimit,ssact,sstactile,n_exec"
export ZMAX_FULL_EVERY=999999
export ZMAX_SKIP_IDS="ssyolo,ssllm,ssreason,n_vlm_llm,n_dsvl,ss_l5,ss_seg,ssaoi,ssvlm,ssllm_in,ssintact,ssintact_dec,swintact,ss_lora_l4,ssmani_exp,ss_mem_l3,ssbg_vlm,ss_mani_eng,ssmani_c,ssmani_p,n_calib_mani,n_geoplan,swds,swvideo,n_realscene,ssrender"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
exec ./gui-venv311/bin/python -m debugpy --listen 127.0.0.1:5678 src/lerobot/engineering/start.py
