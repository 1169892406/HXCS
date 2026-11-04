# HXCS 编译说明

HXCS **1.0.0** 是 **Python 运行时插件**（1.x 早期曾用 WASM/Go，2.x 起合并 HA 运行时）。

> 完整功能、安装与排障说明见仓库根目录 [README.md](../README.md)。

## 目录结构

```
src/
├── manifest.json        插件清单（runtime: python）
├── requirements.lock    依赖锁（带 sha256，平台会校验）
└── runtime/
    ├── hxcs_worker.py   主 Worker（社区商店 + HA 运行时）
    ├── hx_ha_runtime/   HA 集成运行时（1043 行兼容层）
    ├── homeassistant/   HA API 兼容层（15 实体平台 + helpers）
    └── vendor.zip       第三方依赖打包（aiohttp/pycryptodome/midealan 等）
```

## 为什么 vendor 是 zip

`.hpkg` 有 **包内文件数上限 256**。依赖展开是 563 个文件，超限。

- 打成单个 `vendor.zip` → 只占 1 个文件名额
- Worker 首次启动**解压**到 `<data>/plugins/hxcs-vendor/`（跨版本保留）
- 解压而不是直接从 zip import：zipimport 不支持原生扩展
  （pycryptodome 的 `.so`，midealan 用 AES 加密设备通信）

## 打包

HXCS 走平台**免签名通道**，不需要签名密钥：

```bash
cd homex

# 1. 打包
go run ./cmd/cli plugin package --dir <HXCS>/src --out build/homex.hxcs-1.0.0.hpkg

# 2. 去签名（若产物已带签名段）
go run ./cmd/cli plugin unsign build/homex.hxcs-1.0.0.hpkg

# 3. 验证（提示「未签名」是预期结果）
go run ./cmd/cli plugin verify build/homex.hxcs-1.0.0.hpkg

# 4. 取摘要，更新 index.json 的 package_sha256
sha256sum build/homex.hxcs-1.0.0.hpkg
```

**关键提醒**：`plugin unsign` 只清空 `signature.value`，**保留** `algorithm` /
`key_id` 骨架。删除整个 signature 段会让 manifest 校验失败
（`PLUGIN_MANIFEST_INVALID: 缺少 signature.algorithm`）。

安装侧要求宿主平台已打开免签名通道：

```yaml
# homex.yaml
plugin:
  allow_unsigned: true    # 默认 false
```

或在市场页「允许未签名插件」开关中开启（改完即生效，无需重启）。

## 功能

| 能力 | 工具 |
|---|---|
| 社区商店 | catalog_list / catalog_fetch / community_status |
| 集成管理 | integrations_list / integration_install / integration_remove |
| HA 运行时 | integration_load / config_flow / entry_setup / entry_reload / entry_remove / service_call |

## 安装 HA 集成的完整链路

1. 市场页社区分区 → 选集成 → 「获取并安装」
2. Worker 下载 zip → sha256 校验 → 解压到持久化目录 → 立即 runtime.install()
3. 已安装列表的「HA 集成」区块 → 「配置」
4. 配置页逐步执行集成的 config_flow（发现设备 → 选设备 → 提交）
5. 完成后 entry_setup → 设备实体注册进平台