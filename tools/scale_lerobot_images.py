#!/usr/bin/env python3
"""把 lerobot 数据集里的图像缩到 128x128 重存一份 —— 降内存占用 (480x640 解码后常驻 8.4G → 0.6G)

背景: 15:54 整机冻死的根因 = 训练 dataloader 把 9171 帧 480x640 全解成 PIL 常驻 (Anonymous 8.4G),
      叠加 7 个常驻模型进程 → 30G 吃满 → 系统不再写日志, 硬重启。
      而 policy 本来就把图 resize 到 64/128, 480x640 纯浪费内存/解码时间。

用法: python tools/scale_lerobot_images.py <src_dir> <dst_dir> [--size 128]
"""
import io
import json
import shutil
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

IMG_KEY = "observation.images.top"


def main():
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    size = 128
    if "--size" in sys.argv:
        size = int(sys.argv[sys.argv.index("--size") + 1])

    files = sorted((src / "data").rglob("*.parquet"))
    if not files:
        sys.exit(f"没找到 parquet: {src}/data")

    (dst / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    rows = 0
    for f in files:
        rel = f.relative_to(src / "data")
        out = dst / "data" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        pf = pq.ParquetFile(f)
        writer = None
        for batch in pf.iter_batches(batch_size=200):
            tbl = pa.Table.from_batches([batch])
            col = tbl.column(IMG_KEY).combine_chunks()
            if not pa.types.is_struct(col.type):
                sys.exit(f"{IMG_KEY} 不是 struct: {col.type}")
            paths = col.field("path")
            new_bytes = []
            for b in col.field("bytes"):
                if b is None or b.is_valid is False:
                    new_bytes.append(None)
                    continue
                raw = b.as_py()
                if raw is None:
                    new_bytes.append(None)
                    continue
                im = Image.open(io.BytesIO(raw)).convert("RGB").resize((size, size), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=92)
                new_bytes.append(buf.getvalue())
            new_col = pa.StructArray.from_arrays(
                [pa.array(new_bytes, type=pa.binary()), paths], names=["bytes", "path"]
            )
            i = tbl.schema.get_field_index(IMG_KEY)
            tbl = tbl.set_column(i, IMG_KEY, new_col)
            if writer is None:
                writer = pq.ParquetWriter(out, tbl.schema)
            writer.write_table(tbl)
            rows += tbl.num_rows
        if writer:
            writer.close()
        print(f"  {f.name}: 累计 {rows} 行", flush=True)

    # meta 全量复制, 只改图像 shape
    if (dst / "meta").exists():
        shutil.rmtree(dst / "meta")
    shutil.copytree(src / "meta", dst / "meta")
    info_p = dst / "meta" / "info.json"
    info = json.loads(info_p.read_text())
    info["features"][IMG_KEY]["shape"] = [size, size, 3]
    info_p.write_text(json.dumps(info, indent=4))
    if (src / "images").exists():
        shutil.copytree(src / "images", dst / "images", dirs_exist_ok=True)

    # 校验
    chk = pq.ParquetFile(sorted((dst / "data").rglob("*.parquet"))[0])
    sample = next(chk.iter_batches(batch_size=1))
    im = Image.open(io.BytesIO(sample.column(IMG_KEY)[0].as_py()["bytes"]))
    print(f"OK · {rows} 行 · 样本图 {im.size} {im.mode} · dst={dst}")
    print(f"体积: {sum(p.stat().st_size for p in dst.rglob('*') if p.is_file())/1e6:.0f} MB")


if __name__ == "__main__":
    main()
