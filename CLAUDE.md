# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

b8k-music is a GTK 3 music player for the Lenovo YOGA Tablet 10 (B8000-H) running the
[lenovo-b8000h-linux](https://github.com/trudenboy/lenovo-b8000h-linux) shell. Large touch
targets, Russian UI, playback continues with the window closed.

## Commands

There is no build, test suite or linter. Checks available:

- `python3 -m py_compile b8k-music sources/*.py` — syntax check.
- `python3 b8k-music` — run from the checkout (finds `sources/` next to itself). Needs
  PyGObject, python-mpv/libmpv, qrcode, and `yandex_music` + `ya_passport_auth` importable
  (pip, or `PYTHONPATH=<ROOT>/usr/local/lib/b8k-music` after an `install.sh` into a scratch ROOT).
  Without the tablet shell, `b8k_ui` is absent and the program falls back (no buzz, `ask()` always yes).
- `sh install.sh [ROOT]` — installs into a root file system; the tablet shell's image build calls it.
  Downloads pinned wheels (sha256-checked, cached in `$B8K_CACHE` or `.cache/`) and unpacks them
  next to the sources in `/usr/local/lib/b8k-music`. Bumping a library means updating both URL and sum
  in the `WHEELS` heredoc.

## Architecture

- `b8k-music` — the whole app, one Python file: `Music(Gtk.Application)` (app id `b8k.Music`),
  `Player` (libmpv, sound only), `Covers` (cover cache in `~/.cache/b8k-music/`).
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
a thread, `done(result, error)` runs on the GTK main loop. Fire-and-forget calls (`feedback`) use a
bare daemon thread. Every GTK touch from another thread goes through `GLib.idle_add`, including
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

- `fetch(what, arg, show)` is the one way to ask the source for data: it calls `show` at once with
  the kept answer from `self.data`, re-asks the source when the answer is older than `FRESH` (or on
  `force`), and calls `show` again only if the answer changed. So `show` callbacks must be safe to
  run twice. `self.data` is saved to `~/.cache/b8k-music/data.json` (latest `KEEP`), deleted on logout.
- After a change on the service (a like), `forget()` the affected keys.
- `Covers` decodes in worker pools (disk and network separate) and keeps `PIXBUFS` decoded covers in
  an LRU; the GTK thread never decodes images.
- In `sources/yandex.py`, `_api()` shares one connect between concurrent callers; keep new calls
  going through it.

### Playback state

- `self.queue` is what plays; a view's `shown` is what its list displays. On the radio page
  (`self.radio_view`) they are the *same list object* (`view["shown"] is self.queue`), so
  `_radio_more` extending the queue extends the list; `fill()` stores the list without copying on
  purpose.
- Tapping a track in a list copies the list's tracks into a new queue and drops the radio.
- «▶ Слушать» on a radio page starts it (`start_radio`); the page then shows its growing queue. It
  fetches more via `radio_next` when `RADIO_AHEAD` tracks remain, and sends start/finish/skip
  feedback.
- Likes: `self.liked` (track ids) via `fetch("liked")`; hearts update optimistically and
  revert if `src.like()` fails.
- `set_playing()` owns the side effects of playing: `$XDG_RUNTIME_DIR/b8k-awake/<pid>.suspend`
  keeps the tablet from suspending (the shell's b8k-sleep reads it).
- Closing the window (the shell's «Закрыть» sends a toplevel close) stops the music and quits; music
  keeps playing only while the window is open behind other programs. This replaced an earlier
  hide-on-close, which left music playing after «Закрыть».
- Stale async results are dropped by identity checks (`_play` compares `self.queue[self.index] is track`).

### Layout constraint

Everything under the search row lives inside one `ScrolledWindow`. Anything tall outside it makes the
window taller than the room the on-screen keyboard leaves and hides the top row (see `show_main`).

## Conventions

- Comments and docstrings are terse plain English describing behaviour from the user's side
  ("A radio plays on and on"); UI strings are Russian.
- Every file starts with `# SPDX-License-Identifier: GPL-2.0`.
- Commit subjects are a full sentence ending with a period, describing the effect
  (e.g. "Keep the window within the room the on-screen keyboard leaves.").
