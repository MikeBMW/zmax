#!/usr/bin/env python3
"""AOI 自主更新器 —— 4060(主节点) 推程序到工控机 192.168.23.23 并上线验收 (2026-09-27)

老倪要求: 主节点要能自主更新工控机程序, **只用 10082/10083**, 不用 10084/10085 试跑口。

流程(全程无人工):
  ① 程序拷进 8794 静态目录 (agent_hub --dir)
  ② 经反向通道让工控机 iwr 下载 + Get-FileHash 与本地 SHA256 逐位核对(不一致就中止, 不动产线)
  ③ 备份现役程序为 <名>.bak ④ 停旧起新(**始终 10082/10083**, 分离启动, 不受窗口关闭影响)
  ⑤ 验收(缺一即判失败): /storage 200 · /last_result 200 · POST /capture_detect 回执 code=200 ·
     GET /picture?kind=origin&grab=1 字节>0 且 /storage 的 files_total **不增长**(v5 不落盘口径)
  ⑥ 任一失败 → 用 .bak 回滚 + 重启 + 复验, 并如实报失败

用法:
  python tools/aoi_remote_deploy.py --finger ~/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v6.py \
                                   --surface ~/zmax/zmax_data/aoi_v4/surface_10083_work_v5.py
  可选: --no-restart(只推文件不重启) · --dry(只做 ① ② 核对) · --pubdir <目录>
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
HUB = os.path.join(ROOT, "tools", "agent_hub.py")
# 2026-09-29: 与 agent_hub.py 的 OUT_DIR 同步搬出 /tmp(见 agent_hub.py 顶部"fs.protected_regular"说明)
OUT_DIR = "/home/ubuntu/zmax/zmax_data/agent_hub/out"
HOST = "192.168.23.50"
ILO = "192.168.23.23"
FILENAME_10082 = "cam_finger_10082_work_v20.py"
FILENAME_10083 = "cam_surface_10083_work_v20.py"


def log(msg):
    print("[deploy %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest().upper()


def newest_out():
    try:
        fs = [os.path.join(OUT_DIR, x) for x in os.listdir(OUT_DIR)]
        return max(fs, key=os.path.getmtime) if fs else None
    except OSError:
        return None


def remote(ps, wait=180, label=""):
    """经反向通道在工控机上跑一段 PowerShell, 返回回执文本。"""
    before = newest_out()
    t0 = time.time()
    r = subprocess.run([PY, HUB, "--enqueue", ps], capture_output=True, text=True)
    if r.returncode != 0:
        return "<<ENQUEUE_FAIL: %s>>" % (r.stderr or r.stdout)[:200]
    deadline = time.time() + wait
    while time.time() < deadline:
        f = newest_out()
        if f and f != before and os.path.getmtime(f) >= t0 - 1:
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError:
                pass
        time.sleep(1.0)
    return "<<TIMEOUT %s>>" % label


def http_get(url, timeout=20):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        # ⚠️ 2026-09-30 踩坑: 4xx/5xx 也说明"服务活着"。原来走 except Exception 会丢状态码(st=0),
        #    于是验收认不出 10082 那条**合法 404**("/last_result 尚无检测结果") ⇒ 首帧推理慢时假失败 ⇒ 误回滚。
        try:
            body = e.read()
        except Exception:                      # noqa: BLE001
            body = b""
        return e.code, body
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()


def http_post(url, timeout=90):
    req = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()


def files_total(port):
    st, body = http_get("http://%s:%d/storage" % (ILO, port))
    if st != 200:
        return None
    m = re.search(rb'"files_total":\s*(\d+)', body)
    return int(m.group(1)) if m else None


def verify(port, test_capture=True):
    """验收一路; 返回 (ok, 明细 list)。"""
    out = []

    def chk(name, cond, extra=""):
        out.append(("✅ " if cond else "❌ ") + name + (" " + extra if extra else ""))
        return cond

    # ⚠️ 2026-10-08 踩坑(第二次误回滚就是这样来的): 服务**冷启动到能应答实测 ~89s, 首抓还要更久**,
    #    而验收在重启命令后 ~25s 就来查 /storage ⇒ HTTP 0 ⇒ 假失败 ⇒ 误触发回滚。
    #    处置: readiness 轮询最多 200s, 拿到 200 再往下走(与 capture_detect 的容忍式重试同口径)。
    st, body = 0, b""
    _up_end = time.time() + 200
    while time.time() < _up_end:
        st, body = http_get("http://%s:%d/storage" % (ILO, port))
        if st == 200:
            break
        time.sleep(5)
    ok = chk("/storage HTTP200(等冷启动, 最多 200s)", st == 200, "(%s)" % st)

    def _stable_total(tries=8, gap=1.5):
        """等落盘稳定(连续两次读数相同)再取基准。
        ⚠️ 2026-09-29 踩坑: 基准若在 capture_detect 的**异步 worker 还在落图**时取,
        'grab 不落盘' 会假失败 ⇒ 假失败触发**自动回滚**(危险)。实测就是这么误判过一次。"""
        last = None
        for _ in range(tries):
            cur = files_total(port)
            if cur is not None and cur == last:
                return cur
            last = cur
            time.sleep(gap)
        return last

    if test_capture:
        # ⚠️ 2026-10-08 踩坑(v21 金手指部署就是被这条回滚的): 服务**冷启动后首抓必失败**
        #    (SciCam_Grab 冷启/空闲后首抓返回失败), 实测启动后 ~100s 内 POST /capture_detect
        #    回 500, 而同一时刻 /picture?grab=1 已能出图 ⇒ 单次断言 = **假失败 ⇒ 误触发自动回滚**。
        #    处置: 轮询重试最多 180s, 首次拿到 code=200 即判通过; 全程失败才算失败。
        st, body = 0, b""
        _cd_end = time.time() + 180
        while time.time() < _cd_end:
            st, body = http_post("http://%s:%d/capture_detect" % (ILO, port))
            if st == 200 and b'"code":200' in body:
                break
            time.sleep(15)
        ok &= chk("POST /capture_detect 回执 code=200(容忍冷启首抓, 最多 180s)",
                  st == 200 and b'"code":200' in body,
                  body[:80].decode("utf-8", "replace"))
        # /last_result 的两种合法形态: ①200+verdict/count ②404+「尚无检测结果」(后台推理还没跑完)
        # 表面(housing) 推理实测 ~8.9s ⇒ 轮询等, 别用固定短等待(会假失败)。2026-09-27 踩过。
        #
        # ⚠️ 2026-10-08 **第三次**踩同一个坑(v24 金手指部署就这么被滚掉过一次):
        #    冷启动/推理忙时 /last_result 会**瞬时拒连**(urlopen Errno 111, st=0), 而原实现 45s 窗口
        #    一到就判死 ⇒ ok_all=False ⇒ **自动回滚**, 把刚推上去的新程序换成旧的。同一次验收里
        #    /storage 已 200、POST /capture_detect 已 code=200、grab=1 已出图(411KB) —— 服务明明是活的。
        #    处置(缺一不可): ① 传输层错误(st==0)不算"判决失败", 继续轮询 ② 窗口 45s→120s
        #    ③ 全程只有传输层错误时**降级为警告**, 不判死(其余判据已证明服务活着)。
        _esc = "".join("\\u%04x" % ord(c) for c in "尚无检测结果")
        t_end = time.time() + 120
        st, body = 0, b""
        _seen_http = False
        while time.time() < t_end:
            st, body = http_get("http://%s:%d/last_result" % (ILO, port))
            if st != 0:
                _seen_http = True          # 服务在 HTTP 层应答过 ⇒ 已经不是"连不上"
            legal = (st == 404 and (not body or "尚无检测结果".encode() in body
                                    or _esc.encode() in body))
            if st == 200 or legal:
                break
            time.sleep(3)
        legal404 = (st == 404 and (not body or "尚无检测结果".encode() in body
                                  or _esc.encode() in body))
        if st == 200 or legal404:
            ok &= chk("/last_result 判决通道", True,
                      ("200 " if st == 200 else "404-尚无(在等/推理慢) ")
                      + body[:60].decode("utf-8", "replace"))
        elif not _seen_http:
            # 全程只有传输层错误 ⇒ 不判死(见上面 2026-10-08 说明), 只留证据行
            out.append("⚠️ /last_result 全程连不上(传输层错误, 非判决失败) —— 不判死: "
                       "/storage 与 grab=1 已证明服务在跑")
        else:
            ok &= chk("/last_result 判决通道", False,
                      ("%s " % st) + body[:60].decode("utf-8", "replace"))
    n_before = _stable_total()          # 取基准: 等检测线程落盘稳定(见 _stable_total 注释)
    st, img = 0, b""
    for _try in range(5):      # 2026-09-30 踩坑: 服务刚重启/相机未热身时**首抓会返回错误体**(实测 46B)
        st, img = http_get("http://%s:%d/picture?kind=origin&grab=1" % (ILO, port), timeout=60)
        if st == 200 and len(img) > 10000:
            break
        log("      grab=1 第 %d 次没出图 (HTTP %s / %dB) → 4s 后重试" % (_try + 1, st, len(img)))
        time.sleep(4)
    ok &= chk("grab=1 出图", st == 200 and len(img) > 10000,
              "%d 字节" % len(img) + ("" if len(img) > 10000 else "  错误体: " + img[:140].decode("utf-8", "replace")))
    n_after = files_total(port)
    ok &= chk("grab 不落盘(files_total 不增)", n_after is not None and n_before == n_after,
              "%s→%s" % (n_before, n_after))
    return bool(ok), out


def start_pair(restart=True):
    py = r"D:\xspace\ultralytics_AOI\venv\Scripts\python.exe"
    d = r"D:\xspace\ultralytics_AOI"
    ps = (
        'cd %s; '
        'foreach($p in 10082,10083){ $c=Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue; '
        'if($c){ Stop-Process -Id $c.OwningProcess -Force } }; Start-Sleep 4; '
        '$sh=New-Object -ComObject WScript.Shell; '
        '$sh.Run("cmd /c cd /d %s && %s cam_finger_10082_work_v20.py > %s\\v5f.log 2>&1",0,$false) | Out-Null; '
        '$sh.Run("cmd /c cd /d %s && %s cam_surface_10083_work_v20.py > %s\\v5s.log 2>&1",0,$false) | Out-Null; '
        # 2026-10-08 实测: "Sleep 40 后单次探测" 会把慢绑定的那一路误报成 DOWN —— 连续两条部署日志出现
        #   "10082 -> up pid 7160 / 10083 -> DOWN", 而实际 20s 后 /storage 就 200 了(误判会误导现场排查)。
        #   改成轮询到两路都监听(或 150s 超时)再报**稳态**, 真 DOWN 时给出下一步。
        '$dl=(Get-Date).AddSeconds(150); $miss="x"; '
        'do { Start-Sleep -Seconds 5; $miss=""; foreach($p in 10082,10083){ '
        '$c=Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue; if(-not $c){ $miss="y" } } } '
        'while ($miss -ne "" -and (Get-Date) -lt $dl); '
        'foreach($p in 10082,10083){ $c=Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue; '
        '"$p -> " + $(if($c){"up pid " + $c.OwningProcess}else{"DOWN(150s 未监听: 看 v5f/v5s.log, 10083 可等保活拉起)"}) }'
    ) % (d, d, py, d, d, py, d)
    return remote(ps, wait=200, label="start")


def stop_pair():
    ps = ('foreach($p in 10082,10083){ $c=Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue; '
          'if($c){ Stop-Process -Id $c.OwningProcess -Force; "stopped $p" } }')
    return remote(ps, wait=60, label="stop")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--finger", default=os.path.expanduser("~/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v20.py"))
    ap.add_argument("--surface", default=os.path.expanduser("~/zmax/zmax_data/aoi_v4/cam_surface_10083_work_v20.py"))
    ap.add_argument("--pubdir", default="/home/ubuntu/zmax/zmax_data/aoi_v4/deliver/v6")
    ap.add_argument("--only", default="both", choices=["both", "10082", "10083"],
                    help="哪一路当验收判据(另一路仅报状态, 不参与成败与回滚)")
    ap.add_argument("--no-restart", action="store_true", help="只推文件+核对, 不动服务")
    ap.add_argument("--dry", action="store_true", help="只推文件+核对, 不重启不验收")
    a = ap.parse_args()

    pair = [(10082, a.finger, FILENAME_10082), (10083, a.surface, FILENAME_10083)]
    pair_ports = [p for p, _s, _n in pair]
    os.makedirs(a.pubdir, exist_ok=True)
    report = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "files": [], "verify": {}}

    # ① 拷进静态目录
    for _port, src, name in pair:
        if not os.path.exists(src):
            log("✗ 本地文件不存在: %s" % src)
            return 2
        dst = os.path.join(a.pubdir, name)
        subprocess.run(["cp", "-f", src, dst], check=True)
        log("① 已发布 %s (%d B, %s…)" % (name, os.path.getsize(dst), sha256(dst)[:8]))

    # ②备 备份现役 —— **必须在下载覆盖之前**(2026-09-30 踩坑: 原来备份放在下载之后 ⇒ .bak 记的是
    #   刚上线的新文件 ⇒ ⑥ 回滚=把新文件盖回自己(空操作) ⇒ "自动回滚"这条安全网一直是假的,
    #   而我会以为它兜住了。现在: 先备份、带时间戳(永不被后续覆盖)、回滚指定用这一份。
    _BK = time.strftime("%Y%m%d_%H%M%S")
    log("②备 备份现役(下载覆盖之前 · 标记 %s)" % _BK)
    remote("cd D:\\xspace\\ultralytics_AOI; foreach($f in '%s','%s'){ if(Test-Path $f)"
           "{ $t = $f + '.bak_%s'; Copy-Item $f $t -Force; \"backup $f -> $t\" } else { \"no such $f\" } }"
           % (pair[0][2], pair[1][2], _BK), wait=60, label="backup")

    # ② 工控机下载 + SHA256 核对
    dl = ("cd D:\\xspace\\ultralytics_AOI; "
          "foreach($f in '%s','%s'){ iwr \"http://%s:%d/v6/$f\" -OutFile $f -UseBasicParsing -TimeoutSec 60 }; "
          "Get-FileHash %s,%s -Algorithm SHA256 | ForEach-Object { $_.Hash + '  ' + (Split-Path $_.Path -Leaf) }"
          ) % (FILENAME_10082, FILENAME_10083, HOST, 8794, FILENAME_10082, FILENAME_10083)
    out = remote(dl, wait=150, label="download")
    if "TIMEOUT" in out or "ENQUEUE_FAIL" in out:
        log("✗ 通道没回执(%s) —— 工控机上的 ZMAX_Agent 任务没跑? " % out)
        return 3
    ok_hash = True
    for _port, src, name in pair:
        want = sha256(os.path.join(a.pubdir, name))
        line = next((l for l in out.splitlines() if name in l), "")
        got = line.strip().split()[0].upper() if line.strip() else ""
        same = got == want
        ok_hash &= same
        log("② %s SHA256 %s (%s)" % (name, "一致" if same else "不一致!", got[:12] or "无回执"))
        report["files"].append({"name": name, "sha256_local": want, "sha256_remote": got, "same": same})
    if not ok_hash:
        log("✗ 哈希不一致 → 中止, 产线一字未动")
        return 4
    if a.dry:
        log("--dry: 到此为止 (文件已就位, 服务未动)")
        return 0

    # ③ (已废弃) 备份不在这里做 —— 下载之前已备份, 见 ②备; 在下载之后备份等于备份新文件

    if a.no_restart:
        log("--no-restart: 文件已换, 服务未重启")
        return 0

    # ④ 停旧起新 (10082/10083)
    log("④ 重启 10082/10083 上的 v6")
    log("   " + start_pair().strip().replace("\n", " / "))

    # ⑤ 验收
    # ⚠️ 2026-09-30 踩坑: 只该用**本轮真换了文件**的那一路当判据。原来两路都当判据 ⇒
    #    另一台相机自己抽风(10083 grab 出 46 字节)会把本轮的修复误判成失败 ⇒ 触发回滚,
    #    而回滚会把**本轮新文件**换成本轮之前的内容(把刚修好的版本滚掉)。没换文件的那路只报状态。
    # 判据只看**命令行显式指定的那一路**(--only): ②的哈希是"传输完整性", 下载完必然一致,
    # 拿它推断"文件有没有变"永远为空(2026-09-30 踩过: 于是 10082 的失败被降级成"仅报状态")。
    changed = {p for p in pair_ports if a.only in ("both", str(p))}
    ok_all = True
    for port, _src, name in pair:
        ok, detail = verify(port)
        report["verify"][str(port)] = detail
        if port not in changed:
            log("⑤ %d (本轮未换文件, 仅报状态): %s" % (port, "OK" if ok else "⚠️ 异常(与本轮改动无关)"))
            continue
        ok_all &= ok
        log("⑤ %d %s" % (port, "\n     ".join(detail)))
    log("⑤ 验收结果: %s%s" % ("全部通过 ✅" if ok_all else "有失败 ❌",
                            "" if changed else " (本轮无文件变化, 无判据)"))

    # ⑤b 🔴 2026-10-08: 重启会把取像参数打回程序默认 ⇒ "按点位切档"不持久, 点2 会因太暗(20000)而行带乱跳、
    #     判据图整幅变(老倪现场「判据图还是总变」)。这里把上次**已生效并落盘**的档位补回去。
    try:
        import json as _json
        import urllib.request as _ur
        _pf = os.path.expanduser("~/zmax/zmax_data/aoi_v4/cam_param_persist.json")
        _d = _json.load(open(_pf, encoding="utf-8")) or {}
        for _pt in sorted({int(p) for p in pair_ports if a.only in ("both", str(p))}):
            _e = _d.get(str(int(_pt))) or {}
            _q = []
            if _e.get("exposure_us"):
                _q.append("exposure=%g" % _e["exposure_us"])
            if _e.get("gain_db"):
                _q.append("gain=%g" % _e["gain_db"])
            if not _q:
                log("⑤b %d 无落盘档位 ⇒ 跳过复原(相机保持程序默认)" % _pt)
                continue
            with _ur.urlopen("http://192.168.23.23:%d/param?%s" % (int(_pt), "&".join(_q)), timeout=15) as _r:
                _j = _json.loads(_r.read().decode("utf-8", "ignore"))
            log("⑤b %d 复原取像档位 %s ⇒ applied=%s / now=%s"
                % (_pt, _e.get("profile") or "自定义", _j.get("applied"), _j.get("now")))
    except FileNotFoundError:
        log("⑤b 无档位落盘文件 ⇒ 跳过复原")
    except Exception as _e:
        log("⑤b 档位复原跳过(不影响本轮验收): %r" % (_e,))

    # ⑥ 失败 → 回滚
    if not ok_all:
        log("⑥ 验收失败 → 回滚到本次部署前的备份 (.bak_%s)" % _BK)
        remote("cd D:\\xspace\\ultralytics_AOI; foreach($f in '%s','%s'){ $t = $f + '.bak_%s'; "
               "if(Test-Path $t){ Copy-Item $t $f -Force; \"rolled back $f <- $t\" } else { \"NO BACKUP(该文件本轮之前不存在) $f\" } }"
               % (FILENAME_10082, FILENAME_10083, _BK), wait=60, label="rollback")
        log("   " + start_pair().strip().replace("\n", " / "))
        for port, _src, _name in pair:
            ok, detail = verify(port, test_capture=False)
            log("   回滚后 %d: %s" % (port, "OK" if ok else "仍异常"))

    with open(os.path.join(ROOT, "reports", "aoi_deploy_log.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    return 0 if ok_all else 5


if __name__ == "__main__":
    sys.exit(main())
