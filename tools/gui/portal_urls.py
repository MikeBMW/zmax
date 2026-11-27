"""产品服务 · 总索引 URL 解析 (唯一真源 / 纯 stdlib, 不依赖 Qt)

2026-11-27 老倪: 「控制台的总索引 产品服务, 应该打开 8888 服务」。

原来 studio.py / simulink_module.py 各自硬编码 ``http://127.0.0.1:8788/``:
Windows 工位机上没有 framework 网关(zmax-framework.service 是 Linux 单元),
8788 必然不可达 ⇒ 点「产品服务」只弹一句 systemctl 提示, 窗口一个都不开。
而中枢 550C 的 8888 静态站才是现在真在跑的服务总索引。

改为按候选链逐个 TCP 探测, 取第一个通的:
    1. $ZMAX_PORTAL_URL                          (显式指定, 最高优先)
    2. http://127.0.0.1:8788/                    (本机 framework 总索引, Linux 上就是它)
    3. hub:8888                                  (中枢服务站总索引: 10.163.149.123 / 192.168.23.70)
    4. 登记主机 :8788                            (config/ui/dashboard_hosts.json 里的机器)
    5. http://127.0.0.1:8799/                    (生产数据大屏, 最后回退)

主机清单来源(按序): $ZMAX_HUB_URL / $ZMAX_HUB > config/ui/dashboard_hosts.json >
内置 DEFAULT_HUBS。登记主机里的地址可带 scheme, 不带则按 http://<h>:<port>/ 拼。
"""

from __future__ import annotations

import json
import os
import socket
from urllib.parse import urlsplit

PORTAL_PORT = 8788          # 本机 framework 网关 (总索引)
HUB_PORT = 8888             # 中枢服务站静态站 (现在的总索引)
DASHBOARD_PORT = 8799       # 生产数据大屏 (回退)

# 中枢候选: 办公网地址 + 产线网地址
DEFAULT_HUBS = ("10.163.149.123", "192.168.23.70")
# 登记主机兜底 (与 studio.py 历史行为一致)
DEFAULT_HOSTS = ("192.168.23.50",)

HOSTS_FILE = os.path.join("config", "ui", "dashboard_hosts.json")


def _root() -> str:
    return os.environ.get("ZMAX_ROOT") or os.path.expanduser("~/zmax")


def _read_hosts_file():
    """读 config/ui/dashboard_hosts.json —— 兼容 {"hosts": [...]} 与裸数组两种形态。"""
    path = os.path.join(_root(), HOSTS_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        seq = (raw.get("hosts") if isinstance(raw, dict) else raw) or []
        return [str(h).strip() for h in seq if str(h).strip()]
    except Exception:
        return []


def _as_url(host: str, port: int) -> str:
    h = host.strip().rstrip("/")
    if not h:
        return ""
    if h.startswith(("http://", "https://")):
        split = urlsplit(h)
        # 带了端口就尊重它, 否则补默认端口
        if split.port:
            return h + "/"
        return "%s://%s:%d/" % (split.scheme, split.hostname, port)
    return "http://%s:%d/" % (h, port)


def hubs():
    """中枢主机候选(去重保序)。"""
    env = os.environ.get("ZMAX_HUB_URL") or os.environ.get("ZMAX_HUB") or ""
    seq = [h for h in env.replace(";", ",").split(",") if h.strip()]
    seq += _read_hosts_file() or list(DEFAULT_HUBS)
    out = []
    for h in seq:
        u = _as_url(h, HUB_PORT)
        if u and u not in out:
            out.append(u)
    return out


def hosts():
    """登记主机(:8788)候选(去重保序)。"""
    seq = _read_hosts_file() or list(DEFAULT_HOSTS)
    out = []
    for h in seq:
        u = _as_url(h, PORTAL_PORT)
        if u and u not in out:
            out.append(u)
    return out


def candidates():
    """按优先级返回总索引候选 URL 列表(已去重)。"""
    first = [os.environ.get("ZMAX_PORTAL_URL", ""), _as_url("127.0.0.1", PORTAL_PORT)]
    seq = first + hubs() + hosts() + [_as_url("127.0.0.1", DASHBOARD_PORT)]
    out = []
    for u in seq:
        u = (u or "").strip()
        if u and u not in out:
            out.append(u)
    return out


def tcp_ok(url: str, timeout: float = 0.8) -> bool:
    """只测 TCP 端口通不通 —— 不看 ICMP(Windows 上 WLAN 会抢走产线网段路由, ping 通 TCP 全闭)。"""
    if not url:
        return False
    try:
        s = urlsplit(url)
        host = s.hostname or ""
        port = s.port or (443 if s.scheme == "https" else 80)
        if not host:
            return False
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def resolve(timeout: float = 0.8):
    """返回 (url, tried)。全都不通时 url=None, tried 是探测过的完整链(用于报错)。"""
    tried = []
    for u in candidates():
        tried.append(u)
        if tcp_ok(u, timeout=timeout):
            return u, tried
    return None, tried


def fallback() -> str:
    """一个都不通时仍然给出第一个候选, 让调用方照原样尝试/显示地址。"""
    cands = candidates()
    return cands[0] if cands else "http://127.0.0.1:%d/" % PORTAL_PORT


def describe() -> str:
    """给状态栏/日志用的一句话: 当前会打开哪个总索引、为什么。"""
    url, tried = resolve()
    if url:
        idx = tried.index(url)
        why = "首选" if idx == 0 else "回退链第 %d 个" % (idx + 1)
        return "产品服务总索引 → %s (%s)" % (url, why)
    return "产品服务总索引不可达, 已试: %s" % " → ".join(tried)


if __name__ == "__main__":
    print(describe())
