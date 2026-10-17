# SPDX-License-Identifier: GPL-2.0
"""The services music comes from. Every module of this package that defines
SOURCE is one; b8k-music lists them all and needs nothing else to know
about a new one (Звук, Apple Music, ...).

SOURCE has:
  id, label                 "yandex", "Яндекс Музыка"
  logged_in()               True when it has an account to play from
  login_start()             {"code": ..., "url": ...}: the code to enter at url
  login_wait()              blocks until that code is confirmed; True on success
  logout()
  account()                 the account's name, or ""
  collections()             [{"id", "title", "radio": bool}]: what the first
                            page offers (a radio plays on and on)
  tracks(collection_id)     the tracks of a collection that is not a radio
  radio_next(collection_id, last_track)
                            the next few tracks of a radio
  search(query)             tracks, best first
  stream_url(track)         a URL the player can open
  feedback(collection_id, event, track, seconds)
                            optional: "start", "finish" or "skip" of a radio
                            track, so the service learns what one likes

A track is a dict: source, id, title, artist, duration (seconds or None),
cover (an image URL or "").

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
