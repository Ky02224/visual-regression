"""Server-sent events: the subscriber registry and the broadcast helper.

This lives in its own module because almost every write path in the API calls
broadcast_event, so leaving it in dashboard_server would force each extracted
router to import that module back.

The subscriber list is capped. An unbounded list would grow with every browser
tab that ever connected, and each entry holds a bounded queue that a
disconnected client never drains.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

MAX_SUBSCRIBERS = 50
SUBSCRIBER_QUEUE_SIZE = 100

_SSE_SUBSCRIBERS: List[queue.Queue] = []
_SSE_SUBSCRIBERS_LOCK = threading.Lock()


def subscribe() -> queue.Queue:
    """Register a new SSE listener and return its queue.

    When the cap is reached the oldest subscriber is dropped rather than
    refusing the new one: a stale entry is far more likely to be a browser tab
    that went away without closing the stream than an active listener.
    """
    q: queue.Queue = queue.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
    with _SSE_SUBSCRIBERS_LOCK:
        if len(_SSE_SUBSCRIBERS) >= MAX_SUBSCRIBERS:
            try:
                _SSE_SUBSCRIBERS.pop(0)
            except IndexError:
                pass
        _SSE_SUBSCRIBERS.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _SSE_SUBSCRIBERS_LOCK:
        try:
            _SSE_SUBSCRIBERS.remove(q)
        except ValueError:
            pass


def subscriber_count() -> int:
    with _SSE_SUBSCRIBERS_LOCK:
        return len(_SSE_SUBSCRIBERS)


def broadcast_event(event_type: str, data: Dict[str, Any]) -> None:
    """Push an event to every live listener, dropping the ones that cannot take it.

    A subscriber whose queue is full is a client that stopped reading, so it is
    removed rather than retried — otherwise one dead tab would block every
    broadcast behind it.
    """
    msg = {"type": event_type, "data": data, "timestamp": time.time()}
    with _SSE_SUBSCRIBERS_LOCK:
        dead_queues = []
        for q in _SSE_SUBSCRIBERS:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead_queues.append(q)
            except Exception:
                dead_queues.append(q)
        for dq in dead_queues:
            try:
                _SSE_SUBSCRIBERS.remove(dq)
            except ValueError:
                pass
    if dead_queues:
        logger.debug("[SSE] Dropped %d unresponsive subscriber(s)", len(dead_queues))
