# HXCS 编译说明

HXCS 2.x 是 **Python 运行时插件**（1.x 是 WASM/Go）。

## 目录结构

```
src/
├── manifest.json        插件清单（runtime: python）
├── requirements.lock    依赖锁（带 sha256，平台会校验）
└── runtime/
    ├── hxcs_worker.py   主 Worker（社区商店 + HA 运行时）
    ├── hx_ha_runtime/   HA 集成运行时（1000+ 行的兼容层）
    ├── homeassistant/   HA API 兼容层（config_flow/selector/const 等）
    └── vendor.zip       第三方依赖打包（aiohttp/pycryptodome/midealan 等）
```

## 为什么 vendor 是 zip

`.hpkg` 有 **包内文件数上限 256**。依赖展开是 588 个文件，超限。

- 打成单个 `vendor.zip` → 只占 1 个文件名额
- Worker 首次启动**解压**到 `<data>/plugins/hxcs-vendor/`（跨版本保留）
- 解压而不是直接从 zip import：zipimport 不支持原生扩展
  （pycryptodome 的 `.so`，midealan 用 AES 加密设备通信）

## 打包

```bash
cd homex
go run ./cmd/smartctl plugin package --dir plugins/official/hxcs-python --out build/hxcs.hpkg
go run ./cmd/smartctl plugin sign build/hxcs.hpkg --key-id hx-mi-community
```

## 功能

| 能力 | 工具 |
|---|---|
| 社区商店 | catalog_list / catalog_fetch / community_status |
| 集成管理 | integrations_list / integration_install |
| HA 运行时 | integration_load / config_flow / entry_setup / entry_reload / entry_remove / service_call |

## 安装 HA 集成的完整链路

1. 市场页社区分区 → 选集成 → 「获取并安装」
2. Worker 下载 zip → sha256 校验 → 解压到持久化目录 → 立即 runtime.install()
3. 已安装列表的「HA 集成」区块 → 「配置」
4. 配置页逐步执行集成的 config_flow（发现设备 → 选设备 → 提交）
5. 完成后 entry_setup → 设备实体注册进平台
