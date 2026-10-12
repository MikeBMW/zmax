# 下电核对单 · 2026-10-12 · v5.49.1

## 预检实测 (tools/preflight_shutdown.sh)
```
──────── 下电前预检 2026-10-12 16:37:45 ────────
① 机械臂
  ✅ 真值帧龄 255.66s · pos=(0.6005, -0.2480, 0.6019)
  ⚠️ 授权中, 还剩 1842s · epoch=124 · revoked_at=0
  VL 现场放行: 无(默认 fail-closed)
② 有没有东西还在写(采集/训练)
  ✅ 无采集/训练在写
③ 家目录形态
  ✅ ~ 顶层只有 zmax 一个 zmax 相关项
  ✅ 工程 venv 可用
④ 仓库
  ⚠️  未提交 7 个(需确认)
  ✅ HEAD 2a5427e v5.49.1 — 关机收尾: 数据快照(v5.49.1)+归�
  ✅ 最新 tag(按创建时间): v5.49.1
      D "docs/data_snapshots/2026-10-12_\345\205\263\346\234\272\346\224\266\345\260\276_v5.49.1/README.md"
      M "docs/data_snapshots/2026-10-12_\345\205\263\346\234\272\346\224\266\345\260\276_v5.49.1/engineering_db_check.txt"
      M "docs/data_snapshots/2026-10-12_\345\205\263\346\234\272\346\224\266\345\260\276_v5.49.1/git_ref.txt"
      M "docs/data_snapshots/2026-10-12_\345\205\263\346\234\272\346\224\266\345\260\276_v5.49.1/overlay_channel_verify.txt"
      M "docs/data_snapshots/2026-10-12_\345\205\263\346\234\272\346\224\266\345\260\276_v5.49.1/resources.txt"
      M "docs/data_snapshots/2026-10-12_\345\205\263\346\234\272\346\224\266\345\260\276_v5.49.1/shutdown_checklist.md"
⑤ 资源
  磁盘: 315G / 396G (84%, 可用 62G)
  内存: 已用 13G / 30G
⑥ 服务/容器
  ✅ 服务单元 26 个在跑
  ✅ 8791:200  ✅ 8793:200  ✅ 8794:200  ✅ 8798:200
✅ 容器 ss-remote-tap Up 22 hours
✅ 容器 zmax-arm-raw Up 22 hours
✅ 容器 rokae_tcp_sampler Restarting (1) 48 seconds ago
✅ 容器 zmax-sdk-arm-agent Up 6 hours
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
