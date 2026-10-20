# SPDX-License-Identifier: GPL-2.0
"""What plays: a list from one of its tracks on, or a radio that goes on and
on. Session is all of it, the window only shows what it says.

Session(sources, player, work, later, events):
  sources       get(id), the source of a track by its "source", and
                quality(id), what it plays in (sources.Sources)
  player()      gives the player, made the first time it is needed:
                haltia_kit.sound.Player (play(url), toggle(), seek(seconds),
                position, stop()), which keeps the machine awake while it
                plays
  work(func, arg, done)
                func(arg) in a thread, done(result, error) back on this side;
                done may be None
  later(seconds, func)
                func() once, after a while
  events        changed(track or None), grew(new tracks), playing(on),
                time(seconds), failed(text)

The player tells it ended(error) at the end of a track, paused(on) and
timed(seconds) as it plays.

What the window and MPRIS use, and all a session of another kind (one whose
queue a server holds) has to offer: play_list, play_radio, jump, next, prev,
toggle, seek, stop; current, index, tracks, radio, radio_src, state,
position; and the events.

state is "playing" from the tap on a track until the queue runs out (also
while the next track is being fetched or a broken one gives way), "paused"
when one paused it, and "stopped" when nothing goes on; changed and playing
events come with every change of it.

A track one leaves before its end is a skip, paused or not; one that plays
to its end is finished. A radio says so to its service, which learns from it.
Every track is played by its own source; a radio grows from the source of
the track it began with.
"""
RADIO_AHEAD = 2  # ask the radio for more when this few tracks are left
GIVE_WAY = 2  # seconds a track that does not play stays before the next


class Session:
    def __init__(self, sources, player, work, later, events):
        self.sources = sources
        self.make_player = player
        self.player = None
        self.work, self.later, self.events = work, later, events
        self.tracks = []  # the queue
        self.index = -1
        self.radio = None  # the radio playing, or None
        self.radio_src = None  # the source it comes from
        self.playing = False
        self.going = False  # it plays on, unless paused, till the queue runs out
        self.under_way = False  # the current track plays (or played) its sound
        self.asking = None  # a token while the radio is asked for more
        self.stalled = 0  # tries left when the radio's queue ran out

    @property
    def current(self):
        return self.tracks[self.index] if 0 <= self.index < len(self.tracks) else None

    @property
    def position(self):
        """Seconds into the current track."""
        if self.current is None or self.player is None:
            return 0
        return self.player.position or 0

    @property
    def state(self):
        if self.current is None or not self.going:
            return "stopped"
        return "paused" if self.under_way and not self.playing else "playing"

    # --- what the window asks ---------------------------------------------------
    def play_list(self, tracks, i):
        self._begin(None, tracks, i)

    def play_radio(self, radio, tracks, i):
        """The radio from the i-th of tracks, its first ones; it then grows."""
        self._begin(radio, tracks, i)

    def jump(self, i):
        if 0 <= i < len(self.tracks):
            self._start(i)

    def next(self):
        self.jump(self.index + 1)

    def prev(self):
        if self.under_way and self.player and (self.player.position or 0) > 5:
            self.player.seek(0)
        else:
            self.jump(self.index - 1)

    def toggle(self):
        if self.player and self.under_way:
            self.player.toggle()

    def seek(self, sec):
        if self.player and self.under_way:
            self.player.seek(sec)

    def stop(self):
        self._leave()
        if self.player:
            self.player.stop()
        self.tracks, self.index, self.radio, self.radio_src = [], -1, None, None
        self.asking, self.stalled = None, 0
        self._halt()
        self.events.changed(None)

    # --- what the player says ---------------------------------------------------
    def ended(self, error=None):
        track = self.current
        if track is None or not self.under_way:
            return  # the end of a track already left
        if error:
            self.events.failed("Трек не играет: %s" % error)
            self._give_way(track)
            return
        if self.radio and self.under_way:
            self._feedback("finish", track, track.get("duration") or 0)
        self.under_way = False
        if self.index + 1 < len(self.tracks):
            self._start(self.index + 1)
            return
        if not self.radio:
            self._halt()
            return
        self._set_playing(False)
        self.stalled = 2  # one more try after a failed one, then quiet
        self._more()

    def paused(self, on):
        self._set_playing(on is False)

    def timed(self, seconds):
        self.events.time(seconds)

    # --- inside -------------------------------------------------------------------
    def _begin(self, radio, tracks, i):
        if not 0 <= i < len(tracks):
            return
        self._leave()
        self.radio, self.tracks, self.index = radio, list(tracks), -1
        self.radio_src = self.sources.get(tracks[i]["source"]) if radio else None
        self.asking, self.stalled = None, 0
        self._start(i)

    def _leave(self):
        """The current track is left: a skip if it was playing."""
        track = self.current
        if track and self.radio and self.under_way:
            self._feedback("skip", track, self.player.position or 0)
        self.under_way = False

    def _start(self, i):
        self._leave()
        self.index, self.going = i, True
        track = self.tracks[i]
        self.events.changed(track)
        src, sid = self.sources.get(track["source"]), track["source"]
        self.work(lambda t: src.stream_url(t, self.sources.quality(sid)) if src else "", track,
                  lambda url, err: self._play(track, url, err))
        if self.radio:
            self._feedback("start", track, 0)
            if len(self.tracks) - i <= RADIO_AHEAD:
                self._more()

    def _play(self, track, url, error):
        if self.current is not track:
            return  # another track was chosen meanwhile
        if error or not url:
            self.events.failed("Трек не играет: %s" % (error or "нет ссылки"))
            self._give_way(track)
            return
        try:
            if self.player is None:
                self.player = self.make_player()
            self.player.play(url)
        except Exception as exc:
            self.events.failed("Нет проигрывателя (libmpv): %s" % exc)
            self._halt()
            return
        self.under_way = True
        self._set_playing(True)

    def _give_way(self, track):
        """A track that does not play: silence, then the next, unless one
        chose another meanwhile."""
        self.under_way = False
        if self.player:
            self.player.stop()
        self._set_playing(False)

        def go():
            if self.current is not track:
                return
            if self.index + 1 < len(self.tracks):
                self.next()
            else:
                self._halt()

        self.later(GIVE_WAY, go)

    def _more(self):
        if self.asking or not self.radio:
            return
        token = self.asking = object()
        src, radio, last = self.radio_src, self.radio, self.tracks[-1] if self.tracks else None
        self.work(lambda _a: src.radio_next(radio, last), None,
                  lambda tracks, err: self._grew(token, tracks, err))

    def _grew(self, token, tracks, error):
        if token is not self.asking:
            return  # another radio, or none, plays now
        self.asking = None
        known = {(t["source"], t["id"]) for t in self.tracks}
        new = []
        for t in [] if error else tracks or []:
            if (t["source"], t["id"]) not in known:
                known.add((t["source"], t["id"]))
                new.append(t)
        if new:
            self.tracks.extend(new)
            self.events.grew(new)
        if not self.stalled:
            return
        if new:
            self.stalled = 0
            self._start(self.index + 1)
        else:
            self.stalled -= 1
            if self.stalled:
                self._more()
            else:
                self._halt()

    def _feedback(self, event, track, seconds):
        send = getattr(self.radio_src, "feedback", None)
        if send:
            radio = self.radio
            self.work(lambda _a: send(radio, event, track, seconds), None, None)

    def _halt(self):
        """Nothing goes on any more."""
        self.going = False
        self._set_playing(False)

    def _set_playing(self, on):
        self.playing = on
        self.events.playing(on)


class Front:
    """What plays, of either kind: the program's own Session, or a session a
    source holds itself (Music Assistant's queue). The window and MPRIS talk
    to it as to a Session. A list or a radio goes to the kind of its source;
    the one that played before stops, and only the one playing is heard
    from.

    Front(sources, player, work, later, events): as for Session; a source
    with session(events, work, player) holds what plays itself, and gets the
    same player (one libmpv for all).
    """

    def __init__(self, sources, player, work, later, events):
        self.sources, self.work, self.events = sources, work, events
        self.own = Session(sources, player, work, later, self._told(lambda: self.own))
        self.kinds = {}  # source id -> its session
        self.active = self.own

    def _told(self, kind):
        front = self

        class Told:
            def __getattr__(self, name):
                def tell(*args):
                    if front.active is kind():
                        getattr(front.events, name)(*args)
                return tell

        return Told()

    def _player(self):
        if self.own.player is None:
            self.own.player = self.own.make_player()
        return self.own.player

    def _kind(self, track):
        src = self.sources.get(track["source"])
        if src is None or not hasattr(src, "session"):
            return self.own
        if src.id not in self.kinds:
            made = []
            self.kinds[src.id] = src.session(self._told(lambda: made[0]), self.work,
                                             self._player)
            made.append(self.kinds[src.id])
        return self.kinds[src.id]

    def _switch(self, kind):
        if kind is self.active:
            return
        old, self.active = self.active, kind
        for k in self.kinds.values():
            k.active = k is kind
        old.stop()

    # --- what the window asks ---------------------------------------------------
    def play_list(self, tracks, i):
        if 0 <= i < len(tracks):
            self._switch(self._kind(tracks[i]))
            self.active.play_list(tracks, i)

    def play_radio(self, radio, tracks, i):
        if 0 <= i < len(tracks):
            self._switch(self._kind(tracks[i]))
            self.active.play_radio(radio, tracks, i)

    def jump(self, i):
        self.active.jump(i)

    def next(self):
        self.active.next()

    def prev(self):
        self.active.prev()

    def toggle(self):
        self.active.toggle()

    def seek(self, sec):
        self.active.seek(sec)

    def stop(self):
        self.active.stop()

    # --- what the player says: it is the program's own session's ------------------
    def ended(self, error=None):
        self.own.ended(error)

    def paused(self, on):
        self.own.paused(on)

    def timed(self, seconds):
        self.own.timed(seconds)

    # --- what plays -----------------------------------------------------------------
    current = property(lambda self: self.active.current)
    index = property(lambda self: self.active.index)
    tracks = property(lambda self: self.active.tracks)
    radio = property(lambda self: self.active.radio)
    radio_src = property(lambda self: self.active.radio_src)
    state = property(lambda self: self.active.state)
    position = property(lambda self: self.active.position)
    playing = property(lambda self: self.active.playing)
