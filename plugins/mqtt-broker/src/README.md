# HX-MQTT-BROKER

**第三方插件**（HX Community）：平台内置 MQTT 消息总线的市场登记条目。

> 与 HXCS / HX-MI / MSN 天气同类：社区注册表分发，走平台「允许未签名插件」通道。

## 定位

MQTT 是 HOMEX 的**内置消息总线**（公共组件），编译在主服务 `homex-server` 内：

- **没有独立进程**
- **不监听独立端口**（1884 是主服务内部 IPC 通道，由 homex-server 持有）
- **随主服务启动加载**，热升级由平台包热加载机制接管（`package_hotwatch`）
- **无需用户配置**：通道容量、ACL 等属于部署级参数

本插件不实现 broker，它让这个内置组件在应用市场里**可见、可安装、可查状态**。

## 提供的工具（只读）

| 工具 | 返回 |
|---|---|
| `requirements` | 本插件对平台的依赖声明（embedded / 无端口 / 无进程 / 支持热加载） |
| `status` | 本插件这一代的加载状态（`broker_visibility: platform_internal`） |

`status` 刻意**不报告** broker 的连接数/订阅表——wasm 沙箱拿不到主服务内部句柄，
编一个 `running: true` 会在 broker 真出问题时给出假绿。真实运行态看平台 `/readyz`。

## 构建

```bash
# 缺 -buildmode=c-shared 会缺 homex_abi 导出，加载时报 PLUGIN_ABI_INCOMPATIBLE
GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o plugin.wasm .

# 打包 + 官方签名
hxcli plugin package --dir . --out build/hx.mqtt_broker-1.1.0.hpkg --sign-key-id homex-official
hxcli plugin verify build/hx.mqtt_broker-1.1.0.hpkg   # 需 HOMEX_PLUGIN_TRUSTED_KEYS
```

## 版本

- `1.1.0`：以独立官方插件形态登记内置消息总线（无独立进程/端口，随主服务加载，支持热加载）
