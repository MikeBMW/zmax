#!/usr/bin/env python3
import threading, rclpy, numpy as np, cv2, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image
S={"jpg":None,"ts":0.0,"n":0,"err":"","enc":""}
def cb(msg):
    try:
        S["enc"]=getattr(msg,'encoding','')
        h,w=int(msg.height),int(msg.width)
        buf=np.frombuffer(bytes(msg.data),dtype=np.uint8)
        e=S["enc"]
        if e in ('bgr8','8UC3'):   a=buf.reshape(h,w,3)
        elif e=='rgb8':            a=buf.reshape(h,w,3)[:,:,::-1]
        elif e in ('bgra8',):      a=buf.reshape(h,w,4)[:,:,:3]
        elif e in ('mono8','8UC1'):a=cv2.cvtColor(buf.reshape(h,w),cv2.COLOR_GRAY2BGR)
        else:                      a=buf[:h*w].reshape(h,w); a=cv2.cvtColor(a,cv2.COLOR_GRAY2BGR)
        ok,b=cv2.imencode('.jpg',np.ascontiguousarray(a),[cv2.IMWRITE_JPEG_QUALITY,78])
        if ok: S["jpg"]=b.tobytes(); S["ts"]=time.time(); S["n"]+=1
        else: S["err"]="imencode false"
    except Exception as ex:
        S["err"]=repr(ex)[:120]; print("cb err",S["err"],flush=True)
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/frame'):
            j=S["jpg"]
            if j is None:
                self.send_response(503); self.send_header('Content-Type','text/plain')
                self.end_headers(); self.wfile.write(('no frame yet n=%d err=%s enc=%s'%(S["n"],S["err"],S["enc"])).encode()); return
            self.send_response(200); self.send_header('Content-Type','image/jpeg')
            self.send_header('Content-Length',str(len(j))); self.send_header('Access-Control-Allow-Origin','*')
            self.end_headers(); self.wfile.write(j)
        else:
            b=('{"n":%d,"age_s":%.2f,"enc":"%s","err":"%s"}\n'%(S["n"],time.time()-S["ts"] if S["ts"] else -1,S["enc"],S["err"])).encode()
            self.send_response(200); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass
rclpy.init()
n=Node('rs_fast_node')
q=QoSProfile(depth=8,reliability=ReliabilityPolicy.BEST_EFFORT,history=HistoryPolicy.KEEP_LAST)
n.create_subscription(Image,'/realsense/color/image_raw',cb,q)
threading.Thread(target=lambda:HTTPServer(('0.0.0.0',8792),H).serve_forever(),daemon=True).start()
print("[rs_fast_node] :8792 ready",flush=True)
try: rclpy.spin(n)
except Exception as e: print("spin end",repr(e)[:100],flush=True)
