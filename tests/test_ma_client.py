# SPDX-License-Identifier: GPL-2.0
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import aiohttp  # noqa: F401
except ImportError:
    aiohttp = None

if aiohttp:
    from sources.music_assistant import client  # noqa: E402
    from tests import fake_ma  # noqa: E402


@unittest.skipUnless(aiohttp, "no aiohttp")
class Case(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        client.RETRY, client.RETRY_MAX = 0.05, 0.1
        self.server = fake_ma.Server()
        await self.server.start()
        self.events, self.states = [], []

    async def asyncTearDown(self):
        if getattr(self, "c", None):
            await self.c.close()
        await self.server.stop()

    async def connect(self, token=None):
        self.c = client.Client(self.server.url, token or fake_ma.TOKEN,
                               lambda *e: self.events.append(e), self.states.append)
        await self.c.start()
        return self.c

    async def until(self, done):
        for _ in range(200):
            if done():
                return
            await asyncio.sleep(0.01)
        self.fail("it never came")


class Connection(Case):
    async def test_signs_in_with_the_token_and_the_locale(self):
        c = await self.connect()
        self.assertTrue(c.connected)
        self.assertEqual(c.user, "Кот")
        self.assertEqual(self.server.asked[0], ("auth", {"token": fake_ma.TOKEN, "locale": "ru"}))
        self.assertEqual(self.states, [True])

    async def test_a_token_refused(self):
        with self.assertRaises(client.Refused):
            await self.connect("чужой")

    async def test_commands_and_their_parts(self):
        self.server.answers["music/search"] = lambda a: [a["search_query"]] * 5
        c = await self.connect()
        self.assertEqual(await c.call("music/search", search_query="x"), ["x"] * 5)

    async def test_an_error_of_the_server(self):
        def fail(_args):
            raise fake_ma.Fail(10, "The player is not available.")
        self.server.answers["player_queues/play"] = fail
        c = await self.connect()
        with self.assertRaises(client.Error) as err:
            await c.call("player_queues/play", queue_id="q")
        self.assertEqual(err.exception.code, 10)
        self.assertEqual(str(err.exception), "The player is not available.")

    async def test_events_come(self):
        await self.connect()
        await self.server.send("queue_updated", "q", {"state": "playing"})
        await self.until(lambda: self.events)
        self.assertEqual(self.events, [("queue_updated", "q", {"state": "playing"})])

    async def test_comes_back_after_a_drop(self):
        self.server.answers["info"] = {"ok": 1}
        c = await self.connect()
        await self.server.drop()
        await self.until(lambda: self.states == [True, False, True])
        self.assertEqual(await c.call("info"), {"ok": 1})

    async def test_no_connection_no_command(self):
        c = await self.connect()
        await c.close()
        with self.assertRaises(ConnectionError):
            await c.call("info")


class SignIn(Case):
    async def test_a_token_that_lasts(self):
        token = await client.sign_in(self.server.url, "кот", "верный", "Музыка (тест)")
        self.assertEqual(token, fake_ma.TOKEN)
        self.assertIn(("auth/token/create", {"name": "Музыка (тест)"}), self.server.asked)

    async def test_a_wrong_password(self):
        with self.assertRaises(client.Refused):
            await client.sign_in(self.server.url, "кот", "нет", "Музыка")

    async def test_no_server(self):
        with self.assertRaises(ConnectionError):
            await client.sign_in("http://127.0.0.1:9", "кот", "верный", "Музыка")


@unittest.skipUnless(aiohttp, "no aiohttp")
class Address(unittest.TestCase):
    def test_ws_url(self):
        self.assertEqual(client.ws_url("https://ma.example.org/"), "wss://ma.example.org/ws")
        self.assertEqual(client.ws_url("http://10.0.0.2:8095"), "ws://10.0.0.2:8095/ws")
        self.assertEqual(client.ws_url("10.0.0.2:8095"), "ws://10.0.0.2:8095/ws")


if __name__ == "__main__":
    unittest.main()
