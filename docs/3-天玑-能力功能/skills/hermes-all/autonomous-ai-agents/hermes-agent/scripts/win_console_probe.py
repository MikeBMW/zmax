"""Probe for phantom console-window flashes on Windows.

Run it, trigger the suspected action (a few Hermes `terminal` calls, a burst of
normal work, whatever the user says makes the black box appear), then read the log.

    python win_console_probe.py 60 C:/Users/<you>/AppData/Local/Temp/flash.log

Pass a NATIVE forward-slash path for the log: the bundled python resolves a bare
MSYS `/tmp/...` against the drive root of its cwd and dies with FileNotFoundError.

Record types in the log:
    W ...  a VISIBLE console-class / Windows Terminal window appeared -> real flash
    E ...  a console window SHOW event -> catches flashes shorter than one sample
    P ...  a new process appeared, with its parent's name -> who launched it
    DONE   probe finished (with the number of window samples taken)

An empty result is a real answer: nothing on this desktop drew a console window,
so the flash came from elsewhere (UAC / secure desktop, another session, or a
window that was never created as a console).
"""
import ctypes
import sys
import threading
import time
from ctypes import wintypes

USER32 = ctypes.WinDLL("user32", use_last_error=True)
KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
TH32CS_SNAPPROCESS = 0x00000002
CONSOLE_HINTS = ("console", "cascadia", "pseudo")


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class Probe:
    def __init__(self, seconds, out_path):
        self.end = time.time() + float(seconds)
        self.log = open(out_path, "w", encoding="utf-8", buffering=1)
        self.lock = threading.Lock()
        self.samples = 0
        # Seed with what is already on screen: without this the user's own terminal
        # (and its ConPTY helper) is logged as the first "flash" of every run.
        self.seen_windows = self._live_console_windows()
        self.seen_procs = self._procs()

    def _write(self, line):
        with self.lock:
            self.log.write(line + "\n")

    # --- window side -------------------------------------------------------
    @staticmethod
    def _windows():
        found = []

        def cb(hwnd, _lparam):
            pid = wintypes.DWORD()
            USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            cls = ctypes.create_unicode_buffer(300)
            USER32.GetClassNameW(hwnd, cls, 300)
            title = ctypes.create_unicode_buffer(300)
            USER32.GetWindowTextW(hwnd, title, 300)
            found.append((int(hwnd), pid.value, bool(USER32.IsWindowVisible(hwnd)),
                          cls.value, title.value))
            return True

        USER32.EnumWindows(ENUM_PROC(cb), 0)
        return found

    def _watch_windows(self):
        while time.time() < self.end:
            self.samples += 1
            for hwnd, pid, visible, cls, title in self._windows():
                if not visible or hwnd in self.seen_windows:
                    continue
                low = cls.lower()
                if any(hint in low for hint in CONSOLE_HINTS):
                    self.seen_windows.add(hwnd)
                    self._write("%s W pid=%s class=%s title=%r" % (
                        time.strftime("%H:%M:%S"), pid, cls, title))
            time.sleep(0.001)

    # --- event side --------------------------------------------------------
    @staticmethod
    def _live_console_windows():
        """hwnds of console-class windows already visible at startup."""
        live = set()
        for hwnd, _pid, visible, cls, _title in Probe._windows():
            if visible and any(hint in cls.lower() for hint in CONSOLE_HINTS):
                live.add(hwnd)
        return live

    def _watch_show_events(self):
        """Log console windows the moment they are shown, even sub-millisecond ones.

        Sampling can miss a window that is created, shown and hidden inside one tick;
        EVENT_OBJECT_SHOW cannot. Set up defensively — any failure here leaves pure
        sampling, which is still a valid answer.
        """
        EVENT_OBJECT_SHOW = 0x8002
        WINEVENT_OUTOFCONTEXT = 0x0000
        WINEVENT_SKIPOWNPROCESS = 0x0002
        callback_type = ctypes.WINFUNCTYPE(
            None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
            wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)

        def _cb(_hook, _event, hwnd, _idobj, _idchild, _thread, _ms):
            try:
                cls = ctypes.create_unicode_buffer(300)
                USER32.GetClassNameW(hwnd, cls, 300)
                if not any(hint in cls.value.lower() for hint in CONSOLE_HINTS):
                    return
                pid = wintypes.DWORD()
                USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                title = ctypes.create_unicode_buffer(300)
                USER32.GetWindowTextW(hwnd, title, 300)
                self._write("%s E pid=%s visible=%s class=%s title=%r" % (
                    time.strftime("%H:%M:%S"), pid.value,
                    bool(USER32.IsWindowVisible(hwnd)), cls.value, title.value))
            except Exception:
                pass

        self._hook_cb = callback_type(_cb)  # keep a reference or the callback is GC'd
        try:
            hook = USER32.SetWinEventHook(
                EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, None, self._hook_cb, 0, 0,
                WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
            if not hook:
                return
            msg = wintypes.MSG()
            while time.time() < self.end:
                while USER32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    USER32.TranslateMessage(ctypes.byref(msg))
                    USER32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.005)
        except Exception:
            return  # sampling still covers the run

    # --- process side ------------------------------------------------------
    @staticmethod
    def _procs():
        snap = KERNEL32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        table = {}
        ok = KERNEL32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            table[entry.th32ProcessID] = (entry.szExeFile, entry.th32ParentProcessID)
            ok = KERNEL32.Process32NextW(snap, ctypes.byref(entry))
        KERNEL32.CloseHandle(snap)
        return table

    def _watch_procs(self):
        while time.time() < self.end:
            current = self._procs()
            for pid, (name, ppid) in current.items():
                if pid in self.seen_procs:
                    continue
                parent = current.get(ppid) or self.seen_procs.get(ppid)
                self._write("%s P %-22s pid=%-7s ppid=%-7s parent=%s" % (
                    time.strftime("%H:%M:%S"), name, pid, ppid,
                    parent[0] if parent else "?"))
            self.seen_procs = current
            time.sleep(0.03)

    def run(self):
        threads = [threading.Thread(target=self._watch_windows, daemon=True),
                   threading.Thread(target=self._watch_show_events, daemon=True),
                   threading.Thread(target=self._watch_procs, daemon=True)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self._write("DONE window_samples=%d" % self.samples)
        self.log.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    Probe(sys.argv[1], sys.argv[2]).run()
    print("wrote", sys.argv[2])
