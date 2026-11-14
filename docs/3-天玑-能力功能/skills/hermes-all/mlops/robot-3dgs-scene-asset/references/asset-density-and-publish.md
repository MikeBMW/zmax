# 资产密度与发布（3DGS 出图"糊"的判据链）

## 糊 ≠ 数据不够：先看高斯密度

同一场景两次训练的实测对照：

```
16000 步 → 73,894 个高斯   → 留出 PSNR 16.44 dB
24000 步 → 445,521 个高斯  → 留出 PSNR 17.22 dB
```

帧数翻倍（抬头覆盖从 49%/+16° 扩展到 1149 帧合并集）反而低 0.78 dB——因为高斯总数只有对照组的 1/6，场景被「训稀了」。**PSNR 掉下来先算 gaussians/steps 的密度，再考虑加数据**；堆帧数是最容易走错的方向。

## refine_stop_iter 必须与 steps 匹配

`--refine-stop` 之后只精修已有高斯的位姿/颜色，不再加密点。若 `steps=16000` 而 `refine-stop=7500`，后 8500 步密度不再增长，等于白跑一半。取 ≈60% 的 steps：24000 步配 15000。

## 替换在役资产的闸

只有 `psnr_holdout_db` 超过在役值才替换渲染资产；低于就直说「不换」，不要用「覆盖更好/帧更多」当理由。在役那份要在渲染进程实参里核实（`ps … | grep gs_render` 看 `--ply` 指向哪个目录），别凭目录时间猜。

## 发布给用户看（8793 /gsview）

```
资产目录  zmax_data/gs_assets/<name>/   放 gs.splat（+ train_report.json 备查）
枚举接口  /api/gs/list                  按目录列出，gsview 下拉源
查看地址  http://<4060-ip>:8793/gsview?a=<name>
站内入口  station 页的 3DGS 窗口（iframe gsview）、tcp-ar 页也有 3DGS 面板
```

训练完自动发布：守望脚本轮询远端 `train_report.json`（存在 且 该 out 目录无 gs_train 进程 = 真完成），scp `gs.splat` 到资产目录即可被 `/api/gs/list` 看见。轮询周期 5 分钟足够，别用长连接。

## 并发容量：一次只跑一个训练

550C 是 15 核，同时 3 个 `gs_train` 会让 sshd 拿不到 CPU——**ping 通、22 端口 banner 超时、服务 HTTP 返回 000**，看着像机器挂了，其实训练还在跑。起新训练前先数进程：

```
ps -eo etime,args | grep 'gs_train[.]py' | grep -v grep
```

已有任务就先等它跑完，别叠第三个；SSH 失联时不要重启机器，用守望脚本等它自恢复（服务任务跑完释放核心后 banner 会自己回来）。

## ETA 要给实测

从日志里取一行 `N/steps 步 · 耗时s` 算 s/步，再乘剩余步数。并行时会从 0.38 s/步涨到 0.6 s/步，ETA 差一倍——先看 load 再报数。
