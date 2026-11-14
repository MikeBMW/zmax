#!/usr/bin/env bash
# Intel 上重建厂家 interfaces 包 (ROS2 Jazzy)
source /opt/ros/jazzy/setup.bash
cd /home/intel/ros2_ws || exit 1
rm -rf build install log
colcon build --packages-select interfaces
echo "BUILD_RC=$?"
source /home/intel/ros2_ws/install/setup.bash
echo "AMENT_PREFIX_PATH=$AMENT_PREFIX_PATH"
ros2 interface show interfaces/srv/GripperSrv | head -10
