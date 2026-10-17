---
name: zmax-vscode-extension
description: "Use when 把 Z-MAX 能力装进 VSCode (自研 .vsix 扩展) — 新建/改/打包/安装/验收。"
version: 1.0.0
author: Hermes Agent
license: MIT
trigger: "Use when 用户说'插件方式''VSCode 版本''把 Z-MAX 插进 VSCode'，或要改 vscode-zmax 扩展、重打包 .vsix。"
metadata:
  hermes:
    tags: [zmax, vscode, extension, vsix, 550b]
    related_skills: [zmax-console, zmax-product-dev-profiles]
---

# Z-MAX 的 VSCode 扩展 (vscode-zmax)

## When to Use
- 用户说"用插件的方式""VSCode 版本""把 Z-MAX 插进 VSCode 开发界面"。
- 要改/重打包 `vscode-zmax/` 扩展, 或扩展已装却"没生效"(先查单例坑, 见下)。

## 定位铁律
扩展是**又一个前端**: 只做「取真源 + 展示 + 触发」, 不复制业务逻辑。
真源 = 本机 8793 只读口 (`/station/status` / `/snapshot/<cam>.jpg` / `/cam/src` / `/aoi/*` / `/station/ledger`)
+ 仓库配置真源 (`config/platform/zmax_product.json` · `param_spec.json` · `flows/calib_closure.json` · `src/lerobot/calibration/calibration_layer.py`)。
写操作一律走后端闸门 (`POST /ctl/arm` 两步 + 5 分钟窗口), 扩展**不新开旁路、不静默写**。
只对 **550B** (调试档, `vscode_debug=true`) 生效。

## 工程与命令
```
工程 vscode-zmax/  (package.json + extension.js 纯 JS 免编译 + media/zmax.svg + README.md)
打包 cd vscode-zmax && npx --yes @vscode/vsce package --allow-missing-repository
安装 code --install-extension zmax550b-0.1.0.vsix --force
卸载 code --uninstall-extension zmax.zmax550b
语法 node --check extension.js ; 清单 node -e "JSON.parse(require('fs').readFileSync('package.json','utf8'))"
```
本机 node/npm 在 `~/.hermes/tools/node-26.7.0-linux-x64/bin/`; npm registry 可达; 缺 LICENSE 只是警告。

## 坑 (踩过的)
1. **VSCode 单例**: 装完扩展后 `code <path>` 只会把请求转给**已在跑的实例** ⇒ 扩展不会加载, exthost 里查不到、日志为空。
   必须 `code -n <path>` (新窗口) 或触发 Reload Window; 或停掉旧实例再起。别以为"装了就生效"。
2. **扩展真激活的判据** (不靠肉眼):
   - `grep -i zmax550b <logs>/window1/exthost/exthost.log` → 应有 `ExtensionService#_doActivateExtension zmax.zmax550b`
   - 扩展内自带**自证日志**: `pullStatus()` 前 3 次把状态行同时写 `/tmp/zmax550b_ext.log` (与 8793 真源可逐字段对账)
   - 反过来: 自证日志出现 ⇒ 说明 `createTreeView × N` 与命令注册都没抛错 (抛错会中断 activate)
3. **视图/命令 id 必须在 package.json 声明**: `createTreeView('未声明的 id')` 会抛错并让整个扩展激活失败。
   注册了但没在 `contributes.commands` 里声明的命令, 命令面板里看不到 (本次漏过 `zmax550b.calib.gsMap`)。
4. **窗口标题可能被工作区的 `window.title` 改掉** ⇒ `wmctrl -l | grep "Visual Studio Code"` 找不到窗口, 别据此判"窗口没了"。
5. **Webview 里加载本机 http 图片**: 要在 `<head>` 写 CSP `img-src http://127.0.0.1:8793 data:`; 图 503 时用 img `onerror` 显示后端原文 (本次 `arm`/`local2` 无帧 ⇒ snapshot 503 "该路还没有帧")。
6. 截图取证本机只有 `scrot` (`gnome-screenshot`/`import` 不存在): `DISPLAY=:0 scrot -o -u <out.png>` (聚焦窗口) / `-m` (多屏)。
7. 日志目录 `~/.config/Code/logs/<ts>/window1/{exthost,renderer}.log`; 只有 `cli.log` ⇒ 说明那次调用只是转发/没真正开窗口。
8. **装完扩展后, 已经打开的窗口不会加载它** ⇒ 用户"看不到图标/只有代码"几乎都是这个: 必须 Reload Window (`Ctrl+Shift+P` → Reload Window) 或新开窗口。
   排查顺序: 先在 exthost.log 看**用户那个窗口**的目录里有没有 `_doActivateExtension zmax.zmax550b`; 没有就是没重载, 不是扩展坏了。
9. **别用 xdotool 驱动 VSCode**: Linux 默认 `keyboard.dispatch="code"`(为 IME) ⇒ XTest 合成按键**不被 VSCode 接收**, `ctrl+shift+p` + type 全部无效 (本次白试两次)。
   验收只能靠: 扩展自证日志 / exthost 激活记录 / **窗口标题**(默认标题模板含活动编辑器名 ⇒ 用 `xdotool getactivewindow getwindowname` 就能免视觉判断某个编辑器/面板是否真打开了) / 让用户自己按键。
   想自动化必须先改 `keyboard.dispatch: "keyCode"`, 代价是牺牲中文输入法 —— 不划算。
10. 工作区的 `settings.window.title` 会改写窗口标题 ⇒ `wmctrl -l | grep "Visual Studio Code"` 会找不到窗口, 也会让用户看到自己没写过的字 (本次"精简多根"就是扩展作者写进 `ZMAX.code-workspace` 的, 已删); 用户报"这几个字哪来的"优先查 `.code-workspace` 的 window.title。

## 验收判据 (P0)
1. `code --list-extensions --show-versions | grep zmax` 出现 `zmax.zmax550b@<ver>`
2. exthost.log 有 `_doActivateExtension zmax.zmax550b`
3. `/tmp/zmax550b_ext.log` 状态行的 TCP 帧龄 / 授权 / 撞车 / 字节数与 `curl -s 127.0.0.1:8793/station/status` 一致
4. 离线 (8793 不在) 时状态栏显示告警色 + 明示错误原因, 四个视图不空白崩溃
5. 授权命令必须两步 modal 确认; 未授权时状态栏不出现"看起来能动"的假象
