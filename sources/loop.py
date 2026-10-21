# SPDX-License-Identifier: GPL-2.0
"""One asyncio loop for every source, in a daemon thread of its own, made
the first time a source needs it. Sources whose libraries are asyncio
(Яндекс, Music Assistant) run their work on it and wait for the result
from the program's worker threads; long-lived work (a server's connection)
lives on it too.

run(coro, timeout=120)  waits for coro's result; raises what it raised,
                        or TimeoutError after timeout, coro cancelled
start(coro)             runs coro on the loop and does not wait: a
                        concurrent.futures.Future
call(func, *args)       func(*args) on the loop's thread, soon
"""
import asyncio
import concurrent.futures
import threading

_loop = None
_lock = threading.Lock()


def _get():
    global _loop
    with _lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="sources", daemon=True).start()
        return _loop


def run(coro, timeout=120):
    future = asyncio.run_coroutine_threadsafe(coro, _get())
    try:
        return future.result(timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()  # nobody waits for it now
        raise


def start(coro):
    return asyncio.run_coroutine_threadsafe(coro, _get())


def call(func, *args):
    _get().call_soon_threadsafe(func, *args)
