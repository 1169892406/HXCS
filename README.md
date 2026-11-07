# HXCS — HOMEX 社区商店

> **HOMEX Community Store**　·　插件 ID `homex.hxcs`　·　当前版本 **1.0.9**　·　运行时 Python

HXCS 让 HOMEX 平台具备**社区生态**：它既是第三方插件的分发注册表客户端，也是
一个 **Home Assistant 集成兼容运行时**。安装并启用后，市场页会展示本仓库索引
的全部社区插件；打开「兼容 HA 插件」开关后，可以直接运行 Home Assistant 生态
里的 Python 集成（例如美的空调局域网控制），无需 Home Assistant 本体。

本仓库同时承担两个角色：

| 角色 | 说明 |
|---|---|
| **插件本体** | `src/` 是 HXCS 插件的源码与构建产物 |
| **分发注册表** | `index.json` + `plugins/` 是社区插件的索引与制品仓库 |

---

## 一、能力总览

HXCS 对外提供 **12 个工具**，分为三组：

### 1.1 社区商店（3 个）

| 工具 | 作用 |
|---|---|
| `catalog_list` | 拉取注册表 `index.json`，返回可安装插件清单（含 GitHub 星数实时刷新） |
| `catalog_fetch` | 下载指定插件的 `.hpkg` 字节，带 sha256 校验 |
| `community_status` | 查询社区开关状态与注册表连通性 |

### 1.2 HA 集成管理（3 个）

| 工具 | 作用 |
|---|---|
| `integrations_list` | 列出已安装的 HA 集成与运行状态 |
| `integration_install` | 下载集成 zip → sha256 校验 → 解压到持久化目录 → 立即 `runtime.install()` |
| `integration_remove` | 卸载集成并清理 config entry |

### 1.3 HA 运行时生命周期（6 个）

| 工具 | 作用 |
|---|---|
| `integration_load` | 从持久化目录加载集成包到运行时 |
| `config_flow` | 逐步执行集成的配置流程（发现设备 → 选设备 → 提交） |
| `entry_setup` | 启动 config entry，把实体/设备注册进平台 |
| `entry_reload` | 重载 entry（配置变更后不重启） |
| `entry_remove` | 删除 entry |
| `service_call` | 调用集成内注册的服务 |

---

## 二、Home Assistant 兼容层

### 2.1 支持的实体平台（15 种）

```
binary_sensor   button      climate      cover       diagnostics
fan             humidifier  light        lock        media_player
number          select      sensor       switch      time
water_heater
```

### 2.2 兼容的 HA API 模块

真实 HA 集成本身是 Python 包，会 `import homeassistant.*`。HXCS 内置了这些模块的
兼容实现，让未修改的集成能直接运行：

```
homeassistant/
├── core.py              HomeAssistant 对象骨架
├── config_entries.py    ConfigEntry / ConfigFlow 基类
├── data_entry_flow.py   流程引擎
├── const.py             常量
├── exceptions.py        异常类型
├── components/          15 个实体平台
└── helpers/
    ├── entity.py              Entity 基类
    ├── entity_registry.py     实体注册表
    ├── device_registry.py     设备注册表
    ├── update_coordinator.py  轮询协调器
    ├── config_validation.py   配置校验
    ├── selector.py            选择器
    ├── aiohttp_client.py      HTTP 客户端
    ├── dispatcher.py          信号分发
    ├── json.py                JSON 工具
    └── typing.py              类型别名
```

### 2.3 兼容基线

```
BASELINE = "2026.10-phase2"
```

集成 manifest 只允许这些键：`domain` / `name` / `version` / `config_flow` /
`documentation` / `requirements` / `dependencies` / `after_dependencies` /
`iot_class` / `codeowners`。出现未知键会被拒（fail-closed，不静默忽略）。

### 2.4 已上架的 HA 集成

| 集成 | 版本 | GitHub 星数 | 说明 |
|---|---|---|---|
| `midea_ac_lan` | 2026.10.0 | 1,930 | 美的空调局域网控制：自动发现或手动添加，支持空调/风扇/灯光/加湿器，无需云端 |

### 2.5 安装 HA 集成的完整链路

1. 市场页社区分区 → 选集成 → 「获取并安装」
2. Worker 下载 zip → **sha256 校验** → 解压到持久化目录 → 立即 `runtime.install()`
3. 已安装列表的「HA 集成」区块 → 「配置」
4. 配置页逐步执行集成的 `config_flow`（发现设备 → 选设备 → 提交）
5. 完成后 `entry_setup` → 设备实体注册进平台

---

## 三、安全机制

HXCS 在宿主平台的沙箱之上又加了三层：

### 3.1 凭据加密存储（CredentialVault）

集成配置里形似密码的字段（`password` / `passwd` / `token` / `secret` /
`api_key` / `apikey` / `credential`）会被自动分离出来，用主密钥派生的流密码
加密落盘，配合 HMAC 认证：

- 主密钥由 HOMEX 宿主注入（`HX_HA_MASTER_KEY`，32 字节）
- 每条记录用独立随机 nonce
- 读取时校验 HMAC，篡改即报 `credential authentication failed`
- 明文凭据**不进入** config entry 持久化

### 3.2 网络策略（NetworkPolicy / ControlledSession）

集成的出站请求受 `network_allowed_hosts` 白名单约束：

- **空列表 = deny-all**（默认拒绝，不是默认放行）
- 支持 `proxy_url` 走 HTTP/SOCKS5 代理
- 违反策略抛 `NetworkPolicyError`，不静默放行

### 3.3 稳定标识（RegistryStore）

设备与实体 ID 由命名空间 + 业务键做 SHA-256 派生，保证：

- 集成升级/重载后同一台设备**不会变成两个实体**
- 实体 `entity_id` 冲突时自动加数字后缀，不覆盖既有实体

---

## 四、配置项

安装后在配置页可改这些字段：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `community_enabled` | boolean | `false` | 启用社区插件：开启后市场页显示社区注册表中的第三方插件 |
| `registry_url` | string (uri) | `https://raw.githubusercontent.com/1169892406/HXCS/main` | 注册表地址（`index.json` 所在目录） |
| `ha_compat_enabled` | boolean | `false` | 兼容 HA 插件：开启后支持加载并运行 HA 风格集成包 |
| `proxy_url` | string | 空 | HTTP 或 SOCKS5 代理地址，加速 GitHub 下载；留空直连 |
| `network_allowed_hosts` | array | `[]` | HA 集成的出站宿主 allowlist；**空列表 = deny-all** |

### 4.1 自带配置界面（entry.ui）

HXCS 从 1.0.9 起**自带独立配置界面**（`entry.ui: "ui/index.html"`），不再依赖平台的
通用表单。这意味着：

- 配置页有完整的页头、分段卡片与交互（与语音识别配置页同构）
- 带**「测试连通」按钮**：一键探测注册表地址是否可达
- 带**社区状态展示**：实时显示注册表插件数、信任根指纹
- 所有交互通过平台的 postMessage RPC 通道完成，**不需要为它改平台代码**

> 界面的实现与安全约束见「六、目录结构」与仓库内 `src/ui/`。
> 平台侧机制：插件在 `.hpkg` 里带 `ui/` 目录 + manifest 声明 `entry.ui`，平台自动发现
> 并用 sandbox iframe 渲染（`allow-scripts`、无 `allow-same-origin`、CSP `connect-src 'none'`）。

### 4.2 GitHub 星数刷新

社区卡片上显示的星数来自 GitHub API 实时查询，**不使用任何 token**：

- 未认证限流 60 次/小时，因此缓存 **60 分钟**
- 一轮刷新约 4~5 次调用 = 5 次/小时，余量充足
- 失败时回落到注册表里的静态值，不阻塞列表渲染

> 早期版本曾有 `github_token` 配置项，已彻底移除（不入配置、不入请求头）。

---

## 五、安装

### 5.1 前提：平台的免签名插件通道

HXCS **不带 ed25519 签名**（`signature.value` 为空字符串）。这是刻意的：
本仓库内容由社区贡献，平台不为其安全性背书。

安装 HXCS 前，宿主平台必须显式打开免签名通道，二选一：

**方式 A — 系统管理界面（推荐，改完即生效）**

市场页 → 「允许未签名插件」→ 阅读风险告知 → 勾选同意 → 开启

**方式 B — 部署配置**

```yaml
# homex.yaml
plugin:
  allow_unsigned: true    # 默认 false，改完需重启
```

> **默认是拒绝的。** 不配置时平台按 fail-closed 拒收未签名包 —— 这是安全门，
> 不是能力开关。

### 5.2 官方插件不受此开关影响

**官方插件无条件必须带有效签名。** 未签名副本、自称官方的包，即使打开开关
也不会被放行。HXCS 属于第三方社区插件，走免签名通道。

### 5.3 安装方式

**方式 A — 市场页上传**

市场页 → 上传 `.hpkg` → 选择 `homex.hxcs-1.0.9.hpkg`

**方式 B — 直接安装**

```bash
curl -X POST http://<host>:8080/api/v1/plugins/install \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Household-Id: $HH" \
  -H "Content-Type: application/json" \
  -d @- <<EOF
{"package_b64": "$(base64 -w0 homex.hxcs-1.0.9.hpkg)"}
EOF
```

**已装过旧版本的机器**：先卸载再装。同版本不同包会报 `PLUGIN_ALREADY_INSTALLED`
或 `PLUGIN_VERSION_CONFLICT`。

---

## 六、目录结构

```
index.json                                   顶层索引（注册表入口）
src/                                         HXCS 插件源码
├── manifest.json                            插件清单（runtime: python）
├── requirements.lock                        依赖锁（带 sha256，平台会校验）
├── BUILD.md                                 构建说明
├── ui/                                      自带配置界面（entry.ui）
│   ├── index.html                           页面骨架（页头 + 分段卡片）
│   ├── app.js                               交互 + postMessage RPC（含 ping/pong）
│   └── style.css                            样式（自实现，不依赖平台 CSS）
└── runtime/
    ├── hxcs_worker.py                       主 Worker（社区商店 + HA 运行时）
    ├── hx_ha_runtime/                       HA 集成运行时（1043 行兼容层）
    │   ├── runtime.py                       install / config_flow / entry_setup
    │   ├── loader.py                        集成包加载与 manifest 校验
    │   ├── flow.py                          流程引擎
    │   ├── entity.py                        实体投影
    │   ├── registry.py                      设备/实体注册表
    │   ├── security.py                      凭据加密存储
    │   ├── network.py                       网络策略
    │   └── models.py / mapping.py / errors.py / core.py
    ├── homeassistant/                       HA API 兼容层（15 实体平台 + helpers）
    └── vendor.zip                           第三方依赖打包（aiohttp / pycryptodome / midealan 等）
plugins/<plugin-id>/releases/<ver>.hpkg      预打包制品
```

### 6.1 为什么依赖打成 vendor.zip

`.hpkg` 有**包内文件数上限 256**，而依赖展开是 563 个文件，超限。

- 打成单个 `vendor.zip` → 只占 1 个文件名额
- Worker 首次启动解压到 `<data>/plugins/hxcs-vendor/`（跨版本保留）
- 解压而不是直接从 zip import：zipimport 不支持原生扩展
  （pycryptodome 的 `.so`，midealan 用 AES 加密设备通信）

---

## 七、构建

```bash
# 1. 打包（在 homex 仓库里）
go run ./cmd/cli plugin package --dir <HXCS>/src --out build/homex.hxcs-1.0.9.hpkg

# 2. 去签名（本插件走免签名通道，不需要密钥）
go run ./cmd/cli plugin unsign build/homex.hxcs-1.0.9.hpkg

# 3. 验证结构（应当提示「未签名：平台会拒绝安装」，这是预期结果）
go run ./cmd/cli plugin verify build/homex.hxcs-1.0.9.hpkg

# 4. 更新 index.json 里的 version / package_url / package_sha256
sha256sum build/homex.hxcs-1.0.9.hpkg
```

> `plugin unsign` 会**清空 `signature.value` 但保留 `algorithm` / `key_id` 骨架**，
> 不是删除整个 signature 段 —— 后者会让 manifest 校验失败（
> `PLUGIN_MANIFEST_INVALID: 缺少 signature.algorithm`）。

---

## 八、上架社区插件

### 8.1 步骤

1. 按《HOMEX 插件开发指南》开发（manifest schema v2）
2. `plugin build` / `plugin package` 产出 `.hpkg`
3. 把 `version` / `package_url` / `package_sha256` 登记进 `index.json`
4. 制品放 `plugins/<plugin-id>/releases/`，提 PR

### 8.2 签名策略

第三方插件**不强制签名**（走平台免签名通道），支持的三种形态：

| 形态 | 签名 | 平台标识 | 说明 |
|---|---|---|---|
| 未签名 | 无 | `unsigned` | 市场页显示「未签名 · 来源未经验证」警示 |
| 自签 | 有，密钥不在信任集 | `signed_trusted` | 平台验过签但未背书发布者 |
| 官方 | 有，密钥在官方集 | `signed_official` | 只有这种能获得「官方」徽标 |

**注意**：manifest 自称 `trust: official` 的未签名包会被**直接拒绝**，不是降级 ——
以官方名义分发却拿不出签名，属于伪造形态。

### 8.3 上架要求（机器校验，缺一拒收）

- manifest 必须声明 `license`
- 依赖必须精确 pin（`name==version`），禁止 `git+` / `http` / `file` 源
- 禁止 `subprocess` / `os.system` / `pip install`
- 出站主机必须在 `resources.http.allowed_hosts` 白名单内

---

## 九、排障

| 现象 | 原因 | 解法 |
|---|---|---|
| `PLUGIN_SIGNATURE_INVALID` | 平台没开免签名通道 | 打开市场页开关，或配置 `plugin.allow_unsigned: true` |
| `PLUGIN_ALREADY_INSTALLED` | 已装过同名插件 | 先卸载再装 |
| `PLUGIN_VERSION_CONFLICT` | 同版本号但包内容不同 | 换版本号，或卸载旧包 |
| 社区插件列表为空 | `community_enabled` 未开 | 配置页打开「启用社区插件」 |
| HA 集成配置页无反应 | `ha_compat_enabled` 未开 | 配置页打开「兼容 HA 插件」 |
| 星数不更新 | 缓存 60 分钟未到 | 正常行为；或检查 GitHub 连通性（`proxy_url`） |
| 集成出站请求被拒 | `network_allowed_hosts` 为空 | 把目标主机加进 allowlist |

---

## 十、版权与许可

- HXCS 本体：MIT
- 兼容层参考 Home Assistant 的公开 API 形态，仅为互操作，不包含 HA 源码
- 各社区插件的许可证与来源仓库在对应卡片上明示

## 十一、免责声明

本仓库内容由社区贡献。**HOMEX 不对其安全性、合规性、可用性作任何担保。**

启用「允许未签名插件」即表示你已知晓并自行承担由此产生的全部安全与法律风险，
包括但不限于：设备被控制、家庭数据被读取、插件被替换为恶意版本。

发现恶意插件请通过 GitHub Issues 举报。