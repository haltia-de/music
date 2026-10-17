# SPDX-License-Identifier: GPL-2.0
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import answers  # noqa: E402
from tests import fake  # noqa: E402


class Source:
    def __init__(self):
        self.asked = []
        self.reply = ["a"]

    def tracks(self, list_id):
        self.asked.append(list_id)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def liked(self):
        return {"2", "1"}

    def logout(self):
        raise AssertionError("never asked")


class Shows:
    def __init__(self):
        self.seen = []

    def __call__(self, answer, error):
        self.seen.append((answer, error))


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "cache", "data.json")
        self.now = 1000.0
        self.src = Source()
        self.a = self.make()

    def tearDown(self):
        self.dir.cleanup()

    def make(self):
        self.work, self.later = fake.Work(), fake.Later()
        return answers.Answers(self.src, self.work, self.later, self.path, lambda: self.now)

    def test_asks_then_keeps(self):
        show = Shows()
        self.a.get("tracks", "x", show)
        self.a.get("tracks", "x", show)
        self.assertEqual(self.src.asked, ["x"])
        self.assertEqual(show.seen, [(["a"], None), (["a"], None)])

    def test_asks_again_when_old_and_shows_only_a_change(self):
        self.a.get("tracks", "x", Shows())
        self.now += answers.FRESH + 1
        show = Shows()
        self.a.get("tracks", "x", show)
        self.assertEqual(len(self.src.asked), 2)
        self.assertEqual(show.seen, [(["a"], None)])
        self.now += answers.FRESH + 1
        self.src.reply = ["b"]
        show = Shows()
        self.a.get("tracks", "x", show)
        self.assertEqual(show.seen, [(["a"], None), (["b"], None)])

    def test_an_error_shows_only_with_nothing_kept(self):
        self.src.reply = OSError("нет связи")
        show = Shows()
        self.a.get("tracks", "x", show)
        self.assertIs(show.seen[0][1], self.src.reply)
        self.src.reply = ["a"]
        self.a.get("tracks", "x", Shows())
        self.src.reply = OSError("нет связи")
        show = Shows()
        self.a.get("tracks", "x", show, force=True)
        self.assertEqual(show.seen, [(["a"], None)])

    def test_one_request_for_two_askers(self):
        self.work.held = True
        one, two = Shows(), Shows()
        self.a.get("tracks", "x", one)
        self.a.get("tracks", "x", two)
        self.work.run()
        self.assertEqual(self.src.asked, ["x"])
        self.assertEqual((one.seen, two.seen), ([(["a"], None)], [(["a"], None)]))

    def test_forget_asks_again(self):
        self.a.get("tracks", "x", Shows())
        self.a.forget("tracks", "x")
        self.a.get("tracks", "x", Shows())
        self.assertEqual(len(self.src.asked), 2)

    def test_only_reads(self):
        with self.assertRaises(ValueError):
            self.a.get("logout", None, Shows())

    def test_a_set_is_kept_as_a_list(self):
        show = Shows()
        self.a.get("liked", None, show)
        self.assertEqual(show.seen, [(["1", "2"], None)])

    def test_kept_between_runs(self):
        self.a.get("tracks", "x", Shows())
        self.later.fire()
        again = self.make()
        show = Shows()
        again.get("tracks", "x", show)
        self.assertEqual(show.seen, [(["a"], None)])
        self.assertEqual(self.src.asked, ["x"])

    def test_keeps_the_latest(self):
        for i in range(answers.KEEP + 5):
            self.now += 1
            self.a.get("tracks", str(i), Shows())
        self.a.flush()
        self.assertEqual(len(self.a.kept), answers.KEEP)
        self.assertNotIn(("tracks", "0"), self.a.kept)
        self.assertIn(("tracks", str(answers.KEEP + 4)), self.make().kept)

    def test_reset_drops_what_is_on_its_way(self):
        self.a.get("tracks", "x", Shows())
        self.a.flush()
        self.work.held = True
        show = Shows()
        self.a.get("tracks", "y", show)
        self.a.reset()
        self.work.run()
        self.assertEqual(show.seen, [])
        self.assertEqual(self.a.kept, {})
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
