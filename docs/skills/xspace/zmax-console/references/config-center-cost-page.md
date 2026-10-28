# 配置中心加一页 + 成本/报价单一唯一依据 (2026-10-19 实操)

## 加页规程 (veh6_config_page.py)
1. 页构建器 `_cost_page(self, th)` 返回 QWidget; 调用处 `self.tabs.addTab(_scrollable(self._cost_page(th), th), "💰 成本/报价")`
   放在**末尾**(保既有页序号), 整体 try/except 包住, 构造失败时挂一个红字页而不是让整页崩。
2. `_TAB_ORDER` 加同一个关键字 —— 北斗次序用 `_kw in tabText` 匹配, 忘加它只会排到最后 (不报错, 但用户看到的顺序不对)。
3. 记住页签 `cc_last_tab.txt` 存的是**页名**, 新页无需迁移。
4. 页宽/文字: 每个 QLabel 都会被页级扫描设成可选中 (NoTextInteraction → TextSelectableByMouse), 新页零额外工作。

## 成本/报价的唯一依据与唯一公式
- 参数唯一依据 `config/platform/zmax_cost_model.json` (**只存输入**: hardware[] + software.price + labor.cost_per_person_year + line{stations,shifts,persons_per_shift} + alt_arm.saving)。
- 公式只写在 `tools/cost_model.py`: `total = hw + sw` · `annual = stations*shifts*persons*labor` · `payback = total/annual` · `alt_total = total - alt`。
  配置中心页 / 命令行 / 以后的立项文档和画布节点**都调它**, 页面里不写第二套算式。
- **派生值不落盘**: 文件里不许出现 total/payback/annual_save 键 (回不来也没人改得对); 判据里显式断言 `not any(k in d for k in (...))`。
- 写回只写 6 个假设: `save_line()` 读-改-写单键 + `.bak_时间戳` + **回读比对**; 页面拿到 `ok=False` 时红字「别按这个数报价」。

## 页面结构 (老倪认可的形态, 一屏)
BOM 表 (部件/型号/单价/状态 + 合计行) → 6 个可改假设 (QSpinBox/QDoubleSpinBox, `valueChanged→refresh()`, 不用点按钮) → 结果块 (单套投入/年节省/静态回本/替代臂, 各一行, 且**写清口径**「不计折现/质量损耗/增产」) → 4 个按钮 (重新估算/写入唯一依据/复制TSV/导出JSON) → 一行状态。
万元与元的换算只发生在界面上 (`*1e4` 进出), 唯一依据一律元。

## 判据 (tools/verify_cost_page.py, 32 项, 全过才算交付)
默认口径逐项数值 · 改 1 个输入即重算 (1→2 工位: 36 万/1.01 年) · 页面文字里真出现那些数字 (不只存变量) · 页面结果与 `cost_model.estimate()` 逐字段相同 (同源) · BOM 行数=唯一依据项数+1 · 写回后唯一依据真变+备份生成+字节级还原 · 导出 JSON 回读一致 · 剪贴板 TSV · 画布 mtime 未变 · 页签总数=原 N+1。

## 覆盖旧页判据
加页后必须复跑 `verify_product_ui.py` (47/47) 与 `verify_config_center_text_copy.py` (15/15) —— 后者会数全页 QLabel, 新页控件若没被扫描到会当场红。
