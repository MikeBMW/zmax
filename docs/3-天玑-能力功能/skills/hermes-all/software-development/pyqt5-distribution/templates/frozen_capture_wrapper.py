# 冻结包「窗口版 exe 跑脚本」的捕获包装器（模板：复制后改两处路径即可）
#
# 用途: PyInstaller --windowed 产物里 sys.stdout/stderr 是 None，脚本的 print 与 traceback 全丢，
#       表现是「进程起来、几秒后没了、日志 0 字节」。用本包装器起目标脚本即可拿到真原因。
#
# 用法: "<安装目录>/<App>.exe" "<安装目录>/cap_run.py"
#       （入口脚本需支持 argv[1] 是 .py 时同进程 runpy 执行，见 references/frozen-runtime-subprocess-and-macos-gl.md §1b）
import os
import runpy
import sys
import time
import traceback

# ── 只改这两处 ────────────────────────────────────────────
TARGET = r"C:\path\to\install\_internal\tools\target_script.py"
LOG = r"C:\path\to\instance\logs\cap_run.log"
# ────────────────────────────────────────────────────────

# 窗口版 exe 不继承调用方的环境变量；入口需要的能力闸/单线程闸/根路径在这里钉死
os.environ.setdefault("ZMAX_ROOT", os.path.dirname(os.path.dirname(LOG)))  # 按项目实际根改
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

os.makedirs(os.path.dirname(LOG), exist_ok=True)
fh = open(LOG, "a", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = sys.stderr = fh
fh.write("\n===== start %s pid=%s target=%s =====\n" % (time.strftime("%F %T"), os.getpid(), TARGET))

try:
    runpy.run_path(TARGET, run_name="__main__")
except SystemExit as e:            # 业务里的 sys.exit("人话原因") 会走这里
    fh.write("SystemExit: %r\n" % (e.code,))
except BaseException:
    traceback.print_exc(file=fh)

fh.write("===== end %s =====\n" % time.strftime("%F %T"))
fh.flush()
