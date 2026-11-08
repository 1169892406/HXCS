// HX-Mqtt Broker —— HOMEX 第三方插件（HX Community），放在 HXCS 仓的
// plugins/mqtt-broker/src 下，与其它社区插件同一套分发方式。
//
// replace 指向同级平台 SDK 的本地路径只是**开发期便利**：发布包已编入
// plugin.wasm，用户拿到的 .hpkg 不含 replace，也不需要平台源码。
//
// 构建路径按本仓布局：HXCS/plugins/mqtt-broker/src → 平台 SDK 在
// <workspace>/homex/sdk/go（四个 ../）。改工作区布局时同步这一行。
module homex.dev/homex/plugins/community/mqtt-broker

go 1.24

require homex.dev/homex/sdk/go v0.0.0

replace homex.dev/homex/sdk/go => ../../../../homex/sdk/go
