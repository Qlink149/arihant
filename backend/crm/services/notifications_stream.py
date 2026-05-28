import asyncio
import json
from typing import Any, AsyncIterator, Dict, Optional


class NotificationsStream:
    """
    In-memory pubsub for SSE notifications.

    Note: This is process-local. In multi-worker deployments, users will only receive
    events published on the same worker that holds their SSE connection.
    """

    def __init__(self) -> None:
        self._queues: Dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def register(self, user_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._queues.setdefault(user_id, set()).add(q)
        return q

    async def unregister(self, user_id: str, q: asyncio.Queue) -> None:
        async with self._lock:
            if user_id not in self._queues:
                return
            self._queues[user_id].discard(q)
            if not self._queues[user_id]:
                self._queues.pop(user_id, None)

    async def publish(self, user_id: str, payload: Dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._queues.get(user_id, set()))
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop oldest by recreating queue item lossily; keep stream alive.
                try:
                    _ = q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

    async def stream(self, user_id: str, *, heartbeat_seconds: int = 15) -> AsyncIterator[bytes]:
        q = await self.register(user_id)
        try:
            # Initial handshake comment so proxies flush early
            yield b": connected\n\n"
            while True:
                try:
                    item: Optional[Dict[str, Any]] = await asyncio.wait_for(q.get(), timeout=heartbeat_seconds)
                except asyncio.TimeoutError:
                    yield b": heartbeat\n\n"
                    continue
                data = json.dumps(item, default=str)
                yield f"event: notification\ndata: {data}\n\n".encode("utf-8")
        finally:
            await self.unregister(user_id, q)


notifications_stream = NotificationsStream()

