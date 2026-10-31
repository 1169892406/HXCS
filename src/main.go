// hxcs —— HOMEX Community Store 连接器。
//
// 职责只有两件事：
//  1. catalog.list   拉取社区注册表（GitHub）的 index.json，把插件清单交给市场页；
//  2. catalog.fetch  下载指定插件的 .hpkg 字节（base64），由前端走既有
//                    POST /plugins/install 完成安装（验签/权限/schema 全走平台公开路径）。
//
// # 为什么不做「直接安装」
//
// 安装走平台既有 API（前端拿到字节后 POST）而不是插件代劳：插件没有
// 装插件的能力，也不该有 —— 那会把信任边界打穿。本插件只做「取货」，
// 「上架验收」仍由平台的 Install 全链路（验签/权限求交/schema 校验）把关。
//
// # 信任模型（社区信任根）
//
// 注册表 index.json 自带 trust_root（社区公钥）。社区插件用该 key 签名；
// 部署侧把社区公钥加进 HOMEX_PLUGIN_TRUSTED_KEYS 后，安装即可通过验签。
// 用户只需信任一次社区根，不必逐插件确认 —— 责任边界在 index.json 的
// 免责声明与卡片上的来源/许可证展示。
package main

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"homex.dev/homex/sdk/go/plugin"
)

type hxcsConfig struct {
	CommunityEnabled bool   `json:"community_enabled"`
	RegistryURL      string `json:"registry_url"`
	// HACompatEnabled 开启后支持 HA 风格集成包的展示与导入。
	// 默认关闭：HXCS 仅作为社区插件商店。
	HACompatEnabled bool `json:"ha_compat_enabled"`
}

var cfg hxcsConfig

func init() {
	plugin.Register(plugin.Plugin{
		Configure: func(ctx *plugin.Context, config json.RawMessage) error {
			if len(config) > 0 {
				if err := json.Unmarshal(config, &cfg); err != nil {
					return fmt.Errorf("配置解析失败: %w", err)
				}
			}
			if cfg.RegistryURL == "" {
				cfg.RegistryURL = "https://raw.githubusercontent.com/homex-community/hxcs-registry/main"
			}
			ctx.LogInfo("hxcs 配置完成 enabled=%t registry=%s", cfg.CommunityEnabled, cfg.RegistryURL)
			return nil
		},

		Call: func(ctx *plugin.Context, tool string, args json.RawMessage) (json.RawMessage, error) {
			return call(ctx, tool, args)
		},

		Health: func(ctx *plugin.Context) (plugin.HealthStatus, error) {
			return plugin.HealthStatus{OK: true}, nil
		},

		Event: func(ctx *plugin.Context, subject string, payload json.RawMessage) error {
			return nil
		},
	})
}

// —— 工具实现 ————————————————————————————————————————————

func communityStatus() (json.RawMessage, error) {
	return json.Marshal(map[string]any{
		"enabled":     cfg.CommunityEnabled,
		"registry":    cfg.RegistryURL,
		"registry_v":  "1",
		"ha_compat":   cfg.HACompatEnabled,
	})
}

// catalogList 拉取注册表 index.json 并原样返回（前端按官方目录同一结构渲染）。
func catalogList(ctx *plugin.Context) (json.RawMessage, error) {
	if !cfg.CommunityEnabled {
		return nil, fmt.Errorf("社区插件未启用：请在 HXCS 配置页打开「启用社区插件」")
	}
	url := strings.TrimRight(cfg.RegistryURL, "/") + "/index.json"
	body, err := httpGet(ctx, url, 1<<20)
	if err != nil {
		return nil, fmt.Errorf("拉取社区注册表失败: %w", err)
	}
	var idx struct {
		RegistryVersion string           `json:"registry_version"`
		TrustRoot       json.RawMessage  `json:"trust_root"`
		Plugins         []map[string]any `json:"plugins"`
	}
	if err := json.Unmarshal(body, &idx); err != nil {
		return nil, fmt.Errorf("注册表格式非法: %w", err)
	}
	// ha_compat 关闭时过滤掉 HA 集成包（type=ha_integration）：
	// 用户没开兼容模式就不该看到装不了的东西。
	if !cfg.HACompatEnabled {
		filtered := make([]map[string]any, 0, len(idx.Plugins))
		for _, p := range idx.Plugins {
			if pt, _ := p["type"].(string); pt == "ha_integration" {
				continue
			}
			filtered = append(filtered, p)
		}
		idx.Plugins = filtered
	}
	return json.Marshal(idx)
}

// catalogFetch 下载指定插件的 .hpkg，返回 base64 + sha256 供前端安装。
func catalogFetch(ctx *plugin.Context, args json.RawMessage) (json.RawMessage, error) {
	if !cfg.CommunityEnabled {
		return nil, fmt.Errorf("社区插件未启用")
	}
	var in struct {
		PackageURL    string `json:"package_url"`
		ExpectSHA256  string `json:"expect_sha256"`
	}
	if err := json.Unmarshal(args, &in); err != nil {
		return nil, fmt.Errorf("参数解析失败: %w", err)
	}
	if in.PackageURL == "" {
		return nil, fmt.Errorf("缺少 package_url")
	}
	// 只允许相对路径（拼在注册表 base 之后），禁止绝对 URL 注入。
	if strings.Contains(in.PackageURL, "://") || strings.HasPrefix(in.PackageURL, "/") {
		return nil, fmt.Errorf("package_url 必须是注册表内相对路径")
	}
	url := strings.TrimRight(cfg.RegistryURL, "/") + "/" + in.PackageURL
	body, err := httpGet(ctx, url, 32<<20)
	if err != nil {
		return nil, fmt.Errorf("下载插件包失败: %w", err)
	}
	sum := sha256.Sum256(body)
	got := hex.EncodeToString(sum[:])
	if in.ExpectSHA256 != "" && got != strings.ToLower(in.ExpectSHA256) {
		return nil, fmt.Errorf("包摘要不匹配：期望 %s 实际 %s（注册表数据与包不一致，拒绝交付）", in.ExpectSHA256, got)
	}
	return json.Marshal(map[string]any{
		"package_b64": base64.StdEncoding.EncodeToString(body),
		"sha256":      got,
		"size":        len(body),
	})
}

// —— HTTP 辅助（会话即开即关，不留状态）———————————————

func httpGet(ctx *plugin.Context, url string, maxBytes int64) ([]byte, error) {
	sess, err := ctx.HTTPOpen(plugin.HTTPOpenRequest{})
	if err != nil {
		return nil, fmt.Errorf("打开 HTTP 会话失败: %w", err)
	}
	defer func() { _ = ctx.HTTPClose(sess.SessionID) }()
	resp, err := ctx.HTTPSessionDo(plugin.HTTPSessionRequest{
		SessionID: sess.SessionID,
		Method:    "GET",
		URL:       url,
		Headers:   map[string]string{"Accept": "application/json, application/octet-stream"},
		TimeoutMS: 15000,
	})
	if err != nil {
		return nil, err
	}
	body, err := resp.Body()
	if err != nil {
		return nil, err
	}
	if resp.Status != 200 {
		return nil, fmt.Errorf("HTTP %d", resp.Status)
	}
	if int64(len(body)) > maxBytes {
		return nil, fmt.Errorf("响应超过上限 %d 字节", maxBytes)
	}
	return body, nil
}

// call 是工具分发的独立入口（Register 回调与测试共用同一实现，
// 避免"测试测的是另一条路径"）。
func call(ctx *plugin.Context, tool string, args json.RawMessage) (json.RawMessage, error) {
	switch tool {
	case "community_status":
		return communityStatus()
	case "catalog_list":
		return catalogList(ctx)
	case "catalog_fetch":
		return catalogFetch(ctx, args)
	default:
		return nil, plugin.ErrNotImplemented
	}
}

// main 只为让 go vet 满意。
func main() { _ = io.EOF }
