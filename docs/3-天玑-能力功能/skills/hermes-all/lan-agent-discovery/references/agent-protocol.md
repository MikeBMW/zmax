# Agent-to-agent tool calling over LAN

HTTP tool-calling protocol for two agents on the same LAN. Use when both machines run a real agent and each exposes a small JSON-RPC-style HTTP API.

## Endpoints

- `GET /v1/health` returns `{"ok": true, "agent_id": "..."}`
- `GET /v1/tools` returns the tool list the caller may invoke
- `POST /v1/call` performs one tool and returns the result or a typed error

## Call request body

```json
{
  "from": "agent-a",
  "to": "agent-b",
  "tool": "run_command",
  "args": {"cmd": "ipconfig", "timeout": 20},
  "req_id": "req-001",
  "nonce": "nonce-123",
  "ttl_sec": 60
}
```

| field | meaning |
|---|---|
| from, to | sender / receiver agent ids |
| tool | name of the tool on the receiver |
| args | tool arguments, must match `parameters` in `/v1/tools` |
| req_id | client-chosen; used to match the answer |
| nonce | one-time random; prevents replay |
| ttl_sec | server must refuse to execute after this many seconds |

## Call response body

```json
{
  "req_id": "req-001",
  "from": "agent-b",
  "result": {"status": "ok", "stdout": "...", "code": 0}
}
```

or

```json
{
  "req_id": "req-001",
  "from": "agent-b",
  "result": null,
  "error": {
    "code": "tool_not_found",
    "message": "...",
    "retryable": false
  }
}
```

## Rules

- Authenticate every request with `Authorization: Bearer <api_key>`. One key per machine; never put the key in the URL or in a public log.
- Server must not re-execute a `req_id` with different `args` (idempotency guard).
- Retry with exponential backoff (1s, 2s, 4s) for network errors, up to 2-3 attempts. Follow `error.retryable`; retry tool-level failures only if the caller marks them retryable.
- Per-call timeout 30s. Larger results should be chunked or truncated before sending.
- Tool parameters must match the schema in `/v1/tools`; an unknown `tool` name returns `tool_not_found` and must not be treated as a transient error.
