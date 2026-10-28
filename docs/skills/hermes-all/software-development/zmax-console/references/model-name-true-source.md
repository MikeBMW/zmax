# 「在役模型」列必须写**真实模型名**

触发: 用户说「在役模型的名字要改成真实模型的名字, 例如 L2 YOLO」「每层模型都要改成实际的模型」,
或你在某个面板里看到 `L2 在役 (指针)` / `L4 在役 (稳定指针)` 这种只描述**指针种类**的名字。
(2026-10-14 老倪原话; 当时模型引擎窗口 + 配置通道 + 大屏 dashboard.json 都是这种写法。)

## 铁律
1. **真名唯一依据(按优先级; 与配置通道用同一条规则 ⇒ 两处必然同值)**
   - ① `http://127.0.0.1:8796/status/all` 里该层 `state=in_service` 的 `name` = 引擎**实际**加载的模型:
     - L2 `YOLO 检测 + 2D→3D 解算 (真机域在役)`
     - L3 `SmolVLA+LEW 长程规划 (在役运行时 ckpt)`
     - L4 `INTACT-JEPA 意图-动作 (在役稳定指针)`
     - L5 `DeepSeek 视觉规划 (L5 大模型主路)`
   - ② 保障 = `tools/model_inventory.py` 在役行名 —— 它自己读 `models/active_models.json` 的 `name`
     (各层在役指针/软链的唯一依据; 换模型=改这里), 别在代码里再写第二份。
   - ③ 只有**产物自身元数据**能证明的身份才当真名: 如 L5 本地 merged 的 `config.json`
     `architectures[0]=SmolVLMForConditionalGeneration` ⇒ 名 `SmolVLM`。读不到就写 `名称唯一依据未登记`, **不许编模型名**。
2. **名与权重路径必须指同一个东西**。引擎报的名与磁盘产物家族不同时(实测 L5: 引擎在役 = DeepSeek 云端 API 主路,
   磁盘另有本地 merged = SmolVLM), 列里保留引擎名, **tooltip 必须写明**磁盘上另有哪个模型 ——
   不许名字和路径各指一个东西还装作一致。
3. **列宽是硬约束**(在役模型列 340px): 真名超宽就按像素预算收显示串(先摘尾部括号限定词, 再逐字截 + `…`),
   **完整名常驻 tooltip**; 不许 `ElideNone` 硬切, 也不许把列撑变形。
4. **名字只带一个层前缀**: inventory 末尾拼 `f"{layer} · {name}"`, 而 candidate 名自身已写成 `L2 候选 · …`
   ⇒ 直接拼会出 `L2 · L2 候选 · …`(大屏 `dashboard.json` 实测就是这样)。拼之前先
   `re.sub(r"^L<n>\s*(?:·\s*)?", "", name)` 收口。
5. **改完名字要顺带重生成所有派生物**(快照是落盘的, 不会自己跟着变):
   - `tools/dashboard_source.py` ⇒ `tools/web/dashboard.json` · `tools/web/unified_app.html` · `zmax_data/datapush/dashboard.json`
   - 再把 `tools/web/unified_app.html` 覆盖到 `tools/web/state3d_app/dash/src/main/assets/unified_app.html`
     (手机 APK 离线页, 没有自动同步步骤)
   - 配置中心「模型配置」域的名字在 `tools/mcd_build.py`(`model.ckpt_l2` 等, 已是 `L2 在役权重 (YOLO)` 真名)
   - 收尾: `grep -rn "在役 (指针)\|L2 · L2" tools/web/ zmax_data/datapush/` 必须为空

## 判据 (钉住, 不靠目检)
`tools/verify_model_engine_unified.py`:
- ⑮ 四层在役名含真实家族词(YOLO/SmolVLA/INTACT/DeepSeek|SmolVLM)
- ⑮b 窗口「在役模型」与配置通道「在役模型」逐字同值(两处不许两套名)
- ⑮c 旧硬写名字已从唯一依据代码里消失(只查代码行, 忽略注释, 否则自己的注释会假报失败)
- ⑮d 列里被收的完整真名 + 家族冲突说明都在 tooltip
- 配套: `tools/verify_model_engine_same_render.py` 11/11(两处界面同一份渲染)

## 坑
- 矩阵 `build()` 的 rows 是**列优先**结构: `{"name": "在役模型", "vals": {"L2": …, "L5": …}}` ——
  取法应是 `{r['name']: r['vals'] for …}['在役模型']`, 写成 `r['vals']['在役模型']` 会 KeyError。
- 判据里读面板行要在 `win.panel.feed(inv, st)` 之后取 `win.panel._rows_cache`; 表格里同一层可能既有
  在役行也有候选行, 按第 0 列文字(`🔎 L2 · 候选` vs `L2`)定位, 别按行号猜。
- `zmax-console/SKILL.md` 已顶到 100k 上限: **新增写作放 references/, 不要再往 SKILL.md 追长段**。
