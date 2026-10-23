#!/usr/bin/env bash
# 保存数据 (切远程遥控前): config 真源 + 工程库 + 画布 + units + Intel 进化产物 ⇒ tar + 校验
set -eu
cd /home/ubuntu/zmax
TS=$(date +%Y%m%d_%H%M)
A="data/database/zmax/archive/state_${TS}_remote"
rm -rf "$A"; mkdir -p "$A/config" "$A/units" "$A/intel"

cp -rL config/. "$A/config/"                                    # 软链解引用: 参数真源
cp -f data/database/zmax/zmax_engineering.db "$A/" 2>/dev/null || true
cp -f data/database/zmax/zmax_space.proj "$A/" 2>/dev/null || true
cp -f data/database/zmax/config_meta.json "$A/" 2>/dev/null || true
cp -f /etc/systemd/system/zmax-*.service "$A/units/" 2>/dev/null || true
cp -f /etc/systemd/system/zmax-*.timer "$A/units/" 2>/dev/null || true
cp -rf /etc/systemd/system/zmax-*.service.d "$A/units/" 2>/dev/null || true

# Intel 侧进化产物 (对称性引擎自主进化的账本; 取不回就明说, 不静默略过)
for f in symmetry_ledger.jsonl symmetry_best.json advisor.jsonl; do
  scp -q -o ConnectTimeout=8 "intel@192.168.23.70:/home/intel/evolve/$f" "$A/intel/" 2>/dev/null \
    && echo "  intel/$f 已取回" || echo "  ⚠ intel/$f 未取回 (远端不可达)"
done

tar czf "data/database/zmax/archive/zmax_state_${TS}_remote.tar.gz" -C "$(dirname "$A")" "$(basename "$A")"
TAR="data/database/zmax/archive/zmax_state_${TS}_remote.tar.gz"
N=$(tar tzf "$TAR" | wc -l)
SZ=$(du -h "$TAR" | cut -f1)
# 解包逐文件校验 (只比大小, 抽样比 sha; 不靠"写完了"三个字)
rm -rf /tmp/verify_state; mkdir -p /tmp/verify_state
tar xzf "$TAR" -C /tmp/verify_state
DIFF=$(diff -rq "$A" "/tmp/verify_state/$(basename "$A")" | wc -l)
echo "归档: $TAR"
echo "条目 $N · 体积 $SZ · 解包差异 $DIFF"
echo "$TAR"
