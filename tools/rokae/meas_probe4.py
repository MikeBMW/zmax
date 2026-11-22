import json, os, socket, sys, time
sys.path.insert(0, "/sdk")
import datetime as _dt
import xcoresdk_python as x
IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect((IP, 1)); lip = s.getsockname()[0]; s.close()
r = x.xMateRobot(); r.connectToRobot(IP, lip)
v = x.PyTypeVectorDouble([0.0]*6)
def dump(tag):
    try:
        c = v.content
        print(json.dumps({"tag": tag, "content_type": type(c).__name__, "content": [round(float(z),5) for z in c], "get0": float(v.get(0))}))
    except Exception as e:
        print(json.dumps({"tag": tag, "err": "%s: %s" % (type(e).__name__, e)}))
r.startReceiveRobotState(_dt.timedelta(milliseconds=1), [x.RtSupportedFields.jointPos_m])
time.sleep(0.3); dump("nrt")
ec={}
r.setRtNetworkTolerance(100, ec); print(json.dumps({"tol": ec}))
ec={}
r.setMotionControlMode(x.MotionControlMode.RtCommandMode, ec); print(json.dumps({"switch_rt": ec}))
time.sleep(0.5)
print(json.dumps({"rt_ret": r.getStateData("jointPos_m", v, 6)})); dump("rt")
ok,t0=0,time.time()
for _ in range(600):
    r.getStateData("jointPos_m", v, 6); ok+=1; time.sleep(0.001)
print(json.dumps({"hz": round(ok/(time.time()-t0),1)}))
ec={}
r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec); print(json.dumps({"back_nrt": ec}))
