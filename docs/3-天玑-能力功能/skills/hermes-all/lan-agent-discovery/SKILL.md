---
name: lan-agent-discovery
description: "Find a remote device on the LAN and retrieve the result."
version: 1.0.0
author: "Hermes Mini4 (Upstage AI)"
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [network, lan, discovery]
    related_skills: [blocked-page-recovery]
---

# LAN agent discovery

Given a target machine on the local network, verify it is reachable, find what service it is offering, and get the requested result from it. Use for the user's recurring 'find / see / connect to something on the same Wi-Fi' and 'make two agents talk on the LAN' requests.

## When to Use

- The user wants to find, see, or connect to a device or service on the same Wi-Fi / local network.
- The user wants two agents (or this agent and another process) to exchange tool results over the LAN.
- The user gives a target IP or hostname and asks for 'the result' from it.

## Always-on rules

1. **Act on a clear goal. No questions.** When the user says 'just do it', 'don't ask me', or 'I only want the result', do not open clarifying questions and do not pad with a menu of options. Probe, report only what you actually read, and give the smallest verified path that closes the gap. Ask only if the target and goal are genuinely ambiguous.
2. **Result first, process second, options last.** Lead with the finding: reachable or not; which service answered and on what port; is it an agent API or a proxy. Then the one-line next step. Do not lead with procedure, with lists of alternatives, or with 'there are several paths'.
3. **Reported facts only.** Never claim a remote agent called, a file was read, or an API returned something you did not observe. Name the blocker plainly and give the smallest verified path that closes it.
4. **Capability boundary.** I only have tools that run in this environment. I cannot execute code or call tools on another machine through the chat channel. If a result requires code on a machine I cannot reach, say so exactly and give the smallest verified path to run it there, or the exact interface I can call from here.
5. **One question per probe.** Reachability first, then service presence, then interface. Switch protocol only after the interface is confirmed.

## Procedure, in order

1. **Reach the host.** Ping it from this machine's terminal. rc 0 with replies = reachable; otherwise not on the subnet, off, or ICMP blocked.
2. **Find what is listening.** Probe candidate ports (working list: 80, 8000, 8080, 3000, 5000, 9000, 8888, 7860). Read the `Server` response header; it names the software (for example tinyproxy/1.11.1).
3. **Classify the interface.**
   - Returns a JSON agent API (`/v1/call`, `/health`, `/v1/tools`): it is an agent API. Use the agent protocol.
   - Returns 403 for unknown paths and forwards unknown traffic (tinyproxy, nginx, haproxy, mitmproxy): it is a proxy. Do not treat it as an agent call endpoint; do not guess an API on a proxy.
   - Returns HTML or a login wall: it may be a web UI with auth. Look for the gate before guessing.
4. **Get the result through the real interface.**
   - If the remote machine exposes an agent API: call it directly.
   - If it only offers a proxy: the proxy is not a result. Either route through it (if it can forward) or add a small result endpoint on the target machine (a running HTTP service that answers a defined request), then call that endpoint from here. An unauthenticated proxy with a 403 wall is a blocker, not an agent result — say so and give the exact endpoint to add on the target.
   - Authentication required: ask for it, then proceed.

## Target is a sibling agent instance (same product, e.g. Hermes)

A sibling instance usually answers on **no network port even while it is running**: its gateway binds loopback only. Port-scan silence is not absence — confirm over SSH before reporting it dead.

1. **Sweep the subnet for live hosts, not just open ports.** ICMP sweep plus a TCP probe of candidate ports; then resolve names (`ping -a`, `nbtstat -A`, reverse DNS). Phones, IoT bridges and routers answer ICMP and one low port — they are not the target. Compare against the user's description ('the 4060 box', 'the production host') before claiming a match.
2. **Log in and check the service, not the port.** `systemctl is-active hermes-gateway`, `cat ~/.hermes/gateway_state.json`, `ss -ltnp | grep -E 'hermes|python'`. The state file names the real `hermes_home`, `code_version`, the listening pid and each platform's state — that is what identifies which brain is live.
3. **Report identity, version, platform state, freshness.** version (`hermes --version`), gateway state, which messaging accounts are connected, and the mtime of `state.db` / `memories/MEMORY.md`. An older code version or an old memories mtime means a divergent copy, not the same brain.

## Pitfalls

- Do not attach an HTTP agent protocol to a proxy. A 403 from a proxy is not a missing API; it is a missing path or an access rule. Read the Server header first.
- A port that timed out is not necessarily dead. A firewall can block it while 8888 answers. Probe repeatedly and record what actually answered.
- **Silent TCP timeout while ICMP answers is not proof the firewall rules are wrong.** Seen live: ping 31 ms, every TCP port timed out, the host's own `ss -ltnp` showed sshd listening on 0.0.0.0:22, and minutes later all ports were open with nothing changed — an upstream/edge drop, not a misconfiguration. Get an outside vantage before telling the user to edit anything: `curl -s -H 'Accept: application/json' 'https://check-host.net/check-tcp?host=<ip>:<port>&max_nodes=3'` then poll `https://check-host.net/check-result/<request_id>`. Three continents timing out = upstream drop (retry later, say so plainly); only you timing out = your egress.
- Pinger reachability is not an API. ICMP yes does not mean any service will answer.
- Do not dress up partial observation as a result. If you only saw a proxy on 8888 and no credentials, report it as a proxy, not as the agent's output.
- A loopback-bound gateway is invisible to any scan. Hermes listens on `127.0.0.1:<random high port>`, so a full 1-65535 scan of a host that runs a live agent returns only its web services. Never conclude 'no agent here' from a scan; SSH in and read `gateway_state.json`.
- Two gateways attached to the same messaging account both answer the same inbound message. File/memory sync does not fix that — flag it to the user as a routing decision (which side should own the account) instead of silently leaving both connected.

## Support files

- `references/agent-protocol.md` — HTTPS agent-to-agent calling protocol (endpoints, JSON schemas, auth, retry, idempotency).
- `references/probing.md` — LAN probe order and what to record at each step.
- `scripts/lan-probe.py` — reusable probe: ping a target and probe its common HTTP ports, printing status and the Server header.
- `references/ssh-setup-windows.md` — Windows OpenSSH Server enable/start/firewall; the "running result endpoint" when the target is Windows and only a shell is available.
- `references/hermes-peer-discovery.md` — subnet sweep snippet, password SSH login from Windows without sshpass/paramiko (background pty + submit), and the commands that prove a sibling Hermes gateway is live.
