# 飞书发送 (演练/交付文档) —— 工具选择与收尾

## 工具选择 (选错就白跑一轮)
- **纯文字** → `tools/feishu_send.py` (= `feishu_send.send_text(txt, DEFAULT_CHAT)`; 只接受 `--text`/位置参数/`--image`, **没有 `--text-file`**)。
  多行长文不要在 shell 里转义, 写个小脚本读文件再调 `send_text` (本项目 `tools/feishu_send.py` 可直接 import)。
- **文件** (pdf/docx/图片) → `tools/feishu_send_file.py <files...> [--text-file ...]`。
  ⚠️ **必须至少给一个文件** —— 只给 `--text-file` 会打印“没有要发的文件 (给文件名或 --zip)”就退出 (exit 0! 不报错),
  于是**文字结论静默漏发**。要么把一份文件一起带上, 要么改用 `feishu_send.send_text`。
- 默认群 `DEFAULT_CHAT = oc_c0b4048546145c5c581ddd1a9e8f565d` (dataworld/静界 报告群, 老倪在看)。

## 大批量发送
- 单份 0.5MB pdf 上传约 1~2 分钟; 7 份 pdf+docx ≈ 10 分钟。**用后台跑 + notify**, 别前台等。
- 每份的输出行是 `{"file": …, "ok": true, "message_id": "om_…", "msg": "success"}` ⇒ **用它做回执**, 不要自己编 message_id。
- 收尾三件 (缺一不算完成):
  1. `tools/feishu_check_messages.py` **回读群消息**核实 (核验以群消息为准, 不看本地日志);
  2. 回执落库: `UPDATE drill_runs SET feishu_msg_id=? WHERE task_id=?` (列名是 **task_id**, 不是 task)
     + 追加 `reports/drill/feishu_delivery.json` (该文件从第 2 轮起是**数组**, 不是对象);
  3. 重跑 `tools/verify_drill_report.py`, 待办里的“<任务> 飞书未发”应清零 (它读的就是库里 feishu_msg_id)。
- 注意 `endswith('.docx')` 之类按扩展名判类型会全错 (上传后的 file_key 不带扩展名)。
