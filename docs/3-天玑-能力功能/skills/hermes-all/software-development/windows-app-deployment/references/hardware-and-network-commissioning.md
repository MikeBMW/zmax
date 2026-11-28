# Hardware & Network Commissioning

A packaged console (or the user) reports every device offline, or asks "can you see
`<ip>`?" / "is the robot connected?". Order that answers it in minutes: **link → L2 →
ports → the device's own telemetry**. The app's UI is the last thing to trust, not the
first.

## 1. The NIC, not the cable

```powershell
Get-NetAdapter | Select Name,InterfaceDescription,Status,LinkSpeed,ifIndex
Get-NetIPAddress -AddressFamily IPv4 | Select IPAddress,PrefixLength,InterfaceAlias
```

- `169.254.x/16` on the plant adapter means **link up, no DHCP** — a plant segment is
  statically addressed, so nothing will ever arrive on its own. Assign an address in the
  device subnet: `New-NetIPAddress -InterfaceIndex <idx> -IPAddress <host>.100
  -PrefixLength 24` (leave the gateway empty; the WLAN default route must stay, the on-link
  route comes with the address).
- Select the adapter by `InterfaceDescription`/`Name` (it is usually a USB GbE dongle), not
  by `ifIndex` — the index changes between boots. Multiple `169.254.x` entries mean multiple
  dongles; pick the one that is `Up` at 1 Gbps.
- A previous session's "reachable" result expires as soon as the host's own address changes
  (WLAN roaming, dongle unplugged). Re-measure instead of arguing with the old result.

## 2. Link, layer 2, then real ports

`ping -n 3 <ip>` alone proves nothing either way. Add:

- `Get-NetNeighbor -InterfaceIndex <idx> -IPAddress <ip>` — State `Reachable` **and** a MAC
  means L2 works; the MAC OUI names the vendor (Intel, Raspberry Pi/Orin modules, ...).
- one TCP connect per actual service port; never conclude "host down" from one closed port.

```powershell
foreach ($p in 22,80,8797,8794,39061) { $c=New-Object Net.Sockets.TcpClient;
  $ok=$c.ConnectAsync($ip,$p).Wait(900); "$p -> $(if($ok -and $c.Connected){'open'}else{'closed'})"; $c.Close() }
```

## 3. Identify the box from what it says about itself

- SSH banner (read the first line of a raw socket on 22): `SSH-2.0-OpenSSH_9.6p1
  Ubuntu-3ubuntu13.16` → distro and version.
- `curl -s -i http://<ip>/` → `Server:` header (`nginx/1.24.0 (Ubuntu)`, `BaseHTTP/0.6
  Python/3.10.12`, ...).
- Its own JSON endpoints (`/api/cams`, `/status`) name the cameras and the controller.

## 4. Prove the device chain from telemetry, not from open ports

An open port on the vision box says nothing about the robot. The chain is proven by the
endpoint that reports the device:

- controller: `{"ok":true,"status":{"ctrl":"<controller-ip>","jointPos":[…],
  "jointTorque":[…],"endInRef":[…]}}` = controller linked, live joint state.
- camera: `HTTP 200` + `Content-Length` + `X-Frame-Age: 0.01` = a live frame. HTTP 200 with
  zero bytes is *not* a frame.

Quote those numbers back to the user; they end the "is it connected?" question without
interpretation.

## 5. Read the 503 body before declaring a host down

Well-built services answer with cause + hint:

```json
{"ok":false,"err":"RealSense mini-service(8789) unreachable: Connection refused","hint":"bash tools/rs_service.sh start"}
{"ok":false,"err":"this camera has no frame right now (source returned 0 bytes)"}
```

That distinguishes "capture not started" from "network down" and usually ends the
investigation — but report it as the service's own diagnosis, and ask for credentials
instead of guessing them when the fix needs a shell on that host.

## 6. After the link is up, the console is still lying

The app caches offline state and backs off per source (tens of seconds), so relaunch it (or
re-open the page) before judging. Ports owned by a *different* machine (portal, station
overview, ar3d served from the dev/Ubuntu node) stay closed by design — name which host owns
which port instead of calling every red port a fault.

## 7. Which process holds the camera

Windows webcams are exclusive, so "the camera stopped working in <other app>" is usually
ownership, not permission or driver. Presence first:
`Get-PnpDevice -Class Camera,Image | Select Status,FriendlyName,InstanceId` (`OK` = present),
then ownership from the per-app consent store:

```powershell
$b='HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam'
(Get-ItemProperty $b).Value                 # global switch: Allow / Deny
(Get-ItemProperty "$b\NonPackaged").Value   # desktop (non-packaged) apps, own global switch
Get-ChildItem "$b\NonPackaged" | ForEach-Object {
  $p = Get-ItemProperty $_.PSPath
  '{0,-55} value={1} lastStop={2}' -f $_.PSChildName, $p.Value, $p.LastUsedTimeStop }
```

- `LastUsedTimeStop = 0` → that executable is using the camera **now**; any numeric value →
  it released it. The number is FILETIME-scale; compare it relatively, never as a date.
- Entry names are path-mangled (`C:#Program Files#Tencent#Weixin#Weixin.exe`).
- **No per-app entry is not a denial** — the child key inherits from `NonPackaged`, which
  inherits the global value. A missing entry plus `Allow` up the chain means permitted.
- Confirmation from the other side: the grabbing helper's log prints the device it opened
  (`[local] 出图: /dev/video0`), which is how a Linux-style open maps to the default webcam.
- After stopping the holder, re-read `lastStop`: flipping from `0` to a timestamp is the proof
  the device is free. Then tell the user to close and reopen the video call — apps cache the
  device handle and keep failing until they re-open it.

## This cell's addresses (re-verify with §2 before trusting)

Workstation USB NIC: static `<plant>.100/24` on the dongle, WLAN keeps the default route.

| Host | Role | Ports seen open |
|---|---|---|
| Orin | robot-side companion | 22, 8794 (`/frame.jpg`), 39061 (`/status` → `ctrl` + joints) |
| IPC | AOI + plant PC | only 10082 / 10083 (AOI gold / surface); 22, 8788, 8791, 8793, 8802 closed here |
| Rokae controller | arm | SDK pushes to the Orin; no direct TCP from the workstation |
| Ubuntu vision/AR box | camera + AR service layer | 22, 80 (nginx), 8797 (`/api/cams`, `/snap/<cam>.jpg`), 8802, 39061 |
