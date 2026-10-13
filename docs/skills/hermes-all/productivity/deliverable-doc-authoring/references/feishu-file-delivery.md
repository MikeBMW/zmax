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
python3 tools/feishu_send_file.py --zip --text-file /tmp/结论.txt  # 多行文字结论走文件 (避免 shell 转义/引号地狱)
python3 tools/feishu_send_file.py --dry-run --zip              # 只换 token/只打包（自检不刷屏）
python3 tools/feishu_send_file.py 路径.md [更多] --text "说明"
```

🔴 **`--zip` 打的是 `docs/deliverables/*.md` 全部**，会把目录里所有历史 md 一起打包发出去。
要发「本次这几件」就别用 `--zip`：自己按清单建 zip（含 .docx/.json，`--zip` 只收 .md），把 zip 路径当位置参数传给工具。
多行结论用 `--text-file`（`--text` 收单行）。
凭据读 `~/.hermes/.env` 的 `FEISHU_APP_ID/SECRET`；目标群默认 `FEISHU_REPORT_CHAT_ID`（可 `--chat` 覆盖）。

## 交付口径（用户偏好）
- **一条文字结论 + 一个压缩包**，不要把 5 份文档拆成 5 条消息（刷屏）；压缩包件数在发送前打印出来核对。
- 文字结论里把「**已证明 / 未达标·未证明**」分成两段写：硬指标（成功率、节拍这类）没达成就**原样写实测值与差距**，
  不写"基本达标"；真源里 `value` 为空的指标标"待实测 + 实测入口"，不编造实测值。用户会去现场复测。
- 开工/阶段进展也走这条通道（一条就够），别等全部完成才第一次发声。

## 回读核验（发送成功 ≠ 用户看到了）
用户会直接要求「检查飞书端」：此时**不要引用自己的发送返回值**，去服务端读回来。
- **列消息**（找出自己发的那几条）：`GET /im/v1/messages?container_id_type=chat&container_id=<chat>&sort_type=ByCreateTimeDesc&page_size=50`。
  🔴 **群里随时有新消息，你那条很快就被挤岀第一页**（本项目实测只翻 20 条就全变成别人刚发的）：必须用返回的 `page_token` 继续翻页再判"没发出去"。
- **按 id 直查（最可靠）**：`GET /im/v1/messages/<message_id>` → 看 `msg_type` / `deleted` / 正文长度与 `file_key`。
- 🔴 **文件字节级回读必须走"消息资源"端点**：`GET /im/v1/messages/<message_id>/resources/<file_key>?type=file`。
  用 `GET /im/v1/files/<file_key>` 会被拒（`400 code=234008 The app is not the resource sender`，排查建议会跑偏）——换对端点立刻拿到文件，别据此判定"无权限/发失败了"。
- 拉到本地后与原件逐字节比（`sha256` + 字节数），并把两端 sha256 贴回群里供用户下载后自查（本项目实测两端 34957 B / sha256 完全一致）。
- 结论按三档报：**服务端存在 / 未撤回 / 字节一致**；缺哪档说哪档。部分服务未运行时（如 AOI 检测未启动）只报"接口级已验证"，不写"端到端已通"。

```bash
python3 tools/feishu_check_messages.py                                  # 列最近消息，标出本机器人发的
python3 tools/feishu_check_messages.py --pages 8 --find "交付文档包"      # 翻页找更早的（默认只拉最新一页）
python3 tools/feishu_check_messages.py --download <file_key> /tmp/back.zip --compare <本地zip>
```

## 多档/多件投递的编排（分档包）
- **每个 send 用一次独立的 terminal 调用**（前台，timeout 给足 ~400s）。
  🔴 别把多个发送塞进一个脚本/`execute_code` 循环：那条路径有执行上限，超时会**杀掉进程并丢掉已打印的 `message_id`** ——
  结果是「不知道发出去几条」，就得靠服务端回读来重建状态，白跑一轮。
- **补发前先读服务端消息列表**，确认已到哪几条（文字/文件各自一条），**只补缺口**，绝不盲重发。
  某档的「文件」比「文字」晚到是常态：文字一条 send 很快，文件要上传，循环被打断时常见的是「文字到了、文件没到」。
- **完整 `message_id` 要从列表的 JSON 字段取**（`mine_list[].message_id`）；人类可读行里的 mid 会**截断**，拿去做直查会 404。
  若某条已滑出当前页窗口，就用 `--pages` 翻页或直接用它自己执行时打印的 id。
- 分档投递的收尾格式：每档「文字摘要 + zip」；每档核验后把 **bytes + 两端 sha256** 贴出来，一档一行，写清哪档还没发/待核。
