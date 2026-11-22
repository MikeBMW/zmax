import sys, inspect
sys.path.insert(0, "/sdk")
import xcoresdk_python as x
jp = x.JointPosition([0.0]*6)
print("JointPosition OK", type(jp))
try:
    c = x.MoveAbsJCommand(jp, 20.0, -1)
    print("MoveAbsJCommand(jp, speed, -1) OK")
except Exception as e:
    print("sig1 fail:", e)
    try:
        c = x.MoveAbsJCommand(jp, 20.0)
        print("MoveAbsJCommand(jp, speed) OK")
    except Exception as e2:
        print("sig2 fail:", e2)
