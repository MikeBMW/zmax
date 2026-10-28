# 唯一依据改了 → 工程库 / 参数中心自动同步 (配置中心显示的数是哪来的)

配置中心 / 参数中心 / 画布侧栏「参数中心」上的数字都不是界面自己算的，链路是：

```
config/platform/*.json  (KPI 文案、产品特性、参数规格)  ← 唯一上游，人可编
        ↓ engineering_db.py build
zmax_engineering.db  (product_features / params / functions …)  ← 只读服务 8798 读它
        ↓ HTTP /api
配置中心 · 参数中心页 · 画布右侧栏「参数中心」
```

## 改一条指标文案的标准动作
1. 只改唯一依据 JSON，**不在 GUI 里硬写那串字**。先 grep 确认没有第二处源码内联：
   `grep -rn "头到孔底\|<旧串片段>" tools/ src/ config/` —— 命中的应是 `config/platform/*.json` 与生成物（`.db`）。
2. `python3 tools/engineering_db.py build` 重建库。
3. **两处都要回读，不只一处**：
   ```bash
   python3 -c "import sqlite3;c=sqlite3.connect('data/database/zmax/zmax_engineering.db');
   print(c.execute(\"select feature_id,kpi from product_features where feature_id='PF-…'\").fetchall())"
   python3 -c "import sqlite3;c=sqlite3.connect('data/database/zmax/zmax_engineering.db');
   print(c.execute(\"select param_id,cn,value,unit,source from params where cat='platform'\").fetchall())"
   ```
   `product_features.kpi` 对了 **不代表** `params` 对了（见下条）。
4. 8798 服务把库读进内存 ⇒ `sudo systemctl restart zmax-engdb.service`，再 `curl /summary` 看 `built_at` 变新。

## 🔴 参数中心是「从 KPI 文本现算」的：只看 product_features 会假统一
`params` 表里的数字/单位/中文名是从 KPI 串解析出来的（`param_registry.KPI_NUM`），而
`config/platform/param_spec.json` 里 `code=auto` 的播种行会带着**旧的** 中文名 / 单位 / 默认值。
后果：文案已改成 `节拍 <12秒`，库里却是「值 12、单位 mm、中文名还写着 头到孔底 <4mm」—— 界面看着像没改完。

**定式**
- `code=auto` 行的 cn / unit / default **一律以唯一依据现算为准**，只保留人工收紧的 `min/max/choices`；
  算完原子写回 `param_spec.json`（临时文件 + `os.replace`），下次 build 不会再被旧行覆盖。
- 中文单位（秒 / 毫秒 / 分钟 / 次 / 盘）必须进 KPI 数字正则，否则单位落成 `-`：
  `r"([<>≥≤]=?\s*)(\d+(?:\.\d+)?)\s*(%|mm|ms|s|Hz|kg|deg|N|秒|毫秒|分钟|次|盘)?"`
- 判据：改完必跑 `verify_param_center.py` + `verify_product_ui.py`，并在交付里写「唯一依据 JSON →
  product_features → params(cn/value/unit/default)」三处逐字段一致。

## 自动同步（不用人记 build）
- `python3 tools/engineering_db.py stale` → 逐份唯一依据 sha256 比对库里 `meta.sources`（另有 `meta.src_extra`
  存 `param_spec.json` / `zmax_product.json` / `zmax_perf_spec.json` 的文件 hash），落后打 `(True, 'platform 变了')`。
- `python3 tools/engineering_db.py ensure-fresh` → 落后才重建，没变零动作并打「✅ 工程库已是最新」。
- crontab 保障：`*/3 * * * * cd ~/zmax && /usr/bin/python3 tools/engineering_db.py ensure-fresh >> /tmp/zmax_db_sync.log 2>&1`
  换机器 / 新实例要重新装这条，否则又回到「JSON 已改、界面不变」。
- **验法不碰真值**：`cp 库 /tmp/t.db` → 把副本 `meta.sources` 写个假 sha → `is_stale` 应回 `(True, 'platform 变了')`
  → `ensure_fresh('/tmp/t.db')` 重建 → 再查回 `(False, '')`。只测「stale 能报」不测「能自愈」= 没验。

## 收尾口径
- 报数字：`stale` 输出 + 两个 verify 的条数（如 param_center 7/7、product_ui 47/47）。
- `check` 报红先分清是不是自己的改动：按失败项回查数据（例 `fn_notes 74/76` = 两条功能没描述），
  与本轮无关就如实说「旧红 + 缺哪两条」，**不要为了变绿去编内容**。
- 比对/哈希代码里别用和被调函数同名的循环变量（`for k,(p,_sha) in …: _sha(text)`）⇒
  `TypeError: 'str' object is not callable`，整条同步判据直接崩；循环变量加后缀（`_sha_v`）。
- 唯一依据 `config/`、`data/` 多被 `.gitignore` 排除（出厂骨架在 `defaults/`）⇒ 数据改动**不在 git 里**，
  别拿「git status 干净」当没生效；代码改动（engineering_db.py / param_registry.py）等验收后统一 commit+push。
