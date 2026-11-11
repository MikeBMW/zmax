# -*- coding: utf-8 -*-
"""AOI 本机镜像服务 —— 产线 10082/10083 的代码原样搬过来跑旁路。

    service/prod/        产线现役文件 (逐字节一致, sha256 见 prodload.PROD_SHA256)
    service/stubs.py     Windows SDK 桩 (只为能加载, 绝不伪造相机成功)
    service/prodload.py  加载器 + judge_gold/judge_surface (与产线同一份判据)
    service/sources.py  帧源 (remote/cam/file/dir/push)
    service/app.py       路由 (对齐 /capture_detect /picture /crop_info /last_result ...)
    service/run.py       命令行入口
    client.py            节点侧客户端 (local_bypass)
"""
from .prodload import judge_gold, judge_surface, load, info, PROD_SHA256   # noqa: F401

__all__ = ["judge_gold", "judge_surface", "load", "info", "PROD_SHA256"]
