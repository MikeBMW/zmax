#!/usr/bin/env python3
"""在 Intel(x86_64, ROS2 Jazzy) 上重建厂家 interfaces 包(纯 .srv/.msg)。

老倪 2026-11-14 路线1: 驱动留 Orin, 业务迁 Intel ⇒ Intel 侧也要能"看懂"厂家的服务类型。
来源: Orin 的 install/interfaces/share/interfaces/{srv,msg} (纯文本, 与架构无关)
"""
import os
import subprocess
import sys

SRC = os.path.expanduser("~/ros2_iface")
WS = os.path.expanduser("~/ros2_ws")
PKG = os.path.join(WS, "src", "interfaces")

if not os.path.isdir(SRC):
    sys.exit("缺 %s (先解包 .srv/.msg)" % SRC)

srvs = sorted(f for f in os.listdir(os.path.join(SRC, "srv")) if f.endswith(".srv"))
msgs = sorted(f for f in os.listdir(os.path.join(SRC, "msg")) if f.endswith(".msg"))
print("srv %d 个 · msg %d 个" % (len(srvs), len(msgs)))

os.makedirs(os.path.join(PKG, "srv"), exist_ok=True)
os.makedirs(os.path.join(PKG, "msg"), exist_ok=True)
for f in srvs:
    with open(os.path.join(SRC, "srv", f), encoding="utf-8") as r:
        open(os.path.join(PKG, "srv", f), "w", encoding="utf-8").write(r.read())
for f in msgs:
    with open(os.path.join(SRC, "msg", f), encoding="utf-8") as r:
        open(os.path.join(PKG, "msg", f), "w", encoding="utf-8").write(r.read())

open(os.path.join(PKG, "package.xml"), "w", encoding="utf-8").write("""<?xml version="1.0"?>
<package format="3">
  <name>interfaces</name>
  <version>0.0.1</version>
  <description>厂家 tashan_robot_so 接口定义(在 Intel/Jazzy 上重建, 与 Orin/Humble 同名同定义)</description>
  <maintainer email="zmax@local">zmax</maintainer>
  <license>Proprietary</license>
  <buildtool_depend>ament_cmake</buildtool_depend>
  <buildtool_depend>rosidl_default_generators</buildtool_depend>
  <exec_depend>rosidl_default_runtime</exec_depend>
  <member_of_group>rosidl_interface_packages</member_of_group>
</package>
""")

srv_lines = "\n".join('  "srv/%s"' % f for f in srvs)
msg_lines = "\n".join('  "msg/%s"' % f for f in msgs)
interface_files = ",\n".join(x for x in [srv_lines, msg_lines] if x)
open(os.path.join(PKG, "CMakeLists.txt"), "w", encoding="utf-8").write("""cmake_minimum_required(VERSION 3.8)
project(interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
%s
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
""" % interface_files)

print("生成完成:", PKG)
env = dict(os.environ)
env["CMAKE_BUILD_PARALLEL_LEVEL"] = "4"
r = subprocess.run("source /opt/ros/jazzy/setup.bash && cd %s && colcon build --packages-select interfaces" % WS,
                   shell=True, executable="/bin/bash", capture_output=True, text=True, timeout=1200)
print(r.stdout[-1500:])
print(r.stderr[-1500:])
print("BUILD_RC", r.returncode)
