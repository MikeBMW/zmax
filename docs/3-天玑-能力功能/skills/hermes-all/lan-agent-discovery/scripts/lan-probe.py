#!/usr/bin/env python3
"""Quick reachability + HTTP probe for a LAN target.

Usage:
    python3 lan-probe.py <target-ip> [port...]

Prints ping result, then for each port: HTTP status, Server header, and a
body snippet. If the target does not answer ICMP, it still probes ports.
"""

import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_PORTS = [80, 8000, 8080, 3000, 5000, 9000, 8888, 7860]


def ping(host):
    for cmd in (["ping", "-n", "1", host], ["ping", "-c", "1", host]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            if r.returncode == 0:
                return True, (r.stdout or "") + (r.stderr or "")
        except Exception:
            continue
    return False, ""


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            body = r.read(160)
            server = r.headers.get("Server", "")
            return True, "HTTP %s  Server=%s  body[:80]=%r" % (
                r.status, server, body)
    except urllib.error.HTTPError as e:
        body = e.read(40)
        server = e.headers.get("Server", "")
        return True, "HTTPError %s  Server=%s  body[:40]=%r" % (
            e.code, server, body)
    except Exception as e:
        return False, type(e).__name__ + " " + str(e)[:50]


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "192.168.43.181"
    ports = sys.argv[2:] or list(DEFAULT_PORTS)

    ok, out = ping(target)
    print("PING", target, "reachable" if ok else "no-response")
    print((out or "").strip()[-300:])

    for port in ports:
        ok, text = fetch("http://%s:%d/" % (target, port))
        print("PORT %d %s" % (port, text))


if __name__ == "__main__":
    main()
