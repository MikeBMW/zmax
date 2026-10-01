# 小版本迭代 (VERSION.md 规范 + tools/bump_version.py)

适用于「保存数据, 小版本迭代」「发版」「升级版本号」。**规范真源 = 仓库根的 `VERSION.md`**; 改动只走脚本, 不手改。

## 一条命令 + 6 处同步
```bash
cd /home/ubuntu/zmax
printf '%s' "<一句话: 做了什么 + 根因>" > /tmp/v<新号>.txt
./gui-venv311/bin/python tools/bump_version.py --to <X.Y.Z> --summary-file /tmp/v<新号>.txt --dry   # 先干跑看命中
./gui-venv311/bin/python tools/bump_version.py --to <X.Y.Z> --summary-file /tmp/v<新号>.txt         # 真写(自动 py_compile)
```
脚本负责 5 处 + 1 行历史: studio.py 品牌 QLabel · studio.py 窗口标题(2 处) · studio.py changelog 注释前缀 ·
update_checker.py `CURRENT_VERSION` · docs_sync.py `"version"`+`"zmax_version"` · version_sync.py `zmax_ver`(不带 v) ·
`tools/ci/integrity_check.py` `EXPECTED_VERSION` · `VERSION.md` 版本历史表首行。
语义: 主(架构) · 次(功能模块) · 补丁(修复/小优化); 加工具/修 bug 属**补丁**。

## 干跑判据 (每条必须 旧命中>0 且 新命中>0)
`--dry` 打印 `旧命中 N → 新命中 M ✅`。任何一条 `新命中 0 ❌` = 写回后旧串还在。
**先跑 `--dry` 再真写** —— 这个脚本的病是静默: 匹配不到就什么都不改, 但照旧打印"✅ 已写盘"。

## 🚦 发布/出包 (2026-10-01 实测: tag 打了却一个 CI 都没起)
- **GitHub 只跑「被推 ref 那一棵树里」的 workflow**。真源 `MikeBMW/zmax` 的 `.gitignore` 封了 `.github/`
  ⇒ 打 tag 推上去**一个 run 都不会起**。判据: `git ls-tree -r --name-only <tag> | grep .github/workflows`
  必须非空(空 = 那个 tag 永远不会出包); 佐证: `workflow_dispatch` 指定 `ref=tag` 会 422
  "Workflow does not have 'workflow_dispatch' trigger"。修法: 把 `build-win-exe.yml` `git add -f` 入库,
  或把 tag 推到**带 CI 的仓库** `MikeBMW/lerobot-smolvla-lew`(历史 Releases 的 `Z-MAX_Console.exe` /
  `Z-MAX_Console-macOS.zip` 都在那儿)。
- 本机**没有 `gh`**: 盯 CI 从 `~/.git-credentials` 取 token 后打 REST `/repos/<o>/<r>/actions/runs` 与
  `/repos/<o>/<r>/actions/runs/<id>/jobs`(读 `jobs[].steps[].conclusion` 才有"哪一步挂了"的证据)。
  **报告口径: "推送成功" ≠ "发布完成"** —— 必须报 Release URL + 资产文件名/大小, 或失败 step 名原文。
- ⛔ 不用 `workflow_dispatch` 试探 API 通不通: 它**立刻起一次真构建**(按默认分支旧代码 + 产物挂到
  你随手写的 tag 名上)。要探测只碰只读端点。

## 🕳 三条当天踩到并已固化的坑
1. **看板/面板空态不许留白** —— 没在训练时进度条留空 = 现场读不出"上一次是什么时候"。空态必须显示
   **上次训练**(时间 + 结果/步数), 值来自状态真源, 不许前端自造。
2. **重启控制台用独立方式; 判活不许 `pgrep` 自匹配** —— 正路
   `systemctl --user restart zmax-studio.service`(ExecStart 指 worktree 的 launch_studio.sh);
   自查式脚本里 `pgrep -f "<模式>"` 会命中**脚本自己的命令行文本** ⇒ 误判"已有实例"而 33ms 静默退出(假成功)。
   判活用 `ps -eo pid,cmd | grep "[s]tudio.py"` 或剔除自身 pid; 判断训练在跑同理用
   `ps -eo pid,cmd | grep "[j]oint_train_all"` / `nvidia-smi`, 别用 `pgrep -f`。
3. **诊断/探针脚本本身必须先自验** —— 两次因探针写错下错结论: ①连线字段名靠猜 ⇒ 把好节点报成"孤岛"
   (先看真 JSON 的键名); ②`grep -E "a\|b"` 里的 `\|` 被当**字面量** ⇒ 页面明明改了却报"没改"。
   纪律: 探针先在**已知答案**的样本上验证再对目标跑, 结论前换第二种口径交叉核对。

## 坑 (都踩过)
1. **品牌位一律单 v (v5.17.0 起, 与 git tag 逐字一致)** —— 历史坑: vv5.16.x 时代品牌是**双 v**
   (`Z-MAX vv5.16.35`) 而窗口标题/tag 是单 v, 三处互相打架; 老倪裁定双 v 是笔误。
   工具必须**认版本号不认记法**: 匹配用 `v{1,2}<ver>` 正则(老 vv 检出也能平滑升级), 写回统一单 v
   (`nv_brand = nv`); 否则 QLabel/窗口标题/CURRENT_VERSION/docs_sync/integrity 五处**全部 0 命中且不报错**
   ⇒ "改了版本等于没改"。
1b. **版本号还藏在没人查的地方**: 状态栏 `sb.showMessage("Z-MAX v1.0.4 …")` 与「关于」框
   `<b>Z-MAX v1.0.1</b>` 长期停在 1.0.x(不在同步清单里, integrity 也不查) ⇒ 改版本时顺手
   `grep -rn 'Z-MAX v1\.0\.' tools/gui/` 一并对齐(老倪口径: 不要留下第二处旧号)。
1c. 🔴 **打 tag 前先确认"这个 tag 会触发 CI"**: 见上面《发布/出包》一节。
2. **旧版本号探测别用裸 `Z-MAX v(\d+\.\d+\.\d+)`** —— 会命中 changelog 里的历史串(实测探出 1.0.4) ⇒ 只在
   `QLabel("Z-MAX v{1,2}…")` → 窗口标题 → 兜底 这三档里取, 取众数。
3. `version_sync.py` 的 `zmax_ver` **不带 v**(`"5.17.0"`), 其余品牌位带**单 v** —— 一处口径错就会漏同步。
4. `--from` 显式给上, 别依赖自动探测(探测逻辑本身也会漂)。
5. 版本号只在**下次启动**的窗口标题生效: 已在跑的控制台不会自更新(别为此重启 GUI —— 老倪投诉过反复重启)。

## 收尾(必做)
```bash
./gui-venv311/bin/python tools/ci/integrity_check.py     # 期望: "完整性检查通过: 版本号/功能卡/页面字典/导航/类 五处一致"
# 回读核验 6 处 + VERSION.md 首行, 然后:
git add -A && git commit -m "v<新号>: <摘要>" && git tag -f v<新号> -m "Z-MAX v<新号>"
git push origin main && git push -f origin v<新号>       # tag 语义: 与品牌同为**单 v**
# (-f 只在 tag 刚落、还没被任何 CI/Release 消费时用; 已发布过就换新版本号, 别移 tag)
```
changelog/VERSION.md 的摘要只写「做了什么 + 根因」, 不写过程; 版本历史表按行追加在**表首**。
