# v5.50.740 · 核心归位到src+调试停跳+跨平台打包+三产品同步

- 版本: v5.50.740 (判据全否见 judge_*.txt)
- git: a0ad25761f4b · v5.50.739-37-ga0ad257
- 三产品: 550A/550B/550C 随包发布 · 真源 updated=2026-10-17 (v5.50.740) · 现役 active=550B

## 本轮改了什么
1. 核心归位: RealStateSpaceSim(4240 行) + 22 个零 Qt 模块迁入 src/lerobot/{engine,ops,serving,features,skills,perception,middleware}
   与 tools/gen/; tools/gui 只留 GUI 与 ≤40 行别名 shim (sys.modules 换真身)
2. 删死代码: zmax_gui_launch.py (与 studio.py 逐字节相同, 15819 行) / le_robot_home.py / le_robot_studio.py
3. 调试停跳: 调试器连上时不启动 _HwFetcher/_StatusLightFetcher, 线程内未捕获异常只落盘
4. pyqtgraph 加固: setData(skipFiniteCheck=True) + refresh 重入闸 + Y 量程去级联
5. 跨平台: 23 个 shim 路径探测兼容 _MEIPASS; Windows/macOS 打包 job 补 engine/ops/serving/features/skills/
   perception/middleware + tools/gen
6. 判据修正: verify_product_ui ⑨ 改「真源↔工程库同源」不再写死 89/190; verify_config_page_product_sync
   改读 _star_facts 摘要 (「当前 X」已不在左树文本)

## 判据
- ✅ integrity: ✅ Z-MAX v5.50.740 完整性检查通过: 版本号/功能卡/页面字典/导航/类 五处一致
- ✅ verify_src_layering: ✅ 全部通过 (27 项)
- ✅ verify_engine_location: ✅ 全部通过 (7 项)
- ✅ verify_product_dev_profiles: 结论: ✅ 全过 — 三产品分工已写进真源、有单一读取口、四处已接线、子进程实测按档取值
- ✅ verify_product_ui: This plugin does not support propagateSizeHints()
- ✅ verify_config_page_product_sync: ✅ PASS 8/8
- ✅ verify_product_release_factory: ==================================================================================
- ✅ verify_signal_panel: This plugin does not support propagateSizeHints()
- ✅ verify_trace_cols: ✅ 全部通过

## 已知未过 (非本轮引入)
- verify_product_consistency ⑤ topic 签名单射性: 157 topic 落 21 个签名, 自 10-13 起同样 1 项红,
  属结构性建模 (报告内已注明超出数据一致性范围)。
