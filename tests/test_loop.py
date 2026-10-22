# SPDX-License-Identifier: GPL-2.0
import asyncio
import concurrent.futures
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sources import loop  # noqa: E402


class Run(unittest.TestCase):
    def test_the_result(self):
        async def quick():
            return 7
        self.assertEqual(loop.run(quick()), 7)

    def test_a_timeout_cancels_the_work(self):
        cancelled = threading.Event()

        async def slow():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with self.assertRaises(concurrent.futures.TimeoutError):
            loop.run(slow(), 0.1)
        self.assertTrue(cancelled.wait(2))


if __name__ == "__main__":
    unittest.main()
