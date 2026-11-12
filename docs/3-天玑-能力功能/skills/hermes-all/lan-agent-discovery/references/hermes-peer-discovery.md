# Finding a sibling Hermes instance on the LAN

The sibling agent's gateway binds `127.0.0.1`, so discovery happens in two phases: find the host on the network, then prove the agent over SSH.

## Phase 1 — find the host (Windows git-bash, stdlib only)

```python
import socket, concurrent.futures as cf
net = "192.168.1."
ports = [22, 80, 443, 3389, 5900, 8000, 8019, 8080, 8791, 8793, 8797, 8888, 39061, 39071, 10082]

def probe(a):
    ip, p = a
    s = socket.socket(); s.settimeout(0.4)
    try:
        s.connect((ip, p)); return (ip, p)
    except Exception:
        return None
    finally:
        s.close()

hit = {}
with cf.ThreadPoolExecutor(512) as ex:
    for r in ex.map(probe, [(net + str(i), p) for i in range(2, 255) for p in ports]):
        if r: hit.setdefault(r[0], []).append(r[1])
for ip in sorted(hit, key=lambda x: int(x.split('.')[-1])):
    print(ip, sorted(hit[ip]))
```

Also ICMP-sweep and resolve names — hosts that answer ping but no probed port are usually phones/IoT, and naming them saves a wrong-target claim:

```bash
for i in $(seq 2 254); do ping -n 1 -w 300 192.168.1.$i | grep -q 'TTL=' && echo ".$i alive"; done
for i in 2 3 4 5; do ping -a -n 1 -w 500 192.168.1.$i | head -2 | tail -1; done
```

Confirm a host's identity from its HTTP titles/services (`<title>` of each page, `Server:` header, proxy vs JSON API) before calling it the target.

## Phase 2 — password SSH from Windows with no sshpass/paramiko

The password can only be typed, so drive an interactive pty session and answer the prompt with `submit` (a bare `\n` is not a line terminator on a Windows pty):

1. `terminal(command="ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no ubuntu@<ip>", background=true, pty=true)`
2. `process_manage(action="poll", session_id=...)` until `'s password:` appears.
3. `process_manage(action="submit", data="<password the user supplied>")` — ask the user if not given; never guess or try a remembered password from a different host.
4. Poll for the shell prompt, then submit one compact command batch (chain with `;` and `echo '=== MARKER ==='` so the output is readable in the captured tail). Poll again to read it.
5. Finish with `submit("exit")` so no session is left hanging.

## Phase 3 — prove the agent is live

```bash
systemctl is-active hermes-gateway
systemctl show hermes-gateway -p MainPID -p ExecStart --value
cat ~/.hermes/gateway_state.json          # hermes_home, code_version, platforms.<x>.state, updated_at
ss -ltnp | grep -E ':(8019|35781)\b'      # expect 127.0.0.1 only
ls -lt ~/.hermes/sessions | head -4
stat -c '%y %n' ~/.hermes/state.db ~/.hermes/memories/MEMORY.md
~/.hermes/hermes-agent/.hermes/bin/hermes --version
```

Read `gateway_state.json` for `hermes_home`: a service can run under another unix user and write state into the directory you are looking at, so the home path in that file is the authoritative brain, not `~`.

## What to report

- host and name, gateway state (active/connected platforms), code version vs this machine, freshness of `state.db` / `MEMORY.md`.
- if both instances have the same messaging account connected, say so as a risk in one line and ask which side should own it.
