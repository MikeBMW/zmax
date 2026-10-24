#!/usr/bin/env python3
"""分层卸载测速: 定位「ROS2 一发布图像就掉速」卡在哪一步。

四档逐层加料, 每档跑 --secs 秒, 打印 fps 与每帧耗时:
  A 只取帧(+对齐)          —— 相机/对齐本身的上限
  B +深度发到 0 订阅者话题   —— 只加「打包 0.6MB」的代价
  C +彩色发到 0 订阅者话题   —— 再叠 0.9MB
  D 彩色+深度发到**生产话题** —— 有真实订阅者(Reliable 订阅方/网络订阅方)时的代价

判读要点(实测 D405 640x480@30, Orin):
  A 26.5fps → B 7.5fps → C 3.0fps;
  把网络订阅端整个停掉后帧率纹丝不动(3.07→3.15fps)
  ⇒ 掉速随**消息字节数**线性变差、与订阅者无关 ⇒ 病在 rclpy 逐字节打包(0.9MB≈170ms/帧),
    不是网络、不是带宽、不是相机。修法 = 换小消息(CompressedImage JPEG/PNG ~41KB/159KB)
    或旁路 HTTP, 不是换传输协议、也不是加带宽。

相机只能被一个进程独占 ⇒ 在役服务在跑时先停、跑完再起(实测释放要 18~20s, 8s 不够):
  sudo -n systemctl stop <unit>; sleep 20
  python3 ros_publish_cost_attribution.py --secs 6
  sudo -n systemctl start <unit>
若报 EIO / Couldn't resolve requests: 再等 10s 重试; 连着失败可把父 hub 端口
`authorized` 0→1 重新枚举(设备会从 lsusb 消失, 不是硬件坏)。
"""
import argparse
import time

import numpy as np
import pyrealsense2 as rs


def pack_image(arr, enc):
    from sensor_msgs.msg import Image

    m = Image()
    m.height, m.width = int(arr.shape[0]), int(arr.shape[1])
    m.encoding = enc
    m.is_bigendian = 0
    m.step = int(arr.shape[1] * (3 if enc == "bgr8" else 2))
    m.data = arr.tobytes()
    return m


def run_stage(name, secs, pub_color, pub_depth, w, h, fps_req):
    import rclpy

    pipe = rs.pipeline()
    cfg = rs.config()
    cfg.enable_stream(rs.stream.color, w, h, rs.format.bgr8, fps_req)
    cfg.enable_stream(rs.stream.depth, w, h, rs.format.z16, fps_req)
    pipe.start(cfg)
    align = rs.align(rs.stream.color)
    n = 0
    lat = []
    t0 = time.time()
    try:
        while time.time() - t0 < secs:
            a = time.time()
            fs = align.process(pipe.wait_for_frames(2000))
            c, d = fs.get_color_frame(), fs.get_depth_frame()
            if c and pub_color is not None:
                pub_color.publish(pack_image(np.asanyarray(c.get_data()), "bgr8"))
            if d and pub_depth is not None:
                pub_depth.publish(pack_image(np.asanyarray(d.get_data()), "16UC1"))
            rclpy.spin_once(NODE, timeout_sec=0)
            lat.append(time.time() - a)
            n += 1
    finally:
        pipe.stop()
    el = time.time() - t0
    lat.sort()
    p50 = 1000 * lat[len(lat) // 2] if lat else -1
    print("%-38s %6.2f fps · 每帧 %5.0f ms (p50 %5.0f)" % (name, n / el, 1000 * el / max(n, 1), p50), flush=True)
    time.sleep(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=6.0)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--color-topic", default="/realsense/color/image_raw")
    ap.add_argument("--depth-topic", default="/realsense/depth/image_rect_raw")
    ap.add_argument("--test-color-topic", default="/bench/color")
    ap.add_argument("--test-depth-topic", default="/bench/depth")
    ap.add_argument("--skip-d", action="store_true", help="不往生产话题发(只想证打包代价时用)")
    args = ap.parse_args()

    global NODE
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import Image  # noqa: F401  (pack_image 里用)

    rclpy.init()
    NODE = Node("publish_cost_attribution")
    q_rel = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE)
    q_be = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.BEST_EFFORT)
    pub_col_test = NODE.create_publisher(Image, args.test_color_topic, q_rel)
    pub_dep_test = NODE.create_publisher(Image, args.test_depth_topic, q_be)
    pub_col_real = NODE.create_publisher(Image, args.color_topic, q_rel)
    pub_dep_real = NODE.create_publisher(Image, args.depth_topic, q_be)

    print("分辨率 %dx%d @%dfps · 每档 %.1fs · 停服务后须等 18~20s 再跑" % (args.width, args.height, args.fps, args.secs))
    run_stage("A 只取帧+对齐(不发布)", args.secs, None, None, args.width, args.height, args.fps)
    run_stage("B +深度→测试话题(%s)" % args.test_depth_topic, args.secs,
              None, pub_dep_test, args.width, args.height, args.fps)
    run_stage("C +彩色→测试话题(%s)" % args.test_color_topic, args.secs,
              pub_col_test, pub_dep_test, args.width, args.height, args.fps)
    if not args.skip_d:
        run_stage("D 彩色+深度→生产话题(有订阅者)", args.secs,
                  pub_col_real, pub_dep_real, args.width, args.height, args.fps)
    print("\n判读: A→B→C 每档的降幅应与新增字节数成比例, 且 B/C 档**没有任何订阅者**;")
    print("      若 B/C 就掉速 ⇒ 病在发布端打包, 换小消息(CompressedImage/HTTP), 不要换协议或加带宽。")
    rclpy.shutdown()


if __name__ == "__main__":
    main()
