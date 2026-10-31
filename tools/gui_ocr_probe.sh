#!/usr/bin/env bash
# 截当前前台窗口 + OCR, 只打印含关键词的行(带坐标), 用于在 GUI 里找按钮
export DISPLAY=:0
W=$(xdotool getactivewindow 2>/dev/null)
OUT=${1:-/tmp/ocr_shot.png}
scrot -u "$OUT" >/dev/null 2>&1 || scrot "$OUT" >/dev/null 2>&1
tesseract "$OUT" /tmp/ocr_out -l chi_sim+eng --psm 11 tsv >/dev/null 2>&1
python3 - "$OUT" <<'PY'
import csv,sys
rows=[r for r in csv.DictReader(open('/tmp/ocr_out.tsv'),delimiter='\t') if (r.get('text') or '').strip()]
KW=('运行','画布','状态空间','Simulink','单步','停止','节点','返回','平台')
hit=[]
for r in rows:
    t=r['text'].strip()
    if any(k in t for k in KW):
        x=int(r['left'])+int(r['width'])//2; y=int(r['top'])+int(r['height'])//2
        hit.append((y,x,t))
if not hit:
    print('(关键词零命中) 屏幕前 40 个词:', ' | '.join(r['text'].strip() for r in rows[:40]))
else:
    for y,x,t in sorted(hit):
        print(f'y={y:5d} x={x:5d}  {t}')
PY
