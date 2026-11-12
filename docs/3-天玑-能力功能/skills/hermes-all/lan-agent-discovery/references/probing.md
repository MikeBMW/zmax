# Probing a remote host on the LAN

Order and what to record after each step. Run from the machine that owns the tools (here: this Windows box) via the terminal.

## Order

1. `ping <target>` - record rc and reply count. Outcome: reachable, or not (subnet/off/ICMP blocked).
2. HTTP probe on candidate ports: 80, 8000, 8080, 3000, 5000, 9000, 8888, 7860. Record: port, HTTP status (or timeout/error), and the `Server` header.
3. Classify the interface. See below.
4. Choose the transport. If an API, call it. If a proxy, either route through it or add a backend on the target and call that.

## Classification

| What you see | Meaning | Next step |
|---|---|---|
| JSON API answers (`/v1/call`, `/health`) | Agent API | Call it with the agent-protocol |
| 403 on unknown paths; forwards unknown traffic | Proxy (tinyproxy, nginx, haproxy, mitmproxy) | Do not guess an API. Route through it or add a backend |
| HTML / login page | Web UI with auth | Find the gate before using |
| Only ICMP answers; no port open | N/A | Nothing to call. Report the gap |

## Notes

- The `Server` header is the single most valuable read. It tells you proxy vs runtime vs app vs WAF before you guess the next endpoint.
- A timeout is not proof the port is dead; record it as 'no answer on probe' and move on.
- tinyproxy returns 403 on unknown paths and requires a valid HTTP method; it is a forward proxy, not an agent API.
