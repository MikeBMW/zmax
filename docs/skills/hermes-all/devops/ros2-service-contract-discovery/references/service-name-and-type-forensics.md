# 服务名/消息类型取证（2026-10-08 夹爪「点了没反应」根因）

## 症状 → 真因 → 一步取证
| 症状 | 真因 | 取证 |
|---|---|---|
| `ros2 service call` 永远 `waiting for service to become available`，30s 后 `rcl node's context is invalid` | **服务名错**（代码里的名字 ≠ 驱动实际暴露的） | `ros2 service list -t | grep <关键词>`，以**实测名**为准 |
| 话题列得出但订不到；`echo` 报 `Cannot echo topic ... contains more than one type: [...]` | 有**另一节点用第二种消息类型**发/订同名话题（多份工作空间新旧版本混装） | 显式指定类型读 `ros2 topic echo <topic> std_msgs/msg/Float32`；`ros2 topic info <topic> -v` 看双方类型 |
| CLI 报错但现场「东西动了」 | **客户端超时 ≠ 动作没下发** | 只看真值/回执判完成，**绝不重发** |

## 本次实况（可复现）
- 驱动真名 = `/gripper_srv`（`interfaces/srv/GripperSrv`）；执行器三处写 `/gripper_driver`（**不存在**）⇒ 所有夹爪指令石沉大海，与 9-21「松开夹爪不好使」同病。
- 改成实测名后：回执 `curr_pos=977.0`；真值 `/gripper_pos` 1000(全开) → 0.0(闭) → 夹住模块后 174（口径：空爪≈21 / 夹住模块≈185）。
- 类型冲突：驱动发 `Float32`，而 `ss_remote_tap` 订 `Float64` ⇒ 不显式指定类型读值必失败。Orin 上有三份工作空间（`tashan0924`/`0810bak`/`0810`）⇒ 先统一版本再排障。

## 纪律
- 名字/类型/字段一律**实测**（`list -t` / `info -v` / `interface show`）；代码与注释里的名字只能当候选。
- 驱动「历来无常驻」是放大器：`ros2 node list` 里没有它 = 驱动根本没跑。无免密 sudo 时用 `@reboot` crontab 代替 systemd unit。
