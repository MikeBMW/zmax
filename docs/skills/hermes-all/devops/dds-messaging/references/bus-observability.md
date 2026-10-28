# DDS 总线可观测性 · 实测坑

目标场景: 把整套系统的节点间数据做成 **DDS 总线**上可观察的 topic(对标 Vector CANoe 的
Trace/Statistics/Restbus), 并能在量产不序列化的前提下**随时工程探测**。

## 零、收口/部署实测坑(2026-09-29)
- `os.path.getsize(不存在的文件)` 抛 FileNotFoundError ⇒ 守护进程整个 DDS 参与者建不起来, **所有话题静默**
  (现象: 状态灯全黑 + 日志刷“DDS 不可用: No such file”)。缺文件与空文件都要当“没配”。
- 改 systemd unit 前必看 `systemctl cat` 实际内容: `write_file` 对“本任务未读过的既有文件”会**拒绝写入**
  (返回错误但不抛异常), 静默留下旧路径 ⇒ 服务异常。
- 路径收口后旧路径一律留软链, 并实测一条老命令(例: 用旧路径 `import zmax_node`)。

## 一、观察者读取端必须用深历史(最容易错的一条)

发布端 QoS 若为 `BEST_EFFORT + KEEP_LAST(1)`(常见于“最新值”语义), 探针/分析仪**照抄该 QoS**
会在突发下大量丢样: 实测一轮发 182 条, 读取端只收到 **1~3 条** —— 因为读取端 history 深度=1,
两次 `take()` 之间到达的全部被覆盖。

修法(不改变发布端语义, 也不需要 RELIABLE —— 读端 RELIABLE + 写端 BEST_EFFORT 属于
**QoS 不兼容**, 根本不会匹配):

```python
from cyclonedds.core import Policy, Qos
from cyclonedds.sub import DataReader
from cyclonedds.topic import Topic
qos = Qos(Zn._p(Policy.Reliability.BestEffort, 0), Zn._p(Policy.History.KeepLast, 200))
reader = DataReader(dp, Topic(dp, "zmax/" + key, Zn.TOPICS[key]), qos=qos)
```

DDS 的 **History 不参与 RxO 匹配**, 所以读端可以在写端只留 1 条的前提下自己留 200 条。
实测: 同口径由 1~3 条提升到 80→182 条。

## 二、突发洪灌要自己节流

即使读端深历史, 写端 `KEEP_LAST(1)` 在**极高瞬时速率**下仍会覆盖尚未发出的样点(实测 80/182)。
回灌/回放类工具默认加 `--pace 0.001`(1ms/条), 182 条零丢失。这不是丢包 bug, 是 QoS 语义。

## 三、`Node.pub()/send()` 传**短键**, 不要传全名

节点封装自己会补 `zmax/` 前缀; 传 `"zmax/hw_state"` ⇒ 双重前缀 ⇒ `KeyError`。始终传 `hw_state`。

## 四、不要给每条连线开一个话题

N 条画布连线若开 N 个 topic, 发现/内存/可读性一起崩。CANoe 口径: **一条 Message 多条 Signal**
—— 全部连线走同一条已注册话题(如 `zmax/link_value`), 信号身份 = (源节点, 源端口);
新增话题必须先进注册表, 否则订阅端 `TOPICS[key]` KeyError(实测踩到)。

## 五、探针要跟随档位切换

档位白名单是唯一开关(量产 prod=0 话题是设计预期, 不是故障)。若探针只在启动时定订阅集,
切档后永远看不到新话题。每轮对账一次档位, 补订新话题、把不再允许的话题标灰而不是删掉历史。

## 六、脚本跑在仓库外时的路径反推坑

`REPO = dirname(dirname(__file__))` 这类反推: 脚本一旦被放到别处(如 ~/xxx.py), REPO 会变成
`/home`, `sys.path` 里塞进不存在的目录, 于是 `import hardware_view` 每轮抛 ModuleNotFoundError,
话题静默为空(日志里只有异常, 容易被当成"没数据")。脚本一律显式 `ZMAX_REPO=/home/ubuntu/zmax_rel`。

## 七、判定"话题活着"的三个前提(缺一个就会误报)

1. 档位白名单包含它; 2. 发布进程真的在发(看 `journalctl -u <svc>` 里有没有 ModuleNotFoundError);
3. 配对 > 0(`matched_pubs`)。
只有 `count` 会骗人: 报 0 条既可能是"设计不发", 也可能是"发了没人收"。

## 八、配置文件防呆: 空文件 ≠ 没配置

`CYCLONEDDS_URI=file://<0 字节文件>` 解析失败 ⇒ 参与者掉出默认发现网 ⇒ 现象是
“日志显示正常 write, 但配对=0、对端 0 条”。
修: 加载配置前判断 `os.path.getsize(cfg) > 0`, 否则当**未配置**处理并打一行告警;
**同一个仓库里发布端与守护端要同一套防呆**(只改一边 = 只修一半, 实测守护端早有保护、发布端漏了,
于是"主话题一直空"看着像没数据)。

## 九、最终归属: 同一条链路的代码不得分居两处

上述第 六/八 两条的根因都是“代码在仓库外 + 两边实现不同步”。把发布端/守护端/聚合端与类型定义
收进同一个可 CICD 的路径(`src/lerobot/<pkg>/` + `tools/<tool>/`), systemd 指过去;
否则每次排障都要先判“改的是哪个副本”。

## 十、回灌/回放(restbus)的口径

把工程数据(画布 json)发到总线上以便无真机时观察时:
* 报文里写明来源与性质(`kind='bus-sim'`, `text='from canvas json (工程回灌·非实测)'`),
  UI/报告必须能一眼区分“回灌”与“真机实测”;
* 发前先等配对(`wait_for_match`), 发完 linger 2s 再退 —— BEST_EFFORT 下进程立刻退出会
  让读者收不全; 持续回灌用 `--watch --rate`。

## 十一、新增一条话题到「信号分析可见」的端到端清单

新增话题不是"加个 dataclass"就完事 —— 少登记一处, 症状都是"页面上没这条"且**不报错**。按序改齐:

1. **类型**: `dds/ss_types.py` 新增 IdlStruct (字段带单位; 缺测写 `-1.0`, 别用 0 冒充)。
   ★ **别忘 `@dataclass`** (同模块其它类型都带, 新写的容易漏): 漏了类型照样注册、守护照样起,
   只有实例化那一步抛 `XxxType() takes no arguments` ⇒ 该话题静默不发。新类型先 `python -c` 构造一次再往下走。
2. **注册**: `dds/zmax_node.py` 的话题→类型映射 + QoS 分级 (状态快照类 = `state`)。漏这步 ⇒ 订阅端 `TOPICS[key]` KeyError。
3. **发布端**: `tools/dds/ss_daemon.py` 增 `pub_<topic>()`, 读**唯一依据 JSON**; 帧龄超阈值要**如实写"陈旧/未训练"**,
   绝不静默沿用旧值; `trained/frozen` 这类状态原样转发。挂到常驻节拍线程里, 不是只发一次。
4. **目录册**: `src/lerobot/dataspace/topics.py` 补名称/类型/来源/周期描述 —— 页面上的说明文案从这里来。
5. **档位白名单 `MODE_TOPICS` 是手抄多份**: `tools/dds/ss_daemon.py`、`tools/gui/zmax_telemetry.py`、
   `src/lerobot/dataspace/topics.py` 都要加, 并在文件里注明哪份是唯一依据。只加一处 ⇒ 探针按档位订阅时看不到它。
 ★ **还有第二道闸**: `tools/zmax_profile.py` 的 `topics = core|all|none` (产品档位)。话题进了
 `MODE_TOPICS` 却不在 `core` 元组里 ⇒ A 档静默滤掉、B 档看得到 (现场表现为"同一话题有时有有时没有")。
 两道闸都要登记, 少一道都是"没发出来"。
6. **重启对的那个服务**: 信号分析页的实时值来自 `live.json`, 它由 **`zmax-dataspaces-probe.service`**
   (`venvs/dds-venv` 跑 `src/lerobot/dataspace/probe.py --watch`) 写; `zmax-dataspaces-loop.service` 只写 `loop.json`
   —— 重启它页面一个字段都不会变(实测白等一轮)。判据 = `live.json` 话题数 N→N+1 **且**该话题下有字段值。
7. **验证三步**: ① 订阅器真收到 ≥2 帧且间隔符合周期 ② 回读 `live.json` 该话题有值 ③ 页面上能选到它。
   三步缺一步都别宣布"已接进信号分析"。

## 十二、发布的是「真值」不是「显示摘要」(三个读者必须同名)

两条都是**静默**故障(话题活着、字段却空着或只是近似), 判据不卡就永远发现不了:

1. **同一份唯一依据 JSON 有三个读者** (生产者写 / 守护转发 / 界面取信号) ⇒ 字段名必须逐字一致。
   实测踩过: 守护照 **DDS 消息的字段名** (`v`/`a`/`x`) 去读文件里叫 `v_mms`/`a_mms2` 的键 ⇒ 那些量全读空,
   界面上只剩剩下的一半 —— 看着像"这个话题没有那些量", 实际是读错键。判据要断「生产者写的名 ==
   转发者读的名 == 界面读的名」。
2. **派生量/上限值要从唯一依据取, 不要转发「给人看的四舍五入摘要」**: 算法导出给人看的摘要常常
   `round(x, 4)`, 拿它当模型参数发布 ⇒ `4.166667` 变 `4.1667`, 与唯一依据对不上, 1e-6 的判据红, 
   且界面曲线与真值有肉眼看不出的偏差。发布端一律回唯一依据函数取值。
3. **一个源只允许一个读者**: 两个消费者都要附同一个派生量(如位姿来自同一个 tap)时, 由**一个生产者**
   读源并写进共享 JSON, 另一个只转发 —— 否则两处各读一份、各算一次"新鲜度", 迟早出现"A 通道的值
   是新的、B 通道是旧的"这种自打脸。
4. **采样率不匹配的派生量要"算在慢的拍上并保留"**: 用 `(本tick − 上tick)/dt` 计变化率的量, 在
   动作/数据在 tick 内不变的场景下只在边界那一拍出尖峰(16ms), 界面按几十 Hz 采不到 ⇒ 现场看恒为 0
   (假信号)。改成**按数据块边界算一次并保留到下一块**。

> 验证脚本的 venv 分工: DDS 侧 venv 通常**没有** numpy / huggingface_hub, GUI 侧 venv 没有 cyclonedds。
> 既要验类型声明又要跑算法时: 纯算法模块按**文件路径** importlib 加载, DDS 类型声明用 **AST 读字段**,
> "真的上线了"由 `live.json` 的实收计数 + fields 证明 —— 三条都不需要把两个 venv 合成一个。

> 改完代码服务行为没变时, 先问**服务自己的解释器**加载的是哪个副本, 别看仓库文件:
> `systemctl cat <svc>` 拿 ExecStart 的解释器/CWD, 再用那个 python 打印 `module.__file__`。
> editable 安装的 `.pth` 可能指向已不存在的旧路径 ⇒ 你改的副本和它加载的副本不是同一份。

> 挂载到"某层在役/推理中"这类状态列时: 计数/新鲜度取**真跑过的痕迹**(真调用计数、落盘帧龄),
> 不要拿"话题里有没有某字段"当代理信号 —— 代理字段一旦不写, 判定就恒假(真跑也显空闲)。
