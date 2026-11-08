// HX-Mqtt Broker —— HOMEX 官方插件：平台内置 MQTT 消息总线的**市场登记条目**。
//
// # 定位（用户 2026-11-08 口径）
//
// MQTT 是平台的**内置消息总线**（公共组件），编译在主服务里：
//   · 没有独立进程；
//   · 不监听独立端口（1884 是主服务内部 IPC 通道，由 homex-server 持有）；
//   · 随主服务启动加载，热升级由平台包热加载机制接管。
//
// 因此本插件**不实现 broker**，它做的是三件事：
//   1. 让这个内置组件在应用市场里**可见、可安装**（用户口径：做成单独的官方插件）；
//   2. 通过 `requirements` 工具如实登记"我依赖平台提供什么"（可审计的声明）；
//   3. 通过 `status` 工具报告**它自己这一代的加载状态**。
//
// # 为什么不在插件里假装 broker 在跑
//
// wasm 沙箱拿不到主服务内部的 broker 句柄，也没有任何 host API 能查它的连接数/
// 订阅表。编一个 "running: true" 出来，会在 broker 真出问题时给出**假绿**——
// 那比不给状态更糟。所以 status 只回报"本插件这一代已加载"，并明确写清
// `broker_visibility: platform_internal`：真实运行态要看平台侧（/readyz）。
//
// 编译（缺一不可，否则加载报 PLUGIN_ABI_INCOMPATIBLE）：
//
//	GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o plugin.wasm .
package main

import (
	"encoding/json"

	"homex.dev/homex/sdk/go/plugin"
)

const (
	pluginID = "hx.mqtt_broker"
	version  = "1.1.0"
)

// requirementsPayload 是 `requirements` 工具的结果：**声明**本插件对平台的依赖，
// 不承担"探测平台是否满足"的职责（那属于平台侧就绪检查）。
func requirementsPayload() map[string]any {
	return map[string]any{
		"plugin_id": pluginID,
		"version":   version,
		// embedded=true 是这个插件与其它 MQTT 类插件的根本区别：
		// 它不携带 broker 实现，也不要求外部进程。
		"embedded": true,
		"host_requirements": []string{
			"主服务内置 MQTT 消息总线（编译进 homex-server，随主服务启动）",
			"无需独立进程、无需独立监听端口",
			"设备消息经宿主统一分发：插件侧用 SDK 高层接口，不直接对接 MQTT",
		},
		"ports":      []int{}, // 显式空数组：本插件不占用任何端口
		"processes":  []string{},
		"hot_reload": true, // 随包热加载（平台 package_hotwatch），无需重启主服务
	}
}

func init() {
	plugin.Register(plugin.Plugin{
		Configure: func(ctx *plugin.Context, _ json.RawMessage) error {
			// 无用户可配置项（通道容量/ACL 等属于部署级参数，由部署配置管理）。
			// 这里只留一条加载痕迹，方便在插件日志里确认"这一代起来了"。
			ctx.LogInfo("hx.mqtt_broker %s 已加载：内置消息总线（无独立进程/端口）", version)
			return nil
		},

		Call: func(ctx *plugin.Context, tool string, _ json.RawMessage) (json.RawMessage, error) {
			switch tool {
			case "requirements":
				return json.Marshal(requirementsPayload())

			case "status":
				// 只报"我这一代已加载"。broker 的真实运行态在平台侧，
				// 本插件刻意不伪造（见文件头）。
				return json.Marshal(map[string]any{
					"plugin_id":          pluginID,
					"version":            version,
					"generation_loaded":  true,
					"transport":          "embedded",
					"broker_visibility":  "platform_internal",
					"broker_status_hint": "真实运行态见平台 /readyz（内置 broker 由 homex-server 持有）",
				})

			default:
				return nil, plugin.ErrNotImplemented
			}
		},

		// Health 不实现 = 视为健康（SDK 约定）。本插件没有外部依赖，
		// 把"平台 broker 可用性"当自己的健康判据会造成错误的因果链：
		// broker 抖动 → 插件被判不健康 → 自动回滚，而插件本身没坏。
	})
}

func main() {} // c-shared 下不执行；保留以满足 go vet 对 main 包的要求。
