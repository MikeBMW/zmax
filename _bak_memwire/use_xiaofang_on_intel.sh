#!/bin/bash
# 把 intel(550C) 的飞书身份切成小芳的 app (cli_aac4912eb6389bc2 / Hermes小芳)
# secret 从 ~/.hermes/feishu_xiaofang.env 取, 全程不回显
set -u
H=intel
SRC=/home/ubuntu/.hermes/feishu_xiaofang.env
[ -f "$SRC" ] || { echo "!! 缺 $SRC"; exit 1; }

echo "== 1. 备份 intel 现有飞书配置 =="
ssh $H 'cp ~/.hermes/.env ~/.hermes/.env.bak-before-xiaofang-$(date +%H%M); cp ~/.hermes/config.yaml ~/.hermes/config.yaml.bak-before-xiaofang-$(date +%H%M); ls -1 ~/.hermes/*.bak-before-xiaofang-* | tail -2'

echo "== 2. 传凭据并合并 .env (替换旧 FEISHU_*) =="
cat "$SRC" | ssh $H 'cat > /tmp/xf.env && chmod 600 /tmp/xf.env && python3 - <<PY
import os
new={}
for l in open("/tmp/xf.env"):
    l=l.strip()
    if l and "=" in l and not l.startswith("#"):
        k,v=l.split("=",1); new[k]=v
p=os.path.expanduser("~/.hermes/.env")
lines=open(p).read().splitlines() if os.path.exists(p) else []
out=[]; seen=set()
for l in lines:
    k=l.split("=",1)[0].strip() if ("=" in l and not l.strip().startswith("#")) else None
    if k in new:
        out.append("%s=%s"%(k,new[k])); seen.add(k)
    else:
        out.append(l)
for k,v in new.items():
    if k not in seen: out.append("%s=%s"%(k,v))
open(p,"w").write("\n".join(out)+"\n"); os.chmod(p,0o600)
print("  .env 已更新, 键:", sorted(new))
PY
rm -f /tmp/xf.env'

echo "== 3. 对齐 config.yaml 的 platforms.feishu =="
cat "$SRC" | ssh $H 'python3 - <<PY
import os,re
new={}
for l in os.sys.stdin.read().splitlines():
    if l.strip() and "=" in l and not l.startswith("#"):
        k,v=l.split("=",1); new[k]=v.strip()
p=os.path.expanduser("~/.hermes/config.yaml")
s=open(p).read()
aid=new["FEISHU_APP_ID"]; sec=new["FEISHU_APP_SECRET"]
s=re.sub(r"(?m)^(\s*)app_id:\s*cli_[0-9a-f]+", r"\1app_id: "+aid, s)
s=re.sub(r"(?m)^(\s*)app_secret:\s*\S+", r"\1app_secret: "+sec, s)
if "enabled: true" not in s:
    s=s.replace("  feishu:\n", "  feishu:\n    enabled: true\n",1)
open(p,"w").write(s); os.chmod(p,0o600)
print("  config.yaml app_id ->", aid)
PY'

echo "== 4. 重启 intel gateway =="
ssh $H 'export XDG_RUNTIME_DIR=/run/user/$(id -u); systemctl --user restart hermes-gateway; sleep 8; systemctl --user is-active hermes-gateway; python3 -c "
import json;d=json.load(open(\"/home/intel/.hermes/gateway_state.json\"));f=(d.get(\"platforms\") or {}).get(\"feishu\",{})
print(\"feishu:\",f.get(\"state\"),\"| err:\",f.get(\"error_message\"),\"| 更新\",f.get(\"updated_at\"))
"'

echo "== 5. 用 intel 侧的 .env 自证机器人身份 =="
ssh $H 'python3 - <<PY
import json,os,urllib.request
env={}
for l in open(os.path.expanduser("~/.hermes/.env")):
    l=l.strip()
    if "=" in l and not l.startswith("#"):
        k,v=l.split("=",1); env[k]=v
def req(u,d=None,tok=None):
    h={"Content-Type":"application/json"}
    if tok: h["Authorization"]="Bearer "+tok
    return json.loads(urllib.request.urlopen(urllib.request.Request(u,data=json.dumps(d).encode() if d else None,headers=h),timeout=12).read())
t=req("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",{"app_id":env["FEISHU_APP_ID"],"app_secret":env["FEISHU_APP_SECRET"]})
tok=t.get("tenant_access_token"); print("  token:", t.get("code"))
b=req("https://open.feishu.cn/open-apis/bot/v3/info",tok=tok).get("bot",{})
print("  intel 现在使用的机器人:", b.get("app_name"), "| app_id:", env["FEISHU_APP_ID"])
ch=req("https://open.feishu.cn/open-apis/im/v1/chats?page_size=20",tok=tok)
print("  可见群:", [(i.get("name"), i[\"chat_id\"][:14]+\"...\") for i in (ch.get(\"data\") or {}).get(\"items\",[])])
PY'
