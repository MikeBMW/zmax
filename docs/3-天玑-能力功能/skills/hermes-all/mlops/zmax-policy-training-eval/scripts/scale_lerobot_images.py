#!/usr/bin/env python3
"""把 lerobot 数据集里的图像预缩到 policy 输入尺寸, 另存一份 —— 解决训练时 dataloader 全量解码吃内存

为什么: image dtype 的 lerobot 数据集在训练时会把帧解成 PIL 常驻匿名内存, 量级 = 帧数×H×W×3×4B
        (9171 帧 480x640 => 8.4G)。而 policy 反正要 resize 到 resize_images_to/siglip_image_size(64~128),
        原分辨率纯浪费; 叠在常驻模型栈上会直接冻死整机。
实测: 480x640 -> 128x128, 数据集 2.2G -> 48M, 训练加载内存 8.4G -> 0.45G, 画质对 policy 无损。

用法: python tools/scale_lerobot_images.py <src_dir> <dst_dir> [--size 128] [--quality 92]
注意: 缩完要把 policy 的 resize_images_to 也改成 --size, 否则二次缩小白亏。
"""
import io
import json
import shutil
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

# lerobot 的 image feature 是 struct{bytes, path}; 多相机时按需改这个键
IMG_KEY = "observation.images.top"


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    size = int(sys.argv[sys.argv.index("--size") + 1]) if "--size" in sys.argv else 128
    quality = int(sys.argv[sys.argv.index("--quality") + 1]) if "--quality" in sys.argv else 92
    files = sorted((src / "data").rglob("*.parquet"))
    if not files:
        sys.exit(f"没找到 parquet: {src}/data")
    (dst / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)

    rows = 0
    for f in files:
        out = dst / "data" / f.relative_to(src / "data")
        out.parent.mkdir(parents=True, exist_ok=True)
        writer = None
        for batch in pq.ParquetFile(f).iter_batches(batch_size=200):
            tbl = pa.Table.from_batches([batch])
            col = tbl.column(IMG_KEY).combine_chunks()
            paths = col.field("path")
            new_bytes = []
            for b in col.field("bytes"):
                raw = b.as_py() if (b is not None and b.is_valid) else None
                if raw is None:
                    new_bytes.append(None)
                    continue
                im = Image.open(io.BytesIO(raw)).convert("RGB").resize((size, size), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=quality)
                new_bytes.append(buf.getvalue())
            new_col = pa.StructArray.from_arrays(
                [pa.array(new_bytes, type=pa.binary()), paths], names=["bytes", "path"]
            )
            tbl = tbl.set_column(tbl.schema.get_field_index(IMG_KEY), IMG_KEY, new_col)
            if writer is None:
                writer = pq.ParquetWriter(out, tbl.schema)
            writer.write_table(tbl)
            rows += tbl.num_rows
        if writer:
            writer.close()
        print(f"  {f.name}: 累计 {rows} 行", flush=True)

    if (dst / "meta").exists():
        shutil.rmtree(dst / "meta")
    shutil.copytree(src / "meta", dst / "meta")
    info_p = dst / "meta" / "info.json"
    info = json.loads(info_p.read_text())
    info["features"][IMG_KEY]["shape"] = [size, size, 3]
    info_p.write_text(json.dumps(info, indent=4))
    if (src / "images").exists():
        shutil.copytree(src / "images", dst / "images", dirs_exist_ok=True)

    chk = pq.ParquetFile(sorted((dst / "data").rglob("*.parquet"))[0])
    im = Image.open(io.BytesIO(next(chk.iter_batches(batch_size=1)).column(IMG_KEY)[0].as_py()["bytes"]))
    print(f"OK · {rows} 行 · 样本图 {im.size} {im.mode} · dst={dst}")
    total = sum(p.stat().st_size for p in dst.rglob('*') if p.is_file())
    print(f"体积: {total/1e6:.0f} MB")


if __name__ == "__main__":
    main()
