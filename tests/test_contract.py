# SPDX-License-Identifier: GPL-2.0
"""Every source keeps to the contract in sources/__init__.py."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sources  # noqa: E402
from tests import fake  # noqa: E402

KINDS = {"track", "list", "radio", "folder"}


class Contract(unittest.TestCase):
    def keeps(self, src):
        for name in sources.REQUIRED:
            self.assertTrue(hasattr(src, name), "%s lacks %s" % (src.id, name))
        for qid, title, hint in getattr(src, "qualities", None) or []:
            self.assertTrue(qid and title)

    def items(self, items):
        for item in items:
            self.assertIn(item["kind"], KINDS)
            for key in ("id", "title"):
                self.assertIn(key, item)
            if item["kind"] == "track":
                for key in ("source", "artist", "duration", "cover"):
                    self.assertIn(key, item)
            else:
                for key in ("subtitle", "cover"):
                    self.assertIn(key, item)

    def test_the_stand_in(self):
        src = fake.Source()
        self.keeps(src)
        for row in src.home():
            self.assertIn("title", row)
            self.items(src.home_row(row["id"]))
        self.items(src.browse(""))
        self.items(src.search("x"))
        self.items(src.tracks(src.likes_list))

    def test_every_source_that_loads(self):
        found = sources.load()
        if not found:
            self.skipTest("no source imports here (yandex_music missing)")
        for src in found.values():
            self.keeps(src)


if __name__ == "__main__":
    unittest.main()
