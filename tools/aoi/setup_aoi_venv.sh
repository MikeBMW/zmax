#!/usr/bin/env bash
# 建"产线数值栈"解释器 —— 离线 AOI 开发必须用它 (版本不同判据结果就不同)
#
#   bash tools/aoi/setup_aoi_venv.sh
#
# 工控机现役数值栈 (实测自 10082/10083 程序环境):
#   python 3.10 · numpy 1.26.4 · opencv-python 4.10.0.84 · flask 3.x
# gui-venv311 是 cv2 5.0.0 ⇒ 同一帧会命中不同窗口, 不能用来复现产线判据。
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv-aoi310"
UV="${UV:-$HOME/.hermes/bin/uv}"

if [ ! -x "$UV" ]; then
  echo "缺 uv ($UV)。装: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
  echo "[1/2] 建 venv: $VENV (python 3.10)"
  "$UV" venv "$VENV" -p 3.10
fi
echo "[2/2] 装产线数值栈"
"$UV" pip install --python "$VENV/bin/python" \
  numpy==1.26.4 opencv-python==4.10.0.84 flask
"$VENV/bin/python" - <<'PY'
import numpy, cv2
from importlib.metadata import version
print("numpy", numpy.__version__, "| opencv", cv2.__version__, "| opencv-python", version("opencv-python"),
      "| flask", version("flask"))
PY
echo "OK: $VENV/bin/python"
