# SPDX-License-Identifier: GPL-2.0
"""What one likes. A heart changes at the tap; the service is told after,
one request per track at a time, and ends up with the last tap.

Likes(source, answers, work, changed, failed):
  source        has liked() and like(track, on), or likes stay off (able)
  answers       answers.Answers, through which the liked ids are asked
  work          as for playback.Session
  changed()     hearts are to be drawn again
  failed(text)  the service refused or could not be reached

able                whether the source knows likes at all
liked(track)        what its heart shows
toggle(track)
refresh(force=False)
                    the liked ids from the service; taps not yet confirmed,
                    and confirmed ones its answer does not show yet, stay
reset()             forgets all (another account)
"""

FAILED = "Не удалось отметить трек: нет связи?"


class Likes:
    def __init__(self, source, answers, work, changed, failed):
        self.src, self.answers, self.work = source, answers, work
        self.changed, self.failed = changed, failed
        self.able = bool(source and hasattr(source, "like") and hasattr(source, "liked"))
        self.reset()

    def reset(self):
        self.ids = set()  # liked as far as the service said
        self.wanted = {}  # track id -> on, while a tap is not confirmed
        self.sending = {}  # track id -> on, the request on its way
        self.recent = {}  # track id -> on, confirmed but not yet in an answer
        self.age = getattr(self, "age", 0) + 1

    def liked(self, track):
        if not track:
            return False
        if track["id"] in self.wanted:
            return self.wanted[track["id"]]
        return track["id"] in self.ids

    def toggle(self, track):
        if not (track and self.able):
            return
        self.wanted[track["id"]] = not self.liked(track)
        self.changed()
        if track["id"] not in self.sending:
            self._send(track)

    def refresh(self, force=False):
        if self.able:
            self.answers.get("liked", None, self._got, force)

    def _got(self, ids, error):
        if error or ids is None:
            return
        ids = set(ids)
        for tid, on in list(self.recent.items()):
            if (tid in ids) == on:
                del self.recent[tid]  # the service's answer has it now
            else:
                (ids.add if on else ids.discard)(tid)
        self.ids = ids
        self.changed()

    def _send(self, track):
        tid, on, age = track["id"], self.wanted[track["id"]], self.age
        self.sending[tid] = on
        self.work(lambda _a: self.src.like(track, on), None,
                  lambda _r, err: self._sent(age, track, on, err))

    def _sent(self, age, track, on, error):
        if age != self.age:
            return
        tid = track["id"]
        del self.sending[tid]
        if error:
            self.wanted.pop(tid, None)
            self.changed()
            self.failed(FAILED)
            return
        (self.ids.add if on else self.ids.discard)(tid)
        self.recent[tid] = on
        self.answers.forget("liked", None)
        self.answers.forget("tracks", "likes")
        if self.wanted.get(tid, on) != on:
            self._send(track)  # tapped again meanwhile
        else:
            self.wanted.pop(tid, None)
