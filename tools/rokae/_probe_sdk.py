import sys, json
sys.path.insert(0, "/sdk")
import xcoresdk_python as x
r = x.xMateRobot(); r.connectToRobot("192.168.23.160")
jp = r.jointPos({})
print("joints_deg", [round(float(v)*57.2958, 2) for v in jp.jointPosition] if hasattr(jp, "jointPosition") else jp)
try:
    print("limits", r.jointLimit({}))
except Exception as e:
    print("no jointLimit:", e)
