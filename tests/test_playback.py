# SPDX-License-Identifier: GPL-2.0
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import playback  # noqa: E402
from haltia_kit.testing import FakePlayer  # noqa: E402
from tests import fake  # noqa: E402
from tests.fake import track  # noqa: E402


class Case(unittest.TestCase):
    def setUp(self):
        self.session(fake.Source())

    def session(self, source):
        self.src, self.player = source, FakePlayer()
        self.work, self.later, self.events = fake.Work(), fake.Later(), fake.Events()
        self.s = playback.Session(fake.Sources(source), lambda: self.player, self.work,
                                  self.later, self.events)
        return self.s

    def told(self, event=None):
        return [(r, e, i) for r, e, i, _s in self.src.told if event in (None, e)]


class List(Case):
    def test_plays_the_tapped_track_then_on_to_the_end(self):
        self.s.play_list([track(1), track(2)], 1)
        self.assertEqual(self.player.what, "fake://low/2")
        self.assertTrue(self.events.on)
        self.s.ended()
        self.assertFalse(self.events.on)

    def test_goes_to_the_next_at_the_end(self):
        self.s.play_list([track(1), track(2)], 0)
        self.s.ended()
        self.assertEqual(self.s.current["id"], "2")
        self.assertEqual(self.player.what, "fake://low/2")

    def test_the_queue_is_its_own(self):
        tracks = [track(1), track(2)]
        self.s.play_list(tracks, 0)
        tracks.append(track(3))
        self.assertEqual(len(self.s.tracks), 2)

    def test_prev_starts_over_after_a_while(self):
        self.s.play_list([track(1), track(2)], 1)
        self.player.position = 30
        self.s.prev()
        self.assertEqual((self.s.current["id"], self.player.position), ("2", 0))
        self.s.prev()
        self.assertEqual(self.s.current["id"], "1")

    def test_stop_forgets_all(self):
        self.s.play_list([track(1)], 0)
        self.s.stop()
        self.assertIsNone(self.s.current)
        self.assertIsNone(self.events.tracks[-1])


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
        self.assertFalse(self.player.playing)  # so the machine may sleep

    def test_a_player_error_gives_way_too(self):
        self.s.play_list([track(1), track(2)], 0)
        self.s.ended("поток оборвался")
        self.assertFalse(self.player.playing)
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
        self.player.position = 7
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
        self.assertEqual(self.player.what, "fake://low/2")

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


class State(Case):
    def setUp(self):
        super().setUp()
        self.player.on_pause = self.s.paused

    def test_playing_paused_stopped(self):
        self.assertEqual(self.s.state, "stopped")
        self.s.play_list([track(1), track(2)], 0)
        self.assertEqual(self.s.state, "playing")
        self.s.toggle()
        self.assertEqual(self.s.state, "paused")
        self.s.toggle()
        self.s.stop()
        self.assertEqual(self.s.state, "stopped")

    def test_playing_while_the_next_is_fetched(self):
        self.s.play_list([track(1), track(2)], 0)
        self.work.held = True
        self.s.ended()
        self.assertEqual(self.s.state, "playing")
        self.work.run()
        self.s.ended()
        self.assertEqual(self.s.state, "stopped")

    def test_playing_while_a_broken_one_gives_way(self):
        self.src.broken.add("1")
        self.s.play_list([track(1)], 0)
        self.assertEqual(self.s.state, "playing")
        self.later.fire()
        self.assertEqual(self.s.state, "stopped")
        self.assertIs(self.events.on, False)

    def test_a_radio_that_runs_dry_stops(self):
        self.src.batches = [[], [], []]
        self.s.play_radio("r", [track(1)], 0)
        self.s.ended()
        self.assertEqual(self.s.state, "stopped")


class Time(Case):
    def test_position_and_time_of_the_track_playing(self):
        self.assertEqual(self.s.position, 0)
        self.s.play_list([track(1)], 0)
        self.player.position = 42
        self.assertEqual(self.s.position, 42)
        self.s.timed(43)
        self.assertEqual(self.events.times, [43])
        self.s.stop()
        self.assertEqual(self.s.position, 0)


class TwoSources(Case):
    """Every track is played by its own source."""

    def setUp(self):
        self.other = fake.Source(batches=[[dict(track(9), source="other")]])
        self.other.id = "other"
        super().setUp()
        self.sources = fake.Sources(self.src, self.other)
        self.sources.qualities["other"] = "flac"
        self.s.sources = self.sources

    def test_each_track_from_its_source_in_its_quality(self):
        self.s.play_list([track(1), dict(track(2), source="other")], 0)
        self.assertEqual(self.player.what, "fake://low/1")
        self.s.ended()
        self.assertEqual(self.player.what, "fake://flac/2")

    def test_a_radio_grows_and_learns_from_its_own_source(self):
        mine = dict(track(1), source="other")
        self.s.play_radio("r", [mine], 0)
        self.assertEqual(self.other.asked, [("r", mine)])
        self.assertEqual([t["id"] for t in self.s.tracks], ["1", "9"])
        self.assertEqual([e for _r, e, _i, _s in self.other.told], ["start"])
        self.assertEqual(self.src.asked + self.src.told, [])

    def test_same_ids_of_two_sources_are_two_tracks(self):
        self.other.batches = [[track(1)]]
        self.s.play_radio("r", [dict(track(1), source="other")], 0)
        self.assertEqual(len(self.s.tracks), 2)

    def test_a_source_gone_gives_way(self):
        self.s.play_list([dict(track(1), source="gone"), track(2)], 0)
        self.assertTrue(self.events.failures)
        self.later.fire()
        self.assertEqual(self.player.what, "fake://low/2")


class Held:
    """A session a source holds itself: it records what it is asked."""

    def __init__(self, events):
        self.events, self.asked, self.active = events, [], False
        self.current, self.index, self.tracks, self.radio, self.radio_src = None, -1, [], None, None
        self.state, self.position, self.playing = "stopped", 0, False

    def play_list(self, tracks, i):
        self.asked.append(("play_list", i))
        self.current = tracks[i]
        self.events.changed(tracks[i])

    def stop(self):
        self.asked.append(("stop",))
        self.current = None
        self.events.changed(None)

    def next(self):
        self.asked.append(("next",))


class Kinds(unittest.TestCase):
    """A source that holds its queue plays through its own session."""

    def setUp(self):
        self.mine = fake.Source()
        self.server = fake.Source()
        self.server.id = "server"
        self.made = []
        self.server.session = lambda events, work, player: (
            self.made.append(Held(events)) or self.made[-1])
        self.player, self.events = FakePlayer(), fake.Events()
        self.f = playback.Front(fake.Sources(self.mine, self.server), lambda: self.player,
                                fake.Work(), fake.Later(), self.events)

    def test_the_own_kind_by_default(self):
        self.f.play_list([track(1)], 0)
        self.assertEqual(self.player.what, "fake://low/1")
        self.assertEqual(self.made, [])

    def test_a_held_queue_plays_its_tracks_and_the_other_stops(self):
        self.f.play_list([track(1)], 0)
        theirs = dict(track(2), source="server")
        self.f.play_list([theirs], 0)
        held = self.made[0]
        self.assertEqual(held.asked, [("play_list", 0)])
        self.assertTrue(held.active)
        self.assertFalse(self.player.playing)  # the own one stopped
        self.assertIs(self.f.current, theirs)
        self.f.next()
        self.assertEqual(held.asked[-1], ("next",))
        self.assertEqual(self.events.tracks[-1], theirs)

    def test_only_the_one_playing_is_heard(self):
        self.f.play_list([dict(track(2), source="server")], 0)
        held = self.made[0]
        self.f.play_list([track(1)], 0)
        self.assertEqual(held.asked[-1], ("stop",))
        told = len(self.events.tracks)
        held.events.changed(dict(track(3), source="server"))  # it says something late
        self.assertEqual(len(self.events.tracks), told)
        self.assertEqual(self.f.current["id"], "1")

    def test_one_player_for_all(self):
        self.f.play_list([dict(track(2), source="server")], 0)
        self.assertIs(self.f._player(), self.player)
        self.f.play_list([track(1)], 0)
        self.assertIs(self.f.own.player, self.player)


if __name__ == "__main__":
    unittest.main()
