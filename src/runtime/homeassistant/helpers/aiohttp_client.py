"""最小 homeassistant.helpers.aiohttp_client 兼容层。

HA 集成（尤其带云账号的）会用 async_create_clientsession 建一个
自己的 aiohttp 会话。HXCS 运行时里网络出口由宿主的 network_session
统一管控（deny-by-default allowlist），所以这里不能真让集成自己开大网。

策略：
  · async_get_clientsession(hass) → 宿主的受控会话（不新建）
  · async_create_clientsession(hass, ...) → 也返回宿主会话（忽略自定义参数）
这样集成能正常跑，但出站仍受 allowlist 约束。
"""
from __future__ import annotations


def async_get_clientsession(hass):
    """返回 HOMEX 控制的 deny-by-default 网络会话。"""
    return hass.data["hx_http_session"]


def async_create_clientsession(hass, *args, **kwargs):
    """HA 集成想自建会话时，仍返回宿主受控会话。

    真实 HA 允许集成自建会话（不受 HA 的 verify_ssl / cookie jar 约束），
    但 HXCS 的架构要求所有出站都过宿主 allowlist —— 否则"插件不许随便
    连外网"这条约束会被一个集成绕过。
    """
    return async_get_clientsession(hass)


__all__ = ["async_create_clientsession", "async_get_clientsession"]
