import json, os, socket, sys, time
sys.path.insert(0, "/sdk")
import datetime as _dt
import xcoresdk_python as x
IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect((IP, 1)); lip = s.getsockname()[0]; s.close()
r = x.xMateRobot(); r.connectToRobot(IP, lip)
v = x.PyTypeVectorDouble([0.0]*6)
print(json.dumps({"dir": [n for n in dir(v) if not n.startswith("__")][:20]}, ensure_ascii=False))
print(json.dumps({"repr": str(v)[:80]}))
r.startReceiveRobotState(_dt.timedelta(milliseconds=1), [x.RtSupportedFields.jointPos_m])
time.sleep(0.5)
print(json.dumps({"nrt_ret": r.getStateData("jointPos_m", v, 6), "repr_after": str(v)[:100]}))
