#!/bin/bash
# 重启某个端口上的常驻 python 服务 —— 按**端口**收口, 不按进程名匹配
#
# 用法: bash restart_port_service.sh <port> <入口.py> [日志路径]
#   例: bash restart_port_service.sh 8797 tools/tcp_ar_server.py
#   解释器用环境变量覆盖: PY=/path/to/venv/bin/python
#
# 为什么按端口而不是 pkill -f:
#  ① `pkill -f <名字>` 会匹配到执行它的这条 shell 自己 (argv 里含同样的字符串),
#     最坏是半途自杀 —— 服务已被杀掉、命令后半段没跑, 现场看到的就是"点什么都没反应"。
#  ② 每连接一进程 (ForkingMixIn) 的服务, 父 + 多个 fork 子进程**共享同一个监听 socket**,
#     `ss -ltnp` 会为同一个端口列出**一串 pid**。只 kill 第一个 ⇒ 旧代码还在服务,
#     症状是「改了代码行为没变」(实测: 新端点一直返回旧的 7 个点, 而代码里早已是 54 个),
#     而 curl 全是 200、服务端字段回读也"看起来对"(旧进程也有那些字段)。
# 端口号不会出现在任何进程名里, 按端口找 pid 天然不会匹配到自己。
set -u
PORT=${1:?用法: restart_port_service.sh <port> <入口.py> [日志]}
ENTRY=${2:?缺入口文件}
LOG=${3:-zmax_data/logs/svc_${PORT}.log}
PY=${PY:-./gui-venv311/bin/python}

pids() { ss -ltnp 2>/dev/null | grep ":${PORT}\b" | grep -oP 'pid=\K[0-9]+' | sort -u; }

mapfile -t P < <(pids)
if [ ${#P[@]} -gt 0 ]; then
  echo "停 ${PORT}: ${#P[@]} 个 (${P[*]})"
  kill "${P[@]}" 2>/dev/null
  # 循环等到**扫描为空**, 不是 kill 一次就 sleep
  for _ in $(seq 1 25); do sleep 0.3; [ -z "$(pids)" ] && break; done
  if [ -n "$(pids)" ]; then
    echo "TERM 没清干净, 补 KILL"
    mapfile -t L < <(pids)
    kill -9 "${L[@]}" 2>/dev/null
    sleep 1.5
  fi
else
  echo "${PORT} 当前没在监听"
fi

# 端口仍被占就显式失败: 继续起 = 新进程 bind 失败(errno 98), 而你会在跟旧代码对话
if [ -n "$(pids)" ]; then
  echo "⛔ ${PORT} 仍被占: $(pids) —— 不启动新实例"
  exit 1
fi

# 起之前用**运行它的那个解释器**做语法自检: 语法错会让服务起不来, 现场就是"整个页面没了"
"$PY" -c "import py_compile; py_compile.compile('$ENTRY', doraise=True)" || {
  echo "⛔ 语法自检失败, 不重启"; exit 2; }

mkdir -p "$(dirname "$LOG")"
nohup "$PY" "$ENTRY" >> "$LOG" 2>&1 &
NEWPID=$!
echo "新 pid=$NEWPID"
for _ in $(seq 1 40); do sleep 0.5; [ -n "$(pids)" ] && break; done

# 断言应答的 pid 不在 stop 前那批里 —— 否则说明旧进程还活着在服务
for q in $(pids); do
  for old in ${P[@]:+"${P[@]}"}; do
    [ "$q" = "$old" ] && { echo "⛔ 应答的仍是旧 pid $q —— 旧代码还在服务"; exit 3; }
  done
done

echo "✅ ${PORT} 由新进程服务: $(pids | tr '\n' ' ')"
echo "下一步: 用**只有新代码才有的字段/内容特征**验收 (新端点、新增的点数/条数), 不要用 HTTP 200"
