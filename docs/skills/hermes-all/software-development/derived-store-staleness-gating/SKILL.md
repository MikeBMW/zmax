---
name: derived-store-staleness-gating
description: "Use when 生成物(库/索引/缓存/派生配置)落后于真源, 要自动同步、判定是否过期, 或出现「值变了文案没变」。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [single-source, derived-data, staleness, sync, sqlite, cron]
    related_skills: [zmax-engineering-repo, shared-state-file-integrity, integration-level-audit]
---

# 生成物 vs 真源: 过期检测与自动同步

适用: 任何「真源(人可编的 JSON/源码) → 生成物(数据库/索引/缓存/投影配置)」的链路。

## When to Use
- 用户说「保证全局数据统一 / 自动同步数据库」，或报「改了真源界面还是旧值」。
- 要给生成物加「过期检测 / 按需重建 / cron 自动同步」。
- 同一指标在真源与界面上文案或单位对不上(假统一)。
- 改完库发现接口/页面仍报旧值(服务已把库读进内存)。
症状触发: 改了真源界面还是旧值 · 用户要求「保证全局数据统一, 自动同步」 · 需要判断某个库/缓存是不是过期。

## 一、判据先定: 过期与否只看内容指纹, 不看时间
- `built_at` / 文件 mtime **都不能证明内容对**: 刚 build 过的库也可能没含你刚改的那一项。
- 正确机制(build 时落指纹 → 运行时比对):
  1. build 阶段把**每个真源路径 → `sha256[:16]`** 写进生成物自己的元数据表(`meta.sources` 之类)。
  2. 提供 `stale` 命令: 重新算真源指纹逐项比, 返回 `(bool, reason)`, reason 写到「哪个源变了」(如 `platform 变了`)。
  3. 提供 `ensure-fresh`: 仅当 stale 时重建, 否则零空转(可直接进 cron)。
- 验收(必做, 别只信「我加了 cron」): **人为把生成物里的指纹改坏** → `stale` 报 `True`+原因 → `ensure-fresh` 重建 →
  `stale` 回 `False`。三拍都要有输出。
- cron 兜底(把 `<...>` 换成工程根):
  `*/3 * * * * cd <工程根> && /usr/bin/python3 tools/<db_tool>.py ensure-fresh >> /tmp/<db>_sync.log 2>&1`
  设计要点: cron 跑的是**幂等的 ensure-fresh**, 不是无条件 build —— 无条件 build 在大库上会把磁盘/CPU 白烧掉。

## 二、生成物被常驻服务读进内存时
库重建了, 但服务启动时已把内容读进内存 ⇒ 接口还报旧值。
- 重建后必须重启该服务, 再回读接口核对(不要只核库文件)。
- 报告里写「重建 + 重启 + 回读值」三件, 少一件就是没验。

## 三、派生数字的假统一: 值变了, 文案/单位没变
界面上的行常常是「从真源文本现算数字 + 中文名/单位取旧 spec」 ⇒ 数字更新了, 文案还是旧的, 看着一致实则两套口径。
- 规则: **由真源播种的字段(code/marker = `auto`), 中文名/单位/默认值必须跟随真源文本写回 spec 文件**;
  人工收紧的 `min/max/choices` 一律不动 —— 那是判据, 不是文案。
- 覆盖方向: spec 只在**非 auto** 行覆盖生成值, 否则 auto 行永远被旧默认钉住。
- 抠数字的正则单位表必须含中文单位(`秒|毫秒|分钟|次|盘|件|mm|%`); 缺一个整行就匹配不到, 值静默退回 0/None。
- 验收: 改真源 → build → 回读该行, 断言**文案/单位/值三项**与真源逐字一致。只比数值会漏掉整类问题。

## 四、Z-MAX 落地实例 (可直接照抄的命令)
```bash
cd /home/ubuntu/zmax
python3 tools/engineering_db.py build         # 重建 (落 meta.sources 指纹)
python3 tools/engineering_db.py stale         # (bool, reason)
python3 tools/engineering_db.py ensure-fresh  # 落后才重建
python3 tools/engineering_db.py check         # 17 项结构/漂移自检
```
- 真源改了但 `check` 报 `drift ['project']` 属常态(画布/总工程被改过) ⇒ `build` 后复 check 全绿, 不是故障。
- `zmax-engdb.service`(8798) 把库读进内存: 重建后 `sudo systemctl restart zmax-engdb.service` 再回读 `/summary` 的 `built_at`。
- 参数中心口径: `tools/param_registry.py::_sync_spec_auto` 让 `code=auto` 行跟随真源文本回写 `config/platform/param_spec.json`。
- 真源在 `config/`(指向实例包 `sources/config` 的**软链**)时, 改它 `git status` 不显示、`git add` 报
  `beyond a symbolic link` ⇒ 改完要按工程仓库那套办法留快照才进 git。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 用 `built_at`/mtime 判新鲜 | 库「刚 build 过」但缺刚改的那一项 | 只认 `stale` 的真源指纹比对结果 |
| cron 里无条件 build | 每 3 分钟重建一次大库, 磁盘与 CPU 白烧 | cron 只跑 `ensure-fresh`(幂等) |
| 只重库不重启服务 | 接口/界面继续报旧值, 以为同步失败 | 重建后 restart 读库的服务, 再回读核对 |
| 只比数值不比文案 | 「节拍 12.0」对, 单位还是旧的 mm | 文案/单位/值三项一起断言 |
| 单位正则漏中文单位 | 整行匹配不到, 值静默 0/None | 单位表补齐 秒/毫秒/分钟/次/盘/件/mm/% |
| 更新方向写反 | 人工收紧的 min/max 被生成值覆盖, 判据失效 | spec 只覆盖非 auto 行 |
