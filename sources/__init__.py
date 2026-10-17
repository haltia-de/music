# SPDX-License-Identifier: GPL-2.0
"""The services music comes from. Every module of this package that defines
SOURCE is one; b8k-music lists them all and needs nothing else to know
about a new one (Звук, Apple Music, ...).

SOURCE has:
  id, label                 "yandex", "Яндекс Музыка"
  logged_in()               True when it has an account to play from
  login_start()             {"code", "url", "qr"}: the code to enter at url,
                            and a URL to show as a QR code to scan; either
                            may be "" when the service has no such way in
  login_wait()              blocks until one of them is confirmed; True on
                            success
  logout()
  account()                 the account's name, or ""
  home()                    [{"id", "title"}]: the rows of the first page; a
                            row of tracks may name the "list" they come from
  home_row(row_id)          the items of a row
  browse(folder_id)         the items of a folder; "" is the top one
  tracks(list_id)           the tracks of a list
  radio_next(radio_id, last_track)
                            the next few tracks of a radio
  search(query)             tracks, best first
  stream_url(track, quality)
                            a URL the player can open, in one of qualities
  qualities                 [(id, title, hint)], the lowest first
  feedback(radio_id, event, track, seconds)
                            optional: "start", "finish" or "skip" of a radio
                            track, so the service learns what one likes
  liked(), like(track, on)  optional: the ids of the tracks one likes, and
                            liking a track or no longer

An item is a dict with a kind: "track", or "list", "radio" or "folder"
with id, title, subtitle and cover (an image URL or ""). A list opens to
its tracks, a radio plays on and on, a folder holds more items.

A track is a dict: kind "track", source, id, title, artist, duration
(seconds or None), cover.

A source may block (network): b8k-music calls it from a worker thread.
"""
import importlib
import pkgutil
import sys


def load():
    """{id: SOURCE} of every source that imports; a broken one is skipped."""
    found = {}
    for info in pkgutil.iter_modules(__path__):
        try:
            mod = importlib.import_module("%s.%s" % (__name__, info.name))
        except Exception as exc:  # a source must never take the program down
            sys.stderr.write("b8k-music: source %s: %s\n" % (info.name, exc))
            continue
        src = getattr(mod, "SOURCE", None)
        if src is not None:
            found[src.id] = src
    return found
