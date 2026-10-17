# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

b8k-music is a GTK 3 music player for the Lenovo YOGA Tablet 10 (B8000-H) running the
[lenovo-b8000h-linux](https://github.com/trudenboy/lenovo-b8000h-linux) shell. Large touch
targets, Russian UI, playback continues with the window closed.

## Commands

There is no build or linter. Checks available:

- `python3 -m unittest` — tests in `tests/` (playback, answers, likes, with stand-ins from `tests/fake.py`;
  no GTK, mpv or network). One test: `python3 -m unittest tests.test_playback.Radio`.
  Not installed on the tablet.
- `python3 -m py_compile b8k-music *.py sources/*.py` — syntax check.
- `python3 b8k-music` — run from the checkout (finds `sources/` next to itself). Needs
  PyGObject, python-mpv/libmpv, qrcode, and `yandex_music` + `ya_passport_auth` importable
  (pip, or `PYTHONPATH=<ROOT>/usr/local/lib/b8k-music` after an `install.sh` into a scratch ROOT).
  Without the tablet shell, `b8k_ui` is absent and the program falls back (no buzz, `ask()` always yes).
- `sh install.sh [ROOT]` — installs into a root file system; the tablet shell's image build calls it.
  Copies the top-level `*.py` modules and `sources/` to `/usr/local/lib/b8k-music`; a new module next to them
  needs a line there. Downloads pinned wheels (sha256-checked, cached in `$B8K_CACHE` or `.cache/`) and unpacks them
  next to the sources in `/usr/local/lib/b8k-music`. Bumping a library means updating both URL and sum
  in the `WHEELS` heredoc.

## Architecture

- `b8k-music` — the window, one Python file: `Music(Gtk.Application)` (app id `b8k.Music`),
  `Player` (libmpv, sound only), `Covers` (cover cache in `~/.cache/b8k-music/`).
- `playback.py` — `Session`, what plays (see Playback below); `answers.py` — `Answers`, the
  service's answers kept (see Caching); `likes.py` — `Likes`, the hearts. No GTK; each docstring is its module's interface.
- `sources/` — music services. `sources/__init__.py` docstring is the source interface contract
  (the `SOURCE` object's methods and the track dict shape); read it before touching a source or
  adding one. `sources.load()` imports every module defining `SOURCE`; a module that fails to import
  is skipped, never fatal. Adding a service = adding a file there, no change to `b8k-music`.
- `sources/yandex.py` — Яндекс Музыка. Both libraries are asyncio; they share one event loop on a
  daemon thread (`_Loop`) and every public method blocks on its result. Account (tokens) in
  `~/.local/share/b8k-music/yandex.json`, mode 600, written atomically via `.new` + `os.replace`.
  Token renewal: music token from x_token, falling back to the refresh token.
  - Login runs QR and device-code flows at once; `login_wait` takes whichever confirms first. The QR
    session lives in the `PassportClient`'s cookie jar, so that client stays open from
    `login_start` to `login_wait`.
  - Home rows and the Browse tree mirror the Music Assistant Yandex provider
    (`/mnt/data/Projects/mass/ma-provider-yandex-music/provider/`, `get_recommendations` and
    `browse.py`) — the reference for which API calls feed which row/folder.
  - Radios are rotor *sessions* (`rotor_session_new` with seeds); a wave mode is `user:onyourwave#<mode>`
    and adds a `setting…` seed. Feedback goes to the session.
  - Item ids are prefixed strings the source parses back: `playlist:<uid>:<kind>`, `album:<id>`,
    `artist:<id>`, `stations:<type>`, `tag:<slug>`, …
- `music.conf` / `music.svg` — registration with the shell (`/usr/local/share/b8k/apps.d/`).

### Threading rule

Source methods block on the network. Call them through `Music.work(func, arg, done)`: `func` runs in
a thread, `done(result, error)` runs on the GTK main loop; `done` may be None for fire-and-forget
calls (`feedback`). Every GTK touch from another thread goes through `GLib.idle_add`, including
mpv property/event callbacks in `Player`.

### Navigation

`self.views` is a stack: the section root first (`home` or `browse`, chosen by the header buttons),
then what was opened (`browse` folder, `list`, `search`, `radio`). Each view dict owns its page (a
`ScrolledWindow` in `self.stack`) and widgets (`list`, `note`, `play`, `shown`, `hearts`) while
`alive`; ← destroys only the top page and shows the one below as it was. Both roots stay built in
`self.roots`. Async callbacks check `view["alive"]` before touching widgets.

A tap only opens (cards, folders, radios); playback starts only from a track row or «▶ Слушать».
A track card on the home page opens its row's list (`row["list"]`) scrolled to that track.

### Settings

The gear opens a `settings` view. Settings live in `~/.config/b8k/music.conf`, section `[music]`
(`load_setting`/`save_setting`, the same shape as b8k-max's `max.conf`). `quality` is one of the
source's `qualities` ids, the lowest by default, and is passed to `stream_url(track, quality)`; it
applies from the next track.

### Caching

- `self.answers.get(what, arg, show)` is the one way to ask the source for data: `show` runs at once
  with the kept answer, the source is asked again when it is older than `FRESH` (or on `force`), and
  `show` runs again only if the answer changed, so `show` callbacks must be safe to run twice.
  `what` must be in `answers.READS`; a new read method of the source goes there. Kept in
  `~/.cache/b8k-music/data.json` (latest `KEEP`); `reset()` on logout drops it and what is in flight.
- After a change on the service (a like), `forget()` the affected keys.
- `Covers` decodes in worker pools (disk and network separate) and keeps `PIXBUFS` decoded covers in
  an LRU; the GTK thread never decodes images.
- In `sources/yandex.py`, `_api()` shares one connect between concurrent callers; keep new calls
  going through it.

### Playback

`self.session` (`playback.Session`) owns the queue, the radio, its growth, start/finish/skip
feedback and the awake file; `Music` only calls it (`play_list`, `play_radio`, `jump`, the bar's
buttons) and draws its events (`on_track`, `on_grew`, `on_playing`, `say`). `Player` reports to it
(`ended(error)`, `paused`). Change playback rules there, with a test in `tests/test_playback.py`.

- The session keeps its own copy of the tracks. The radio page (`self.radio_view`) mirrors it:
  `on_grew` appends rows and `shown` entries, so row positions equal queue positions.
  `radio_on(view)` is "this radio page's radio plays".
- A radio page loads the radio's first batch (`radio_next(id, None)`, which opens a rotor session)
  and shows it like a list, without playing. «▶ Слушать» or a tap on a track plays it; it grows via
  `radio_next(id, last track of the queue)` when `RADIO_AHEAD` tracks remain, one request at a time.
- Leaving a track that played its sound, paused or not, is a skip; playing to the end is a finish.
  A track without a stream (or an mpv error) goes quiet and gives way after `GIVE_WAY` seconds,
  unless another was chosen.
- Likes: `self.likes` (`likes.Likes`) answers `liked(track)` and takes `toggle(track)`; the heart
  changes at once, one request per track is in flight and the service ends with the last tap; a
  failure reverts to the confirmed state. Liked ids come via `answers` (`refresh()` on the first
  page, forced on the house button); confirmed taps stay on until an answer shows them.
- `$XDG_RUNTIME_DIR/b8k-awake/<pid>.suspend` exists while music plays; it keeps the tablet from
  suspending (the shell's b8k-sleep reads it).
- Closing the window (the shell's «Закрыть» sends a toplevel close) stops the music and quits; music
  keeps playing only while the window is open behind other programs. This replaced an earlier
  hide-on-close, which left music playing after «Закрыть».

### Layout constraint

Everything under the search row lives inside one `ScrolledWindow`. Anything tall outside it makes the
window taller than the room the on-screen keyboard leaves and hides the top row (see `show_main`).

## Conventions

- Comments and docstrings are terse plain English describing behaviour from the user's side
  ("A radio plays on and on"); UI strings are Russian.
- Every file starts with `# SPDX-License-Identifier: GPL-2.0`.
- Commit subjects are a full sentence ending with a period, describing the effect
  (e.g. "Keep the window within the room the on-screen keyboard leaves.").
