from __future__ import annotations

import asyncio
import ipaddress
import socket
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .errors import HACompatError


class NetworkPolicyError(HACompatError):
    code = "HA_COMPAT_NETWORK_DENIED"


@dataclass(slots=True)
class NetworkPolicy:
    """Explicit egress allow-list. Empty is deny-all."""
    allowed_hosts: set[str] = field(default_factory=set)
    allowed_schemes: set[str] = field(default_factory=lambda: {"https"})
    allow_private: bool = False
    max_response_bytes: int = 2 * 1024 * 1024

    def validate(self, url: str) -> None:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in self.allowed_schemes or not host or host not in self.allowed_hosts:
            raise NetworkPolicyError(f"egress destination denied: {parsed.scheme}://{host}")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
        except socket.gaierror as exc:
            raise NetworkPolicyError(f"destination resolution failed: {host}") from exc
        if not self.allow_private:
            for address in addresses:
                ip = ipaddress.ip_address(address)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                    raise NetworkPolicyError(f"private destination denied: {host}")


class ControlledSession:
    def __init__(self, policy: NetworkPolicy) -> None:
        self.policy = policy

    async def request(self, method: str, url: str, *, data: bytes | None = None,
                      headers: dict[str, str] | None = None, timeout: float = 10):
        self.policy.validate(url)
        def perform():
            request = urllib.request.Request(url, data=data, headers=headers or {}, method=method.upper())
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read(self.policy.max_response_bytes + 1)
                if len(body) > self.policy.max_response_bytes:
                    raise NetworkPolicyError("response exceeds policy limit")
                return {"status": response.status, "headers": dict(response.headers), "body": body}
        return await asyncio.to_thread(perform)

    async def get(self, url: str, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs):
        return await self.request("POST", url, **kwargs)
