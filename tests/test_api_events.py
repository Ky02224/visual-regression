"""Tests for the SSE subscriber registry.

Every write path in the API calls broadcast_event, and none of this had a test.
The two failure modes it guards against are both invisible in normal use: the
subscriber list growing forever as browser tabs come and go, and one client that
stopped reading blocking every broadcast behind it.
"""

from __future__ import annotations

import queue
import threading

import pytest

from visual_regression.api import events


@pytest.fixture(autouse=True)
def _clean_registry():
    """The registry is module state; keep tests from leaking into each other."""
    with events._SSE_SUBSCRIBERS_LOCK:
        events._SSE_SUBSCRIBERS.clear()
    yield
    with events._SSE_SUBSCRIBERS_LOCK:
        events._SSE_SUBSCRIBERS.clear()


class TestSubscription:
    def test_subscribe_returns_a_queue_and_registers_it(self):
        q = events.subscribe()
        assert isinstance(q, queue.Queue)
        assert events.subscriber_count() == 1

    def test_unsubscribe_removes_it(self):
        q = events.subscribe()
        events.unsubscribe(q)
        assert events.subscriber_count() == 0

    def test_unsubscribing_twice_is_harmless(self):
        """The SSE endpoint unsubscribes in a finally block that can run after
        the subscriber was already dropped as unresponsive."""
        q = events.subscribe()
        events.unsubscribe(q)
        events.unsubscribe(q)
        assert events.subscriber_count() == 0

    def test_unsubscribing_something_never_registered_is_harmless(self):
        events.unsubscribe(queue.Queue())
        assert events.subscriber_count() == 0

    def test_the_registry_is_capped(self):
        """Unbounded growth here would leak a queue per browser tab that ever
        connected, for the process's lifetime."""
        for _ in range(events.MAX_SUBSCRIBERS + 25):
            events.subscribe()
        assert events.subscriber_count() == events.MAX_SUBSCRIBERS

    def test_the_oldest_subscriber_is_dropped_at_the_cap(self):
        first = events.subscribe()
        for _ in range(events.MAX_SUBSCRIBERS):
            events.subscribe()

        events.broadcast_event("ping", {})

        assert first.empty(), "the evicted subscriber still received events"


class TestBroadcast:
    def test_delivers_to_every_subscriber(self):
        subscribers = [events.subscribe() for _ in range(3)]
        events.broadcast_event("run_finished", {"run_id": "r1"})
        for q in subscribers:
            msg = q.get_nowait()
            assert msg["type"] == "run_finished"
            assert msg["data"] == {"run_id": "r1"}

    def test_stamps_each_message_with_a_timestamp(self):
        q = events.subscribe()
        events.broadcast_event("x", {})
        assert isinstance(q.get_nowait()["timestamp"], float)

    def test_broadcasting_with_no_subscribers_is_a_no_op(self):
        events.broadcast_event("x", {})

    def test_a_full_queue_is_dropped_rather_than_retried(self):
        """A client that stopped reading must not block every later broadcast."""
        stalled = events.subscribe()
        for _ in range(events.SUBSCRIBER_QUEUE_SIZE):
            stalled.put_nowait({"filler": True})

        events.broadcast_event("x", {})

        assert events.subscriber_count() == 0

    def test_a_healthy_subscriber_survives_a_stalled_neighbour(self):
        stalled = events.subscribe()
        healthy = events.subscribe()
        for _ in range(events.SUBSCRIBER_QUEUE_SIZE):
            stalled.put_nowait({"filler": True})

        events.broadcast_event("run_finished", {"run_id": "r1"})

        assert healthy.get_nowait()["type"] == "run_finished"
        assert events.subscriber_count() == 1

    def test_concurrent_broadcasts_do_not_corrupt_the_registry(self):
        """Broadcasts come from request handlers and background worker threads.

        The total stays under SUBSCRIBER_QUEUE_SIZE so nobody is legitimately
        evicted for being full — any subscriber lost here is a locking bug, not
        back-pressure.
        """
        subscribers = [events.subscribe() for _ in range(5)]
        threads_count, per_thread = 4, 20
        assert threads_count * per_thread < events.SUBSCRIBER_QUEUE_SIZE

        def worker():
            for _ in range(per_thread):
                events.broadcast_event("tick", {})

        threads = [threading.Thread(target=worker) for _ in range(threads_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            assert not t.is_alive()

        assert events.subscriber_count() == len(subscribers)
        for q in subscribers:
            assert q.qsize() == threads_count * per_thread, "a broadcast was lost"
