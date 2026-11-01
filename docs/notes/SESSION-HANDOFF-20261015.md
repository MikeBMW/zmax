# 交接快照 · 2026-10-15 (关机前保存)

**当前版本: v5.50.730 · 代号「北斗七星版」** (版本号由老倪指定, 不再自主升级)
**控制台**: `XSpace Console — Z-MAX v5.50.730` (重启命令 `bash tools/studio_ctl.sh restart --force`)
**仓库**: 本地 == 远端 (main), tag `v5.50.730` 已推; 工作区干净; 守卫全绿 (完整性 / repo_guard 62.4MB / secret_scan)

## 本轮落地 (北斗七星版)

1. **配置中心 = 北斗七星阵**: 左树仅 7 行 `N. 名称 · 星名` (1 产品配置·天枢 … 7 文档配置·瑶光), 页签名 = 配置名, 点左树/星图**真跳页**;
   每页顶部阵图条 (标题/别号/五行/定义/关系/**本页唯一依据**/七星星图)。
2. **模型配置页 = 功能配置 ←→ L2/L3/L4/L5 层模型映射** (本页主要信息): 四层在役一行一层 (层/职责/主模型/版本/状态/附加在役/承载功能数/模型来源)
   + 全量映射表 74 行 (组合层 L4/L5 一行列两条模型; 平台支撑 13 条明写"不归属层模型")。
   层模型名与版本**取主控制台模型矩阵** `tools/model_config_matrix.py --json` (L5 = DeepSeek 视觉规划), 避免与 `model_inventory` 两边打架。
3. **产品配置页** 复用「🏭 Z-MAX 平台」页描述 (平台描述/平台产品/产品特性 23 条), 与主控制台左侧卡面同源 (`tools/gui/zmax_platform_info.py`)。
4. **功能配置页** 收 系统2/1/0 + 平台支撑 全部 **74 条功能** + 汇总; 功能表带「专利渠道」列。
5. **UI 修**: 底部信息窗改竖直分隔条 (可拖/可收起/内容随当前配置面) · 每页包 `QScrollArea` (可滚) · 表格给足最小高度 (不再"根本看不到")。
6. **专利** (老倪 2026-10-15 令):
   · 唯一依据 `config/patents/patent_registry.json` (编写稿 `config/patents/drafts/`), 生成器 `tools/patent_center.py` (`--build|--coverage|--export|--preview`)。
   · **12 件发明专利, 8 类层次; 功能渠道 74/74 条全部挂上 (未挂 0)**。
   · 文档 `docs/patents/` = 12 md + 12 docx + `00_专利申请渠道清单.md`; 文档内数据全部**唯一依据现算**; 落地引用 39 条**逐条真实存在**。
   · 文档配置页新增「📜 专利」块, 与 SOR/项目立项/合作协议**同页同级共用预览窗**。
   · **待填**: 申请人主体 / 发明人署名 / 申请号·公开号 (提交后回填)。

## 判据 (交付前必跑, 当前全绿)

| 判据 | 结果 |
|---|---|
| `tools/verify_config_center_seven_stars.py` | 18/18 |
| `tools/verify_config_center_info_panel.py` | 27/27 |
| `tools/verify_patent_channel.py` | 23/23 |
| `tools/verify_product_ui.py` | 51/51 |
| `tools/verify_task_order_split.py` | 28/28 |
| `tools/tests/test_config_center_domains.py` | 全过 |

出图: `docs/data_snapshots/20261015_config_center_seven_stars/` (real_1..7: 天璇/天枢/天玑/玉衡/性能配置点左树/文档配置专利/模型配置层映射)

## 未完成 / 待定 (下次接着做)

1. **专利署名**: 申请人主体 + 发明人 (老倪未给, 不敢编); 现文档明写"待填"。
2. **元任务预测输入退化**: 7 场景驱动扭矩完全相同 (‖T‖ = 51.9615 N·m) ⇒ 预测无区分度; 需换输入口径。
3. **真机网卡此刻不在位** (`enxeae07a800a2f` UNKNOWN; .23.23 / .23.66 100% 丢包) ⇒ AOI 10083 曝光写不了、真机动作不可达 (纪律: 拒发)。
   链路一回先做曝光扫描 80000/40000/30000/16000us。
4. **YOLO 域偏移**: 真机帧 best conf 仅 0.219 (≥0.40 → 0 框) ⇒ 需曝光救画面 + 真机在役帧域适应微调 (口径: 报数必带 imgsz/conf)。
5. **CI 出包队列**: v5.50.73~79 与 v5.50.730 的 Windows/macOS 包仍在跑; 落地后核字节数。
   `v5.50.80` 的 Release 已按老倪要求**删除**, 其 CI 已取消; v5.50.730 的 Release 已署名为「北斗七星版」。
6. 遗留: L5 DeepSeek 视觉 300s 超时回包空 / INTACT `z_pred` 全 NaN / LoRA A-B 未证明提升 / `ss_moe` 无执行注册 / 视觉安全闸 `safe=false`。

## 恢复命令

```bash
cd ~/zmax && bash tools/studio_ctl.sh restart --force                # 起控制台 (窗口标题应显示 v5.50.730)
./gui-venv311/bin/python tools/patent_center.py --coverage            # 专利渠道 74/74
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_config_center_info_panel.py   # 27/27
```
