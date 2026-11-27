# 公开仓库的密钥纪律 (2026-10-10 事故后定)

## 事故
`MikeBMW/zmax` 是 **public** 仓库。ECS 网关机 root 口令以明文写进 55 个已入库文件（代码 3 处 + 文档/技能快照 52 处），另有一处 4090 机口令。任何人 clone 即拿到服务器 root。

## 铁律
1. **口令/token 一律不进仓库**，包括文档、技能快照、记忆文件、示例代码、systemd 单元。真值只放 `zmax_data/secrets/*.env`(600) 或环境变量(`ZMAX_ECS_PW` 等)。
2. **本地技能源 (`~/.hermes/skills/**`) 也会被同步进仓库** —— 在本地技能里写明文 = 下一次“入库”就泄露。改代码时要同步改技能源。
3. 代码里取口令用 helper（环境变量 → secrets 文件 → 找不到就**报错退出**），**不要留 "兜底明文"**：`os.environ.get("X") or "明文"` 是最常见的泄露方式。
4. 删 HEAD 里的明文 ≠ 收回泄露：git 历史/已发布 Release/别人已 clone 都还有。**处置顺序：先改服务器口令（旧值立即失效），再考虑清历史**。

## 轮换线上口令（改 ECS root）的硬顺序 (2026-10-10 实做)
1. **先建密钥登录再改口令**: 本机公钥追到远端 `authorized_keys` 并用 `ssh -o BatchMode=yes` 验证能进 —— 这是改口令唯一的保险绳。
2. **口令走 stdin** 不进命令行: `printf 'root:%s\n' "$NEW" | ssh <目标> chpasswd`（写进命令字符串会短暂出现在远端 ps/日志）。
3. **验证必须禁公钥**: `sshpass -p "$PW" ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no -o IdentitiesOnly=yes ...`。不禁公钥时本机已有 key 会让错误口令也“登录成功”，把没生效的轮换读成生效。
4. **旧口令要反向验证**: 拿旧值再测一次，确认被拒才算轮换成功；否则说明改的不是真正生效的那份。
5. **同一口令常在多处**: `/etc/zmax-ecs-*.env`(systemd 用 `sshpass -e` + `EnvironmentFile`) 与 `secrets/zmax.env` 是**两份独立凭据** —— 只改一处，隧道一重启就断。改完必须重启单元并复验远端反向端口在听。
6. 新口令字符集只用 env 文件安全字符(字母数字 + `-_.@#%+`)，避免引号/空格弄坏 EnvironmentFile 解析。

## 陷阱
- 凭据存在 ≠ 凭据有效: 发现明文后先做“仅密码认证”活验，再决定轮换范围。
- `docs/reports/` 被 `.gitignore` 忽略，入库要 `git add -f`（提交时报 “nothing to commit” 就是这个原因）。
## 自查命令 (可复制)
```
cd /home/ubuntu/zmax
python3 tools/secret_scan.py                 # 全量已跟踪文件; 命中退出码 1
python3 tools/secret_scan.py --staged        # 提交前闸
python3 tools/repo_guard.py --staged         # 大文件/交付件闸
git ls-files -z | xargs -0 grep -n "sshpass -p" | grep -v '\${'   # 残留明文兜底
curl -s -H "Authorization: token $TOKEN" https://api.github.com/repos/MikeBMW/zmax | grep -o '"visibility":"[a-z]*"'  # 确认仓库可见性
```

## secret_scan 的已知盲区
- 只能报“真值形态”（固定前缀+长度）。**普通密码没有前缀，必须靠 `密码=`/`sshpass -p <明文>` 这类上下文规则**（2026-10-10 已补入 PATTERNS）。
- 新规则上线后务必跑一次**全量**（非 --staged）：本次就是补规则后当场又抓出一处之前漏掉的 4090 口令。
