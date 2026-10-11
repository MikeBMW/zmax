# 下电核对单 · 2026-10-11 · v5.47.1

## 预检实测 (tools/preflight_shutdown.sh)
```
──────── 下电前预检 2026-10-11 18:41:00 ────────
① 机械臂
  ✅ 真值帧龄 0.03s · pos=(0.5927, 0.1406, 0.6436)
  无授权(窗口已过期) · epoch=117 · revoked_at=0
  VL 现场放行: 无(默认 fail-closed)
② 有没有东西还在写(采集/训练)
  ✅ 无采集/训练在写
③ 家目录形态
  ✅ ~ 顶层只有 zmax 一个 zmax 相关项
  ✅ 工程 venv 可用
④ 仓库
  ⚠️  未提交 9 个(需确认)
  ✅ HEAD 446a2cb 存档: 2026-10-11 状态同步 (记忆/技能/飞�
  ✅ 最新 tag(按创建时间): v5.47.0
      M VERSION.md
      M tools/ci/integrity_check.py
      M tools/gui/docs_sync.py
      M tools/gui/studio.py
      M tools/gui/update_checker.py
      M tools/gui/version_sync.py
⑤ 资源
  磁盘: 307G / 396G (82%, 可用 70G)
  内存: 已用 7G / 30G
⑥ 服务/容器
  ✅ 服务单元 27 个在跑
  ✅ 8791:200  ✅ 8793:200  ✅ 8794:200  ✅ 8798:200
✅ 容器 ss-remote-tap Up 25 hours
✅ 容器 zmax-arm-raw Up 26 hours
✅ 容器 rokae_tcp_sampler Up 25 hours
✅ 容器 zmax-sdk-arm-agent Up 25 hours
  ✅ 飞书网关(用户级): active
──────── 结论 ────────
  🟢 可以下电(臂 idle、无授权、无写入、仓库已保存)
```
## 手工确认项
- [ ] 现场无人作业 / 机械臂周围无人 (真机 rt 类动作后必下电, 本轮无授权窗口、无在途运动)
- [ ] 本机相机画面已确认 (近黑 ⇒ 快层闸 fail-closed, 属设计行为)
- [ ] 现场设备: Orin / 工控机 / AOI / 珞石控制器 电源顺序按现场规程
- [ ] 数据已保存: 快照+归档+MANIFEST 已入库 (见 README.md)
- [ ] 需要我执行下电时再说一声: sudo shutdown -h now
