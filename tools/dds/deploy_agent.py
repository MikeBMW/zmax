#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚚 deploy_cmd 执行代理 —— 把 DDS 上的部署指令接到真部署流程 (2026-10-25)

背景: deploy_cmd 以前只有 dry-run 打印 (tools/dds_node_4060.py), 指令到了没人执行。
现在它跨网也能到 (ws-bus 中继), 所以必须有一个**带闸**的执行器, 否则等于把部署口
暴露给"任何能发 DDS 的人"。本代理就是那道闸。

铁律 (缺一条就不许执行):
  ① 动作白名单: 只认 promote / rollback (stop_train 等未定义执行器 ⇒ 一律拒)
  ② 发起人白名单: ZMAX_DEPLOY_ISSUERS (默认 老倪,laoliu,console,8793,4060)
  ③ promote 的产物必须: 文件真实存在 + 扩展名 .pt/.pth/.safetensors + realpath 落在
     ZMAX_DEPLOY_ROOTS (默认 zmax_data,models,runs,external) 之内 —— 不许指 /etc、不许 ..
  ④ 先 `--check-only` 校验 (真加载 + 真帧推理), 通过后才可能 `--yes` 真换软链
  ⑤ 真执行必须显式开: ZMAX_DEPLOY_EXEC=1; 否则只 dry-run 并照样落审计
  ⑥ 幂等 + 限速: 同一条指令 120s 内不重复执行; 两次执行间隔 ≥20s
  ⑦ 每条指令一条审计 (含裁决/耗时/rc/输出尾), 谁也不许"静默执行"

用法:
  python3 tools/dds/deploy_agent.py --dry-run          # 只看不动 (默认)
  ZMAX_DEPLOY_EXEC=1 python3 tools/dds/deploy_agent.py --apply
审计: zmax_data/runtime/deploy/audit.jsonl  (一行一条, 含 verdict)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, os.path.join(ROOT, "dds")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zmax_node import Node                                                   # noqa: E402

DATA = os.environ.get("ZMAX_DATA", os.path.join(ROOT, "zmax_data"))
AUDIT = os.path.join(DATA, "runtime", "deploy", "audit.jsonl")
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
PROMOTE = os.path.join(ROOT, "tools", "l5_promote_l2.py")

ACTIONS = {"promote": "换在役软链到新产物", "rollback": "用登记的旧指向回滚"}
SUFFIX_OK = (".pt", ".pth", ".safetensors")
ISSUERS = {s.strip() for s in os.environ.get(
    "ZMAX_DEPLOY_ISSUERS", "老倪,laoliu,console,8793,4060,550C,ECS").split(",") if s.strip()}
ROOTS = [os.path.realpath(p if os.path.isabs(p) else os.path.join(ROOT, p))
         for p in os.environ.get("ZMAX_DEPLOY_ROOTS",
                                 "zmax_data,models,runs,external").split(",") if p.strip()]


def audit(rec):
    try:
        os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:                                                      # noqa: BLE001
        print("⚠️ 审计写失败: %s" % e, flush=True)


def _tail(s, n=600):
    s = (s or "").strip()
    return s[-n:]


class Agent:
    def __init__(self, apply=False, min_interval=20.0, dedupe_s=120.0):
        self.apply = apply
        self.min_interval = min_interval
        self.dedupe_s = dedupe_s
        self.last_exec = 0.0
        self.seen = {}
        self.stat = {"recv": 0, "accepted": 0, "rejected": 0, "applied": 0, "failed": 0}
        self.node = Node("deploy_agent")
        self.node.sub("deploy_cmd")
        self.node.pub("deploy_cmd")     # 预建 writer: 防止以后要 ack 时首次丢帧

    # ── 三道闸 ──
    def check(self, m):
        if m.action not in ACTIONS:
            return False, "动作不在白名单 %s (收到 %r)" % (sorted(ACTIONS), m.action)
        if m.issuer not in ISSUERS:
            return False, "发起人不在白名单 (收到 %r)" % m.issuer
        if m.action == "promote":
            art = (m.artifact or "").strip()
            if not art:
                return False, "promote 缺 artifact"
            rp = os.path.realpath(art if os.path.isabs(art) else os.path.join(ROOT, art))
            if not os.path.isfile(rp):
                return False, "产物不存在: %s" % rp
            if not rp.endswith(SUFFIX_OK):
                return False, "产物扩展名不允许: %s" % os.path.basename(rp)
            if not any(rp == r or rp.startswith(r + os.sep) for r in ROOTS):
                return False, "产物不在允许目录内: %s (允许 %s)" % (rp, ROOTS)
            return True, rp
        return True, ""     # rollback 不需要产物

    def run(self, args, timeout=300):
        t0 = time.time()
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
            return p.returncode, _tail((p.stdout or "") + (p.stderr or "")), round(time.time() - t0, 1)
        except subprocess.TimeoutExpired:
            return 124, "超时 %ss" % timeout, round(time.time() - t0, 1)
        except Exception as e:                                                  # noqa: BLE001
            return 125, "%s: %s" % (type(e).__name__, e), round(time.time() - t0, 1)

    def handle(self, m):
        self.stat["recv"] += 1
        key = (m.issuer, m.action, m.artifact, round(float(m.ts or 0), 2))
        now = time.time()
        rec = {"ev": "deploy_cmd", "recv_ts": time.strftime("%Y-%m-%d %H:%M:%S"),
               "issuer": m.issuer, "layer": m.layer, "action": m.action,
               "artifact": m.artifact, "note": m.note, "cmd_ts": m.ts,
               "exec_mode": "apply" if self.apply else "dry-run"}
        prev = self.seen.get(key)
        if prev and now - prev < self.dedupe_s:
            rec.update(verdict="ignored", reason="重复指令(幂等窗口 %.0fs)" % self.dedupe_s)
            self.stat["rejected"] += 1
            audit(rec)
            print("⏭ 忽略重复: %s %s %s" % (m.issuer, m.action, m.artifact), flush=True)
            return
        self.seen[key] = now
        if len(self.seen) > 500:
            self.seen = {k: v for k, v in self.seen.items() if now - v < self.dedupe_s * 4}

        ok, detail = self.check(m)
        if not ok:
            rec.update(verdict="rejected", reason=detail)
            self.stat["rejected"] += 1
            audit(rec)
            print("⛔ 拒绝: %s | %s %s %s" % (detail, m.issuer, m.action, m.artifact), flush=True)
            return
        self.stat["accepted"] += 1
        rec["resolved"] = detail

        if now - self.last_exec < self.min_interval:
            rec.update(verdict="throttled", reason="距上次执行 <%.0fs" % self.min_interval)
            self.stat["rejected"] += 1
            audit(rec)
            print("⏳ 限速: 距上次执行不足 %.0fs" % self.min_interval, flush=True)
            return
        self.last_exec = now

        if m.action == "promote":
            rc, out, dur = self.run([PY, PROMOTE, "--best", detail, "--check-only"])
            rec.update(stage="check-only", rc=rc, dur_s=dur, out=out)
            if rc != 0:
                rec.update(verdict="rejected", reason="check-only 未过 (rc=%d): %s" % (rc, out[-200:]))
                self.stat["rejected"] += 1
                audit(rec)
                print("⛔ check-only 未过 rc=%d" % rc, flush=True)
                return
            if not self.apply:
                rec.update(verdict="dry-run-ok", reason="校验通过; 未开 ZMAX_DEPLOY_EXEC ⇒ 不换软链")
                audit(rec)
                print("✅ dry-run: 校验通过 (未换软链) %s" % os.path.basename(detail), flush=True)
                return
            rc2, out2, dur2 = self.run([PY, PROMOTE, "--best", detail, "--yes"])
            rec.update(stage="apply", rc=rc2, dur_s=dur2, out=out2,
                       verdict="applied" if rc2 == 0 else "failed")
            self.stat["applied" if rc2 == 0 else "failed"] += 1
            audit(rec)
            print("%s 真换软链 rc=%d" % ("✅" if rc2 == 0 else "❌", rc2), flush=True)
            return

        # rollback
        if self.apply:
            rc, out, dur = self.run([PY, PROMOTE, "--restore"])
            rec.update(stage="restore", rc=rc, dur_s=dur, out=out,
                       verdict="applied" if rc == 0 else "failed")
            self.stat["applied" if rc == 0 else "failed"] += 1
        else:
            rc, out, dur = 0, "dry-run: 将执行 l5_promote_l2.py --restore", 0.0
            rec.update(stage="restore", rc=rc, dur_s=dur, out=out, verdict="dry-run-ok")
        audit(rec)
        print("%s rollback (rc=%d)" % ("✅" if rc == 0 else "❌", rc), flush=True)

    def run_forever(self):
        print("=" * 78, flush=True)
        print("🚚 deploy_cmd 执行代理 | 模式=%s | 允许动作=%s" %
              ("APPLY(真执行)" if self.apply else "DRY-RUN(只校验)", sorted(ACTIONS)), flush=True)
        print("   允许发起人: %s" % sorted(ISSUERS), flush=True)
        print("   允许产物目录: %s" % ROOTS, flush=True)
        print("   审计: %s" % AUDIT, flush=True)
        print("=" * 78, flush=True)
        matched = self.node.wait_for_match("deploy_cmd", 1, 6)
        print("   配对 deploy_cmd: %s | 等指令…" % matched, flush=True)
        t_last = 0.0
        while True:
            got = self.node.sub("deploy_cmd").take()
            for m in got:
                if not (m.issuer or m.action or m.artifact):
                    continue            # 空样 (latch 回放)
                try:
                    self.handle(m)
                except Exception as e:                                          # noqa: BLE001
                    print("⚠️ 处理异常: %s: %s" % (type(e).__name__, e), flush=True)
            if time.time() - t_last >= 10:
                t_last = time.time()
                print("📊 %s" % self.stat, flush=True)
            time.sleep(0.2)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="真执行 (需同时 ZMAX_DEPLOY_EXEC=1)")
    g.add_argument("--dry-run", action="store_true", help="只校验不执行 (默认)")
    ap.add_argument("--min-interval", type=float, default=20.0)
    a = ap.parse_args()
    env_on = os.environ.get("ZMAX_DEPLOY_EXEC", "0") in ("1", "true", "yes")
    apply_mode = bool(a.apply and env_on)
    if a.apply and not env_on:
        print("⚠️ 给了 --apply 但 ZMAX_DEPLOY_EXEC 未开 ⇒ 仍按 dry-run 跑 (双重闸)", flush=True)
    Agent(apply=apply_mode, min_interval=a.min_interval).run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
