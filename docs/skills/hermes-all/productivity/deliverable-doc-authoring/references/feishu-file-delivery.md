# 成稿交付通道：把文档/报告发到飞书（文件而非截图）

文档写完了不等于交到了 —— 交付这一步也要真做 + 回读。本项目（Z-MAX）的群通道：

## 通道选择
- 文字/图片：`tools/feishu_send.py`。
- **文件（.md / .zip / .pdf）**：`tools/feishu_send_file.py` —— 另一个通道，`im/v1/images` 只收图片，发 `.md` 必须走 `im/v1/files`。

## 链路（每步真做 + 回读）
1. 自换 `tenant_access_token`（`POST /auth/v3/tenant_access_token/internal`）—— **不走长驻 gateway 的 token 缓存**，因此不会被已过期 token 拖出 `99991663`。
2. `POST /open-apis/im/v1/files`：**multipart/form-data**，字段 `file_type=stream`、`file_name`、`file`(二进制) → 返回 `file_key`。
3. `POST /open-apis/im/v1/messages?receive_id_type=chat_id`：`msg_type=file`、`content={"file_key": …}`。
4. **回读** `code==0` 并打印 `message_id`；上传成功≠消息发出，分阶段打印，失败要能看出卡在哪一步。

```bash
python3 tools/feishu_send_file.py --zip --text "汇总说明"      # 文档目录打包一个 zip + 一句话
python3 tools/feishu_send_file.py --dry-run --zip              # 只换 token/只打包（自检不刷屏）
python3 tools/feishu_send_file.py 路径.md [更多] --text "说明"
```
凭据读 `~/.hermes/.env` 的 `FEISHU_APP_ID/SECRET`；目标群默认 `FEISHU_REPORT_CHAT_ID`（可 `--chat` 覆盖）。

## 交付口径（用户偏好）
- **一条文字结论 + 一个压缩包**，不要把 5 份文档拆成 5 条消息（刷屏）；压缩包件数在发送前打印出来核对。
- 文字结论里把「**已证明 / 未达标·未证明**」分成两段写：硬指标（成功率、节拍这类）没达成就**原样写实测值与差距**，
  不写"基本达标"；真源里 `value` 为空的指标标"待实测 + 实测入口"，不编造实测值。用户会去现场复测。
- 开工/阶段进展也走这条通道（一条就够），别等全部完成才第一次发声。
