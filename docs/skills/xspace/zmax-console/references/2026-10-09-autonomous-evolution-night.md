# 自主进化首夜教训 (2026-10-09 · v5.35.0→v5.36.0)

老倪令: 「每个节点/每个功能/每一行代码都要全方位检查, 100% 功能有小联通, 不留死角」。
当夜跑遍 51 个判据 + 全量四层训练, 得到的可复用教训 (都付了时间代价)。

## 1. 训练失败先怀疑"路径", 别先怀疑模型
数据整合/目录搬家后, 两处静默杀手:
- **数据集 yaml 里写死绝对路径**: `data/datasets/yolo_annot/dataset/data.yaml` 的 `path:` 还指老位置
  (`data/yolo_annot`) ⇒ ultralytics 报 `images not found`。修法: `gui-venv311/bin/python tools/yolo_annot_dataset.py --build --check`
  (注意必须是 gui-venv311, 系统 python3 没 cv2)。
- **jsonl 清单里写死图片绝对路径**: L5 的 `train.jsonl` 38/38 全是搬迁前的路径 ⇒ 训练"没有可用样本"。
  修法: `tools/fix_l5_manifest_paths.py` (先备份到 `zmax_data/backups/`, 三级兜底: 尾段重挂 → data↔data/datasets → 按名全盘找)。
  同时给消费端加**解析器**(`img_path(row)`) —— 只修清单不修代码, 下次搬家还会翻车。

## 2. 判据自己也会过时, 修判据 ≠ 修产品
一个"❌"先问: 是产品坏了, 还是判据口径过期?
- `probe_text_labels` 取 `dv._gl_items["uff_lab"]` (GLTextItem) —— 该实现早已弃用改自绘 LabelOverlay ⇒ KeyError。
- `probe_pages_sweep` 只数 `QPushButton` ⇒ 插拔场景/架构页 (QToolButton+卡片) 被误判"0 可交互"。
- `verify_scene_overlay_canvas` 在 8791 服务忙时 `urlopen(timeout=4)` 失手 ⇒ 误报 start=False;
  直调实测 `frames=20` 正常 —— 结论: 该判据 ④ 不稳, 需重试/放长超时。
**先直调复现一次再定性** (本夜的 overlay 就是直调一次才洗清)。

## 3. 离屏 Qt 两个坑 (每次都会踩)
- **teardown SIGABRT(134)**: 判定打完 + `os._exit(0)` 收口, 别让 `win.close()/app.quit()` 把 exit code 搅成 134。
- **studio.py 把 sys.stdout 重定向进 GUI 日志面板**: 探针的 print 会消失 ⇒ 结论写文件 (`open('/tmp/xxx.txt','w')`)。

## 4. 老机器残留路径是定时炸弹
`tools/verify_p3_metrics.py` 写死 `/home/xspace/lerobot-smolvla-lew` ⇒ 本机 import 即崩。
一律 `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`。
排查一把梭: `git grep -n "/home/xspace\|/home/jetson" -- 'tools/*.py' 'src/*' '*.sh'`

## 5. 单卡纪律 & 杀进程纪律
- 同刻只许一个模型进程; 训练在跑时 GPU 探针必然 OOM (`CUDA out of memory`) —— 别当产品缺陷报。
- **杀进程一律写脚本**: 内联 `pkill -f "probe_..."` 会匹配到自己的命令行把自己 SIGTERM 掉。
  见 `tools/kill_probes.sh` (按命令行过滤 + 白名单保护训练关键字)。

## 6. 训练报数只报实测, 不报"应该能"
本夜实况: L4 342.5s(rc0) · L3 1373.8s/500步(rc0) · L2 30轮0.4min(rc0) · L5 120步82s(rc0, loss 0.58→0.12, 3.12GB)
同口径结论: L2 conf 0.662 vs 在役 0.649 ⇒ **未证明提升, 不切在役软链**;
L5 0.75 vs 基座 0.8333 (n=12<20) ⇒ 样本不足不下结论。
⇒ 纪律: 四层"能训能推"是事实, "有提升"没证明就不动默认档 (瓶颈是数据量, 不是步数)。
