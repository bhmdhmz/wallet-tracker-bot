"""A dependency-free HTTP endpoint, so the tracker can run as a "web service".

Platforms like Render only offer a free instance type for services that bind a
port. This exposes GET / and GET /healthz with a small JSON status payload,
which doubles as the target for an external keep-alive pinger.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

log = logging.getLogger(__name__)

STATUS: dict = {
    "service": "wallet-tracker",
    "started_at": int(time.time()),
    "last_poll": None,
    "wallets": 0,
    "alerts_sent": 0,
    "errors": 0,
}


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        writer.close()
        return

    body = json.dumps({**STATUS, "uptime_seconds": int(time.time()) - STATUS["started_at"]})
    payload = body.encode()
    writer.write(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(payload)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + payload
    )
    try:
        await writer.drain()
    except ConnectionError:
        pass
    writer.close()


async def start(port: int) -> None:
    server = await asyncio.start_server(_handle, "0.0.0.0", port)
    log.info("Health endpoint listening on port %s", port)
    asyncio.create_task(server.serve_forever())
