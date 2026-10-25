# ECS 迁移清单（39.102.211.79 → 新实例）

生成时间: 2026-10-25 · 本机侧硬编码面: **200 个文件 / 486 处**

## 0. 先做的一件事：确认是不是弹性公网 IP (EIP)

若旧实例的公网 IP 是 EIP：**解绑 → 绑到新实例**，所有硬编码（下面这张表）**一处都不用改**。
若公网 IP 是随实例分配的固定带宽 IP：迁移后 IP 必变 ⇒ 必须逐项改下表。

## 1. 本机侧硬编码清单（按出现次数）

| 文件 | 处数 |
|---|---|
| `docs/skills/xspace/zmax-data-pipeline/SKILL.md` | 21 |
| `docs/skills/xspace/zmax-data-closed-loop/SKILL.md` | 15 |
| `docs/skills/xspace/zmax-cicd/SKILL.md` | 12 |
| `docs/skills/xspace/software-development/zmax-console/references/common-operations.md` | 11 |
| `docs/skills/xspace/zmax-console/references/common-operations.md` | 11 |
| `docs/skills/xspace/zmax-data-pipeline/references/ecs-relay-deploy.md` | 10 |
| `docs/skills/xspace/lerobot-act-training/references/zmax-relay-deploy.md` | 10 |
| `docs/skills/xspace/software-development/zmax-console/references/simulink-id-and-skill-tokens.md` | 10 |
| `VERSION.md` | 9 |
| `docs/skills/xspace/docker-gpu-training/references/mac-native-arm64-deploy.md` | 9 |
| `docs/skills/xspace/zmax-console/SKILL.md` | 9 |
| `src/lerobot/engineering/nodes/library.py` | 8 |
| `docs/skills/xspace/software-development/zmax-console/references/novnc-public-channel-2026-08-19.md` | 8 |
| `docs/skills/xspace/software-development/zmax-console/references/remote-deploy-chain.md` | 8 |
| `docs/skills/xspace/zmax-console/references/novnc-public-channel-2026-08-19.md` | 8 |
| `docs/skills/xspace/zmax-policy-training-eval/SKILL.md` | 7 |
| `docs/skills/xspace/software-development/zmax-console/SKILL.md` | 7 |
| `docs/skills/xspace/lerobot-act-training/SKILL.md` | 7 |
| `docs/skills/xspace/zmax-model-compare-report/references/ecs-snapshot-502-fix.md` | 6 |
| `docs/skills/xspace/software-development/zmax-console/references/relay-middleware.md` | 6 |
| `docs/skills/xspace/software-development/zmax-console/references/web-vnc-display-channel.md` | 6 |
| `src/lerobot/engine/ss3d_live.py` | 5 |
| `src/lerobot/features/dbc.py` | 5 |
| `docs/memory/xspace.md` | 5 |
| `docs/memory/sync.md` | 5 |
| `docs/patch/ORIN_UPLINK_FIELD.md` | 5 |
| `docs/skills/xspace/zmax-cicd-pipeline/SKILL.md` | 5 |
| `docs/skills/xspace/systemd-boot-services/references/reverse-tunnel-diagnosis.md` | 5 |
| `tools/ecs_lockdown.sh` | 5 |
| `src/lerobot/engineering/canvas_publish.py` | 4 |
| `docs/skills/xspace/zmax-cicd-pipeline/references/20260809-remote-4090-train-chain.md` | 4 |
| `docs/skills/xspace/zmax-data-pipeline/references/dds-data-space-update.md` | 4 |
| `docs/design/SCENE_OVERLAY.md` | 4 |
| `tools/publish_status.py` | 4 |
| `docs/skills/xspace/software-development/zmax-console/references/state-3d-mobile-web-2026-09-06.md` | 4 |
| `hermes_gateway_mac/orin_infer_service.py` | 3 |
| `hermes_gateway_mac/orin_stream.sh` | 3 |
| `flows/scene-api.php` | 3 |
| `src/lerobot/dataspace/loop_state.py` | 3 |
| `docs/ops/ZMAX-DATA-LOOP-OVERVIEW.md` | 3 |
| `src/lerobot/middleware/relay.py` | 3 |
| `docs/notes/DATA-CLOSED-LOOP.md` | 3 |
| `docs/notes/studio_hero_buttons_backup_20261015.py` | 3 |
| `docs/skills/xspace/http-relay-service/references/zmax-relay-deploy.md` | 3 |
| `docs/memory/web-design-brief.md` | 3 |
| `docs/skills/xspace/zmax-model-compare-report/SKILL.md` | 3 |
| `docs/skills/xspace/systemd-boot-services/references/local-units.md` | 3 |
| `docs/skills/xspace/zmax-policy-training-eval/scripts/ws_probe.py` | 3 |
| `docs/skills/xspace/software-development/zmax-console/references/20260808-topsys-zmax-arch.md` | 3 |
| `docs/skills/xspace/software-development/zmax-console/references/three-model-compare-v2.md` | 3 |
| `hermes_gateway_mac/collect_upload.py` | 2 |
| `src/lerobot/ops/flow_ci.py` | 2 |
| `docs/incidents/TASK_LEDGER_20260925.md` | 2 |
| `src/lerobot/dataspace/topics.py` | 2 |
| `deploy/systemd/zmax-vnc-tunnel.service` | 2 |
| `tools/ss3d_live_push.py` | 2 |
| `tools/remote_monitor_aggregate.py` | 2 |
| `tools/dev_platform_check.py` | 2 |
| `tools/probe_ecs_upload.py` | 2 |
| `tools/verify_hil_chain.py` | 2 |
| `docs/memory/hermes-jingjing-memory-2026-09-08.md` | 2 |
| `src/lerobot/policies/left_right/state_space/web_agent_bridge.py` | 2 |
| `docs/memory/archive/mem_20260915.md` | 2 |
| `docs/memory/web-simulation-patent-content.md` | 2 |
| `docs/memory/hermes-jingjing-memory-2026-10-24.md` | 2 |
| `docs/skills/xspace/http-relay-service/references/zmax-ws-event-loop.md` | 2 |
| `docs/skills/xspace/http-relay-service/references/websocket-relay.md` | 2 |
| `docs/memory/xiaofang.md` | 2 |
| `docs/memory/hermes-jingjing-memory-latest.md` | 2 |
| `docs/skills/xspace/zmax-cicd/references/ecs-relay-patterns.md` | 2 |
| `docs/memory/hermes-jingjing-memory-2026-10-25.md` | 2 |
| `docs/skills/xspace/software-development/zmax-console/references/20260808-layered-module-grid.md` | 2 |
| `docs/skills/xspace/software-development/zmax-console/references/font-scaling-and-library-layout.md` | 2 |
| `docs/skills/xspace/software-development/zmax-console/references/test-acceptance-full-auto-2026-09-04.md` | 2 |
| `docs/skills/xspace/software-development/zmax-console/references/20260807-dataset-mgmt-cleanup.md` | 2 |
| `docs/design/SIMULINK-PIPELINE-DETAILS.md` | 2 |
| `docs/skills/xspace/zmax-console/references/font-scaling-and-library-layout.md` | 2 |
| `docs/design/factory_fine_ops_supervision.md` | 2 |
| `docs/skills/xspace/software-development/zmax-console/references/websockify-broken-custom-bridge-2026-09-06.md` | 2 |
| `hermes_gateway_mac/robot_status_push.py` | 1 |
| `hermes_gateway_mac/cicd_pull_deploy.py` | 1 |
| `src/lerobot/engineering/status_hub.py` | 1 |
| `simulink-spec.md` | 1 |
| `src/lerobot/ops/ppt_engine.py` | 1 |
| `src/lerobot/robots/zmax_orin/robot_zmax_orin.py` | 1 |
| `flows/scene.html` | 1 |
| `docs/ops/ZMAX-产品升级规范V3.md` | 1 |
| `docs/incidents/TASK_LEDGER_20260924.md` | 1 |
| `tools/systemd/zmax-hil-bridge.service` | 1 |
| `tools/systemd/zmax-ecs-station.service` | 1 |
| `deploy/systemd/zmax-ecs-mobile.service` | 1 |
| `tools/systemd/zmax-ecs-ov.service` | 1 |
| `docs/notes/DATA-SPACE-MAP.md` | 1 |
| `docs/incidents/关机前状态留档_20261008_晚.md` | 1 |
| `flows/dual_brain_peg_yolo.json` | 1 |
| `docs/ops/REMOTE-CONTROL.md` | 1 |
| `src/lerobot/middleware/nodes/n_hil.py` | 1 |
| `docs/ops/ZMAX-CICD-版本管理.md` | 1 |
| `docs/3DGS-2026-10-14-收工记录.md` | 1 |
| `docs/notes/DOCUMENT-TOPOLOGY.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-11.md` | 1 |
| `tools/zmax-hil-bridge.service` | 1 |
| `src/lerobot/policies/zmax_sys1/configuration_zmax_sys1.py` | 1 |
| `src/lerobot/policies/zmax_sys1/modeling_zmax_sys1.py` | 1 |
| `docs/memory/hermes-jingjing-user-2026-08-29.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-22.md` | 1 |
| `docs/memory/archive/MEMORY_live_20260929.md` | 1 |
| `docs/notes/ci-cd-design.md` | 1 |
| `docs/memory/archive/mem_20260929.md` | 1 |
| `src/lerobot/policies/left_right/state_space/hil_bridge.py` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-08.md` | 1 |
| `docs/notes/restore_matrix.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-12.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-17.md` | 1 |
| `docs/skills/hermes-all-index.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-23.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-08.md` | 1 |
| `docs/design/global_data_space_mapping_20260929.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-21.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-15.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-15.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-07.md` | 1 |
| `docs/skills/xspace/github-actions-ci/references/failed-job-rerun-and-log-forensics.md` | 1 |
| `docs/deliverables/功能说明_5.50.A.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-19.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-01.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-14.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-17.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-21.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-27.md` | 1 |
| `docs/design/ARCHITECTURE-OVERVIEW.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-14.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-06.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-16.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-08-28.md` | 1 |
| `docs/skills/xspace/http-relay-service/references/host-down-vs-service-down-triage.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-10.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-13.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-12.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-05.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-06.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-07.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-01.md` | 1 |
| `docs/skills/xspace/http-relay-service/templates/frpc.toml` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-18.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-05.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-12.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-14.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-08-29.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-15.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-09.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-16.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-02.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-03.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-03.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-23.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-01.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-18.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-30.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-13.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-04.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-23.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-20.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-07.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-04.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-02.md` | 1 |
| `docs/patch/A1_ORIN_UPLINK_DEPLOYED.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-02.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-08-31.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-20.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-13.md` | 1 |
| `docs/memory/shared-memory.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-09.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-10.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-19.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-08-31.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-11.md` | 1 |
| `docs/memory/hermes-jingjing-user-2026-09-09.md` | 1 |
| `docs/patch/REAL_MACHINE_AUTHORIZATION_REQUEST.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-09-11.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-08-28.md` | 1 |
| `docs/skills/xspace/state-space-canvas-engineering/SKILL.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-10.md` | 1 |
| `docs/skills/xspace/zmax-cicd-pipeline/references/z700-docker-mac-deploy.md` | 1 |
| `docs/memory/hermes-jingjing-memory-2026-10-22.md` | 1 |
| `docs/skills/xspace/zmax-model-compare-report/references/simulink-pipeline-details.md` | 1 |
| `docs/skills/xspace/zmax-scene-engineering/SKILL.md` | 1 |
| `docs/skills/xspace/software-development/zmax-console/references/feature-list-exhibition-2026-08-19.md` | 1 |
| `docs/skills/xspace/zmax-data-pipeline/scripts/start_relay.sh` | 1 |
| `docs/skills/xspace/software-development/zmax-console/references/feature-card-recovery.md` | 1 |
| `docs/skills/xspace/zmax-data-pipeline/templates/zmax_relay.py` | 1 |
| `docs/skills/xspace/zmax-data-pipeline/templates/ws_relay.py` | 1 |
| `docs/skills/xspace/software-development/zmax-console/references/ppt-engine.md` | 1 |
| `docs/skills/xspace/software-development/zmax-console/references/wsl-display-links.md` | 1 |
| `docs/skills/xspace/software-development/zmax-console/references/20260807-dataset-mgmt-disk.md` | 1 |
| `docs/skills/xspace/software-development/zmax-console/references/ws-event-loop.md` | 1 |
| `docs/skills/xspace/software-development/zmax-console/references/ui-button-lifecycle.md` | 1 |
| `docs/skills/xspace/zmax-console/references/feature-card-recovery.md` | 1 |
| `docs/skills/xspace/software-development/zmax-console/references/deploy-dropdown-and-path-pitfalls.md` | 1 |
| `docs/skills/xspace/software-development/zmax-console/references/feature-dbc-capability-db-2026-08-19.md` | 1 |


## 1b. 真正要改的**代码**（文档/skills 里的引用不算）

共 **117 个文件 / 313 处**

| 文件 | 处数 |
|---|---|
| `tools/gui/simulink_module.py` | 39 |
| `tools/gui/studio.py` | 27 |
| `src/lerobot/engineering/nodes/library.py` | 8 |
| `tools/gui/verification_dialog.py` | 7 |
| `tools/snapshot_state_sync.sh` | 6 |
| `tools/web/station.html` | 6 |
| `src/lerobot/engine/ss3d_live.py` | 5 |
| `src/lerobot/features/dbc.py` | 5 |
| `tools/gen_l2_guide_tactile_page.py` | 5 |
| `tools/ecs_lockdown.sh` | 5 |
| `tools/ecs_overlay_forward.sh` | 5 |
| `tools/web/README_deloy.md` | 5 |
| `src/lerobot/engineering/canvas_publish.py` | 4 |
| `tools/gui/_model_tree_ffpd_legacy.py` | 4 |
| `tools/publish_status.py` | 4 |
| `tools/gui/ss3d_daemon.py` | 4 |
| `tools/gui/model_tree.py` | 4 |
| `tools/deploy_zmax_live.py` | 4 |
| `tools/export_capability_web.py` | 4 |
| `src/lerobot/dataspace/loop_state.py` | 3 |
| `src/lerobot/middleware/relay.py` | 3 |
| `tools/data_closed_loop.py` | 3 |
| `tools/ecs_bringup.sh` | 3 |
| `tools/gen_web_feature_pages.py` | 3 |
| `tools/orin_state_upload.py` | 3 |
| `tools/gui/feature_list.py` | 3 |
| `tools/sys_clean_full.sh` | 3 |
| `tools/ecs_publish.py` | 3 |
| `tools/app/state3d/HANDOVER.md` | 3 |
| `tools/web/index_with_entries.html` | 3 |
| `hermes_gateway_mac/orin_infer_service.py` | 3 |
| `hermes_gateway_mac/orin_stream.sh` | 3 |
| `src/lerobot/ops/flow_ci.py` | 2 |
| `src/lerobot/dataspace/topics.py` | 2 |
| `src/lerobot/policies/left_right/state_space/web_agent_bridge.py` | 2 |
| `tools/orin_uplink.py` | 2 |
| `tools/zmax_auto_collector.py` | 2 |
| `tools/gs_push_feishu.py` | 2 |
| `tools/dataspace_loop_check.py` | 2 |
| `tools/collect_upload_npz.py` | 2 |
| `tools/shutdown_v5_49_1.sh` | 2 |
| `tools/save_data_v5_42_0.sh` | 2 |
| `tools/relay_train.py` | 2 |
| `tools/auto_loop.py` | 2 |
| `tools/hw_uploader.py` | 2 |
| `tools/ss3d_live_push.py` | 2 |
| `tools/cloud_backup_engineering_db.py` | 2 |
| `tools/remote_monitor_aggregate.py` | 2 |
| `tools/stress_test.py` | 2 |
| `tools/dds_hw_aggregator.py` | 2 |
| `tools/dev_platform_check.py` | 2 |
| `tools/probe_ecs_upload.py` | 2 |
| `tools/verify_hil_chain.py` | 2 |
| `tools/data_sync.py` | 2 |
| `tools/dds/aggregator.py` | 2 |
| `tools/p3_metrics_bridge.py` | 2 |
| `tools/orin_pipeline.py` | 2 |
| `tools/shutdown_v5_47_1.sh` | 2 |
| `tools/hw_upload_relay.py` | 2 |
| `tools/app/room_ctl/MainActivity.java` | 2 |
| `tools/app/live/README.md` | 2 |
| `tools/web/scene-overlay.html` | 2 |
| `tools/web/room.html` | 2 |
| `tools/app/room/MainActivity.java` | 2 |
| `tools/web/state3d_app/room_ctl/src/main/java/com/zmax/room/ctl/MainActivity.java` | 2 |
| `tools/web/state3d_app/room/src/main/java/com/zmax/room/MainActivity.java` | 2 |
| `tools/web/state3d_app/live/src/main/java/com/zmax/live/MainActivity.java` | 2 |
| `tools/web/state3d_app/dash/src/main/java/com/zmax/dash/MainActivity.java` | 2 |
| `deploy/systemd/zmax-vnc-tunnel.service` | 2 |
| `hermes_gateway_mac/collect_upload.py` | 2 |
| `src/lerobot/engineering/status_hub.py` | 1 |
| `src/lerobot/ops/ppt_engine.py` | 1 |
| `src/lerobot/policies/zmax_sys1/configuration_zmax_sys1.py` | 1 |
| `src/lerobot/policies/zmax_sys1/modeling_zmax_sys1.py` | 1 |
| `src/lerobot/policies/left_right/state_space/hil_bridge.py` | 1 |
| `src/lerobot/robots/zmax_orin/robot_zmax_orin.py` | 1 |
| `src/lerobot/middleware/nodes/n_hil.py` | 1 |
| `tools/start_station_stream.sh` | 1 |
| `tools/hw_to_robot_status.py` | 1 |
| `tools/publish_canvas.py` | 1 |
| `tools/live_monitor.py` | 1 |
| `tools/cicd_deploy.py` | 1 |
| `tools/cam_push_sim.py` | 1 |
| `tools/l5_hil_agent.py` | 1 |
| `tools/upload_model.py` | 1 |
| `tools/z700_build_package.py` | 1 |
| `tools/wall_3cam.py` | 1 |
| `tools/ss_telemetry_daemon.py` | 1 |
| `tools/canvas_add_hil_node.py` | 1 |
| `tools/finalize_data_sync.sh` | 1 |
| `tools/hil_bridge.py` | 1 |
| `tools/zmax_net_optimize.sh` | 1 |
| `tools/systemd/zmax-hil-bridge.service` | 1 |
| `tools/phone_latency_probe.sh` | 1 |
| `tools/systemd/zmax-ecs-station.service` | 1 |
| `tools/systemd/zmax-ecs-ov.service` | 1 |
| `tools/zmax-orin-uplink.service` | 1 |
| `tools/cam_live_src.py` | 1 |
| `tools/publish_live_url.py` | 1 |
| `tools/gui/gen_dual_brain_yolo_flow.py` | 1 |
| `tools/zmax-hil-bridge.service` | 1 |
| `tools/build_hd_dataset.py` | 1 |
| `tools/dds/gen_unicast_cfg.py` | 1 |
| `tools/ss_orin_shadow.py` | 1 |
| `tools/ecs_push_test.py` | 1 |
| `tools/hil_local_api.py` | 1 |
| `tools/app/state3d/MainActivity.java` | 1 |
| `tools/app/state3d/OverlayActivity.java` | 1 |
| `tools/web/state3d_app/hw/src/main/assets/index.html` | 1 |
| `tools/web/state3d_app/app/src/main/java/com/zmax/state3d/MainActivity.java` | 1 |
| `tools/web/state3d_app/app/src/main/assets/index.html` | 1 |
| `tools/web/state3d_app/app/src/main/java/com/zmax/state3d/aoi/OverlayActivity.java` | 1 |
| `tools/web/state3d_app/app/src/main/java/com/zmax/state3d/aoi/MainActivity.java` | 1 |
| `tools/web/state3d_app/live/build_live_apk.sh` | 1 |
| `deploy/systemd/zmax-ecs-mobile.service` | 1 |
| `hermes_gateway_mac/cicd_pull_deploy.py` | 1 |
| `hermes_gateway_mac/robot_status_push.py` | 1 |

> 其余 200 个引用里的绝大多数是 `docs/skills/**` 的说明文字，EIP 不变时它们一句都不用动；EIP 变了再批量替换文档。

## 2. ECS 上跑的东西（本机 systemd unit 可佐证）

| unit | 作用 |
|---|---|
| `zmax-ecs-station.service` | 工位总览中转 |
| `zmax-ecs-ov.service` | 叠加/预览 |
| `zmax-ecs-mobile.service` | 手机端服务 |
| `zmax-hil-bridge.service` / `zmax-hil-bridge.service(tools)` | HIL 桥 `/hil/state` |
| `zmax-vnc-tunnel.service` | VNC 隧道 |
| 宝塔 nginx | 站点 `/www/wwwroot/datadrive.world` |
| **frps** | `/root/frp/frps.toml` · `bindPort=7000` · `auth.token=zmax-4060` · `vhostHTTPPort=8891` · unit `frps.service` |
| SSH 22022 | **不是 sshd 端口**：由 Orin 侧 `frpc` 注册 `remote_port=22022` 后才监听。frps 活着但零客户端 ⇒ 22022 不出现（2026-10-25 实测） |
| 跳板链 | 本机 → ECS:22022(=frpc) → Orin(192.168.23.66) → Intel(192.168.23.70, ProxyJump orin) |
| HTTP API | `/agent/prompt` · `/agent/reply` · `/hil/state` · `/orin/status` |

## 3. 迁移步骤（推荐：快照/自定义镜像，别手工重装）

1. 旧实例 `systemctl stop` 全部 zmax-*（避免数据写到一半）
2. 旧实例打**系统盘快照** → 用快照创建**自定义镜像** → 新实例用该镜像
3. EIP 解绑 → 绑到新实例（这一步决定要不要改代码）
4. 新实例起来后按 §4 逐条验证；不通过就回滚到旧实例

## 4. 验收清单（每条都要有输出，不看“应该没问题”）

```bash
ping <IP>                      # 通
nc -z <IP> 22022               # 端口开
ssh -p 22022 root@<IP> uptime   # 握手成功 + 负载正常
curl -sI https://datadrive.world/ | head -1     # 200
curl -s <IP>/orin/status                        # 遥测有值
curl -s -X POST <IP>/agent/prompt -d '{"q":"ping"}'   # 我的中转通道
ssh orin 'echo ok'             # 跳板能到 Orin
ssh intel 'echo ok'            # 跳板能到 Intel
curl -s 127.0.0.1:8797/api/tcp # 恢复 orin_bridge / age≈0 / stale=false
curl -s -o /dev/null -w '%{http_code}' 127.0.0.1:8793/gs/live.jpg   # 200
```

## 5. 迁移后立刻要做（业务侧）

- 读 Intel 上 `20261025_1030_retrain30k` 的 `train_report.json` → PSNR 是否 >15.26 → 决定是否切换 3DGS
- 恢复 `zmax-orin-sdk-fwd.service`（19061 位姿桥）→ 页面 `/api/tcp` 回到实时
- 光模块：中央相机(local2) 6~8 点外参标定（要现场授权动臂）
