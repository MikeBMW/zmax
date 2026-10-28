# 版本迭代 + 保存数据/归档 (老倪: 「保存数据, 迭代到 x.y.z, 同步三产品, 跨平台」)

一次完整的发版请求通常同时包含四件事: 升版号 · 同步产品档位 · 跨平台打包 · 数据落盘。
顺序与验收如下。

## 1. 版本号只按用户指定升
- 用户没说版本号 ⇒ 不 bump (哪怕改了很多)。用户说了具体号 ⇒ 才动。
- 一次改齐 9 处:
```
./gui-venv311/bin/python tools/bump_version.py <ver>
./gui-venv311/bin/python tools/ci/integrity_check.py     # 断言: 版本号/功能卡/页面字典/导航/类 五处一致
```
  覆盖: `studio.py` (品牌小字/状态栏/关于框/changelog) · `update_checker.CURRENT_VERSION` ·
  `docs_sync` ×2 · `version_sync.zmax_ver` · `ci/integrity_check.EXPECTED_VERSION` · `VERSION.md`。
- 🔴 模块归位后 `docs_sync` 的路径变了 (旧 `tools/gui/docs_sync.py` → `src/lerobot/ops/docs_sync.py`);
  bump 脚本里的 `DOCS` 常量要指向新真身并保留 shim 回退, 否则那两处版本号**静默不改** (五处一致判据不会红,
  因为它只查它认识的那几处)。升完 `grep -rn "<旧版本>" <那 9 个文件>` 确认清零。
- `VERSION.md` 里出现更旧的版本号是**历史 changelog 引用**, 不是当前版本 — 别为它改文件或改判据。

## 2. tag 已推后又在同版本内修 bug
用户只指定了一个版本号, 而修完发现 tag 已经推上去 ⇒ **不自主 bump**, 把 tag 移到包含修复的提交:
```
git tag -f -a v<ver> -m "..."
git push -qf origin v<ver>
```
并在回复里说清"为何移动 tag"(release 刚出、尚未被消费)。替代方案 (升 patch 号) 必须经过用户同意 ——
版本号纪律高于"tag 不可变"的教条。

## 3. 保存数据 = 两份落盘 + 可复核校验
```
docs/data_snapshots/<date>_<主题>/        判据实跑输出 (每项一份) + NOTE.md + git_ref.txt
zmax_data/release_<ver>_<date>/           代码/判据 + truth/ (产品唯一依据·话题类型·画布·工程库) + evidence/ + MANIFEST.md + sha256sums.txt
```
- 归档用脚本写 (`tools/save_release_*.py`), 而不是手抄文件清单: 脚本里列出"代码 27 · 唯一依据 6 · sha256 行 36",
  跑完 `sha256sum -c sha256sums.txt` 回读, 报告 **N/N OK** 这种能复核的数字。
- 归档脚本自己也会报"行数", 与 `find` 实测不一致时**按 find 为准**并在回复里更正 (别把脚本的自报当事实)。
- 判据输出进快照时保留 exit code; 红了先分辨"本轮引入"还是"历史遗留":
  `ls -t reports/<judge>_*.json` 看前几天的同名判据是否同样红, 再决定是修代码还是只记录。

## 4. 三产品同步 (550A/550B/550C)
- 改 `config/platform/zmax_product.json` 与 `defaults/config/platform/zmax_product.json` (出厂骨架) 两处;
  现役档位 (`active_product`) 不要被骨架顶掉。
- 判据: `verify_product_dev_profiles` · `verify_product_consistency` · `verify_product_ui` ·
  `verify_config_page_product_sync` · `verify_product_release_factory` 全跑。
- 改产品 JSON 用 `json.load/dump(indent=2, ensure_ascii=False)`, 只增 `updated` 这类字段; 加新键前先想判据会不会
  因严格结构比对而红 (红了两边都别猜, 先回滚新键再验证一次)。

## 5. 跨平台 (Windows/macOS)
- 本机只能验: 打包配置 (workflow `--add-data` 是否列全归位后的 `src/lerobot/*` 与 `tools/gen`) · shim 的
  `sys._MEIPASS` 路径探测 · YAML 语法。
- **不许声称已产出 exe/.app** —— 产物在 CI; 回复里写"配置与解析已验, 产物由 CI 出"。

## 6. 回复口径
- 先给四件事的完成状态 (版本/数据/三产品/跨平台), 再列判据条数与关键实测数字。
- 任何一项没做或没验, 明确写"没做/没验"及原因, 不用"应该没问题"糊过去。
