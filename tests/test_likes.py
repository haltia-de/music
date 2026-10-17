# SPDX-License-Identifier: GPL-2.0
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import answers  # noqa: E402
import likes  # noqa: E402
from tests import fake  # noqa: E402
from tests.fake import track  # noqa: E402


class Source:
    def __init__(self):
        self.server = set()
        self.told = []  # (id, on)
        self.down = False

    def liked(self):
        return set(self.server)

    def like(self, track, on):
        if self.down:
            raise OSError("нет связи")
        self.told.append((track["id"], on))
        (self.server.add if on else self.server.discard)(track["id"])


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.src, self.work = Source(), fake.Work()
        self.answers = answers.Answers(self.src, self.work, fake.Later(),
                                       os.path.join(self.dir.name, "data.json"))
        self.drawn, self.failures = 0, []
        self.l = likes.Likes(self.src, self.answers, self.work, self.draw,
                             self.failures.append)

    def tearDown(self):
        self.dir.cleanup()

    def draw(self):
        self.drawn += 1

    def test_a_tap_shows_at_once_and_reaches_the_service(self):
        self.work.held = True
        self.l.toggle(track(1))
        self.assertTrue(self.l.liked(track(1)))
        self.assertEqual(self.drawn, 1)
        self.work.run()
        self.assertEqual(self.src.server, {"1"})
        self.assertTrue(self.l.liked(track(1)))

    def test_quick_taps_end_with_the_last(self):
        self.work.held = True
        for _ in range(3):
            self.l.toggle(track(1))
        self.work.run()
        self.assertEqual(self.src.told, [("1", True)])
        self.l.toggle(track(1))
        self.l.toggle(track(1))
        self.l.toggle(track(1))
        self.l.toggle(track(1))
        self.work.run()
        self.assertEqual(self.src.told, [("1", True), ("1", False), ("1", True)])
        self.assertEqual(self.src.server, {"1"})
        self.assertTrue(self.l.liked(track(1)))

    def test_an_old_answer_does_not_put_out_a_heart(self):
        self.work.held = True
        self.l.refresh()  # asks the service: nothing liked yet
        self.l.toggle(track(1))
        self.work.waiting.reverse()  # the like is confirmed first, then the old answer comes
        old = self.work.waiting[1]
        self.work.waiting[1] = (lambda _a: set(), old[1], old[2])
        self.work.run()
        self.assertTrue(self.l.liked(track(1)))

    def test_a_pending_tap_wins_over_the_service(self):
        self.src.server = {"1"}
        self.work.held = True
        self.l.toggle(track(2))
        self.l.refresh()
        self.work.waiting.reverse()
        self.work.run()
        self.assertTrue(self.l.liked(track(1)))
        self.assertTrue(self.l.liked(track(2)))

    def test_a_failure_goes_back(self):
        self.src.down = True
        self.l.toggle(track(1))
        self.assertFalse(self.l.liked(track(1)))
        self.assertEqual(self.failures, [likes.FAILED])

    def test_a_confirmed_like_asks_the_lists_again(self):
        self.l.refresh()
        self.l.toggle(track(1))
        self.assertNotIn(("liked", None), self.answers.kept)

    def test_reset_drops_what_is_on_its_way(self):
        self.work.held = True
        self.l.toggle(track(1))
        self.l.reset()
        self.work.run()
        self.assertFalse(self.l.liked(track(1)))

    def test_a_source_without_likes(self):
        l = likes.Likes(object(), self.answers, self.work, self.draw, self.failures.append)
        self.assertFalse(l.able)
        l.toggle(track(1))
        l.refresh()
        self.assertFalse(l.liked(track(1)))


if __name__ == "__main__":
    unittest.main()
