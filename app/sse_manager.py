"""
SSE connection manager: maps session_id to asyncio Queue for push notifications.
"""
import asyncio
from typing import Dict, Optional


class SSEManager:
    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues[session_id] = q
        return q

    def unsubscribe(self, session_id: str) -> None:
        self._queues.pop(session_id, None)

    def push(self, session_id: str, event: dict) -> bool:
        q = self._queues.get(session_id)
        if q is None:
            return False
        try:
            q.put_nowait(event)
            return True
        except asyncio.QueueFull:
            return False


sse_manager = SSEManager()
