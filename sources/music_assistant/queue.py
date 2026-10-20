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
import time

from gi.repository import GLib

from .. import loop
from . import items
from .sound import Sound

STATES = {"playing": "playing", "paused": "paused"}


class Queue:
    def __init__(self, source, events, work, player):
        self.src, self.events, self.work, self.make_player = source, events, work, player
        self.sound = None
        self.tracks = []
        self.index = -1
        self.radio = None
        self.radio_src = None
        self.state = "stopped"
        self.playing = False
        self.active = False
        self._elapsed = (0.0, 0.0)  # (seconds into the track, when that was so)
        self._item = None  # the server's id of the queue item playing
        self._listening = False

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
        self._set_state("playing")
        self.events.changed(self.current)
        args = {"media": media, "option": "replace"}
        if start:
            args["start_item"] = start
        self._command("player_queues/play_media", **args)

    def jump(self, i):
        if 0 <= i < len(self.tracks):
            self._command("player_queues/play_index", index=i)

    def next(self):
        self._command("player_queues/next")

    def prev(self):
        self._command("player_queues/previous")

    def toggle(self):
        if self.state != "stopped":
            self._command("player_queues/play_pause")

    def seek(self, sec):
        if self.current is not None:
            self._elapsed = (sec, time.monotonic())
            self._command("player_queues/seek", position=int(sec))

    def stop(self):
        if self.sound is not None:
            self._command("player_queues/stop")
        self.tracks, self.index, self.radio, self.radio_src = [], -1, None, None
        self._item = None
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
        def send(_a):
            loop.run(self._ready())
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
            saved = self.src._saved() or {}
            self.sound = Sound(saved["url"], saved["token"], self.src.key(),
                               self.src.device_name(), self._player,
                               allowed=lambda: self.active)
            await self.sound.start()

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
            self.events.time(self._elapsed[0])
        elif name == "queue_updated":
            self._queue(data or {})
        elif name == "queue_items_updated":
            self.work(lambda _a: self.src.call("player_queues/items", queue_id=self.queue_id,
                                               limit=500), None, self._items)

    def _queue(self, q):
        state = STATES.get(q.get("state"), "stopped")
        if q.get("elapsed_time") is not None:
            self._elapsed = (float(q["elapsed_time"]), time.monotonic())
        item = q.get("current_item") or {}
        index = q.get("current_index")
        if item.get("queue_item_id") != self._item and index is not None:
            self._item = item.get("queue_item_id")
            media = item.get("media_item")
            track = items.track(media, self.src.url) if media else None
            if track is not None:
                if 0 <= index < len(self.tracks) and self.tracks[index]["id"] == track["id"]:
                    track = self.tracks[index]
                elif index == len(self.tracks):
                    self.tracks.append(track)
                    self.events.grew([track])
                else:
                    self.tracks = [track] if index == 0 else self.tracks
                    index = self.tracks.index(track) if track in self.tracks else 0
                self.index = index
                self.events.changed(self.current)
        if state != self.state:
            self._set_state(state)

    def _items(self, found, error):
        if error or not found or not self.active:
            return
        tracks = [items.track(i["media_item"], self.src.url) for i in found
                  if (i.get("media_item") or {}).get("media_type") == "track"]
        known = [t["id"] for t in self.tracks]
        if [t["id"] for t in tracks[:len(known)]] == known:
            new = tracks[len(known):]
            if new:
                self.tracks.extend(new)
                self.events.grew(new)
        else:
            current = self.current
            self.tracks = tracks
            ids = [t["id"] for t in tracks]
            self.index = ids.index(current["id"]) if current and current["id"] in ids else -1

    def _set_state(self, state):
        self.state = state
        on = state == "playing"
        if on != self.playing or state == "stopped":
            self.playing = on
            self.events.playing(on)
