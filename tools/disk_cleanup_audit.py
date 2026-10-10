#!/usr/bin/env python3
"""磁盘清理候选审查 (只读): 列出候选 + 逐个查活引用, 不删任何东西。

口径 (来自 disk-redline-guard 技能):
  · 训练 run 同族只留最新; 但被 tools/ · ~/.hermes/scripts · crontab · config 引用的**整目录不删**。
  · 凡在 tools/*.sh 里被赋值过的名字 (PREV=/ART=/NAME=) 视为活引用。
  · 删前必须确认"在役链一条都没匹配上"。
"""
import os, re, subprocess, sys, glob

ROOT = "/home/ubuntu/zmax"
TRAIN = os.path.join(ROOT, "external/lerobot-smolvla-lew/outputs/train")
CANDIDATE_DIRS = os.path.join(ROOT, "zmax_data/stable-wm-cache/datasets")

# 在役链/保护区 (技能里点名的 + 今天新增的) —— 这些**永不删**
PROTECT = {
    "smolvla_lew_v10", "smolvla_lew_v10_1h", "smolvla_lew_v10_fast", "smolvla_lew_v8",
    "smolvla_lew_d1", "smolvla_lew_sim", "smolvla_lew_lora_200", "smolvla_lew_lora_200_r2",
    "smolvla_lew_lora_200_r2_merged", "smolvla_lew_lora_30_r4",
}

GREP_ROOTS = [
    os.path.join(ROOT, "tools"), os.path.join(ROOT, "src"), os.path.join(ROOT, "config"),
    os.path.join(ROOT, "data"), os.path.join(ROOT, "scripts"),
    "/home/ubuntu/.hermes/scripts",
    os.path.join(ROOT, "external/lerobot-smolvla-lew/tools"),
]


def du(path):
    try:
        out = subprocess.run(["du", "-sh", path], capture_output=True, text=True, timeout=120).stdout
        return out.split()[0]
    except Exception:
        return "?"


def refs(name):
    """查活引用: 返回 (命中文件列表, cron 是否引用)。"""
    hits = []
    pat = re.escape(name)
    cmd = ["grep", "-rlE", pat] + [r for r in GREP_ROOTS if os.path.isdir(r)] + \
          ["--include=*.py", "--include=*.sh", "--include=*.yaml", "--include=*.yml",
           "--include=*.json", "--include=*.md"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        hits = [l for l in r.stdout.splitlines() if l.strip()]
    except Exception as e:
        hits = ["<grep 失败: %s>" % e]
    # 排除扫描目录自身产出的日志/记录
    hits = [h for h in hits if "/outputs/" not in h and "/reports/" not in h]
    cron = subprocess.run("crontab -l 2>/dev/null", shell=True, capture_output=True, text=True).stdout
    return hits, (name in cron)


def main():
    print("=" * 78)
    print("训练 run 候选 (非保护区)")
    print("=" * 78)
    rows = []
    for d in sorted(os.listdir(TRAIN)):
        full = os.path.join(TRAIN, d)
        if not os.path.isdir(full):
            continue
        if d in PROTECT:
            continue
        hits, in_cron = refs(d)
        rows.append((d, du(full), len(hits), hits[:2], in_cron))
    for d, size, n, sample, in_cron in rows:
        flag = "🔒活引用" if (n or in_cron) else "🗑 可删"
        print("%-6s %-44s 引用%d%s %s" % (size, d, n, " cron!" if in_cron else "", flag))
        for s in sample:
            print("        ← %s" % s)
    print()
    print("=" * 78)
    print("数据集候选 (stable-wm-cache/datasets)")
    print("=" * 78)
    for f in sorted(glob.glob(CANDIDATE_DIRS + "/*.h5")):
        b = os.path.basename(f)
        hits, in_cron = refs(b)
        print("%-8s %-34s 引用%d%s %s" % (du(f), b, len(hits), " cron!" if in_cron else "",
                                          "🔒活引用" if (hits or in_cron) else "🗑 候选"))
        for s in hits[:2]:
            print("        ← %s" % s)


if __name__ == "__main__":
    main()
