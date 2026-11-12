# API 推送的隐形坑

## 先 commit, 再上传 —— 否则推上去的是旧内容

API 推送脚本读的是 `git show HEAD:<path>` / 工作树里**已提交**的内容。若刚刚只改了文件没
`git add && git commit`, 上传的 blob 和远端已有的完全一样, API 返回成功、CI 也正常跑,
但构建产物里根本没有你的修改 —— 症状是“改了也也生效”, 会白白浪费一整个构建周期。

固定顺序:
1. 本地 `py_compile` / 语法校验;
2. `git add <paths> && git commit`(先入本地历史, 哪怕推不上去);
3. 取 `HEAD` 的 blob 上传;
4. 上传后逐文件对账: 返回的新 tree 里每个 blob sha 应等于本地 `git rev-parse HEAD:<path>`。

## 网络判断: github.com 与 api.github.com 是两条路

`curl -m 12 https://github.com` 返回 `000`(超时)不代表没网 —— 先单独测
`https://api.github.com`(常返回 200)。git push / fetch 走的是 github.com:443,
API 走的是另一个域名, 它们的可达性可以差很远。

- 直连 git 超时 ⇒ 改用 Contents/Git-Data API 落地提交(见主文档步骤)。
- 只要 API 通, 就不必去找代理、也不必等网络恢复。

## 触发 CI 时带上版本号输入

`POST /actions/workflows/<file>/dispatches` 只传 `{"ref":"main"}` 会使用 workflow 里的默认输入;
若默认值是非语义版本(如 `dev-snapshot`), Windows 打包会在版本资源步骤直接失败。
永远显式传 `inputs`: `{"ref":"main","inputs":{"tag":"vX.Y.Z"}}`。
