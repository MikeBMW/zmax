# 参数中心 ↔ 工程库（全局可改数字）维护要点

适用: 给参数中心新增一组可改数字; 参数总数变了要重跑判据; 工程库数字与 GUI 文案对不上。

## 1. 参数中心的结构
- 注册表 = `tools/param_registry.py`; GUI 页 = `tools/gui/param_center.py`; 真源 = 各领域的文件(标定/画布/代码常量/平台/开关/空间点/号位示教点/场景数据)。
- 现有分组(名称: 组): calib 标定/真源参数 · canvas 画布节点数据 · code 代码常量 · platform 平台 · switch 开关 · space 空间点 · teach 号位/示教点 · **scene 场景数据(对象/标记)**。
- 新增一组要动**五处**: 顶部常量(真源路径) → `scan_<组>()` → `scan()` 汇总里相加 → `set_param` 里的写分支 → `CAT_COLOR`/`CAT_CN`(GUI 颜色与中文名)。只加扫描不加写分支 ⇒ 看得到改不了。

## 2. 两个硬规则（破坏了必被判据抓）
- **`params.source` 必须是能 `os.path.join(ROOT, source)` 直接命中的相对路径**(如 `data/scene/objects3d.json`)。工程库判据⑧b 就是这么判真源在不在盘上的; 写成 `json:data/...` 这种带前缀的指针 ⇒ 报「每个数字的真源都在盘上」缺一大片。`json:` 那样的指针只能放 `ref` 字段。
- **只能一个写路径**: 新数据领域已经在别处有专用写入口(如场景 = `tools/scene_edit.py`)时, param_registry 的写分支必须**子进程调那个入口**, 自己绝不写 JSON。两处都写 = 两套备份/回读/校验逻辑打架。

## 3. 写前哨与量纲
- 点类(空间点/号位): 位置包络 ±1.2m + 互距<1mm 只拦**新产生**的重合对; 微调工具 `tools/adjust_point_offset.py` 上限 ±20mm。
- 场景对象: center 单位 m(step 1e-4, ±3m) / size 单位 mm(step 0.1, 0.1~2000)。
- 干跑与真写都返回 JSON: `{ok, written, old, new, msg, chain}`。**只看 exit code 会把干跑当成功** —— 必须读 `ok`/`written`; `written=False` 就是没写进去(如子进程抛错)。

## 4. 改完必跑的判据
- `tools/engineering_db.py build` 然后 `check` —— 参教/链接条数会变(每加一组就重建), 要求 `✅ 判据全绿`。
- `tools/verify_param_center.py`(参数中心链动) · `tools/verify_platform_spec.py`(工程库+功能清单页) · `tools/audit_console_consistency.py`(带数字文案 vs 工程库真值)。
- GUI 里的数字**一律从工程库现算**(studio._live_counts 风格, 按库 mtime 缓存), 不得写在文案里——写死的数字会在下一次加参数时静默漂移, 而“一致性体检”正是拿库比文案。

## 5. CLI 速查
```
python3 tools/param_registry.py scan|stats|list|show <id>|set <id> <value> [--write]|verify|chain <id>|seed
python3 tools/engineering_db.py build|check
```
