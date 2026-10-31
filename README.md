# HXCS — HOMEX Community Store 插件注册表

本仓库是 HOMEX 平台社区插件的分发注册表。HXCS 插件（homex.hxcs）安装并启用后，
市场页会展示本仓库索引的全部插件，标识为「第三方」。

## 目录结构

```
index.json                                  # 顶层索引（注册表入口）
plugins/<plugin-id>/releases/<ver>.hpkg     # 预打包制品
```

## 上架一个社区插件

1. 按《HOMEX 插件开发指南》开发插件（manifest schema v2）
2. `smartctl plugin build / package` 产出 .hpkg
3. 用 hxcs-community 密钥签名（或自带密钥并在 index.json 声明公钥）
4. 提 PR 把制品与 index.json 条目加入本仓库

## 上架要求（机器校验，缺一拒收）

- .hpkg 必须有有效签名（ed25519）
- manifest 必须声明 license
- 依赖必须精确 pin，禁止 git+/http/file 源
- 禁止 subprocess / os.system / pip install
- 出站主机必须在 manifest resources.http.allowed_hosts 白名单内

## 免责声明

本注册表内容由社区贡献，HOMEX 不对其安全性、合规性作任何担保。
每个插件的来源仓库与许可证在卡片上明示。发现问题请通过 GitHub Issues 举报。
