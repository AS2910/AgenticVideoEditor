"""The editor's live channel (2026-10-20, one processing model).

Worker threads publish what changed (a job, the turn, the render) for a video;
every open `GET /videos/{id}/events` stream holds a queue and drains it. In
process and thread-safe: one server, a handful of open editors.
"""
from __future__ import annotations

import queue
import threading


class EventBus:
    def __init__(self, maxsize: int = 500) -> None:
        self._subs: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()
        self._maxsize = maxsize

    def subscribe(self, video_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._maxsize)
        with self._lock:
            self._subs.setdefault(video_id, []).append(q)
        return q

    def unsubscribe(self, video_id: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subs.get(video_id, [])
            if q in subs:
                subs.remove(q)
            if not subs:
                self._subs.pop(video_id, None)

    def publish(self, video_id: str, event: str, data: dict) -> None:
        with self._lock:
            subs = list(self._subs.get(video_id, ()))
        for q in subs:
            try:
                q.put_nowait((event, data))
            except queue.Full:
                # A stream that stopped reading loses the oldest news, not the newest:
                # a reconnect restores state from GET jobs anyway.
                try:
                    q.get_nowait()
                    q.put_nowait((event, data))
                except (queue.Empty, queue.Full):
                    pass

    def listeners(self, video_id: str) -> int:
        with self._lock:
            return len(self._subs.get(video_id, ()))
