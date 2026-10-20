# SPDX-License-Identifier: GPL-2.0
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import fake  # noqa: E402

try:
    import aiohttp  # noqa: F401
    from sources.music_assistant import queue  # noqa: E402
except ImportError:
    queue = None

YM = "yandex_music--x"


def media(n):
    return {"uri": "%s://track/%d" % (YM, n), "name": "Трек %d" % n, "media_type": "track",
            "duration": 100, "artists": [{"name": "Кто-то"}]}


def mine(n):
    return {"kind": "track", "source": "music_assistant", "id": "%s://track/%d" % (YM, n),
            "title": "Трек %d" % n, "artist": "Кто-то", "album": "", "duration": 100,
            "cover": ""}


class Server:
    """The source as the queue sees it: commands are recorded."""

    id, url = "music_assistant", "http://ma"

    def __init__(self):
        self.asked = []
        self.items = []

    def call(self, command, **args):
        self.asked.append((command, args))
        if command == "player_queues/items":
            return [{"media_item": m} for m in self.items]
        return None


@unittest.skipUnless(queue, "no aiohttp")
class Case(unittest.TestCase):
    def setUp(self):
        self.src, self.events = Server(), fake.Events()
        self.q = queue.Queue(self.src, self.events, fake.Work(), lambda: None)
        self.q.active = True

        async def ready():
            pass

        self.q._ready = ready
        self.flushed = []
        self.q.sound = type("Sound", (), {"player_id": "me",
                                          "flush": lambda _s: self.flushed.append(1)})()

    def asked(self):
        return [(c, a) for c, a in self.src.asked if c != "player_queues/items"]

    def test_a_list_from_a_track(self):
        tracks = [mine(1), mine(2), mine(3)]
        self.q.play_list(tracks, 1)
        self.assertEqual(self.asked(), [("player_queues/play_media", {
            "queue_id": "me", "media": [t["id"] for t in tracks], "option": "replace",
            "start_item": tracks[1]["id"]})])
        self.assertEqual(self.q.current, tracks[1])
        self.assertEqual(self.q.state, "playing")
        self.assertEqual(self.events.tracks, [tracks[1]])

    def test_a_radio(self):
        self.q.play_radio(YM + "://playlist/wave", [mine(1)], 0)
        self.assertEqual(self.asked()[0][1]["media"], YM + "://playlist/wave")
        self.assertNotIn("start_item", self.asked()[0][1])
        self.assertEqual(self.q.radio, YM + "://playlist/wave")
        self.assertIs(self.q.radio_src, self.src)

    def test_buttons_are_the_servers(self):
        self.q.play_list([mine(1), mine(2)], 0)
        self.q.next()
        self.q.toggle()
        self.q.seek(42.7)
        self.q.jump(1)
        self.assertEqual([c for c, _a in self.asked()[1:]],
                         ["player_queues/next", "player_queues/pause",
                          "player_queues/seek", "player_queues/play_index"])
        self.assertEqual(self.asked()[3][1]["position"], 42)
        self.assertEqual(len(self.flushed), 5)  # play, next, toggle, seek, jump

    def test_what_the_server_says_plays(self):
        tracks = [mine(1), mine(2)]
        self.q.play_list(tracks, 0)
        self.q._got("queue_updated", {"state": "playing", "current_index": 1,
                                      "elapsed_time": 3,
                                      "current_item": {"queue_item_id": "b",
                                                       "media_item": media(2)}})
        self.assertIs(self.q.current, tracks[1])
        self.assertEqual(self.events.tracks[-1], tracks[1])
        self.q._asked = 0  # long after the command: what the server says goes
        self.q._got("queue_updated", {"state": "paused", "current_index": 1,
                                      "elapsed_time": 50,
                                      "current_item": {"queue_item_id": "b",
                                                       "media_item": media(2)}})
        self.assertEqual(self.q.state, "paused")
        self.assertFalse(self.events.on)
        self.assertEqual(self.q.position, 50)

    def test_the_server_names_a_track_by_its_library(self):
        tracks = [mine(1), mine(2)]
        self.q.play_list(tracks, 0)
        library = {"uri": "library://track/77", "name": "Трек 2", "media_type": "track",
                   "provider_mappings": [{"provider_instance": YM, "item_id": "2"}]}
        self.q._got("queue_updated", {"state": "playing", "current_index": 1,
                                      "current_item": {"queue_item_id": "b",
                                                       "media_item": library}})
        self.assertIs(self.q.current, tracks[1])
        self.assertEqual(self.q.tracks, tracks)

    def test_what_a_short_mention_lacks_comes_from_the_queue(self):
        bare = dict(mine(1), artist="", duration=None)
        self.q.play_list([bare], 0)
        self.q._got("queue_updated", {"state": "playing", "current_index": 0,
                                      "current_item": {"queue_item_id": "a",
                                                       "media_item": media(1)}})
        self.assertEqual((self.q.current["duration"], self.q.current["artist"]), (100, "Кто-то"))
        self.assertEqual(self.events.tracks[-1]["duration"], 100)

    def test_a_queue_changed_elsewhere_is_read_again(self):
        self.q.play_list([mine(1)], 0)
        self.src.items = [media(5), media(6)]
        self.q._got("queue_updated", {"state": "playing", "current_index": 1,
                                      "current_item": {"queue_item_id": "z",
                                                       "media_item": media(6)}})
        self.assertEqual([t["id"] for t in self.q.tracks], [mine(5)["id"], mine(6)["id"]])
        self.assertEqual(self.q.current["id"], mine(6)["id"])

    def test_a_radio_grows_as_the_server_adds(self):
        self.q.play_radio("r", [mine(1)], 0)
        self.src.items = [media(1), media(2), media(3)]
        self.q._got("queue_items_updated", None)
        self.assertEqual([t["id"] for t in self.q.tracks], [mine(n)["id"] for n in (1, 2, 3)])
        self.assertEqual([[t["id"] for t in g] for g in self.events.grown],
                         [[mine(2)["id"], mine(3)["id"]]])

    def test_the_old_state_after_a_command_is_not_news(self):
        self.q.play_list([mine(1)], 0)
        self.q._got("queue_updated", {"state": "idle", "current_index": None})
        self.assertEqual(self.q.state, "playing")
        self.assertTrue(self.events.on)

    def test_a_pause_told_as_idle_is_a_pause_and_play_goes_on(self):
        self.q.play_list([mine(1)], 0)
        self.q.toggle()
        self.assertEqual(self.q.state, "paused")
        self.q._got("queue_updated", {"state": "idle", "current_index": 0,
                                      "current_item": {"queue_item_id": "a",
                                                       "media_item": media(1)}})
        self.assertEqual(self.q.state, "paused")
        self.q.toggle()
        self.assertEqual(self.asked()[-1][0], "player_queues/play")
        self.assertEqual(self.q.state, "playing")

    def test_nothing_comes_back_after_a_stop(self):
        self.q.play_list([mine(1)], 0)
        self.q.stop()
        self.q._got("queue_updated", {"state": "playing", "current_index": 0,
                                      "current_item": {"queue_item_id": "a",
                                                       "media_item": media(1)}})
        self.assertIsNone(self.q.current)
        self.assertEqual(self.q.state, "stopped")
        self.q._got("queue_updated", {"state": "idle", "current_index": 0,
                                      "current_item": {"queue_item_id": "a",
                                                       "media_item": media(1)}})
        self.assertIsNone(self.q.current)
        self.q._asked = 0  # later, it is played from the server's own page
        self.q._got("queue_updated", {"state": "playing", "current_index": 0,
                                      "current_item": {"queue_item_id": "b",
                                                       "media_item": media(1)}})
        self.assertEqual(self.q.state, "playing")

    def test_a_new_track_starts_at_nought(self):
        self.q.play_list([mine(1), mine(2)], 0)
        self.assertLess(self.q.position, 1)
        self.q._elapsed = (200.0, self.q._elapsed[1])
        self.q._got("queue_updated", {"state": "playing", "current_index": 1,
                                      "current_item": {"queue_item_id": "b",
                                                       "media_item": media(2)}})
        self.assertLess(self.q.position, 1)

    def test_time_comes_from_the_server(self):
        self.q.play_list([mine(1)], 0)
        self.q._got("queue_time_updated", 12)
        self.assertAlmostEqual(self.events.times[-1], 12, places=1)

    def test_quiet_while_another_plays(self):
        self.q.active = False
        self.q._got("queue_time_updated", 12)
        self.assertEqual(self.events.times, [])

    def test_stop(self):
        self.q.play_list([mine(1)], 0)
        self.q.stop()
        self.assertEqual(self.asked()[-1][0], "player_queues/stop")
        self.assertIsNone(self.q.current)
        self.assertEqual(self.q.state, "stopped")
        self.assertIsNone(self.events.tracks[-1])

    def test_a_lost_connection_is_said(self):
        self.q._got("connection", False)
        self.assertEqual(self.events.failures, ["Нет связи с Music Assistant"])


if __name__ == "__main__":
    unittest.main()
