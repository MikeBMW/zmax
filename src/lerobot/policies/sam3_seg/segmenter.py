# -*- coding: utf-8 -*-
"""SAM3 开放词汇分割 —— 算法内核 (模型加载 · 前向 · 掩膜)

归属: 与 `policies/yolo_3d/` 同级 —— **感知前端在 policies/ 下统一管理**
(策略(动作) 与 感知(状态输入) 同层级; 调用方/服务/CLI 留在 tools/)。

职责边界 (别越层):
  · 本文件只做"一帧图 + 概念提示词(文本/框/点) → 该概念的**所有实例掩膜**(像素级)+框+分数"。
  · **不自造概念**: 提示词由调用方给(L5 的 VLM/人/工单)。
  · 深度/手眼/TCP 相关的 3D 反解在 `geometry3d.py`; 帧来源在 `frame_source.py`。

权重: 官方 `facebook/sam3` 在 HF 是 gated(需审批) ⇒ 本机用**逐文件镜像**落盘(见 SAM3_DIR),
      加载一律 `local_files_only=True`(不联外网, 也避免半截文件被当权重)。
许可: SAM License —— 允许商用; 禁军事/ITAR; 再分发须附 LICENSE。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np

# ── 运行参数 (env 可覆盖: 换盘/换机/显存不够时降分辨率) ──────────────────────
SAM3_DIR = os.environ.get("ZMAX_SAM3_DIR", "/home/ubuntu/zmax_data/models/sam3_hf")
SAM3_DTYPE = os.environ.get("ZMAX_SAM3_DTYPE", "bf16")            # bf16 | fp16 | fp32
SAM3_SIZE = int(os.environ.get("ZMAX_SAM3_SIZE", "1008"))         # 原生输入边长 1008
MIN_AREA_PX = int(os.environ.get("ZMAX_SEG_MIN_AREA", "200"))     # 掩膜最小面积(滤碎块)
POLY_EPS_PX = float(os.environ.get("ZMAX_SEG_POLY_EPS", "1.5"))   # 轮廓简化容差(px)
# 可选微调适配器 (SAM3 框提示式 LoRA 微调产物)。**默认不开** —— 未证明提升的产物不进默认档。
# 启用: ZMAX_SAM3_ADAPTER=/path/to/lora_adapter (目录) 或 .../adapter_model.safetensors (文件)
SAM3_ADAPTER = os.environ.get("ZMAX_SAM3_ADAPTER", "").strip()


class Sam3Segmenter:
    """SAM3 提示式概念分割 (PCS): 文本/框 → 所有匹配实例的掩膜。

    显存口径: 848M 参数, bf16 ≈1.7GB, 1008² 输入 ⇒ 与别的模型**同刻只有一个**
    (本机红线)。所以按需加载 + 可 unload, 由常驻服务持有单例。
    """

    def __init__(self, model_dir: str | os.PathLike | None = None, dtype: str | None = None,
                 size: int | None = None):
        self.model_dir = Path(model_dir or SAM3_DIR)
        self.dtype_name = (dtype or SAM3_DTYPE).lower()
        self.size = int(size or SAM3_SIZE)
        self.model = None
        self.proc = None
        self.device = None
        self.load_s = None
        self.adapter = None            # 可选适配器取证 dict (默认 None = 纯基座)
        self.base_params = 0
        self.vram_alloc_gb = 0.0

    # ── 加载/卸载 ────────────────────────────────────────────────────────
    def ensure(self, verbose: bool = False):
        if self.model is not None:
            return self
        import torch
        from transformers import Sam3Model, Sam3Processor

        if not (self.model_dir / "model.safetensors").exists():
            raise FileNotFoundError(
                "SAM3 权重不在位: %s/model.safetensors (下载脚本 .hermes/cache/scratch/sam3_dl2.sh)" % self.model_dir)

        dev = "cuda" if torch.cuda.is_available() else "cpu"
        if dev == "cpu" and self.dtype_name != "fp32":
            self.dtype_name = "fp32"
        dt = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[self.dtype_name]

        t0 = time.time()
        proc = Sam3Processor.from_pretrained(str(self.model_dir), local_files_only=True)
        try:                                                     # 输入边长(显存不够时降)
            proc.image_processor.size = {"height": self.size, "width": self.size}
        except Exception:                                        # noqa: BLE001
            pass
        model = Sam3Model.from_pretrained(str(self.model_dir), local_files_only=True, dtype=dt).to(dev)
        model.eval()
        self.model, self.proc, self.device = model, proc, dev
        self.base_params = sum(p.numel() for p in model.parameters())
        self.load_s = time.time() - t0

        # ── 可选适配器 (默认关; 见模块顶部 SAM3_ADAPTER) ─────────────────────
        # 键不匹配一律抛错 (不静默降级成纯基座 —— 那会让"接了适配器"成为假象)。
        ad = os.environ.get("ZMAX_SAM3_ADAPTER", SAM3_ADAPTER).strip()
        if ad:
            from . import finetune as _ft
            from .lora_inject import load_lora_adapter
            # ⚠️ prefix_filter **只对视觉塔**生效 (与训练侧 build_trainable_model 同口径):
            # 文本塔 24 层全注入 (CLIP 序列极短, 不吃显存); 若把"最后 N 个 block"也套到文本塔,
            # 索引 0..23 全部不满足 i>=24 ⇒ 静默少注入 96 个 Linear ⇒ 适配器键对不上直接抛错。
            pf = {"vision_encoder.backbone.layers.":
                  (lambda i, N=_ft.VIT_LORA_BLOCKS: i >= 32 - N)}
            self.adapter = load_lora_adapter(model, ad, targets=dict(_ft.LORA_TARGETS), r=_ft.R,
                                             alpha=_ft.ALPHA, prefix_filter=pf, log=print)
            self.adapter["base_dir"] = str(self.model_dir)
            self.adapter["base_dtype"] = self.dtype_name
            model.eval()
        else:
            self.adapter = None
        if dev == "cuda":
            torch.cuda.reset_peak_memory_stats()          # 前向峰值从**加载完**起算 (含适配器)
            self.vram_alloc_gb = torch.cuda.memory_allocated() / 1e9
        if verbose:
            n = self.base_params / 1e6
            print("[sam3] 加载完成: %.1fs · %s · %s · %.1fM 参数 · 输入 %dpx"
                  % (self.load_s, dev, self.dtype_name, n, self.size))
            print("[sam3] 适配器: %s" % ("未启用 (纯基座)" if not self.adapter
                                         else "%s · %d 张量 · 非零 lora_B %d"
                                         % (self.adapter["path"], self.adapter["n_tensors"],
                                            self.adapter["nonzero_lora_B"])))
            if dev == "cuda":
                print("[sam3] 显存: 已用 %.2f GB / 共 %.2f GB"
                      % (torch.cuda.memory_allocated() / 1e9,
                         torch.cuda.get_device_properties(0).total_memory / 1e9))
        return self

    def mem(self) -> dict:
        """加载后至今的显存: 已用 / **前向峰值** (服务 /health 取证用)。"""
        try:
            import torch
            if torch.cuda.is_available():
                return {"alloc_gb": round(torch.cuda.memory_allocated() / 1e9, 2),
                        "forward_peak_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
                        "total_gb": round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2)}
        except Exception:                                    # noqa: BLE001
            pass
        return {}

    def unload(self):
        import torch
        self.model = self.proc = None
        self.adapter = None
        self.load_s = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return True

    def state(self) -> dict:
        return {"model_dir": str(self.model_dir), "loaded": self.model is not None,
                "device": self.device, "dtype": self.dtype_name, "size": self.size,
                "load_s": self.load_s, "min_area_px": MIN_AREA_PX,
                "base_params_m": round(self.base_params / 1e6, 1),
                "adapter": self.adapter,
                "mem": self.mem()}

    # ── 推理 ────────────────────────────────────────────────────────────
    def segment(self, img_bgr: np.ndarray, texts: list[str] | None = None,
                threshold: float = 0.5, mask_threshold: float = 0.5,
                boxes: list | None = None, box_labels: list | None = None) -> dict:
        """一帧(BGR ndarray) + 概念提示词 → {instances:[{label,score,box_xyxy,area_px,mask}], ms, size}

        ⚠️ 实测坑 (2026-09-29): `Sam3Processor(text=[c1,c2,c3])` 一次喂**多个概念会崩**
        (`Sam3Attention.forward` 里 `view(1,32,8,32)` 收到 24576 个元素 —— 提示特征被按 3 个概念
        拼成了 3×256 维, 而实现按单概念的 heads×head_dim 切) ⇒ **一个概念一次前向**, 本函数按
        texts 逐个跑再合并。单概念热推理 ≈0.4s (4060, bf16, 1008px, 显存 2.1GB)。

        boxes/box_labels: 可选视觉提示([[x1,y1,x2,y2], ...] / [1 正, 0 负]) —— 用于"人在环"精修。
        """
        import cv2
        import torch
        from PIL import Image

        self.ensure(verbose=False)
        texts = [str(t).strip() for t in (texts or []) if str(t).strip()]
        H, W = img_bgr.shape[:2]
        pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))

        def _one(text: str | None) -> list:
            kw: dict = {"images": pil, "return_tensors": "pt"}
            if text:
                kw["text"] = text
            if boxes:
                kw["input_boxes"] = [boxes]
                if box_labels:
                    kw["input_boxes_labels"] = [box_labels]

            inputs = self.proc(**kw)
            # 数值张量按**模型 dtype**搬上去 (处理器默认给 float32; 直接喂 bf16 模型会
            # `mat1 and mat2 must have the same dtype` —— 2026-10-01 实测: 框提示路径因此整条 500)。
            # 注意 `getattr(torch, "bf16")` 取的是 torch.bfloat16 的**别名不存在** ⇒ 会静默抛异常
            # 走 except 分支把 float32 原样送上卡, 所以这里用显式映射表 (与训练侧 build_inputs 同一口径)。
            _dt = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[self.dtype_name]
            for k, v in list(inputs.items()):
                if not hasattr(v, "to"):
                    continue
                try:
                    if v.dtype in (torch.float32, torch.float64) and k != "original_sizes":
                        inputs[k] = v.to(self.device, _dt)
                    else:
                        inputs[k] = v.to(self.device)
                except Exception:                                # noqa: BLE001
                    inputs[k] = v.to(self.device)

            with torch.no_grad():
                out = self.model(**inputs)
            res = self.proc.post_process_instance_segmentation(
                out, threshold=threshold, mask_threshold=mask_threshold,
                target_sizes=inputs.get("original_sizes").tolist())[0]

            masks, scores = res.get("masks"), res.get("scores")
            lab = res.get("labels") or res.get("text_labels") or []
            got = []
            if masks is None or not len(masks):
                return got
            m_np = masks.detach().cpu().numpy()
            if m_np.dtype != bool:
                m_np = m_np > 0.5
            for i in range(m_np.shape[0]):
                m = m_np[i]
                if m.ndim == 3:
                    m = m[0]
                area = int(m.sum())
                if area < MIN_AREA_PX:
                    continue
                ys, xs = np.nonzero(m)
                lbl = str(lab[i]) if isinstance(lab, (list, tuple)) and i < len(lab) else ""
                if not lbl:
                    lbl = text or "?"
                got.append({"label": lbl,
                            "score": float(scores[i]) if scores is not None else None,
                            "box_xyxy": [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())],
                            "area_px": area, "mask": m, "concept": text})
            return got

        t0 = time.time()
        if texts:
            inst = []
            for t in texts:                                      # 一概念一前向 (见上面的坑)
                inst.extend(_one(t))
        else:                                                    # 无文本 ⇒ 纯视觉提示(框/点)或给 presence
            inst = _one(None)
        ms = (time.time() - t0) * 1000
        return {"instances": inst, "ms": ms, "size": [W, H], "texts": texts,
                "threshold": threshold, "mask_threshold": mask_threshold,
                "model_dir": str(self.model_dir), "dtype": self.dtype_name,
                "n_forward": len(texts) or 1}

    @staticmethod
    def mask_to_polys(mask: np.ndarray, eps: float = POLY_EPS_PX) -> list:
        """二值掩膜 → 多边形点集(外轮廓, 简化) —— 叠加规格/页面命中共用这一份几何"""
        import cv2
        m = (mask.astype(np.uint8) * 255)
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        for c in cnts:
            if cv2.contourArea(c) < MIN_AREA_PX:
                continue
            ap = cv2.approxPolyDP(c, eps, True)
            if len(ap) < 3:
                continue
            out.append([[int(p[0][0]), int(p[0][1])] for p in ap])
        return out


# ── 模块级默认实例 (调用方最常用的一行式 API) ──────────────────────────────
DEFAULT = Sam3Segmenter()


def load_model(verbose: bool = True) -> Sam3Segmenter:
    return DEFAULT.ensure(verbose=verbose)


def unload_model() -> bool:
    return DEFAULT.unload()


def state() -> dict:
    return DEFAULT.state()


def segment(img_bgr: np.ndarray, texts: list[str] | None = None, threshold: float = 0.5,
            mask_threshold: float = 0.5, boxes: list | None = None,
            box_labels: list | None = None) -> dict:
    return DEFAULT.segment(img_bgr, texts, threshold, mask_threshold, boxes, box_labels)


def mask_to_polys(mask: np.ndarray, eps: float = POLY_EPS_PX) -> list:
    return DEFAULT.mask_to_polys(mask, eps)
