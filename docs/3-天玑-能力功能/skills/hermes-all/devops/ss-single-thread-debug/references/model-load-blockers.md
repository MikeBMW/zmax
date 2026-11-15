# 模型节点加载阻塞 → 整拍卡死 → 动作头断点永不命中

适用情形：某个模型节点（`ssdec` / `ss2d3d` / 任何 `from_pretrained` 节点）已经在 `ZMAX_CORE_IDS` 里、
引擎启动行也确实列出了它，但下游代码（`predict_action` 等）的断点始终不命中；日志每 30s 出现一次
`===== 循环启动 (pid=…)`。

## 1. 判据：py-spy 栈（唯一决定性证据）

```
_http_backoff_base (huggingface_hub/utils/_http.py:528)
http_backoff (huggingface_hub/utils/_http.py:599)
_hf_hub_download_to_cache_dir (huggingface_hub/file_download.py:1157)
hf_hub_download (huggingface_hub/file_download.py:1028)
cached_files (transformers/utils/hub.py:438)
cached_file (transformers/utils/hub.py:294)
get_processor_dict (transformers/processing_utils.py:1328)
from_pretrained (transformers/processing_utils.py:1734)
from_pretrained (transformers/models/auto/processing_auto.py:330)
__init__ (lerobot/policies/smolvla/smolvlm_with_expert.py:99)   ← self.processor = AutoProcessor.from_pretrained(model_id)
__init__ (lerobot/policies/smolvla_lew/modeling_smolvla_lew.py:87)
__init__ (lerobot/policies/smolvla_lew/modeling_smolvla_lew.py:395)
from_pretrained (lerobot/policies/pretrained.py:203)
_load_policy (lerobot/engineering/nodes/smolvla_lew_l3.py)
peek_state_dim (lerobot/engineering/nodes/smolvla_lew_l3.py)
run (lerobot/engineering/nodes/flow_matching_impl.py)  → node_action_head (library.py) → n_dit.py
```

看见 `_http_backoff_base` 在栈底就不用再往下查配置了。

## 2. 机制

`AutoProcessor.from_pretrained(model_id)` 即使本地缓存齐备，也会先 `get_hf_file_metadata` 联网查 etag
决定要不要更新；网络不通就 `http_backoff` 指数退避反复重试 ⇒ 一次加载卡几十秒到几分钟。
单线程档（`ZMAX_SINGLE_THREAD=1`）里这是同步阻塞 ⇒ 整拍卡住 ⇒ 循环超时重启 ⇒ 下游永远轮不到。

而且 `_load_policy` 一旦失败会熔断 60s 再重试，于是「每拍重试 + 每次卡几十秒」叠加，表现为循环反复重启。

## 3. 修法（三处一起设，缺一无效）

```python
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
try:
    import huggingface_hub.constants as _hfc
    _hfc.HF_HUB_OFFLINE = True      # cached_file 读这个常量，不读 os.environ
    _hfc.TRANSFORMERS_OFFLINE = True
except Exception:
    pass
```

末行是关键：`os.environ` 运行期修改不会更新已 import 的常量表（`HF_HUB_OFFLINE` 在 import 时定型），
只设环境变量对已经 import 过的 huggingface_hub 无效。
落地位置：节点加载函数里（`ckpt` 是本地目录时才设，hub id 需要联网）＋ 调试档默认 env。

## 4. 验收

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -c "
import time; from transformers import AutoProcessor
t=time.time(); p=AutoProcessor.from_pretrained('<vlm_id>')
print('OK %.2fs %s' % (time.time()-t, type(p).__name__))"
```
应在数秒内返回（实测 4.44s `SmolVLMProcessor`）。
缓存完整性先确认：`config.json / processor_config.json / preprocessor_config.json / tokenizer.json /
model.safetensors` 都在 `~/.cache/huggingface/hub/models--<org>--<name>/snapshots/<rev>/`。
离线模式只会立刻抛缺文件，比无限重试好。

## 5. 连带两坑（同一条 `_load_policy` 路上，一次查完）

| 现象 | 真因 | 修法 |
|---|---|---|
| `FileNotFoundError: model.safetensors`，但文件明明在 | 用 `sudo systemd-run` 跑训练 ⇒ 产物属主 `root:600`，ubuntu 起的服务读不到；safetensors 把权限错误报成 not found | `sudo chown -R ubuntu:ubuntu outputs/train/<run>/` |
| `ParsingError: Expected a dict with a 'type' key for PreTrainedConfig` | lerobot 训练保存的 `config.json` 丢了 `type` 字段；老 ckpt 有 `type=smolvla_lew`，新训的没有 | 给 `checkpoints/<step>/pretrained_model/config.json` 与 `last/pretrained_model/config.json` 补 `"type": "smolvla_lew"` |

## 6. 共享日志怎么判「谁在 tick」

`/tmp/ss_canvas_loop.log` 是所有引擎实例**共享追加**的（`import ss_canvas_loop` 会把 stdout 重定向进去），
既有 systemd 服务的输出也有调试会话的。

```bash
grep -a '工程入口 start.py 已接管' /tmp/ss_canvas_loop.log | tail -1   # 当前接管者 pid
ps -eo pid,etimes,args | grep 'debugpy/launcher.*start\.py' | grep -v grep   # 当前真 debuggee
```

别用 `ps | tail -1` 抓 debuggee：launcher 的 child 会反复创建退出，tail 很容易拿到已死的瞬态 pid
（随后 `No such file or directory`）。用 `etimes` 看进程年龄，与刚改的文件 mtime 比，判它跑的是不是新码。
