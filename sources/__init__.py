# SPDX-License-Identifier: GPL-2.0
"""The services music comes from. Every module of this package that defines
SOURCE is one; haltia-music lists them all and needs nothing else to know
about a new one (Звук, Apple Music, ...).

SOURCE has:
  id, label                 "yandex", "Яндекс Музыка"
  logged_in()               True when it has an account to play from; like
                            account(), it reads no network and may be called
                            from the window
  login_start()             the first step of signing in (below)
  login_next(values)        blocks until the step shown is done: values is
                            None after a code step, {field id: text} after
                            a form; gives the next step, True when signed
                            in, False when not confirmed; raises with a
                            message to show (a wrong password)
  logout()
  account()                 the account's name, or ""
  home()                    [{"id", "title"}]: the rows of the first page; a
                            row of tracks may name the "list" they come from
  home_row(row_id)          the items of a row
  browse(folder_id)         the items of a folder; "" is the top one
  tracks(list_id)           the tracks of a list
  radio_next(radio_id, last_track)
                            the next few tracks of a radio, after last_track;
                            with None it starts the radio anew
  search(query)             items of any kind, best first
  stream_url(track, quality)
                            a URL the player can open, in one of qualities
                            ("" when there are none)
Optional:
  qualities                 [(id, title, hint)], the lowest first
  feedback(radio_id, event, track, seconds)
                            "start", "finish" or "skip" of a radio track, so
                            the service learns what one likes
  liked(), like(track, on)  the ids of the tracks one likes (a set or a
                            list), and liking a track or no longer
  likes_list                the id of the list of the tracks one likes

An item is a dict with a kind: "track", or "list", "radio" or "folder"
with id, title, subtitle, cover (an image URL or "") and optionally glyph,
a sign shown when there is no cover. A list opens to its tracks, a radio
plays on and on, a folder holds more items.

A track is a dict: kind "track", source, id, title, artist, duration
(seconds or None), cover, and optionally album (its title).

A step of signing in is a dict with a kind:
  "code"    code, url, qr: the code to enter at url, and a URL to show as a
            QR code to scan; either may be "" when there is no such way in
  "form"    fields: [{"id", "label", "secret" (typed unseen), "value" (what
            the field holds at first), "choices" ([(value, label)] that
            fill it at a tap, e.g. servers found)}]; note: what to say
            above it ("" for nothing)

A source may block (network): haltia-music calls it from a worker thread.

Sources(found, settings, folder, work, later, signed, hearts, failed) holds
the sources found with what each keeps apart. No GTK; every call comes from
the window's thread.
  found         {id: SOURCE}, as load() gives
  settings      get(key, default) and set(key, value), as haltia_kit's
                Settings; keeps off (the ids switched off), source (the one
                shown) and quality.<id>
  folder        where each source's answers are kept, data-<id>.json
  work, later   as for playback.Session
  signed(id)    the sign-in of a source changed
  hearts()      hearts are to be drawn again
  failed(text)  a heart the service refused

all()               the sources, Яндекс first (ORDER), the rest by id
on()                the switched-on ones, in that order
get(id)             a source, or None
is_on(id)
switch(id, on)      True if that changed anything; signing in, answers and
                    what plays stay as they are
shown               the source the pages show: the one kept, else the first
                    switched on; None when none is
show_next()         the next switched-on one is shown
answers(id)         its answers.Answers
likes(id)           its likes.Likes
quality(id), set_quality(id, quality)
signin(id)          {"kind": "in", "name"} | {"kind": "out"} |
                    {"kind": "getting"} (asking the source) |
                    {"kind": "waiting", "code", "url", "qr"} (a code step) |
                    {"kind": "form", "fields", "note"} (a form step) |
                    {"kind": "failed", "note"}
sign_in(id)         goes through the source's steps; signed(id) at each
send(id, values)    what was typed into the form shown
sign_out(id)        the account and its answers and hearts are forgotten
"""
import importlib
import os
import pkgutil
import sys

import answers
import likes

REQUIRED = ("id", "label", "logged_in", "login_start", "login_next", "logout", "account",
            "home", "home_row", "browse", "tracks", "radio_next", "search", "stream_url")


def load():
    """{id: SOURCE} of every source that imports; a broken one is skipped."""
    found = {}
    for info in pkgutil.iter_modules(__path__):
        try:
            mod = importlib.import_module("%s.%s" % (__name__, info.name))
        except Exception as exc:  # a source must never take the program down
            sys.stderr.write("haltia-music: source %s: %s\n" % (info.name, exc))
            continue
        src = getattr(mod, "SOURCE", None)
        if src is None:
            continue
        missing = [name for name in REQUIRED if not hasattr(src, name)]
        if missing:
            sys.stderr.write("haltia-music: source %s lacks %s\n" % (info.name, ", ".join(missing)))
            continue
        found[src.id] = src
    return found


ORDER = ("yandex", "music_assistant")
START = {"kind": "start"}  # what failed was the start of signing in
WAITED = {"kind": "failed"}  # a code was not confirmed


class Sources:
    def __init__(self, found, settings, folder, work, later, signed, hearts, failed):
        self.found, self.settings, self.work = found, settings, work
        self.signed = signed
        rank = {sid: n for n, sid in enumerate(ORDER)}
        self.ids = sorted(found, key=lambda sid: (rank.get(sid, len(ORDER)), sid))
        self._move_old(folder)
        self.kept, self.hearts, self.states, self.ages = {}, {}, {}, {}
        for sid in self.ids:
            src = found[sid]
            self.kept[sid] = answers.Answers(src, work, later,
                                             os.path.join(folder, "data-%s.json" % sid))
            self.hearts[sid] = likes.Likes(src, self.kept[sid], work, hearts, failed)
            self.states[sid] = self._now(sid)
            self.ages[sid] = 0

    def _move_old(self, folder):
        """Before 2.4 there was Яндекс only: its answers and quality."""
        old, new = os.path.join(folder, "data.json"), os.path.join(folder, "data-yandex.json")
        try:
            if os.path.exists(old) and not os.path.exists(new):
                os.replace(old, new)
        except OSError:
            pass
        quality = self.settings.get("quality", None)
        if quality and self.settings.get("quality.yandex", None) is None:
            self.settings.set("quality.yandex", quality)

    # --- which ones -------------------------------------------------------------
    def all(self):
        return [self.found[sid] for sid in self.ids]

    def on(self):
        return [src for src in self.all() if self.is_on(src.id)]

    def get(self, sid):
        return self.found.get(sid)

    def _off(self):
        return [sid for sid in (self.settings.get("off", "") or "").split(",") if sid]

    def is_on(self, sid):
        return sid in self.found and sid not in self._off()

    def switch(self, sid, on):
        off = [i for i in self._off() if i != sid] + ([] if on else [sid])
        if off == self._off():
            return False
        self.settings.set("off", ",".join(off))
        return True

    @property
    def shown(self):
        on = self.on()
        kept = self.settings.get("source", None)
        return next((src for src in on if src.id == kept), on[0] if on else None)

    def show_next(self):
        on, now = self.on(), self.shown
        if len(on) > 1:
            self.settings.set("source", on[(on.index(now) + 1) % len(on)].id)

    # --- what each keeps --------------------------------------------------------
    def answers(self, sid):
        return self.kept[sid]

    def likes(self, sid):
        return self.hearts[sid]

    def quality(self, sid):
        qualities = [q[0] for q in getattr(self.found.get(sid), "qualities", None) or []]
        kept = self.settings.get("quality." + sid, None)
        return kept if kept in qualities else (qualities[0] if qualities else "")

    def set_quality(self, sid, quality):
        self.settings.set("quality." + sid, quality)

    # --- signing in -------------------------------------------------------------
    def signin(self, sid):
        return self.states[sid]

    def _now(self, sid):
        src = self.found[sid]
        return {"kind": "in", "name": src.account()} if src.logged_in() else {"kind": "out"}

    def _set(self, sid, age, state):
        if age != self.ages[sid]:
            return False  # signed out, or begun again, meanwhile
        self.states[sid] = state
        self.signed(sid)
        return True

    def sign_in(self, sid):
        if self.states[sid]["kind"] in ("getting", "waiting"):
            return
        self.ages[sid] += 1
        age, src = self.ages[sid], self.found[sid]
        self._set(sid, age, {"kind": "getting"})
        self.work(lambda _a: src.login_start(), None,
                  lambda step, err: self._step(sid, age, step, err, START))

    def send(self, sid, values):
        state = self.states[sid]
        if state["kind"] != "form":
            return
        # Shown again on a refusal with what was typed, but not the secrets.
        again = dict(state, fields=[f if f.get("secret") else dict(f, value=values.get(
            f["id"], f.get("value", ""))) for f in state["fields"]])
        age, src = self.ages[sid], self.found[sid]
        self._set(sid, age, {"kind": "getting"})
        self.work(lambda _a: src.login_next(values), None,
                  lambda step, err: self._step(sid, age, step, err, again))

    def _step(self, sid, age, step, error, before):
        """The source's answer: the next step, or the end of signing in.
        before is the form to show again with the error, or START."""
        if error:
            if before is START:
                note = "Не удалось начать вход: нет связи?"
            else:
                note = str(error) or "Не удалось войти."
            self._set(sid, age, dict(before, note=note) if before is not START
                      else {"kind": "failed", "note": note})
            return
        if step is True:
            if self._set(sid, age, self._now(sid)):
                self.hearts[sid].refresh()
            return
        kind = step.get("kind", "code") if isinstance(step, dict) else None
        if kind == "form":
            self._set(sid, age, {"kind": "form", "fields": step.get("fields", []),
                                 "note": step.get("note", "")})
            return
        if kind != "code" or not (step.get("qr") or step.get("code")):
            self._set(sid, age, {"kind": "failed", "note": "Вход не подтверждён."
                                 if before is not START else
                                 "Не удалось начать вход: нет связи?"})
            return
        if self._set(sid, age, {"kind": "waiting", "code": step.get("code", ""),
                                "url": step.get("url", ""), "qr": step.get("qr", "")}):
            src = self.found[sid]
            self.work(lambda _a: src.login_next(None), None,
                      lambda nxt, err: self._step(sid, age, nxt, err and RuntimeError(
                          "Вход не подтверждён."), WAITED))

    def sign_out(self, sid):
        self.ages[sid] += 1
        self.found[sid].logout()
        self.hearts[sid].reset()
        self.kept[sid].reset()
        self._set(sid, self.ages[sid], {"kind": "out"})
