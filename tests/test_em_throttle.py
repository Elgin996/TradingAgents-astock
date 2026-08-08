"""F2.2 — Eastmoney throttle serializes concurrent callers."""

from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from tradingagents.dataflows import a_stock


class _RecordingSession:
    def __init__(self, stamps):
        self._stamps = stamps

    def get(self, url, params=None, headers=None, timeout=15, **kwargs):
        self._stamps.append(time.time())

        class _Resp:
            status_code = 200
            text = "{}"

            def json(self):
                return {}

        return _Resp()


@pytest.mark.unit
def test_concurrent_calls_are_serialized(monkeypatch):
    monkeypatch.setattr(a_stock, "_EM_MIN_INTERVAL", 0.2)
    # Reset the schedule so prior tests do not push start_at into the future.
    monkeypatch.setattr(a_stock, "_em_next_free", 0.0)
    stamps = []
    monkeypatch.setattr(a_stock, "_em_session", lambda: _RecordingSession(stamps))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: a_stock._em_get("https://push2.eastmoney.com/x"), range(8)))
    gaps = [b - a for a, b in zip(sorted(stamps), sorted(stamps)[1:])]
    assert all(g >= 0.2 for g in gaps), gaps


@pytest.mark.unit
def test_em_session_is_thread_local():
    """Each thread must get its own Session object."""
    # Hold strong refs so object ids are not recycled after a thread exits.
    sessions: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def capture():
        sess = a_stock._em_session()
        barrier.wait()  # keep all threads (and their locals) alive together
        with lock:
            sessions.append(sess)

    threads = [threading.Thread(target=capture) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sessions) == 4
    assert len({id(s) for s in sessions}) == 4
    # Same thread reuses the same session.
    assert a_stock._em_session() is a_stock._em_session()
