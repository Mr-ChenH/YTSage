"""Optional bearer-token auth for the server API."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, WebSocket, status

from ..config import ServerConfig


def require_auth(config: ServerConfig, request: Request, authorization: str | None = Header(default=None)) -> None:
    if not config.auth_token:
        return
    expected = f"Bearer {config.auth_token}"
    if authorization == expected:
        return
    if request.query_params.get("token") == config.auth_token:
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


async def require_websocket_auth(config: ServerConfig, websocket: WebSocket) -> bool:
    if not config.auth_token:
        return True
    token = websocket.headers.get("authorization")
    if token == f"Bearer {config.auth_token}":
        return True
    query_token = websocket.query_params.get("token")
    return query_token == config.auth_token
