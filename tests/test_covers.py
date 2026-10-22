# SPDX-License-Identifier: GPL-2.0
"""Covers fetched once, not for pages gone, kept within bounds; without GTK."""
import ast
import hashlib
import os
import tempfile
import threading
import unittest
import urllib.request
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

TREE = ast.parse((Path(__file__).resolve().parents[1] / "haltia-music").read_text())
COVERS = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "Covers")
URL = "https://img/1"


class Executor:
    """A pool whose work runs when the test says."""

    def __init__(self, **_kw):
        self.jobs = []

    def submit(self, func, *args):
        job = SimpleNamespace(run=lambda: func(*args), cancelled=False)
        job.cancel = lambda: setattr(job, "cancelled", True) or True
        self.jobs.append(job)
        return job


class Image:
    def __init__(self):
        self.shown, self.handlers = [], {}

    def connect(self, signal, func):
        self.handlers[signal] = func

    def set_from_pixbuf(self, pixbuf):
        self.shown.append(pixbuf)

    def destroy(self):
        self.handlers["destroy"](self)


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.fetched = []
        self.ns = {"os": os, "hashlib": hashlib, "threading": threading, "urllib": urllib,
                   "OrderedDict": OrderedDict, "ThreadPoolExecutor": Executor,
                   "CACHE": self.dir.name, "PIXBUFS": 10, "COVERS_MAX": 1000,
                   "PRUNE_EVERY": 50, "COVER_MAX": 1 << 20, "UA": "test",
                   "GLib": SimpleNamespace(idle_add=lambda func, *a: func(*a),
                                           Error=type("Error", (Exception,), {})),
                   "decode": lambda path, size: "pixbuf of %s at %d" % (
                       os.path.basename(path), size)}
        exec(compile(ast.Module(body=[COVERS], type_ignores=[]), "haltia-music", "exec"),
             self.ns)
        self.covers = self.ns["Covers"]()
        self.covers.net.jobs.clear()
        self.covers.disk.jobs.clear()  # the pruning at start
        self.covers._fetch = lambda url, path: (self.fetched.append(url),
                                                Path(path).write_bytes(b"jpeg"))

    def tearDown(self):
        self.dir.cleanup()

    def run_all(self):
        for job in self.covers.net.jobs + self.covers.disk.jobs:
            if not job.cancelled:
                job.run()


class Fetching(Case):
    def test_one_fetch_for_the_images_that_wait(self):
        a, b = Image(), Image()
        self.covers.get(URL, a, 64)
        self.covers.get(URL, b, 64)
        self.assertEqual(len(self.covers.net.jobs), 1)
        self.run_all()
        self.assertEqual(self.fetched, [URL])
        self.assertEqual(len(a.shown), 1)
        self.assertEqual(a.shown, b.shown)
        c = Image()
        self.covers.get(URL, c, 64)  # decoded already
        self.assertEqual(c.shown, a.shown)
        self.assertEqual(len(self.covers.net.jobs), 1)

    def test_a_page_gone_its_covers_are_not_fetched(self):
        a = Image()
        self.covers.get(URL, a, 64)
        a.destroy()
        self.assertTrue(self.covers.net.jobs[0].cancelled)
        self.covers.net.jobs[0].run()  # had it started already
        self.assertEqual(self.fetched, [])
        self.assertEqual(a.shown, [])

    def test_one_image_still_waiting_keeps_the_fetch(self):
        a, b = Image(), Image()
        self.covers.get(URL, a, 64)
        self.covers.get(URL, b, 64)
        a.destroy()
        self.assertFalse(self.covers.net.jobs[0].cancelled)
        self.run_all()
        self.assertEqual(len(b.shown), 1)
        self.assertEqual(a.shown, [])

    def test_the_cover_asked_last_is_shown(self):
        bar = Image()
        self.covers.get(URL, bar, 96)
        self.covers.get(URL + "2", bar, 96)
        self.run_all()
        self.assertEqual(self.fetched, [URL + "2"])
        self.assertEqual(len(bar.shown), 1)
        self.assertIn(os.path.basename(self.covers.path(URL + "2")), bar.shown[0])


class Disk(Case):
    def test_the_least_used_go_first(self):
        for n, mtime in ((1, 100), (2, 300), (3, 200)):
            path = os.path.join(self.dir.name, "%d.jpg" % n)
            Path(path).write_bytes(b"x" * 400)
            os.utime(path, (mtime, mtime))
        Path(self.dir.name, "data-yandex.json").write_bytes(b"x" * 4000)
        self.covers.prune()
        self.assertEqual(sorted(os.listdir(self.dir.name)),
                         ["2.jpg", "3.jpg", "data-yandex.json"])


class Decoding(unittest.TestCase):
    def test_an_older_kit_shows_no_cover_rather_than_use_gdkpixbuf(self):
        func = next(node for node in TREE.body
                    if isinstance(node, ast.FunctionDef) and node.name == "decode")
        loaders = SimpleNamespace()  # any use of GdkPixbuf fails
        ns = {"pixbuf_of": None, "GdkPixbuf": loaders}
        exec(compile(ast.Module(body=[func], type_ignores=[]), "haltia-music", "exec"), ns)
        self.assertIsNone(ns["decode"]("/no/such.jpg", 64))


if __name__ == "__main__":
    unittest.main()
