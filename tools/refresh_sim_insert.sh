#!/usr/bin/env bash
# 重算右臂插拔段表: 速度取左臂同口径(左臂每循环 3.0s 的等效速度)
set -e
cd "$(dirname "$0")/.."
./gui-venv311/bin/python tools/sim_insert_plan.py
