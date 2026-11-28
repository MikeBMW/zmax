#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WinEvent 窗口探针 —— 数清「谁在弹窗」而不是猜。

用法:
    python winhook.py [秒数] [精确标题]
      python winhook.py 30                     # 记全部顶层窗口
      python winhook.py 30 Z-MAX_Console       # 只记标题精确等于它的

为什么用 python 不用 powershell:
    Add-Type 里的委托被 GC 回收后回调落到野指针, powershell.exe 会以 0xc000041d /
    BEX64 崩溃, WerFault 弹出「Windows PowerShell 已停止工作」—— 排查工具本身
    变成了新的弹窗源。

输出:
    <scratch>/winhook.log  每行一个事件: 时间 ev=0x8000/0x8002 hwnd pid exe [class] title size
    末尾 summary: 按 title 统计 show(0x8002) 次数 + 唯一 hwnd 数
        —— 关键判据: 事件数 == 唯一 hwnd 数  ⇒ 是真的几百个窗口
                     事件数 >> 唯一 hwnd 数 ⇒ 同一个窗口反复 show
        ⚠ 统计必须按 title 精确匹配, 不要 grep 整行: 进程名每行都有,
          会把 505 个窗口虚报成 506(或多算内部 OleMainThreadWnd 之类的辅助窗)。
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time
import collections

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

WINEVENTPROC = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND,
                                  ctypes.c_long, ctypes.c_long, wt.DWORD, wt.DWORD)
EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0x0000

user32.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, WINEVENTPROC,
                                   wt.DWORD, wt.DWORD, wt.DWORD]
user32.SetWinEventHook.restype = wt.HANDLE
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetParent.argtypes = [wt.HWND]
user32.GetParent.restype = wt.HWND
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
user32.GetWindow.restype = wt.HWND
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]

kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                                ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]


def proc_name(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not h:
        return ''
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value)
        return ''
    finally:
        kernel32.CloseHandle(h)


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    want_title = sys.argv[2] if len(sys.argv) > 2 else None
    out = os.path.join(os.environ.get('TMPDIR', os.path.expanduser('~')), 'winhook.log')
    log = open(out, 'w', encoding='utf-8')
    log.write('hook start %s dur=%.0fs title_filter=%r\n'
              % (time.strftime('%H:%M:%S'), dur, want_title))
    log.flush()

    seen = set()
    shows = collections.Counter()      # title -> show 次数
    hwnds = collections.defaultdict(set)

    def cb(hook, event, hwnd, idObject, idChild, thr, tm):
        try:
            if not hwnd or idObject != 0 or idChild != 0:
                return                      # 只要顶层窗口, 不要子控件
            if user32.GetParent(hwnd):
                return
            if user32.GetWindow(hwnd, 4):   # GW_OWNER
                return
            t = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, t, 512)
            title = t.value
            if want_title is not None and title != want_title:
                return
            c = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, c, 256)
            pid = wt.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            key = (event, hwnd, title)
            if key in seen:
                return
            seen.add(key)
            if event == EVENT_OBJECT_SHOW:
                shows[title] += 1
                hwnds[title].add(hwnd)
            r = wt.RECT()
            size = ''
            if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                size = '%dx%d@(%d,%d)' % (r.right - r.left, r.bottom - r.top, r.left, r.top)
            log.write('%s ev=0x%x hwnd=%d pid=%d %s [%s] title=%r %s\n'
                      % (time.strftime('%H:%M:%S'), event, hwnd, pid.value,
                         proc_name(pid.value), c.value, title, size))
            log.flush()
        except Exception as exc:            # noqa: BLE001
            try:
                log.write('cb error %r\n' % (exc,))
                log.flush()
            except Exception:
                pass

    keep = WINEVENTPROC(cb)                 # 必须持有引用, 否则被 GC 后回调野指针崩溃
    h1 = user32.SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, None, keep,
                                0, 0, WINEVENT_OUTOFCONTEXT)
    h2 = user32.SetWinEventHook(EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE, None, keep,
                                0, 0, WINEVENT_OUTOFCONTEXT)

    msg = wt.MSG()
    end = time.time() + dur
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.005)

    log.write('\n--- summary (%s) ---\n' % time.strftime('%H:%M:%S'))
    for title, n in shows.most_common():
        log.write('  show=%-4d unique_hwnd=%-4d title=%r  %s\n'
                  % (n, len(hwnds[title]), title,
                     '真·多个窗口' if n == len(hwnds[title]) else '同一窗口反复 show'))
    log.close()
    print('log:', out)
    print(open(out, encoding='utf-8').read()[-1200:])


if __name__ == '__main__':
    main()
