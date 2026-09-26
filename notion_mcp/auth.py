from __future__ import annotations

import hmac
import ipaddress
import json
from typing import Any, Awaitable, Callable


ASGIApp = Callable[[dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[None]]


class PrivateMCPMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        access_token: str,
        public_host: str,
        allowed_origins: tuple[str, ...] = (),
        unauthenticated_proxy_networks: tuple[str, ...] = (),
        allow_unauthenticated: bool = False,
    ) -> None:
        self.app = app
        self.access_token = access_token
        self.allowed_hosts = {"localhost", "127.0.0.1", "::1", public_host.lower()}
        self.allowed_origins = {origin.rstrip("/") for origin in allowed_origins}
        self.unauthenticated_proxy_networks = tuple(
            ipaddress.ip_network(network, strict=False) for network in unauthenticated_proxy_networks
        )
        self.allow_unauthenticated = allow_unauthenticated

    def _is_trusted_proxy_request(self, scope: dict[str, Any], headers: dict[str, str]) -> bool:
        if not self.unauthenticated_proxy_networks:
            return False
        peer = scope.get("client")
        if not peer:
            return False
        try:
            peer_ip = ipaddress.ip_address(peer[0])
        except ValueError:
            return False
        if not peer_ip.is_loopback:
            return False
        forwarded = headers.get("cf-connecting-ip", "").strip()
        try:
            forwarded_ip = ipaddress.ip_address(forwarded)
        except ValueError:
            return False
        return any(forwarded_ip in network for network in self.unauthenticated_proxy_networks)

    @staticmethod
    async def _response(send: Callable[..., Awaitable[Any]], status: int, message: str, headers: list[tuple[bytes, bytes]] | None = None) -> None:
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        response_headers = [(b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(body)).encode())]
        response_headers.extend(headers or [])
        await send({"type": "http.response.start", "status": status, "headers": response_headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[Any]], send: Callable[..., Awaitable[Any]]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("path") != "/mcp":
            await self._response(send, 404, "Not found")
            return
        if scope.get("method") != "POST":
            await self._response(send, 405, "Method not allowed", [(b"allow", b"POST")])
            return
        headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope.get("headers", [])}
        host = headers.get("host", "").split(":", 1)[0].strip("[]").lower()
        if host not in self.allowed_hosts:
            await self._response(send, 421, "Invalid host")
            return
        origin = headers.get("origin")
        if origin and self.allowed_origins and origin.rstrip("/") not in self.allowed_origins:
            await self._response(send, 403, "Origin not allowed")
            return
        supplied = headers.get("authorization", "")
        expected = f"Bearer {self.access_token}"
        if (
            not self.allow_unauthenticated
            and not self._is_trusted_proxy_request(scope, headers)
            and not hmac.compare_digest(supplied, expected)
        ):
            await self._response(
                send,
                401,
                "Unauthorized",
                [(b"www-authenticate", b"Bearer")],
            )
            return
        await self.app(scope, receive, send)
