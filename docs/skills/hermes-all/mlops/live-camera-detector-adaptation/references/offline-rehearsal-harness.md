# 离线演练取证 (硬件/产线不可用时, 先把链路与判据算通)

配套 SKILL.md §7.3。适用: 相机/机器人/产线此刻不可用, 但用户要的是"**能出结果的方案**"。
做法 = 合成场景 + **调真函数**(不重写一遍) + 断言表 + 报告落盘。

本项目实例: `tools/real_probe_dryrun_selftest.py` (合成"机器人+相机" → 调 `tools/real_autolabel.py`
的真函数), 9 项断言, 报告落 `~/zmax_data/probe_rehearsal/run_<ts>/rehearsal_report.json`。

## 结构 (照抄这个骨架)

1. **合成真值**: 选定一个相机外参/内参作为 `P_true` → 用 `P_true` 渲染"工件在各位姿下的图像"。
2. **合成探针会话**: `frames/*.jpg` + `truth.jsonl` (tcp/tcp_quat) + `roi.jsonl` (每帧工件框),
   写成与真机采集**同一个目录契约** → 后面可以直接喂真代码路径。
3. **调真函数**取点对 → 拟合 → 预检 → 出标签 (`probe_pairs_from_session` / `fit_proj` /
   `probe_design_check` / `label_session`)。**绝不重写一份"演练专用"实现** —— 那证明的是另一条链路。
4. **留出盲测**: 独立采样 3D 点, 比较 `project(P_hat)` 与 `project(P_true)` 的像素差。
   这是唯一能抓住"rms 好看但模型是错的"的判据。
5. **每个场景跑出数字**, 断言打印数字 (不打印数字的断言等于没断言), 报告 json 带时间戳。
6. **真机数据侧独立核查**: 拿归档真机帧做参数级检查 (检出 conf 分布 / 框内亮度 vs 环带 /
   帧与真值的位移一致性) —— 用来确认"合成里成立的前提在真机上真的成立"。
   本轮就是靠它推翻了"按亮度抠目标"这条路 (真机上目标比周围暗 −25 灰度)。

## 演练脚本自己会踩的坑 (都实测踩过, 别重复)

- **断言里的 falsy 陷阱**: `(iou or 1) < 0.5` 在 `iou = 0.0` 时变成 `1 < 0.5 = False` → 断言方向反了。
  一律显式判 `None`: `_iou = lambda d: 1.0 if d.get("iou") is None else d["iou"]`。
- **GT 用错参数 = 测试自证**: 算基准框时若用了与待测项**相同的错误偏移**, 标签和 GT 一起偏 → IoU 不降反升
  (`0.578 vs 0.567`), 测试变成"证明错误做法也能过"。**基准必须用物理真值参数, 待测项才用被测参数**。
- **反向场景要真实存在, 不能设计成必过**: "没夹住"要分两种 —— ①画面里没有其它运动 (门必须拦下);
  ②夹爪可见且在动 (这是**已知盲区**, 会被误放行)。第二种要如实记录 + 给缓解 (ROI), 不是删掉它。
- **合成场景要物理合理**: 长杆夹在一端 → 工件中心离夹爪约 90px; 若把它做成"夹爪紧贴 22px",
  那是边界而不是常态, 会得出过悲观的结论。边界值单独列一个场景, 判据放宽并标"最坏情况"。
- **把"当前实现"一起测**: 保留一个对照组 (旧的取质心/旧口径) 跑同一批数据, 数字放在同一张表里,
  这样"我必须改"本身就是证据 (`旧 14.23px vs 新 8.54px`), 而不是我的断言。
- **退化对照组必须有**: 故意构造病态输入 (共面位姿 / 零检出 / 空标签), 断言"预检/门**拒绝**"才落地 ——
  只测"好输入能过"等于没测闸门。

## 结论怎么写

- 报告分两层: **(a) 演练全绿** 与 **(b) 真机待复测** 分开写。演练数字**不能**当交付证据。
- 每条"还没打通"都写清缺什么、下一步在哪 (人/环境/驱动), 不要用"基本完成"糊过去。

## 复放**产线程序本体**: 把多段判据流水线的失败定位到某一段

与上面"合成场景"互补的另一半。触发场景不同: 现场现象**复现不出来**或**间歇跳变**(同一姿态有时对有时错)
—— 这时合成场景没用, 要的是拿真东西跑。做法 = 把产线程序当模块 import, 喂**冻结真帧**, 调真函数,
读它**自己写出来的 meta**, 由 meta 指出哪一段塌了。

```python
# 桩掉厂商 SDK —— 模块级就会实例化相机/检测器/裁剪器 ⇒ 必须先塞桩类再 exec(import * 不会覆盖已存在的名字)
class _Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Dummy
    def __call__(self, *a, **k): return _Dummy
class _StubLoader:
    def create_module(self, spec): return types.ModuleType(spec.name)
    def exec_module(self, m):
        m.__dict__["__all__"] = []
        m.__dict__["__getattr__"] = lambda n: _Dummy
class _VendorStub:
    def find_module(self, name, path=None): return None
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0].startswith(("SciCam", "Mv", "MvImport")) or name in ("yolo_detector", "gf_crop"):
            return importlib.machinery.ModuleSpec(name, _StubLoader())
        return None
sys.meta_path.insert(0, _VendorStub())

spec = importlib.util.spec_from_file_location("J", SRC)
M = importlib.util.module_from_spec(spec)
M.SciCamera = _Dummy; M.YoloDetector = _Dummy; M.GoldFingerCropper = _Dummy; M.annotate = _Dummy
spec.loader.exec_module(M)
img, met = M.render_judge(frozen_bgr)      # 判据 meta 在 met["judge"]
```

**第一步永远是"把 meta 的所有 key 打一遍"** —— 这类程序往往把每一段的中间量都写进 meta
(检出段 / 合并后段 / 离群块与丢弃数 / 栅格节距·相位·补格数 / 掩膜外接框 / 裁剪框 / 左右端判据 / 输出尺寸),
它就是分段的诊断书, 一眼看出塌在哪, 比读代码猜快得多。

**定位法(从结果往上游对账)**: 数 `raw_segs` → 数 `merged_segs` → 减 `outlier_dropped` →
加 `lattice_added_vs_kept` → 与最终 `n_keys` 比。差在哪一段就查哪一段的规则。
再把"掩膜外接框"与**实际结构跨度**(自己用列剖面找)对比, 判"最外几根是不是压根没进计算"。

**四条纪律**(都实测踩过):
- **度量先校准**: 任何自研度量(自相关 / 节距 / 峰值计数 / 阈值分段)先拿**真值已知的样本**跑
  **同一份代码、同一参数窗口**。实测: 节距搜索范围写窄 ⇒ 本来很好的结构被读成 0.40("结构差"),
  把窗口覆盖到真周期后同帧读 **0.891**(正常视角 0.912) ⇒ **读数错直接导致一整轮方向错误的实物实验**。
  窗口必须覆盖物理可能区间, 并把窗口本身写进报告。
- **帧要冻结**(存盘再跑): 每批重新抓帧的数字不可比(实测两批: 一批跳变、一批全好, 差点误判)。
- **别猜内部函数签名/返回**: 直读源码。实测一个"看着像列剖面"的函数实际返回的是**边缘五元组**,
  照猜的写法当场 TypeError, 白花一轮。
- **离群/畸变类规则要问"丢掉的是什么"**: "超宽块 = 畸形"这种规则换个视角就会把
  "几根粘在一起的真结构"整块丢掉 ⇒ 数量系统性偏少; 正解是按**已知节距切开**, 而不是丢。
