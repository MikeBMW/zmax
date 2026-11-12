---
name: ssh-setup-windows
description: >
  Windows result backend for a remote LAN agent. Procedure to enable/start
  OpenSSH Server, open the firewall, and verify the endpoint so a remote
  machine can SSH in and return command results. Companion to the
  lan-agent-discovery umbrella (Procedure step 4 "get the result").
platforms:
  - windows
---

# Windows OpenSSH result backend

When a remote Windows machine exposes no HTTP agent API, the typical "result
endpoint" is an interactive/command SSH interface. This reference is the
verified procedure to make a Windows machine accept that interface.

## When to use

1. LAN probe found a Windows machine (reachable, port 22 closed / no agent API).
2. You want "the result" of running a command on that machine.
3. Plan: enable OpenSSH Server on the target, auto-start it, open its firewall
   port, then SSH from here and run the result command.

## Procedure

1. **Enable OpenSSH Server capability** (requires the capability source to be
   reachable):

   ```powershell
   Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
   ```

   If the normal `-Online` source is unreachable (no internet / blocked
   Windows Update), resolve a source first: a mounted Windows image, a network
   share of the component store, or the GitHub `OpenSSH-Win64` package. Do not
   treat a 180-second timeout as instant success.

2. **Start the service and set auto-start:**

   ```powershell
   Set-Service -Name sshd -StartupType Automatic
   Start-Service sshd
   ```

3. **Open the firewall. Do not guess the display group by name.** Enumerate
   first, then enable the matching rule:

   ```powershell
   Get-NetFirewallRule | Where-Object { $_.DisplayName -like '*SSH*' -or $_.Name -like '*SSH*' }
   Enable-NetFirewallRule -DisplayName '<the sshd rule you just listed>'
   ```

   Common candidates on different Windows versions: `Open SSH Server`,
   `OpenSSH-SSHServer-In-TCP`, `sshd (OpenSSH)`; the exact `Name`/`DisplayName`
   varies. If the rule is missing, the capability did not register it — re-run
   the enable-step above.

4. **Verify the endpoint:**

   ```powershell
   Get-NetTCPConnection -LocalPort 22
   ```

   You want a LISTENING row (local port 22). Then check password auth is on:

   ```powershell
   Select-String 'PasswordAuthentication' 'C:/Program Files/OpenSSH/etc/ssh/sshd_config'
   ```

   It must be `yes` (or commented-out with `PasswordAuthentication yes`) for
   password login. For key login, add the client public key to
   `C:\Users\<user>\.ssh\authorized_keys` and `chmod 600` it.

5. **Connect from here and get the result:**

   ```powershell
   ssh <user>@<target-ip>
   ```
   Then run the result command interactively, or non-interactively:

   ```powershell
   ssh <user>@<target-ip> 'ipconfig | select-string "IPv4"'
   ```

## Pitfalls

- The OpenSSH capability source must be reachable; without internet there is no
  `Add-WindowsCapability -Online` shortcut, so you need a local source or the
  standalone GitHub package.
- `Add-WindowsCapability -Online` can appear to hang (it timed out at 180 s in
  one run here) and still complete on a second check — re-read the service
  state instead of assuming failure.
- Firewall rule display names/display groups are machine- and
  version-specific. Enumerate `Get-NetFirewallRule` rather than calling by
  guess.
- `sshd` starts as `Manual` by default; set it to `Automatic` if you want it
  to persist across reboots.
- `PasswordAuthentication` is often `no` in the shipped `sshd_config`; for
  password login that line must be present and `yes`.

## Result shape

Return the result as a short JSON object:

```json
{
  "target": "192.168.43.181",
  "via": "ssh",
  "command": "ipconfig | select-string IPv4",
  "status": "ok",
  "output": "..."
}
```

Avoid dumping long, uncolored command output in the final answer.
