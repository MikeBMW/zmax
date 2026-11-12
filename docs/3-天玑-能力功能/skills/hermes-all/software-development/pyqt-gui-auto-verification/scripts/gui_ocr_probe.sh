#!/usr/bin/env bash
# 截当前窗口 + OCR, 只打印含关键词的行(带像素坐标) —— 用来回答
# "界面现在在哪一页 / 这页有没有 X 按钮", 不必把图丢给读屏子代理。
#
# 用法:
#   bash gui_ocr_probe.sh [输出png] [关键词,逗号分隔]
#   bash gui_ocr_probe.sh /tmp/o.png '运行,画布,停止'
#
# 坐标换算: 屏幕坐标 = 窗口位置( xdotool getwindowgeometry 的 Position ) + 图内坐标
set -u
export DISPLAY="${DISPLAY:-:0}"
OUT="${1:-/tmp/gui_ocr_shot.png}"
KW_CSV="${2:-运行,画布,状态空间,Simulink,单步,停止,节点,返回,平台,开始}"

scrot -u "$OUT" >/dev/null 2>&1 || scrot "$OUT" >/dev/null 2>&1 || {
  # 没有 scrot 时退回 Qt 自带抓屏 (同目录 scripts/grab_window_by_winid.py, 需先 wmctrl -l 取 winid)
  echo "scrot 不可用; 用 scripts/grab_window_by_winid.py <winid> $OUT" >&2; exit 2; }

tesseract "$OUT" /tmp/gui_ocr_out -l chi_sim+eng --psm 11 tsv >/dev/null 2>&1 || {
  echo "tesseract 不可用/无 chi_sim 语言包" >&2; exit 3; }

python3 - "$OUT" "$KW_CSV" <<'PY'
import csv, sys
png, kws = sys.argv[1], [k.strip() for k in sys.argv[2].split(',') if k.strip()]
rows = [r for r in csv.DictReader(open('/tmp/gui_ocr_out.tsv'), delimiter='\t')
        if (r.get('text') or '').strip()]
hits = []
for r in rows:
    t = r['text'].strip()
    if any(k in t for k in kws):
        x = int(r['left']) + int(r['width']) // 2
        y = int(r['top']) + int(r['height']) // 2
        hits.append((y, x, t))
print(f'== {png} == 关键词: {kws}')
if hits:
    for y, x, t in sorted(hits):
        print(f'y={y:5d} x={x:5d}  {t}')
else:
    print('(关键词零命中) 前 40 个词:', ' | '.join(r['text'].strip() for r in rows[:40]))
PY
