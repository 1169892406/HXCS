package main

import (
	"encoding/base64"
	"encoding/json"
	"testing"

	"homex.dev/homex/sdk/go/plugin"
	"homex.dev/homex/sdk/go/plugin/hosttest"
)

// TestCatalogListFetchE2E 端到端：catalog_list 从本地注册表拉索引 → catalog_fetch 取包。
// 宿主 HTTP mock 直接回传真实注册表文件内容（绕过真网，但走完整 SDK 调用链）。
func TestCatalogListFetchE2E(t *testing.T) {
	idxRaw := `{"registry_version":"1","trust_root":{"key_id":"hxcs-community"},"plugins":[
		{"plugin_id":"homex.example.demo_weather","name":"示例·天气查询","version":"1.0.0",
		 "type":"prebuilt","package_url":"plugins/demo-weather/releases/demo-weather-1.0.0.hpkg",
		 "package_sha256":"7259ed9e5838571751d02bbf948528bc0a37f10a0f0965b346a9bae8f35691cd"}]}`
	pkgBytes := []byte("fake-hpkg-for-test")
	h := hosttest.New(t)
	h.Fixture(plugin.OpHTTPOpen, map[string]any{"session_id": "s1"})
	h.Fixture(plugin.OpHTTPClose, map[string]any{"ok": true})
	h.On(plugin.OpHTTPSessionRequest, func(raw json.RawMessage) (any, error) {
		var req plugin.HTTPSessionRequest
		_ = json.Unmarshal(raw, &req)
		if req.URL == "http://127.0.0.1:18999/index.json" {
			return plugin.HTTPSessionResponse{Status: 200, BodyB64: base64.StdEncoding.EncodeToString([]byte(idxRaw))}, nil
		}
		// 包下载
		return plugin.HTTPSessionResponse{Status: 200, BodyB64: base64.StdEncoding.EncodeToString(pkgBytes)}, nil
	})

	cfg = hxcsConfig{CommunityEnabled: true, RegistryURL: "http://127.0.0.1:18999"}
	ctx := &plugin.Context{PluginID: "homex.hxcs", HouseholdID: "hh"}

	// 1) catalog_list
	out, err := call(ctx, "catalog_list", json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("catalog_list 失败: %v", err)
	}
	var idx map[string]any
	json.Unmarshal(out, &idx)
	plugins, _ := idx["plugins"].([]any)
	if len(plugins) != 1 {
		t.Fatalf("应返回 1 个插件，实际 %d", len(plugins))
	}
	t.Logf("catalog_list OK: %d 个社区插件", len(plugins))

	// 2) catalog_fetch
	args, _ := json.Marshal(map[string]any{
		"package_url":   "plugins/demo-weather/releases/demo-weather-1.0.0.hpkg",
		"expect_sha256": "",
	})
	out2, err := call(ctx, "catalog_fetch", args)
	if err != nil {
		t.Fatalf("catalog_fetch 失败: %v", err)
	}
	var res map[string]any
	json.Unmarshal(out2, &res)
	if res["sha256"] == "" || res["package_b64"] == "" {
		t.Fatal("应返回 sha256 与 package_b64")
	}
	t.Logf("catalog_fetch OK: size=%v sha256=%v...", res["size"], string(res["sha256"].(string))[:8])
}
