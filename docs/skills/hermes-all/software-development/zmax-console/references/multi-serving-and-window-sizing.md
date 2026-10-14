# 模型引擎：每层多条「在役」+ 窗口尺寸口径（2026-10-14 老倪两条要求）

## 1. 一层可以有多条在役（候选→在役的真源，不是界面开关）
老倪：L2 SAM3 要服役（建图先分割背景）、L3/L4 LoRA 要服役（基座不动，适配层跟状态空间相关）、L5 本地 tool 技能做成技能包——**每层都服役**。

- 真源：`models/active_models.json`。单指针键（`L2.name/path`…）保持不变（很多工具在读）；
  另加 `extra_in_service: {L2:[…],L3:[…],L4:[…],L5:[…]}`，每条 `{kind,name,path,state:"在役",since,role,note,base?,adapter?}`。
- 代码口径：`tools/model_inventory.py::collect_models()` 把 extra 条目按 `is_active=True` 追加进候选三元组
  （`_layer_candidates` 之后），并在 entry 里带 `serving_ext` 字段；
  `tools/gui/model_engine_window.py::_rows()` 把「第一条之外的 active 条目」渲染成 **在役扩展行**
  （层列 `   ↳ L2`，绿色，tooltip 写 `在役真源: extra_in_service[L2]`）。
- **候选行不会因此消失**：真的未证提升的产物仍是候选（灰），判据照旧。别把没验过的东西混进在役。
- 已在役清单（本次）：L2 `SAM3 开放词汇分割`(zmax_data/models/sam3_hf/model.safetensors + outputs/sam3_finetune/annot_v1/lora_adapter)、
  L3 LoRA merged(smolvla_lew_lora_40_*/model_merged.safetensors)、L4 LoRA(zmax_data/stable-wm-cache/checkpoints/intact_l4_v6lora_200/weights.pt)、
  L5 技能包(`models/l5_skill_pack.json`)。
- **L5 技能包真源** = 工程库 `zmax_engineering.db#functions` 里 layer 含 L5 的功能点（30 条）+ 各自 `params.source` 本地实现源；
  生成物 `models/l5_skill_pack.json`。有 8 条实现源缺失 ⇒ 如实写在 pack 里，不要编路径。
- 显示串必须放得进列宽（在役模型列 340px）：扩展行用固定短名（`SAM3 开放词汇分割 (在役原语)` 等），完整名只进 tooltip。

## 2. 独立窗口「不能拖宽 / 横向出屏 / 不能最大化」的真根因（三层，逐条实测）
1. `setFixedWidth(1900)` 钉死宽度 ⇒ 拖不动。改成：设计宽只作默认宽，`setMinimumWidth(980)` + `QSizePolicy.Expanding`，
   列宽由 `_refit(w)` 按设计比例随宽度重算（窄了走横滚，不用省略号）。
2. 窗口 `parent` 传了 ⇒ WM 设 `WM_TRANSIENT_FOR`，GNOME 的 `_NET_WM_ALLOWED_ACTIONS` **没有 MAXIMIZE_\*** ⇒ 最大化无效。
   调用方一律 `ModelEngineWindow(None)`（实例仍存 `self._me_win`，复用不重开）。
3. 还是 QDialog **类型**位 ⇒ 仍按弹窗对待。收口：
   `setWindowFlags((flags | Qt.Window|Qt.WindowMinMaxButtonsHint|Qt.WindowMaximizeButtonHint|Qt.WindowSystemMenuHint) & ~Qt.Dialog)`。
- 验证手段（不要靠肉眼猜）：`xprop -id $W _NET_WM_ALLOWED_ACTIONS`（要出现 MAXIMIZE_HORZ/VERT）、
  `xdotool windowsize $W 1200 600` 后 `getwindowgeometry` 真的变、`wmctrl -i -r $W -b add,maximized_vert,maximized_horz` 后几何=屏幕。
- 屏幕相关：本机双屏 eDP-1 1920x1200(primary) + HDMI 1920x1080 ⇒ `default_w()=min(1900, av.w-80)=1840`；
  注意 `adjustSize()` 会把宽度收回到 minimumWidth（980），**之后必须显式把默认宽摆回来**，否则出来就是 980 宽。

## 3. 「两处界面一致」的新口径（与可调宽并存）
同一个 `ModelEnginePanel` + **同一个宽度** ⇒ 同一份渲染；窗口默认宽 = 面板默认宽 = `ModelEnginePanel.default_w()`，
功能区页面里 `me_panel.setFixedWidth(default_w())`（不随父容器拉伸）。容器比 980 还窄时面板不让步（页面横滚，不缩列）。
`tools/verify_model_engine_same_render.py` 按这个口径判（11/11）。

## 4. 改完必跑的判据 + 派生物
- `tools/gui/model_engine_window.py --selftest`（含在役扩展行/可调宽可最大化/字不截断）
- `tools/verify_model_engine_unified.py`（21/21）· `verify_model_engine_same_render.py`（11/11）· `verify_cfg_table_fit.py`（3/3）
- 派生物：`tools/dashboard_source.py` → `tools/web/dashboard.json`、`tools/web/unified_app.html`，
  并 `cp -f` 到 `tools/web/state3d_app/dash/src/main/assets/unified_app.html`（手机离线页）。
- 窗口截图取证：`echo ss_model_engine > /tmp/zmax_nav_cmd` → `xdotool search --name 模型引擎` → `import -window $W out.png`。
