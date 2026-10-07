#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 L5 · 本地 VLM LoRA 微调 (Qwen2.5-VL-3B, 8GB 4060) — 2026-10-07

老倪口径:
  · 学生 = 本地 Qwen2.5-VL-3B-Instruct (离线可用); 数据来自 tools/l5_vlm_dataset.py 的**教师蒸馏样本**。
  · **未证明提升不进默认档**: 训完必须在**同一批 val 帧**上做基座 vs LoRA 同口径对照
    (判据 = 计划合法率: JSON 可解析 + 必需字段齐), 提升才写 ok, 否则标 candidate。
  · 全程打印 (加载/参数量/每步 loss/ETA/显存), 不静默。

用法:
  gui-venv311/bin/python tools/l5_vlm_lora_train.py --steps 60 --merge
  gui-venv311/bin/python tools/l5_vlm_lora_train.py --eval-only --adapter <dir>   # 只跑同口径对照
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("WANDB_MODE", "disabled")

SNAP = os.path.join(ROOT, "zmax_data/hf_cache/hub/models--Qwen--Qwen2.5-VL-3B-Instruct/snapshots")
DATA = os.path.join(ROOT, "data/l5_vlm_sft")
MODELS = os.path.join(ROOT, "zmax_data/models")
REPORTS = os.path.join(ROOT, "reports")
REQUIRED = ["目标可见", "目标是什么", "目标位置", "在夹爪上吗", "画面质量", "标定建议"]     # describe 任务
REQUIRED_STATE = ["目标可见", "目标是什么", "在夹爪上吗", "画面质量", "下一步动作"]        # state 任务
# ⚠️ 2026-10-08 踩坑: 训练集是 state 任务, 评测却按 describe 的字段表判 ⇒ 合法率恒 0 (自己把口径搞错)。
#   判据字段必须**按每条样本的 task** 取, 与训练同源。
FIELDS_BY_TASK = {"state": REQUIRED_STATE, "describe": REQUIRED}


SNAP_SMOL = os.path.join(ROOT, "zmax_data/hf_cache/hub/"
                         "models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct/snapshots")


def _snap_of(d: str) -> str:
    if not os.path.isdir(d):
        return ""
    subs = sorted(os.listdir(d))
    return os.path.join(d, subs[-1]) if subs else ""


def base_ckpt(model_arg: str = "") -> str:
    """学生模型目录 (离线快照优先, 不走网络)。
    默认 Qwen2.5-VL-3B (需 QLoRA 4-bit 才塞得进 8GB); 也可换 SmolVLM2-500M (bf16 直接放得下)。"""
    if model_arg:
        if os.path.isdir(model_arg):
            return model_arg
        for pat, base in (("smolvlm", SNAP_SMOL), ("smol", SNAP_SMOL), ("qwen", SNAP)):
            if pat in model_arg.lower():
                got = _snap_of(base)
                if got:
                    return got
        return model_arg                       # 交给 transformers 当 HF id 处理
    return _snap_of(SNAP) or _snap_of(SNAP_SMOL) or "Qwen/Qwen2.5-VL-3B-Instruct"


def load_rows(name: str) -> list[dict]:
    p = os.path.join(DATA, f"{name}.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def build_msgs(row: dict, with_answer: bool) -> list[dict]:
    m = [{"role": "system", "content": [{"type": "text", "text": row["system"]}]},
         {"role": "user", "content": [{"type": "image", "image": row["image"]},
                                      {"type": "text", "text": row["user"]}]}]
    if with_answer:
        m.append({"role": "assistant", "content": [{"type": "text", "text": row["answer"]}]})
    return m


def valid_json(text: str, required: list[str] | None = None) -> tuple[bool, str]:
    """判据: JSON 可解析 + 必需字段齐 (与数据通道同一把尺)"""
    import re
    s = (text or "").strip()
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return False, "无 JSON"
    try:
        j = json.loads(m.group(0))
    except Exception:                                                          # noqa: BLE001
        return False, "JSON 解析失败"
    req = required or REQUIRED
    miss = [k for k in req if k not in j]
    return (False, "缺字段:" + ",".join(miss[:3])) if miss else (True, "")


MAX_SIDE = 0        # >0 时把输入图等比缩到该边长 (省视觉 token)


def _prep(processor, row, with_answer=True):
    """一条样本 → 模型输入 + labels (只在 answer 段算 loss)"""
    from PIL import Image
    img = Image.open(row["image"]).convert("RGB")
    if MAX_SIDE and max(img.size) > MAX_SIDE:
        r = MAX_SIDE / max(img.size)
        img = img.resize((max(1, int(img.size[0] * r)), max(1, int(img.size[1] * r))))
    full = processor.apply_chat_template(build_msgs(row, with_answer), tokenize=False,
                                         add_generation_prompt=False)
    prompt = processor.apply_chat_template(build_msgs(row, False), tokenize=False,
                                           add_generation_prompt=True)
    enc = processor(text=[full], images=[img], return_tensors="pt", padding=False)
    ids = enc["input_ids"][0]
    plen = len(processor(text=[prompt], images=[img], return_tensors="pt")["input_ids"][0])
    labels = ids.clone()
    plen = min(plen, labels.shape[0])
    labels[:plen] = -100                      # 只对 answer 段算 loss (prompt 不算)
    enc["labels"] = labels.unsqueeze(0)
    enc["_plen"], enc["_n"] = plen, int(labels.shape[0])
    return enc


def evaluate(model, processor, rows, tag: str, max_new=200) -> dict:
    """同口径评测: 合法率 + 必需字段命中率 (同一批帧, greedy 解码)"""
    import torch
    from PIL import Image
    ok_n, hit, miss = 0, 0, []
    t0 = time.time()
    model.eval()
    for i, row in enumerate(rows, 1):
        try:
            img = Image.open(row["image"]).convert("RGB")
            prompt = processor.apply_chat_template(build_msgs(row, False), tokenize=False,
                                                   add_generation_prompt=True)
            enc = processor(text=[prompt], images=[img], return_tensors="pt").to(model.device)
            with torch.no_grad():
                out = model.generate(**enc, max_new_tokens=max_new, do_sample=False)
            text = processor.batch_decode(out[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)[0]
            _req = FIELDS_BY_TASK.get(row.get("task") or "describe", REQUIRED)
            good, why = valid_json(text, _req)
            if good:
                ok_n += 1
                j = json.loads(text[text.find("{"):text.rfind("}") + 1])
                hit += sum(1 for k in _req if str(j.get(k, "")).strip() not in ("", "看不清"))
            else:
                miss.append({"image": os.path.basename(row["image"]), "why": why, "head": text[:80]})
        except Exception as e:                                                 # noqa: BLE001
            miss.append({"image": os.path.basename(row["image"]), "why": f"{type(e).__name__}: {e}"[:80]})
    n = max(1, len(rows))
    return {"tag": tag, "n": len(rows), "json_ok_rate": round(ok_n / n, 4),
            "field_hit_rate": round(hit / (n * len(_req if rows else REQUIRED)), 4),
            "secs": round(time.time() - t0, 1), "fails": miss[:5]}


def main() -> int:
    ap = argparse.ArgumentParser(description="L5 · 本地 VLM LoRA 微调")
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--epochs", type=float, default=0, help=">0 时按数据量换算步数")
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--max-pixels", type=int, default=200704, help="视觉 token 预算 (401408≈28*28*512)")
    ap.add_argument("--max-len", type=int, default=1024)
    ap.add_argument("--max-side", type=int, default=448, help="输入图最长边上限 (省视觉 token; 0=不缩)")
    ap.add_argument("--tag", default="")
    ap.add_argument("--merge", action="store_true", help="训完合并权重 (部署免带 adapter; 4-bit 档不支持)")
    ap.add_argument("--model", default=os.environ.get("L5_VLM_MODEL", ""),
                    help="学生模型: 快照目录 / 含 qwen|smolvlm 的关键字 / HF id (默认 Qwen2.5-VL-3B 本地快照)")
    ap.add_argument("--no-4bit", dest="load_4bit", action="store_false", default=True,
                    help="不用 QLoRA 4-bit。⚠️ 8GB 卡实测: 3B bf16 全精度 LoRA **必 OOM**"
                         "(权重 6.2G + 适配器搬移就吃满 7.6G) ⇒ 默认走 4-bit(QLoRA)")
    ap.add_argument("--eval-only", action="store_true")
    ap.add_argument("--adapter", default="", help="--eval-only 时评的 adapter 目录")
    ap.add_argument("--eval-n", type=int, default=8)
    a = ap.parse_args()

    global MAX_SIDE
    MAX_SIDE = int(a.max_side or 0)
    ts = a.tag or time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(REPORTS, exist_ok=True)
    ckpt = base_ckpt(a.model)
    _small = ("smol" in ckpt.lower())
    if _small:
        a.load_4bit = False          # 500M 直接 bf16, 不需要 4-bit
    print(f"🧠 L5 VLM LoRA · 起点 {ckpt}")
    print(f"   数据 {os.path.relpath(DATA, ROOT)} · tag={ts}")

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForImageTextToText, AutoProcessor

    t0 = time.time()
    # ⚠️ transformers 5.x: min/max_pixels 只对支持的模型(Qwen 系)有效, 传给 SmolVLM 会刷
    #    "Kwargs ... have to be in processor_kwargs" 告警并**静默忽略** ⇒ 按模型能力给。
    try:
        proc = AutoProcessor.from_pretrained(ckpt, min_pixels=256 * 28 * 28, max_pixels=a.max_pixels)
    except Exception:                                                          # noqa: BLE001
        proc = AutoProcessor.from_pretrained(ckpt)
    if a.load_4bit:
        from peft import prepare_model_for_kbit_training
        from transformers import BitsAndBytesConfig
        print("⏳ 加载 3B 权重 (QLoRA 4-bit nf4 · 8GB 卡唯一可行档) …")
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                 bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
        model = AutoModelForImageTextToText.from_pretrained(
            ckpt, quantization_config=bnb, attn_implementation="sdpa", device_map={"": 0})
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    else:
        print("⏳ 加载 3B 权重 (bf16 全精度) …")
        model = AutoModelForImageTextToText.from_pretrained(
            ckpt, dtype=torch.bfloat16, attn_implementation="sdpa", low_cpu_mem_usage=True).to("cuda")
    model.config.use_cache = False
    print(f"✅ 加载完成 {time.time()-t0:.0f}s · 显存 {torch.cuda.memory_allocated()/2**30:.2f} GB")

    val_rows = load_rows("val")[: a.eval_n]
    tr_rows = load_rows("train")
    if a.eval_only:
        base = evaluate(model, proc, val_rows, "base(未微调)")
        print(f"   基座: 合法率 {base['json_ok_rate']} 字段命中 {base['field_hit_rate']} ({base['secs']}s)")
        if a.adapter:
            from peft import PeftModel
            m2 = PeftModel.from_pretrained(model, a.adapter)
            ad = evaluate(m2, proc, val_rows, "lora")
            print(f"   LoRA:  合法率 {ad['json_ok_rate']} 字段命中 {ad['field_hit_rate']} ({ad['secs']}s)")
            rep = {"ts": ts, "adapter": a.adapter, "base": base, "lora": ad,
                   "delta_json_ok": round(ad["json_ok_rate"] - base["json_ok_rate"], 4),
                   "verdict": "提升" if ad["json_ok_rate"] > base["json_ok_rate"] else "未证明提升"}
            p = os.path.join(REPORTS, f"l5_vlm_ab_{ts}.json")
            json.dump(rep, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"📄 A/B 报告 {os.path.relpath(p, ROOT)} → {rep['verdict']}")
        return 0

    if not tr_rows:
        print("❌ 没有训练样本: 先跑 tools/l5_vlm_dataset.py build")
        return 1

    # 冻结视觉塔 → 只训语言侧 LoRA (8GB 才放得下)
    for n, p_ in model.named_parameters():
        p_.requires_grad = ("visual" not in n)
    lcfg = LoraConfig(r=a.lora_r, lora_alpha=a.lora_r * 2, lora_dropout=0.05, bias="none",
                      task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, lcfg)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model.print_trainable_parameters()

    steps = int(a.epochs * max(1, len(tr_rows)) / (a.batch * a.accum)) if a.epochs > 0 else a.steps
    steps = max(1, steps)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=steps, pct_start=0.1)
    print(f"🚀 训练 {steps} 步 (bs={a.batch}×accum={a.accum} · 样本 {len(tr_rows)} 条 · lr={a.lr} · r={a.lora_r})")

    # ⚠️ 2026-10-08 实测坑: 每步现做图像预处理(PIL+processor)会把 GPU 饿到 5% 利用率,
    #   单步 54s(ETA 53min) —— 纯 CPU 瓶颈。改成**先一次性预编码**(缓存 token 张量), 训练只做 GPU 前反向。
    print(f"⏳ 预编码 {len(tr_rows)} 条样本 (CPU 只做一次) …")
    tc0 = time.time()
    cache = []
    for n_, row in enumerate(tr_rows, 1):
        try:
            enc = _prep(proc, row)
        except Exception as e:                                                 # noqa: BLE001
            print(f"   ⚠️ 预编码跳过 ({type(e).__name__}: {str(e)[:60]})")
            continue
        if enc["_n"] > a.max_len:
            continue
        cache.append({k: v for k, v in enc.items() if not k.startswith("_")})
        if n_ % 10 == 0:
            print(f"   {n_}/{len(tr_rows)} · {time.time()-tc0:.0f}s")
    print(f"✅ 预编码完成 {len(cache)} 条 · 用时 {time.time()-tc0:.0f}s")
    if not cache:
        print("❌ 没有可用样本 (全被跳过)")
        return 1

    i, told = 0, time.time()
    loss_acc, n_acc = 0.0, 0
    while i < steps:
        for enc0 in cache:
            enc = {k: (v.to("cuda") if hasattr(v, "to") else v) for k, v in enc0.items()}
            out = model(**enc)
            loss = out.loss / a.accum
            loss.backward()
            loss_acc += float(out.loss.detach())
            n_acc += 1
            if n_acc % a.accum == 0:
                torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
                i += 1
                if i % 5 == 0 or i == 1 or i == steps:
                    el = time.time() - told
                    print(f"   step {i}/{steps} loss {loss_acc/max(1,n_acc):.4f} "
                          f"lr {sched.get_last_lr()[0]:.2e} {el:.0f}s "
                          f"ETA {(el/max(1,i))*(steps-i):.0f}s "
                          f"显存 {torch.cuda.max_memory_allocated()/2**30:.2f}GB")
                    loss_acc, n_acc = 0.0, 0
            if i >= steps:
                break
    print(f"✅ 训练完成 {steps} 步 用时 {time.time()-t0:.0f}s · 峰值显存 {torch.cuda.max_memory_allocated()/2**30:.2f} GB")

    outdir = os.path.join(MODELS, f"l5_vlm_lora_{ts}")
    model.save_pretrained(outdir)
    print(f"💾 adapter → {os.path.relpath(outdir, ROOT)}")
    if a.merge and a.load_4bit:
        print("⚠️ 4-bit(QLoRA) 档不合并权重 (反量化合并会掉精度) ⇒ 部署用 adapter 目录本身")
    elif a.merge:
        merged = model.merge_and_unload()
        mdir = os.path.join(MODELS, f"l5_vlm_merged_{ts}")
        merged.save_pretrained(mdir, safe_serialization=True)
        proc.save_pretrained(mdir)
        print(f"💾 合并权重 → {os.path.relpath(mdir, ROOT)}")

    rep = {"ts": ts, "steps": steps, "samples": len(tr_rows), "adapter": outdir, "ckpt": ckpt,
           "load_4bit": bool(a.load_4bit), "peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2)}
    p = os.path.join(REPORTS, f"l5_vlm_train_{ts}.json")
    json.dump(rep, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"📄 训练报告 {os.path.relpath(p, ROOT)}")
    print(f"👉 同口径对照: 跑 --eval-only --adapter {os.path.relpath(outdir, ROOT)} (基座 vs LoRA, 同 val 帧)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
