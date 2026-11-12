#!/usr/bin/env python3
"""git push 走不通 (github.com 443 被断 / GnuTLS -110) 时, 用 GitHub 数据接口把本地 HEAD 落地。

用法:  python3 scripts/api_push.py            # 推当前分支 (默认 main)
       BRANCH=dev python3 scripts/api_push.py

做的事 (= SKILL.md 那四步, 但只推差异):
  1. GET /git/ref/heads/<branch> 取远端 base (绝不用本地 origin/main, 它会落后)
  2. 对 `git diff --name-status --no-renames origin/main HEAD` 的每个文件 POST /git/blobs (内容取 HEAD:<path>)
  3. POST /git/trees (base_tree=远端 base 的 tree, 只列本次变更)
  4. POST /git/commits (message 取 `git log -1 --format=%B`, parents=[远端 base]) + PATCH /git/refs/heads/<branch>
  5. 逐文件 GET /contents/<path>?ref=<新 sha> 校验 sha+size == 本地 (删除条目要回 404)

Token 从 ~/.git-credentials 读, 不打印不进对话。

必读前置 (脚本替不了): 先 `git add` + `git commit` —— 这条路推的是提交内容, 不是工作区文件;
工作区改了没提交 ⇒ 推上去的是旧版, 而每步都返 200、哈希还对(对的是旧 sha)。

退出码 0 = 推送并逐文件校验通过 (打印 REMOTE_SHA <远端提交>); 非 0 = 未完成, 按打印的 HTTP 码处理。
"""
import base64, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

REPO = os.environ.get("REPO", os.path.expanduser("~/zmax"))
OWNER = os.environ.get("OWNER", "MikeBMW")
NAME = os.environ.get("NAME", "zmax")
BRANCH = os.environ.get("BRANCH", "main")
API = "https://api.github.com"


def tok():
    for line in open(os.path.expanduser("~/.git-credentials"), encoding="utf-8"):
        m = re.match(r"https://([^:]+):([^@]+)@github\.com", line.strip())
        if m:
            return m.group(1), m.group(2)
    sys.exit("no github credentials in ~/.git-credentials")


def api(method, path, body=None, retries=4):
    user, token = tok()
    data = json.dumps(body).encode() if body is not None else None
    for i in range(retries):
        req = urllib.request.Request(API + path, data=data, method=method,
                                     headers={"Authorization": f"token {token}",
                                              "Accept": "application/vnd.github+json",
                                              "User-Agent": "hermes-api-push",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                b = r.read()
                return json.loads(b) if b else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            if e.code >= 500 and i < retries - 1:
                time.sleep(2 + 2 * i)
                continue
            sys.exit(f"{method} {path} -> {e.code}: {msg}")
        except Exception as e:
            if i < retries - 1:
                time.sleep(2 + 2 * i)
                continue
            sys.exit(f"{method} {path} -> {e}")


def git(*args, binary=False):
    out = subprocess.run(["git", "-C", REPO, "-c", "core.quotepath=false", *args], capture_output=True)
    if out.returncode != 0:
        sys.exit(f"git {' '.join(args)}: {out.stderr.decode()[:300]}")
    return out.stdout if binary else out.stdout.decode().strip()


def main():
    if git("status", "--porcelain"):
        sys.exit("工作区不干净: 先 git commit —— 这条路推的是提交内容, 不是工作区")
    base = api("GET", f"/repos/{OWNER}/{NAME}/git/ref/heads/{BRANCH}")["object"]["sha"]
    base_tree = api("GET", f"/repos/{OWNER}/{NAME}/git/commits/{base}")["tree"]["sha"]
    print(f"remote base {base[:12]} tree {base_tree[:12]}")

    changed = git("diff", "--name-status", "--no-renames", "origin/main", "HEAD").splitlines()
    if not changed:
        sys.exit("origin/main..HEAD 无差异 (本地 remote-tracking 可能已是最新) —— 先 git fetch 或改基准")

    tree, checks = [], {}
    for line in changed:
        st, path = line.split("\t", 1)
        if st == "D":
            tree.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            checks[path] = None
            continue
        content = git("show", f"HEAD:{path}", binary=True)
        blob = api("POST", f"/repos/{OWNER}/{NAME}/git/blobs",
                   {"content": base64.b64encode(content).decode(), "encoding": "base64"})
        tree.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        checks[path] = (git("rev-parse", f"HEAD:{path}"), len(content))
        print(f"  blob {blob['sha'][:12]} {len(content):>9}B {path}")

    new_tree = api("POST", f"/repos/{OWNER}/{NAME}/git/trees", {"base_tree": base_tree, "tree": tree})
    commit = api("POST", f"/repos/{OWNER}/{NAME}/git/commits",
                 {"message": git("log", "-1", "--format=%B"), "tree": new_tree["sha"], "parents": [base]})
    api("PATCH", f"/repos/{OWNER}/{NAME}/git/refs/heads/{BRANCH}",
        {"sha": commit["sha"], "force": False})
    print(f"pushed commit {commit['sha']}")

    ok = 0
    for path, want in checks.items():
        q = urllib.parse.quote(path)
        try:
            got = api("GET", f"/repos/{OWNER}/{NAME}/contents/{q}?ref={commit['sha']}")
        except SystemExit:
            ok += want is None
            print(f"  {'✓ 已删除' if want is None else '✗ 读取失败'} {path}")
            continue
        if want is None:
            print(f"  ✗ 删除未生效 (远端仍在) {path}")
            continue
        good = got["sha"] == want[0] and got["size"] == want[1]
        ok += good
        print(f"  {'✓' if good else '✗'} {path} sha {got['sha'][:12]} size {got['size']} (local {want[0][:12]}/{want[1]})")
    print(f"verify {ok}/{len(checks)}")
    print("REMOTE_SHA", commit["sha"])
    if ok != len(checks):
        sys.exit(1)


main()
