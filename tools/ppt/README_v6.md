# Z-MAX 竞品与合作分析 · ReinBee 模板版（v6）

生成时间 2026-10-24 · 33 页 · 891,592 B

## 交付件

| 文件 | 说明 |
|---|---|
| `Z-MAX_竞品与合作分析_33页_可编辑_ReinBee模板_2026-10-24.pptx` | 主交付件（可编辑） |
| `Z-MAX_竞品与合作分析_33页_可编辑_ReinBee模板_2026-10-24.pdf` | 同版 PDF（发出去不会被改乱） |
| `preview6/s-01..33.png` | 逐页预览 |
| `_history/` | v1–v5 历史版本 |

## 这一版改了什么（相对 v5）

1. **套 ReinBee 汇报模板视觉**
   - 取自 `~/zmax_data/deliverables/模板.pptx` 的设计语言：白底、深蓝 `#1F4E79`、明黄 `#FFC000`
   - 每页页眉：左 `ReinBee` 标识（黄竖条 + 深蓝字，原生文字可改），右 `REIN INTELLIGENCE BEE THE FUTURE`
   - 标题：深蓝粗体 + 蓝黄双短线
   - 表格：深蓝表头 + 白字、浅灰细线
   - 页脚：左下报告名、中 `© ReinBee All Rights Reserved.`、右下页码
   - 封面：白底 + 右上黄蓝双圆 + 左下蓝点阵（模板装饰语言）

2. **型号卡换成真机实拍图（14/30 家）**
   - 取自各公司**官网公开图**，仅用于竞品识别，不声称版权
   - 已配图：智元、银河通用、智平方、优必选、云深处、睿尔曼（缺）、达明、Flexiv、FANUC、Productive、NEURA、遨博、节卡、迦智、新松
   - 未配图 16 家（自变量、千寻、星海图、傅利叶、星动纪元、跨维、中科慧灵、优艾、艾利特、仙工、海康、和椿、富唯、灵犀、慧灵等）保留占位框，卡内标注「官网未公开 / 产品整机图」，绝不放假图
   - 图片来源抓取脚本：`~/.hermes/cache/scratch/grab_robot_pics.py`、`grab_pics2.py`、`grab_all_robots.py`；归一化 `prep_final.py` → `fig6/<key>.jpg`（900×1125，等比不拉伸）

3. **配色收敛**
   - 我方从紫 `#7B3FF2` 改为模板黄系深金 `#B37F00`
   - 各路底色块（浅紫/浅绿）收敛为模板浅灰/浅黄

## 依然是「可编辑」的

- 文字：全部原生 `textbox`（513+ 块），可直接双击改
- 表格：9 个原生 `add_table`，可加行删列
- 图表：12 个原生 chart 对象（P6 六个雷达、P8 两个条形含对数轴、P13 一个、P20 一个堆叠、P28 一个柱状、P32 一个折线），**右键「编辑数据」可改数**
- 图片：`add_picture` 插入，右键「更改图片」可直接换

## 复现

```bash
cd ~/zmax_data/deliverables/robotics_landscape_2026-10-23
~/zmax/gui-venv311/bin/python make_pptx_v6.py     # 出 pptx
soffice --headless --convert-to pdf --outdir /tmp/pv6 *.pptx
```

生成链：`data_v5.json` → `make_pptx_v6.py`（v5 派生：`build_v6.py` 打补丁）→ `fig6/*.jpg`

## 口径不变

四张表逐条录入老倪给的数据，未改一个数字；「未公开/未披露」原样保留，不填 0、不猜数。详见第 33 页。
