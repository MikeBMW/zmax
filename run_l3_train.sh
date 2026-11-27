#!/bin/bash
cd /home/intel/zmax
export PYTHONPATH=/home/intel/zmax/src
exec /home/intel/gsxpu-venv/bin/python -u -m lerobot.scripts.lerobot_train --config_path /home/intel/zmax/config_l3_act_xpu.yaml
