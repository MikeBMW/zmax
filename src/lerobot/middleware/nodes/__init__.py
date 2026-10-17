# -*- coding: utf-8 -*-
"""状态空间**每个节点一个模块** (生成物 · tools/gen_middleware_nodes.py 维护)。

打开任意一个 n_*.py: 文件头就是这个节点的输入输出与工程连线, 下面 compute(ctx) 是
"从总线取数 → 算出结果 → 发回总线"的代码本体。

不要在这里手改端口 —— 端口真源是 flows/state_space_obs.json。
"""
