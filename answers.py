# SPDX-License-Identifier: GPL-2.0
"""The service's answers, kept: shown at once, asked for again when old.
Pages open from what is kept, even with no network.

Answers(source, work, later, path, clock=time.time):
  work, later   as for playback.Session
  path          the file the answers are kept in between runs

get(what, arg, show, force=False)
    show(answer, error) at once with the answer kept, if any. The source's
    what(arg) (what() when arg is None) is asked when that answer is older
    than FRESH, or on force, and show is called again only when the new one
    differs: show may run twice. what is one of READS. Asking for one that is
    already on its way waits for it. An answer is shared: read it, never
    change it. An error is shown only when nothing was kept.
forget(what, arg)   the next get asks the source
reset()             all forgotten, on disk too, and answers still on their
                    way are dropped (another account)
flush()             writes to disk now what waits to be written
"""
import json
import os
import time

FRESH = 15 * 60  # seconds an answer of the service is taken as it is
KEEP = 300  # answers kept, the latest
SAVE_AFTER = 3  # seconds; answers coming together are written once
READS = {"home", "home_row", "browse", "tracks", "search", "liked"}


class Answers:
    def __init__(self, source, work, later, path, clock=time.time):
        self.src, self.work, self.later, self.path, self.clock = source, work, later, path, clock
        self.kept = {}  # (what, arg) -> [time, answer]
        self.asking = {}  # (what, arg) -> [(show, shown)] waiting for the source
        self.age = 0  # grows on reset: what was asked before is dropped
        self.saving = False
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                for what, arg, stamp, answer in json.load(fh):
                    self.kept[(what, arg)] = [stamp, answer]
        except (OSError, ValueError, TypeError):
            self.kept = {}

    def get(self, what, arg, show, force=False):
        if what not in READS:
            raise ValueError("not an answer: %s" % what)
        key = (what, arg)
        entry = self.kept.get(key)
        if entry:
            show(entry[1], None)
            if not force and self.clock() - entry[0] < FRESH:
                return
        if key in self.asking:
            self.asking[key].append((show, bool(entry)))
            return
        self.asking[key] = [(show, bool(entry))]
        func, age = getattr(self.src, what), self.age
        self.work(lambda a: func(a) if a is not None else func(), arg,
                  lambda answer, error: self._got(age, key, answer, error))

    def forget(self, what, arg):
        self.kept.pop((what, arg), None)

    def reset(self):
        self.age += 1
        self.kept, self.asking = {}, {}
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def flush(self):
        if self.saving:
            self._save()

    def _got(self, age, key, answer, error):
        if age != self.age:
            return
        waiting = self.asking.pop(key, [])
        if error:
            for show, shown in waiting:
                if not shown:
                    show(None, error)
            return
        if isinstance(answer, set):
            answer = sorted(answer)
        old = self.kept.get(key)
        self.kept[key] = [self.clock(), answer]
        if not self.saving:
            self.saving = True
            self.later(SAVE_AFTER, self._save)
        changed = not old or old[1] != answer
        for show, shown in waiting:
            if changed or not shown:
                show(answer, None)

    def _save(self):
        self.saving = False
        self.kept = dict(sorted(self.kept.items(), key=lambda kv: kv[1][0])[-KEEP:])
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path + ".new", "w", encoding="utf-8") as fh:
                json.dump([[w, a, s, ans] for (w, a), (s, ans) in self.kept.items()], fh,
                          ensure_ascii=False)
            os.replace(self.path + ".new", self.path)
        except OSError:
            pass
