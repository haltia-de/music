# SPDX-License-Identifier: GPL-2.0
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vault  # noqa: E402
from sources.music_assistant import items  # noqa: E402

try:
    import aiohttp  # noqa: F401
except ImportError:
    aiohttp = None

import sources.music_assistant as ma  # noqa: E402

if aiohttp:
    from sources import loop  # noqa: E402
    from sources.music_assistant import client  # noqa: E402
    from tests import fake_ma  # noqa: E402

BASE = "https://ma.example.org"
YM = "yandex_music--x"
TRACK = {
    "item_id": "134", "provider": "library", "name": "Auberge", "uri": "library://track/134",
    "media_type": "track", "duration": 283,
    "provider_mappings": [{"item_id": "59022114", "provider_instance": YM}],
    "metadata": {"images": [{"type": "thumb", "path": "https://img/1000x1000",
                             "remotely_accessible": True, "proxy_id": None}]},
    "artists": [{"name": "Chris Rea"}],
    "album": {"name": "Auberge", "image": None}}
PLAYLIST = {"item_id": "1:2", "provider": YM, "name": "Премьера", "media_type": "playlist",
            "uri": YM + "://playlist/1:2", "is_dynamic": True, "owner": "yamusic",
            "metadata": {"description": "Только новинки", "images": []}}
FOLDER = {"item_id": "root", "provider": YM, "name": "Yandex Music", "media_type": "folder",
          "uri": YM + "://", "path": YM + "://", "image": None}


class Items(unittest.TestCase):
    def test_a_track(self):
        self.assertEqual(items.track(TRACK, BASE), {
            "kind": "track", "source": "music_assistant", "id": "library://track/134",
            "title": "Auberge", "artist": "Chris Rea", "album": "Auberge", "duration": 283,
            "cover": "https://img/1000x1000"})

    def test_a_station_is_a_radio(self):
        got = items.item(PLAYLIST, BASE)
        self.assertEqual((got["kind"], got["id"], got["subtitle"], got["glyph"]),
                         ("radio", YM + "://playlist/1:2", "Только новинки", "∞"))

    def test_a_playlist_is_a_list(self):
        got = items.item(dict(PLAYLIST, is_dynamic=False), BASE)
        self.assertEqual((got["kind"], got["subtitle"]), ("list", "yamusic"))

    def test_a_folder_opens_by_its_path(self):
        self.assertEqual(items.item(FOLDER, BASE)["id"], YM + "://")

    def test_what_cannot_play_is_left_out(self):
        self.assertEqual(items.items([dict(FOLDER, media_type="podcast"), TRACK], BASE),
                         [items.track(TRACK, BASE)])

    def test_a_cover_through_the_server(self):
        found = {"image": {"path": "/local/x.jpg", "remotely_accessible": False,
                           "proxy_id": "ab12"}}
        self.assertEqual(items.image(found, BASE + "/"),
                         BASE + "/imageproxy/ab12?size=256")
        self.assertEqual(items.image({}, BASE), "")

    def test_a_yandex_cover_is_asked_smaller(self):
        found = {"image": {"path": "https://avatars.yandex.net/get-music-content/1/a/1000x1000",
                           "remotely_accessible": True}}
        self.assertEqual(items.image(found, BASE),
                         "https://avatars.yandex.net/get-music-content/1/a/400x400")

    def test_the_way_up_is_left_out(self):
        self.assertIsNone(items.item(dict(FOLDER, name=".."), BASE))

    def test_uri(self):
        self.assertEqual(items.uri(YM + "://playlist/1:2"), (YM, "playlist", "1:2"))


@unittest.skipUnless(ma.SOURCE, "no aiohttp or no aiosendspin")
class Source(unittest.TestCase):
    """The source against a fake server on the sources' own loop."""

    def setUp(self):
        client.RETRY, client.RETRY_MAX = 0.05, 0.1
        self.dir = tempfile.TemporaryDirectory()
        self.old_vault = ma.VAULT
        ma.VAULT = vault.Vault("music_assistant", os.path.join(self.dir.name, "ma.json"), None)
        self.server = fake_ma.Server()
        loop.run(self.server.start())
        self.src = ma.MusicAssistant()
        self.found = []
        self.old_found, ma.found_servers = ma.found_servers, lambda: self.found

    def tearDown(self):
        loop.run(self.src._drop())
        loop.run(self.server.stop())
        ma.VAULT, ma.found_servers = self.old_vault, self.old_found
        self.dir.cleanup()

    def sign_in(self, **values):
        step = self.src.login_start()
        self.assertEqual(step["kind"], "form")
        return self.src.login_next(dict({"url": self.server.url}, **values))

    def test_signs_in_by_name_and_password_and_keeps_the_token_only(self):
        self.assertFalse(self.src.logged_in())
        self.assertTrue(self.sign_in(login="кот", password="верный"))
        self.assertTrue(self.src.logged_in())
        saved = ma.VAULT.load()
        self.assertEqual(saved["token"], fake_ma.TOKEN)
        self.assertNotIn("верный", str(saved))
        self.assertEqual(self.src.account(), "Кот — " + self.server.url.split("://")[1])

    def test_a_wrong_password(self):
        with self.assertRaises(PermissionError):
            self.sign_in(login="кот", password="нет")
        self.assertFalse(self.src.logged_in())

    def test_signs_in_by_a_token(self):
        self.assertTrue(self.sign_in(token=fake_ma.TOKEN))
        with self.assertRaises(PermissionError):
            self.sign_in(token="чужой")

    def test_no_server(self):
        with self.assertRaises(ConnectionError):
            self.src.login_next({"url": "127.0.0.1:9", "token": "x"})

    def test_offers_the_servers_found(self):
        self.found = [("http://10.0.0.2:8095", "Дома")]
        field = self.src.login_start()["fields"][0]
        self.assertEqual(field["choices"], [("http://10.0.0.2:8095", "Дома")])

    def test_the_device_key_stays(self):
        self.sign_in(token=fake_ma.TOKEN)
        key = self.src.key()
        self.assertEqual(len(key), 32)
        self.assertEqual(self.src.key(), key)

    def test_home_rows_the_server_shows(self):
        self.server.answers["music/recommendations"] = [
            {"provider": YM, "item_id": "feed", "name": "Для вас", "enabled_by_default": True},
            {"provider": "x", "item_id": "y", "name": "Скрытое", "enabled_by_default": False}]
        self.server.answers["music/recommendations/items"] = lambda a: (
            [PLAYLIST] if a == {"provider": YM, "item_id": "feed"} else [])
        self.sign_in(token=fake_ma.TOKEN)
        rows = self.src.home()
        self.assertEqual(rows, [{"id": YM + "|feed", "title": "Для вас"}])
        self.assertEqual(self.src.home_row(rows[0]["id"])[0]["title"], "Премьера")

    def test_lists_and_favourites(self):
        self.server.answers["music/playlists/playlist_tracks"] = lambda a: (
            [TRACK] if a["item_id"] == "1:2" and a["provider_instance_id_or_domain"] == YM
            else [])
        self.server.answers["music/tracks/library_items"] = [TRACK]
        self.sign_in(token=fake_ma.TOKEN)
        self.assertEqual(self.src.tracks(YM + "://playlist/1:2")[0]["title"], "Auberge")
        liked = self.src.liked()
        self.assertEqual(liked, {"library://track/134", YM + "://track/59022114"})
        self.server.answers["music/favorites/remove_item"] = lambda a: a
        self.src.like({"id": YM + "://track/59022114"}, False)
        self.assertIn(("music/favorites/remove_item",
                       {"media_type": "track", "library_item_id": "134"}), self.server.asked)

    def test_browse_begins_with_the_favourites(self):
        self.server.answers["music/browse"] = [FOLDER]
        self.sign_in(token=fake_ma.TOKEN)
        found = self.src.browse("")
        self.assertEqual([(i["kind"], i["id"]) for i in found],
                         [("list", ma.LIKES), ("folder", YM + "://")])

    def test_signing_out_forgets(self):
        self.sign_in(token=fake_ma.TOKEN)
        self.src.logout()
        self.assertFalse(self.src.logged_in())
        self.assertIsNone(ma.VAULT.load())


if __name__ == "__main__":
    unittest.main()
