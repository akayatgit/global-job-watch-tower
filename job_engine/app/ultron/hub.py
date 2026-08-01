"""In-memory WebSocket hub for VIGIL / Ultron multi-tab sync."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class UltronHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self.status_line = 'VIGIL ONLINE — JOB MARKET CORE ACTIVE'
        self.panel_state: dict[str, Any] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        await ws.send_json({
            'type': 'ultron.hello',
            'status': self.status_line,
            'panels': self.panel_state,
            'clients': len(self._clients),
        })

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast(self, event: dict[str, Any], *, skip: WebSocket | None = None) -> None:
        payload = json.dumps(event, default=str)
        dead: list[WebSocket] = []
        async with self._lock:
            clients = list(self._clients)
        for client in clients:
            if client is skip:
                continue
            try:
                await client.send_text(payload)
            except Exception:
                dead.append(client)
        for client in dead:
            await self.disconnect(client)

    async def handle_message(self, ws: WebSocket, data: dict[str, Any]) -> None:
        etype = data.get('type') or data.get('event') or 'ultron.ping'
        if etype == 'ultron.status':
            self.status_line = str(data.get('text') or self.status_line)
        elif etype in ('ultron.panel', 'ultron.command', 'ultron.gesture'):
            panel = data.get('panel')
            if panel and isinstance(data.get('state'), dict):
                self.panel_state[str(panel)] = data['state']
        await self.broadcast({**data, 'type': etype}, skip=None)


hub = UltronHub()
