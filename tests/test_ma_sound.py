# SPDX-License-Identifier: GPL-2.0
import asyncio
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import aiohttp  # noqa: F401
    import aiosendspin  # noqa: F401
    from sources.music_assistant import sound  # noqa: E402
    from tests import fake_ma  # noqa: E402
except ImportError:
    sound = None


@unittest.skipUnless(sound, "no aiohttp or aiosendspin")
class Handshake(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old = sound.RETRY, sound.RETRY_MAX, sound.START
        sound.RETRY, sound.RETRY_MAX, sound.START = 0.05, 0.1, 2
        self.server = fake_ma.Server()
        await self.server.start()
        self.s = sound.Sound(self.server.url, fake_ma.TOKEN, bytes(range(32)), "Музыка (тест)",
                             lambda: None)

    async def asyncTearDown(self):
        await self.s.close()
        await self.server.stop()
        sound.RETRY, sound.RETRY_MAX, sound.START = self.old

    async def test_a_handshake_broken_off_is_tried_again(self):
        try:
            await self.s.start()  # over by START at most, whatever the library makes of it
        except ConnectionError:
            pass
        for _ in range(1000):
            if self.server.sendspin >= 3:
                break
            await asyncio.sleep(0.01)
        self.assertGreaterEqual(self.server.sendspin, 3)
        self.assertFalse(self.s._task.done())


@unittest.skipUnless(sound, "no aiohttp or aiosendspin")
class Pipe(unittest.TestCase):
    def setUp(self):
        self.old = sound.GLib, sound.QUEUED
        sound.GLib = SimpleNamespace(idle_add=lambda func: func())
        sound.QUEUED = 100_000

    def tearDown(self):
        sound.GLib, sound.QUEUED = self.old

    def test_a_player_that_does_not_read(self):
        played = []
        player = SimpleNamespace(play=lambda what, **_o: played.append(what))
        pipe = sound.Pipe(lambda: player, {})
        read = int(played[0].split("://")[1])
        try:
            taken = 0
            while pipe.write(b"x" * 1000):
                taken += 1000
                self.assertLess(taken, 1_000_000)
            self.assertLessEqual(pipe.queued, sound.QUEUED)
        finally:
            os.close(read)
            pipe.drop()


if __name__ == "__main__":
    unittest.main()
