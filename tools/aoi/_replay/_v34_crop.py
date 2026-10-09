# -*- coding: utf-8 -*-
import sys
import numpy as np, cv2
f = sys.argv[1]
y0, y1 = int(sys.argv[2]), int(sys.argv[3])
x0, x1 = int(sys.argv[4]), int(sys.argv[5])
out = sys.argv[6]
im = cv2.imread(f)
crop = im[y0:y1, x0:x1].copy()
# annotate y ruler every 50 px (raw coords)
for yy in range(y0 - y0 % 50 + 50, y1, 50):
    cv2.line(crop, (0, yy - y0), (40, yy - y0), (0, 0, 255), 2)
    cv2.putText(crop, str(yy), (45, yy - y0 + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
cv2.imwrite(out, crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
print("wrote", out, crop.shape)
