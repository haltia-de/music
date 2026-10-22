# SPDX-License-Identifier: GPL-2.0
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from yandex_music.exceptions import UnauthorizedError
    from sources import yandex  # noqa: E402
except ImportError:
    yandex = None


@unittest.skipUnless(yandex, "no yandex_music")
class Renewal(unittest.TestCase):
    """A token the service stops taking while the program runs."""

    def setUp(self):
        self.y = yandex.Yandex()
        self.renewed = []
        clients = iter(["первый", "второй", "третий"])

        async def connect():
            if self.y._expired:
                self.renewed.append(1)
                self.y._expired = False
            self.y._client = next(clients)
            return self.y._client

        self.y._connect = connect

    def test_a_token_refused_is_renewed_and_asked_again(self):
        async def ask():
            api = await self.y._api()
            if api == "первый":
                raise UnauthorizedError("expired")
            return api

        self.assertEqual(self.y._call(ask), "второй")
        self.assertEqual(self.y._call(ask), "второй")
        self.assertEqual(self.renewed, [1])

    def test_renewed_once_only(self):
        async def ask():
            await self.y._api()
            raise UnauthorizedError("revoked")

        with self.assertRaises(UnauthorizedError):
            self.y._call(ask)
        self.assertEqual(self.renewed, [1])


if __name__ == "__main__":
    unittest.main()
