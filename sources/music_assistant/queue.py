# SPDX-License-Identifier: GPL-2.0
"""What plays from Music Assistant: the server's queue of this device,
mirrored. A session of the kind playback.Session's docstring describes, for
the window and MPRIS: its commands go to the server (player_queues/*), and
what plays, pauses or grows is what the server's events say (queue_updated,
queue_items_updated, queue_time_updated), so a change made from elsewhere
(the server's own page) shows here too. The server holds the radio, what
follows a list, and what the services are told.

Queue(source, events, work, player)
  source        the Music Assistant source (__init__.py): its connection,
                listen(), the account (url, token, key) and its id
  events        as for playback.Session
  work          as for playback.Session (the loop's events reach the
                window's side through GLib.idle_add)
  player()      the program's player, which plays the sound (sound.py)

active          set by the session that holds this one (playback.Front):
                while off, no sound is played and no events are told
"""
import asyncio
import logging
import time

from gi.repository import GLib

from .. import loop
from . import items
from .sound import Sound

LOG = logging.getLogger("haltia-music.queue")
STATES = {"playing": "playing", "paused": "paused"}
SETTLE = 6  # seconds the server may still tell the old state after a command
# Commands after which what is heard starts anew, not after the old buffer.
FRESH = {"player_queues/play_media", "player_queues/play_index", "player_queues/next",
         "player_queues/previous", "player_queues/seek", "player_queues/play",
         "player_queues/pause"}
TICK = 1  # seconds between the times told while it plays
KNOWN = 15  # seconds a new player may take to appear on the server


class Queue:
    def __init__(self, source, events, work, player):
        self.src, self.events, self.work, self.make_player = source, events, work, player
        self.sound = None
        self._sounding = None  # the Sendspin player being started
        self.tracks = []
        self.index = -1
        self.radio = None
        self.radio_src = None
        self.state = "stopped"
        self.playing = False
        self.active = False
        self._elapsed = (0.0, time.monotonic())  # (seconds into the track, when so)
        self._item = None  # the server's id of the queue item playing
        self._listening = False
        self._ticking = None  # the GLib source that tells the time
        self._is_known = False  # the server has the player
        # What was asked last ("playing", "paused", "stopped") and when: the
        # server's events say the old state for a moment after a command,
        # and a pause of this player it tells as idle.
        self._want, self._asked = None, 0.0

    @property
    def current(self):
        return self.tracks[self.index] if 0 <= self.index < len(self.tracks) else None

    @property
    def position(self):
        if self.current is None:
            return 0
        seconds, when = self._elapsed
        if self.state == "playing":
            seconds += time.monotonic() - when
        return max(0, seconds)

    @property
    def queue_id(self):
        return self.sound.player_id if self.sound else None

    # --- what the window asks ---------------------------------------------------
    def play_list(self, tracks, i):
        if 0 <= i < len(tracks):
            self._begin(None, tracks, i, [t["id"] for t in tracks], tracks[i]["id"])

    def play_radio(self, radio, tracks, i):
        if 0 <= i < len(tracks):
            start = tracks[i]["id"] if i else None
            self._begin(radio, tracks, i, radio, start)

    def _begin(self, radio, tracks, i, media, start):
        self.radio, self.radio_src = radio, (self.src if radio else None)
        self.tracks, self.index = list(tracks), i
        self._elapsed = (0.0, time.monotonic())
        self._ask("playing")
        self._set_state("playing")
        self.events.changed(self.current)
        args = {"media": media, "option": "replace"}
        if start:
            args["start_item"] = start
        self._command("player_queues/play_media", **args)

    def jump(self, i):
        if 0 <= i < len(self.tracks):
            self._ask("playing")
            self._command("player_queues/play_index", index=i)

    def next(self):
        self._ask("playing")
        self._command("player_queues/next")

    def prev(self):
        self._ask("playing")
        self._command("player_queues/previous")

    def toggle(self):
        if self.current is None:
            return
        if self.state == "playing":
            self._ask("paused")
            self._set_state("paused")
            self._command("player_queues/pause")
        else:
            self._ask("playing")
            self._set_state("playing")
            self._command("player_queues/play")

    def _ask(self, state):
        self._want, self._asked = state, time.monotonic()

    def seek(self, sec):
        if self.current is not None:
            self._elapsed = (sec, time.monotonic())
            self._command("player_queues/seek", position=int(sec))

    def stop(self):
        if self.sound is not None:
            self._command("player_queues/stop")
        self.tracks, self.index, self.radio, self.radio_src = [], -1, None, None
        self._item = None
        self._ask("stopped")
        self._set_state("stopped")
        self.events.changed(None)

    # --- the player's own reports: the server's events say it all --------------
    def ended(self, error=None):
        pass

    def paused(self, on):
        pass

    def timed(self, seconds):
        pass

    # --- the server ---------------------------------------------------------------
    def _command(self, command, **args):
        LOG.debug("%s %s", command, args)

        def send(_a):
            loop.run(self._ready())
            if command in FRESH:
                self.sound.flush()
            return self.src.call(command, queue_id=self.queue_id, **args)

        self.work(send, None, self._done)

    def _done(self, _result, error):
        if error:
            self.events.failed("Music Assistant: %s" % error)

    async def _ready(self):
        """This device is the server's player: signed in, and Sendspin up."""
        await self.src.api()
        if not self._listening:
            self._listening = True
            self.src.listen(self._event)
        if self.sound is None:
            if self._sounding is None:
                self._sounding = asyncio.ensure_future(self._start_sound())
            # One command giving up does not give up for the others.
            await asyncio.shield(self._sounding)
        await self._known()

    async def _start_sound(self):
        """The Sendspin player, kept only once it is up: one that failed is
        closed, and the next command tries anew."""
        try:
            saved = self.src._saved() or {}
            sound = Sound(saved["url"], saved["token"], self.src.key(),
                          self.src.device_name(), self._player,
                          state=self._sound_state, allowed=lambda: self.active)
            try:
                await sound.start()
            except BaseException:
                await sound.close()
                raise
        finally:
            self._sounding = None
        self.sound = sound

    async def _known(self):
        """The server takes commands for the player only once it has made it
        (a new device takes seconds): waits for it, up to KNOWN seconds."""
        if self._is_known:
            return
        api = await self.src.api()
        for _ in range(int(KNOWN / 0.25)):
            try:
                found = await api.call("players/get", player_id=self.queue_id)
            except Exception:
                found = None
            if found and found.get("available"):
                self._is_known = True
                return
            await asyncio.sleep(0.25)
        raise RuntimeError("the server has not taken this device as a player")

    def _sound_state(self, on):
        if not on:
            self._is_known = False  # back as a player only when the server says so

    def _player(self):
        return self.make_player()

    def _event(self, name, object_id, data):
        """From the loop's thread; handled on the window's."""
        if name == "connection" or object_id == self.queue_id:
            GLib.idle_add(lambda: (self._got(name, data), False)[1])

    def _got(self, name, data):
        if not self.active:
            return
        if name == "connection":
            if not data:
                self.events.failed("Нет связи с Music Assistant")
            return
        if name == "queue_time_updated":
            self._elapsed = (float(data or 0), time.monotonic())
            self.events.time(self.position)
        elif name == "queue_updated":
            self._queue(data or {})
        elif name == "queue_items_updated":
            self.work(lambda _a: self.src.call("player_queues/items", queue_id=self.queue_id,
                                               limit=500), None, self._items)

    def _queue(self, q):
        told = q.get("state")
        state = STATES.get(told, "stopped")
        item = q.get("current_item") or {}
        index = q.get("current_index")
        LOG.debug("queue %s index %s item %s (asked %s)", told, index, item.get("name"),
                  self._want)
        settling = time.monotonic() - self._asked < SETTLE
        if self._want == "stopped":
            if told == "playing" and not settling:
                self._want = None  # played from elsewhere since: it is news again
            else:
                return  # stopped here: what the server says about it is not news
        if self._want == "paused":
            if told == "playing" and settling:
                return  # the old state, before the command took
            if told in ("idle", "paused"):
                state = "paused"  # a Sendspin player's pause is told as idle
        elif self._want == "playing" and told != "playing" and settling:
            return  # the old state, before the command took
        moved = item.get("queue_item_id") != self._item and index is not None
        if moved:
            self._item = item.get("queue_item_id")
            media = item.get("media_item")
            if media:
                self._now(index, media)
        # With a new track the server still tells the old one's time.
        if q.get("elapsed_time") is not None and not moved:
            self._elapsed = (float(q["elapsed_time"]), time.monotonic())
        if state != self.state:
            self._set_state(state)

    def _now(self, index, media):
        """The server plays the index-th item, media: which of ours it is
        (the server may name it by its library's URI, the list by the
        service's), else the queue was changed elsewhere and is read again."""
        names = items.uris(media)
        if 0 <= index < len(self.tracks) and self.tracks[index]["id"] in names:
            found = index
        else:
            found = next((i for i, t in enumerate(self.tracks) if t["id"] in names), None)
        if found is None:
            track = items.track(media, self.src.url)
            if index == len(self.tracks) and self.radio:
                self.tracks.append(track)
                self.events.grew([track])
                found = index
            else:
                self.tracks, self.index = [track], 0
                self.events.changed(track)
                self.work(lambda _a: self.src.call("player_queues/items",
                                                   queue_id=self.queue_id, limit=500),
                          None, self._items)
                return
        # A list made of the server's short mentions (recently played) lacks
        # the length, the artist, the cover: the queue's item has them.
        mine, full = self.tracks[found], items.track(media, self.src.url)
        filled = {k: v for k, v in full.items() if v and not mine.get(k)}
        mine.update(filled)
        if found != self.index:
            self._elapsed = (0.0, time.monotonic())  # until the server tells the time
        if found != self.index or filled:
            self.index = found
            self.events.changed(self.current)

    def _items(self, found, error):
        if error or not found or not self.active:
            return
        tracks = [i["media_item"] for i in found
                  if (i.get("media_item") or {}).get("media_type") == "track"]
        ours = [t["id"] for t in self.tracks]
        same = len(tracks) >= len(ours) and all(
            ours[i] in items.uris(m) for i, m in enumerate(tracks[:len(ours)]))
        if same:
            new = [items.track(m, self.src.url) for m in tracks[len(ours):]]
            if new:
                self.tracks.extend(new)
                self.events.grew(new)
            return
        current = self.current
        self.tracks = [items.track(m, self.src.url) for m in tracks]
        names = [items.uris(m) for m in tracks]
        self.index = next((i for i, n in enumerate(names) if current and current["id"] in n),
                          self.index if self.index < len(self.tracks) else -1)

    def _set_state(self, state):
        self.state = state
        on = state == "playing"
        if on != self.playing or state == "stopped":
            self.playing = on
            self.events.playing(on)
        if on and self._ticking is None:
            self._ticking = GLib.timeout_add_seconds(TICK, self._tick)
        elif not on and self._ticking is not None:
            GLib.source_remove(self._ticking)
            self._ticking = None
        if not on:
            self.events.time(self.position)

    def _tick(self):
        """The time bar moves while it plays; the server tells it seldom."""
        if self.state != "playing":
            self._ticking = None
            return False
        if self.active and self.current is not None:
            self.events.time(self.position)
        return True
