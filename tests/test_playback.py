# SPDX-License-Identifier: GPL-2.0
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import playback  # noqa: E402
from tests import fake  # noqa: E402
from tests.fake import track  # noqa: E402


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.awake = os.path.join(self.dir.name, "1.suspend")
        self.session(fake.Source())

    def tearDown(self):
        self.dir.cleanup()

    def session(self, source):
        self.src, self.player = source, fake.Player()
        self.work, self.later, self.events = fake.Work(), fake.Later(), fake.Events()
        self.s = playback.Session(source, lambda: self.player, self.work, self.later,
                                  self.events, self.awake)
        self.s.quality = "low"
        return self.s

    def told(self, event=None):
        return [(r, e, i) for r, e, i, _s in self.src.told if event in (None, e)]


class List(Case):
    def test_plays_the_tapped_track_then_on_to_the_end(self):
        self.s.play_list([track(1), track(2)], 1)
        self.assertEqual(self.player.url, "fake://low/2")
        self.assertTrue(self.events.on)
        self.assertTrue(os.path.exists(self.awake))
        self.s.ended()
        self.assertFalse(self.events.on)
        self.assertFalse(os.path.exists(self.awake))

    def test_goes_to_the_next_at_the_end(self):
        self.s.play_list([track(1), track(2)], 0)
        self.s.ended()
        self.assertEqual(self.s.current["id"], "2")
        self.assertEqual(self.player.url, "fake://low/2")

    def test_the_queue_is_its_own(self):
        tracks = [track(1), track(2)]
        self.s.play_list(tracks, 0)
        tracks.append(track(3))
        self.assertEqual(len(self.s.tracks), 2)

    def test_prev_starts_over_after_a_while(self):
        self.s.play_list([track(1), track(2)], 1)
        self.player.at = 30
        self.s.prev()
        self.assertEqual((self.s.current["id"], self.player.at), ("2", 0))
        self.s.prev()
        self.assertEqual(self.s.current["id"], "1")

    def test_stop_forgets_all(self):
        self.s.play_list([track(1)], 0)
        self.s.stop()
        self.assertIsNone(self.s.current)
        self.assertIsNone(self.events.tracks[-1])
        self.assertFalse(os.path.exists(self.awake))


class NotPlaying(Case):
    def test_a_track_without_a_stream_gives_way(self):
        self.src.broken.add("1")
        self.s.play_list([track(1), track(2)], 0)
        self.assertTrue(self.events.failures)
        self.assertFalse(self.events.on)
        self.later.fire()
        self.assertEqual(self.s.current["id"], "2")

    def test_a_track_chosen_meanwhile_stays(self):
        self.src.broken.add("1")
        self.s.play_list([track(1), track(2), track(3)], 0)
        self.s.jump(2)
        self.later.fire()
        self.assertEqual(self.s.current["id"], "3")

    def test_the_last_one_ends_in_quiet(self):
        self.src.broken.add("1")
        self.s.play_list([track(1)], 0)
        self.later.fire()
        self.assertFalse(self.events.on)
        self.assertFalse(os.path.exists(self.awake))

    def test_a_player_error_gives_way_too(self):
        self.s.play_list([track(1), track(2)], 0)
        self.s.ended("поток оборвался")
        self.assertFalse(os.path.exists(self.awake))
        self.later.fire()
        self.assertEqual(self.s.current["id"], "2")

    def test_the_end_of_a_track_left_is_ignored(self):
        self.s.play_list([track(1), track(2), track(3)], 0)
        self.work.held = True
        self.s.jump(2)  # its stream is not there yet
        self.s.ended()  # the end of track 1, late
        self.assertEqual(self.s.current["id"], "3")


class Radio(Case):
    def test_tells_start_finish_and_skip(self):
        self.s.play_radio("r", [track(1), track(2), track(3), track(4)], 0)
        self.s.ended()
        self.player.at = 7
        self.s.next()
        self.assertEqual(self.told(), [("r", "start", "1"), ("r", "finish", "1"),
                                       ("r", "start", "2"), ("r", "skip", "2"),
                                       ("r", "start", "3")])

    def test_a_skip_while_paused_is_a_skip(self):
        self.s.play_radio("r", [track(1), track(2), track(3), track(4)], 0)
        self.s.toggle()
        self.s.paused(True)
        self.s.next()
        self.assertEqual(self.told("skip"), [("r", "skip", "1")])

    def test_leaving_for_a_list_skips_on_the_radio(self):
        self.s.play_radio("r", [track(1), track(2), track(3), track(4)], 0)
        self.s.play_list([track(9)], 0)
        self.assertEqual(self.told("skip"), [("r", "skip", "1")])
        self.assertIsNone(self.s.radio)

    def test_a_track_that_never_played_is_no_skip(self):
        self.src.broken.add("1")
        self.s.play_radio("r", [track(1), track(2), track(3), track(4)], 0)
        self.s.next()
        self.assertEqual(self.told("skip"), [])

    def test_grows_near_the_end_from_the_last_track(self):
        self.src.batches = [[track(3), track(4), track(5)]]
        self.s.play_radio("r", [track(1), track(2), track(3)], 1)
        self.assertEqual(self.src.asked, [("r", track(3))])
        self.assertEqual([t["id"] for t in self.s.tracks], ["1", "2", "3", "4", "5"])
        self.assertEqual(self.events.grown, [[track(4), track(5)]])

    def test_asks_once_at_a_time(self):
        self.work.held = True
        self.s.play_radio("r", [track(1), track(2)], 0)
        self.s.next()
        self.work.run()
        self.assertEqual(len(self.src.asked), 1)

    def test_asks_again_after_a_failure(self):
        self.src.batches = [OSError("нет связи"), [track(9)]]
        self.s.play_radio("r", [track(1), track(2)], 0)
        self.s.next()
        self.assertEqual(len(self.src.asked), 2)
        self.assertEqual(self.s.tracks[-1]["id"], "9")

    def test_waits_at_the_end_for_more(self):
        self.work.held = True
        self.s.play_radio("r", [track(1)], 0)
        self.work.run()  # nothing came
        self.src.batches = [[track(2)]]
        self.s.ended()
        self.work.run()
        self.assertEqual(self.s.current["id"], "2")
        self.assertEqual(self.player.url, "fake://low/2")

    def test_tries_twice_at_the_end_then_is_quiet(self):
        self.src.batches = [[], OSError("нет связи"), OSError("нет связи"), [track(2)]]
        self.s.play_radio("r", [track(1)], 0)
        self.s.ended()
        self.assertEqual(len(self.src.asked), 3)
        self.assertEqual(self.s.current["id"], "1")
        self.assertFalse(self.events.on)

    def test_more_for_a_radio_left_is_dropped(self):
        self.work.held = True
        self.src.batches = [[track(5)]]
        self.s.play_radio("r", [track(1)], 0)
        self.s.play_radio("q", [track(7), track(8), track(9), track(10)], 0)
        self.work.run()
        self.assertEqual([t["id"] for t in self.s.tracks], ["7", "8", "9", "10"])

    def test_a_service_without_feedback(self):
        self.session(fake.Source(batches=[[track(2)]], feedback=False))
        self.s.play_radio("r", [track(1)], 0)
        self.s.next()
        self.assertEqual(self.s.current["id"], "2")


if __name__ == "__main__":
    unittest.main()
