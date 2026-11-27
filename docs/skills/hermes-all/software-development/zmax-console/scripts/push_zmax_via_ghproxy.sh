#!/usr/bin/env bash
# 推 MikeBMW/zmax 到 GitHub (走 ghproxy 镜像) —— 与 push_via_ghproxy.sh 的区别:
#   ① REPO/URL 换成 zmax;  ② 同一条命令里推 main + tag (tag 才触发出包);
#   ③ tag 可强制重指 (构建失败且无产物时重发);  ④ 末尾核远端 SHA == 本地。
# 用法: push_zmax_via_ghproxy.sh                 # 只推 main
#       push_zmax_via_ghproxy.sh v5.35.0         # 推 main + 该 tag (已存在则强指到 HEAD 后强推)
#       push_zmax_via_ghproxy.sh v5.35.0 --tag-only
set -u
REPO=${ZMAX_REPO:-/home/ubuntu/zmax}
URL="https://ghproxy.net/https://github.com/MikeBMW/zmax.git"
TAG="${1:-}"; MODE="${2:-}"
cd "$REPO" || exit 1

CRED=$(python3 -c "
import re,os
s=open(os.path.expanduser('~/.git-credentials')).read()
print(re.search(r'https://([^@]+)@github\.com', s).group(1))")
AUTH=$(printf '%s' "$CRED" | base64 -w0)
G=(git -c http.sslVerify=false -c "http.extraHeader=Authorization: Basic $AUTH" \
   -c http.postBuffer=524288000 -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=180)

LOCAL=$(git rev-parse HEAD); echo "本地 HEAD = $LOCAL"
REFS=("HEAD:refs/heads/main")
if [ -n "$TAG" ]; then
  if [ "$MODE" != "--tag-only" ]; then
    git tag -f "$TAG" HEAD >/dev/null && echo "tag $TAG 强指 → $(git rev-list -n1 "$TAG" | cut -c1-8)"
  fi
  # 旧 tag 在远端但指向别的提交 (构建失败重发) ⇒ 先删再强推, 否则会"new tag"却停在旧提交
  timeout 200 "${G[@]}" push "$URL" ":refs/tags/$TAG" >/dev/null 2>&1 || true
  REFS+=("refs/tags/$TAG:refs/tags/$TAG")
fi

timeout 600 "${G[@]}" push --force "$URL" "${REFS[@]}" 2>&1 | tail -4
RC=${PIPESTATUS[0]}; echo "  push rc=$RC"

echo "=== 核远端 (必须双向一致) ==="
timeout 90 "${G[@]}" ls-remote "$URL" refs/heads/main ${TAG:+"refs/tags/$TAG"} 2>/dev/null | sed 's/^/  /'
echo "  本地 HEAD = $(git rev-parse HEAD)${TAG:+   tag 本地 = $(git rev-list -n1 "$TAG")}"
