"""登录入口的进程内短窗限流；数据库上限仍提供跨进程最终保护。"""

from __future__ import annotations

import hashlib
import ipaddress
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from fastapi import Request


class LoginRateLimitExceeded(RuntimeError):
    """客户端或全局登录请求超过安全速率。"""


@dataclass(frozen=True, slots=True)
class LoginRateLimitConfig:
    per_client_limit: int = 10
    global_limit: int = 120
    window_seconds: int = 60
    trusted_proxy_cidrs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.per_client_limit <= self.global_limit:
            raise ValueError("客户端登录限额必须大于零且不超过全局限额")
        if not 1 <= self.global_limit <= 100_000:
            raise ValueError("全局登录限额必须在 1 至 100000 之间")
        if not 1 <= self.window_seconds <= 3_600:
            raise ValueError("登录限流窗口必须在 1 至 3600 秒之间")
        for cidr in self.trusted_proxy_cidrs:
            ipaddress.ip_network(cidr, strict=False)


class LoginRateLimiter:
    def __init__(
        self,
        config: LoginRateLimitConfig = LoginRateLimitConfig(),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._clock = clock
        self._trusted_proxies = tuple(
            ipaddress.ip_network(cidr, strict=False)
            for cidr in config.trusted_proxy_cidrs
        )
        self._global_hits: deque[float] = deque()
        self._client_hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, request: Request) -> None:
        now = self._clock()
        client_key = _client_key(
            _client_address(request, self._trusted_proxies)
        )
        cutoff = now - self._config.window_seconds
        with self._lock:
            _prune(self._global_hits, cutoff)
            if len(self._global_hits) >= self._config.global_limit:
                raise LoginRateLimitExceeded("全局登录请求过于频繁")
            hits = self._client_hits.setdefault(client_key, deque())
            _prune(hits, cutoff)
            if len(hits) >= self._config.per_client_limit:
                raise LoginRateLimitExceeded("客户端登录请求过于频繁")
            self._global_hits.append(now)
            hits.append(now)
            self._drop_empty_clients(cutoff)

    def _drop_empty_clients(self, cutoff: float) -> None:
        for key in tuple(self._client_hits):
            hits = self._client_hits[key]
            _prune(hits, cutoff)
            if not hits:
                del self._client_hits[key]


def _client_address(
    request: Request,
    trusted_proxies: tuple[
        ipaddress.IPv4Network | ipaddress.IPv6Network, ...
    ],
) -> str:
    peer = request.client.host if request.client is not None else "unknown"
    peer_ip = _parse_ip(peer)
    if peer_ip is None or not _is_trusted(peer_ip, trusted_proxies):
        return peer
    forwarded_values = request.headers.getlist("X-Forwarded-For")
    if len(forwarded_values) != 1:
        return peer
    forwarded = forwarded_values[0]
    chain = [_parse_ip(part.strip()) for part in forwarded.split(",")]
    if any(address is None for address in chain):
        return peer
    addresses = [address for address in chain if address is not None]
    addresses.append(peer_ip)
    while len(addresses) > 1 and _is_trusted(
        addresses[-1], trusted_proxies
    ):
        addresses.pop()
    return str(addresses[-1])


def _parse_ip(value: str):
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _is_trusted(address, networks) -> bool:
    return any(address in network for network in networks)


def _client_key(address: str) -> str:
    return hashlib.sha256(address.encode("utf-8")).hexdigest()


def _prune(hits: deque[float], cutoff: float) -> None:
    while hits and hits[0] <= cutoff:
        hits.popleft()
