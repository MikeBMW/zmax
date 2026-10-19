"""等老倪手动把臂移到侧面点1, 停稳 3s 就抓下来 (只读 tcp_out/latest.json, 不碰控制器)"""
import json, math, time, sys

P = '/home/ubuntu/zmax/zmax_data/rokae_sdk/tcp_out/latest.json'
LIMIT = float(sys.argv[1]) if len(sys.argv) > 1 else 420.0


def rd():
    d = json.load(open(P, encoding='utf-8'))
    p = [d['x'] * 1000.0, d['y'] * 1000.0, d['z'] * 1000.0]
    a = [math.degrees(d.get('rx', 0)), math.degrees(d.get('ry', 0)), math.degrees(d.get('rz', 0))]
    return p, a, d


def dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


p0, a0, _ = rd()
print('起始 pos=[%.1f, %.1f, %.1f] abc=[%.2f, %.2f, %.2f]' % (p0[0], p0[1], p0[2], a0[0], a0[1], a0[2]), flush=True)

moved = False
peak = 0.0
last = p0
still_s = 0.0
t0 = time.time()
step = 0.4
while time.time() - t0 < LIMIT:
    time.sleep(step)
    try:
        p, a, d = rd()
    except Exception:
        continue
    dm = dist(p, p0)
    peak = max(peak, dm)
    if dm > 10.0:
        moved = True
    still_s = still_s + step if dist(p, last) < 0.5 else 0.0
    if moved and still_s >= 3.0:
        print('到位 pos=[%.1f, %.1f, %.1f] abc=[%.2f, %.2f, %.2f]' % (p[0], p[1], p[2], a[0], a[1], a[2]), flush=True)
        print('位移起始 %.1f mm · 峰值 %.1f mm · 用时 %.1fs · 停稳 %.1fs' % (dm, peak, time.time() - t0, still_s), flush=True)
        json.dump({'from': p0, 'to': p, 'abc': a, 'move_mm': round(dm, 2), 'peak_mm': round(peak, 2),
                   'elapsed_s': round(time.time() - t0, 1), 'raw': d},
                  open('/tmp/pt1_new.json', 'w', encoding='utf-8'), ensure_ascii=False)
        sys.exit(0)
    last = p

print('超时 %.0fs 未检测到"移动后停稳" · 峰值位移 %.1f mm' % (LIMIT, peak), flush=True)
sys.exit(1)
