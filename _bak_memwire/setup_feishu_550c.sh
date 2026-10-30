#!/bin/bash
# 把 550A 上已验证可用的飞书凭据 + 群策略搬到 550C, 启用 platforms.feishu, 重启 gateway 并自检
set -u
H=intel
SRC_ENV=/home/ubuntu/.hermes/.env

echo "== 1. 取本机飞书凭据 (不回显) =="
TMP=$(mktemp /tmp/fs_XXXX.env); chmod 600 "$TMP"
grep -E "^FEISHU_|^GATEWAY_ALLOW_ALL_USERS" "$SRC_ENV" > "$TMP"
n=$(wc -l < "$TMP"); echo "   取到 $n 行 (app_id/secret/policy)"
[ "$n" -ge 2 ] || { echo "!! 本机 .env 没有 FEISHU_*"; exit 1; }

echo "== 2. 推到 550C 并合并 (去重) =="
scp -q "$TMP" $H:/tmp/feishu.env.new || exit 1
rm -f "$TMP"
ssh $H 'python3 - <<PY
import os,re
new={}
for l in open("/tmp/feishu.env.new"):
    l=l.strip()
    if not l or "=" not in l: continue
    k,v=l.split("=",1); new[k]=v
p=os.path.expanduser("~/.hermes/.env")
old=open(p).read().splitlines() if os.path.exists(p) else []
seen=set(); out=[]
for l in old:
    k=l.split("=",1)[0].strip() if "=" in l and not l.strip().startswith("#") else None
    if k in new:
        out.append("%s=%s"%(k,new[k])); seen.add(k)
    else:
        out.append(l)
for k,v in new.items():
    if k not in seen: out.append("%s=%s"%(k,v))
open(p,"w").write("\n".join(out)+"\n")
os.chmod(p,0o600)
print("   .env 行数:", len(out), "| FEISHU 键:", sorted(k for k in new))
PY'

echo "== 3. 打开 platforms.feishu.enabled =="
ssh $H 'cd ~ && (hermes config set platforms.feishu.enabled true 2>&1 | tail -2); grep -A2 "^  feishu:" ~/.hermes/config.yaml | head -3'

echo "== 4. 重启 550C gateway =="
ssh $H 'export XDG_RUNTIME_DIR=/run/user/$(id -u); systemctl --user restart hermes-gateway; sleep 6; systemctl --user is-active hermes-gateway; journalctl --user -u hermes-gateway --since "-2 min" 2>/dev/null | grep -iE "feishu|connected to wss|connected" | tail -4'

echo "== 5. 550C 直推自检 (真发一条到群) =="
ssh $H 'python3 - <<PY
import json,os,urllib.request
env={}
for l in open(os.path.expanduser("~/.hermes/.env")):
    l=l.strip()
    if "=" in l and not l.startswith("#"):
        k,v=l.split("=",1); env[k]=v
aid=env.get("FEISHU_APP_ID"); sec=env.get("FEISHU_APP_SECRET")
def post(u,d,tok=None):
    h={"Content-Type":"application/json"}
    if tok: h["Authorization"]="Bearer "+tok
    r=urllib.request.Request(u,data=json.dumps(d).encode(),headers=h)
    return json.loads(urllib.request.urlopen(r,timeout=10).read())
t=post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",{"app_id":aid,"app_secret":sec})
tok=t.get("tenant_access_token")
print("   token:", "OK" if tok else t)
chats=json.loads(urllib.request.urlopen(urllib.request.Request("https://open.feishu.cn/open-apis/im/v1/chats?page_size=20",headers={"Authorization":"Bearer "+tok}),timeout=10).read())
items=chats.get("data",{}).get("items",[])
print("   可见会话:", [(i["chat_id"][:12]+"...", i.get("name")) for i in items][:5])
if items:
    cid=items[0]["chat_id"]
    r=post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
           {"receive_id":cid,"msg_type":"text","content":json.dumps({"text":"✅ 550C 飞书已接管: 记忆层监控/自主进化由此机汇报 (静默模式, 零指令)"})},tok)
    print("   发送:", r.get("code"), r.get("msg"), (r.get("data") or {}).get("message_id"))
PY'
