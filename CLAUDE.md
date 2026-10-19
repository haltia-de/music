# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

haltia-music (Музыка, id `io.github.haltia_de.Music`, repo `haltia-de/music`) is a GTK 3 music
player of the Haltia desktop, made for the Lenovo YOGA Tablet 10 (B8000-H), but a self-contained
desktop program: it depends on no shell and meets one only through freedesktop standards (its
`.desktop` file, an inhibitor, MPRIS, the Secret Service), per ADR 0001 in
[device-lenovo-b8000h](https://github.com/haltia-de/device-lenovo-b8000h). Touch targets, Russian
UI, music plays while the window is behind other programs. It is headed for Flatpak and deb too
(device repo `docs/plan-desktop-packages.md`): no fixed `/usr` paths, nothing that needs the shell,
user folders only from `GLib.get_user_config_dir()`/`get_user_data_dir()`/`get_user_cache_dir()`
(inside Flatpak `~` is the real home but unreadable, so never `expanduser("~/…")`),
and `requirements.txt` pins every Python library (for flatpak-pip-generator) at the versions the
tablet runs; keep it in step with the APKBUILD's `depends` and `install.sh`'s wheels.

Before 2.0 it was `b8k-music` / `io.github.trudenboy.Music` (ADR 0004 renamed it). Until 3.0 keep:
the `b8k-music` command (a link), the hidden old `.desktop`, `provides`/`replaces="b8k-music"` in
the APKBUILD, `paths.migrate_dirs("b8k-music", "haltia-music")` at start (it moves
`~/.local/share` and `~/.cache` folders; `Settings` moves `~/.config/b8k/music.conf` itself), and
`B8K_CACHE` as the fallback of `HALTIA_CACHE`. No «крупно» in names or descriptions.

## Commands

There is no build or linter. Checks available:

- `python3 -m unittest` — tests in `tests/` (playback, answers, likes, the source contract;
  stand-ins from `tests/fake.py` and `haltia_kit.testing.FakePlayer`; no GTK, mpv or network).
  One test: `python3 -m unittest tests.test_playback.Radio`. Needs `haltia_kit` importable
  (`PYTHONPATH=/mnt/data/Projects/b8k-compat`, the kit's checkout). Not installed; the APKBUILD runs them.
- `python3 -m py_compile haltia-music *.py sources/*.py` — syntax check.
- `python3 haltia-music` — run from the checkout (finds `sources/` next to itself). Needs
  PyGObject, haltia-kit, python-mpv/libmpv, qrcode, libsecret (optional), and `yandex_music` + `ya_passport_auth`
  importable (pip, or `PYTHONPATH=<ROOT>/usr/local/lib/haltia-music` after an `install.sh` into a
  scratch ROOT).
- `sh install.sh [ROOT] [PREFIX]` — PREFIX `/usr/local` by default, `/usr` from the APKBUILD
  (`packaging/alpine/`). Installs
  the program to `PREFIX/bin`, the top-level `*.py` modules and `sources/` to `PREFIX/lib/haltia-music`
  (a new module needs a line there; the program finds that folder from its own path), `data/` (the
  `.desktop` file with `X-B8K-Home`/`X-B8K-Replaces=music`, hicolor icon, metainfo) to
  `PREFIX/share`, and removes the shell's old `apps.d/music.conf` entry. Downloads pinned wheels
  (sha256-checked, cached in `$HALTIA_CACHE` or `.cache/`) and unpacks them into the lib folder.
  Bumping a library means updating both URL and sum in the `WHEELS` heredoc.

## Architecture

- `haltia-music` — the window, one Python file: `Music(Gtk.Application)` (id `APP_ID`, also set as
  the program name before GTK loads, which names the window under Wayland), `Covers` (cover cache
  in `~/.cache/haltia-music/`).
- [haltia-kit](https://github.com/haltia-de/kit) (`haltia_kit`, package `py3-haltia-kit`, at
  `/mnt/data/Projects/b8k-compat`): `sound.Player` (libmpv, keeps the machine awake through logind
  while playing and not paused), `Settings`, `dialogs` (questions inside the window). The look
  (large header and dialogs) comes from the desktop's GTK theme; the shell buzzes touches itself.
- `playback.py` — `Session`, what plays (see Playback below); `answers.py` — `Answers`, the
  service's answers kept (see Caching); `likes.py` — `Likes`, the hearts; `mpris.py` — `Mpris`,
  what plays told to the desktop (see Playback); `vault.py` — `Vault`, where a sign-in is kept. No GTK; each docstring is its module's interface.
- `sources/` — music services. `sources/__init__.py` docstring is the source interface contract
  (the `SOURCE` object's methods and the track dict shape); read it before touching a source or
  adding one. `sources.load()` imports every module defining `SOURCE`; a module that fails to import,
  or whose `SOURCE` lacks a name in `sources.REQUIRED`, is skipped, never fatal. The app uses the
  first source by id and knows nothing service-specific: what it needs from a service goes into the
  contract (e.g. `likes_list`), and `tests/fake.py`'s `Source` keeps to it too
  (`tests/test_contract.py`). Adding a service = adding a file there, no change to `haltia-music`.
- `sources/yandex.py` — Яндекс Музыка. Both libraries are asyncio; they share one event loop on a
  daemon thread (`_Loop`) and every public method blocks on its result. Account (tokens) kept
  by `vault.py` (`Vault`): in the Secret Service (libsecret; schema `io.github.haltia_de.Music`,
  attribute `account=yandex`), or, where no keyring answers (the tablet has none), in
  `~/.local/share/haltia-music/yandex.json`, mode 600. A file is the newest: it moves into the
  keyring when one answers and is deleted only once the keyring holds it.
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

### Threading rule

Source methods block on the network. Call them through `Music.work(func, arg, done)`: `func` runs in
a thread, `done(result, error)` runs on the GTK main loop; `done` may be None for fire-and-forget
calls (`feedback`). Every GTK touch from another thread goes through `GLib.idle_add`; the kit's
player already posts its callbacks that way.

### Navigation

`self.views` is a stack: the section root first (`home` or `browse`, chosen by the header buttons),
then what was opened (`browse` folder, `list`, `search`, `radio`). Each view dict owns its page (a
`ScrolledWindow` in `self.stack`) and widgets (`list`, `note`, `play`, `shown`, `hearts`) while
`alive`; ← destroys only the top page and shows the one below as it was. Both roots stay built in
`self.roots`. Async callbacks check `view["alive"]` before touching widgets.

A tap only opens (cards, folders, radios); playback starts only from a track row or «▶ Слушать».
A track card on the home page opens its row's list (`row["list"]`) scrolled to that track.

### Settings

The gear opens a `settings` view. Settings live in `~/.config/haltia/music.conf`, section `[music]`
(`self.settings`, the kit's `Settings("music")`). `quality` is one of the
source's `qualities` ids, the lowest by default, and is passed to `stream_url(track, quality)`; it
applies from the next track.

### Caching

- `self.answers.get(what, arg, show)` is the one way to ask the source for data: `show` runs at once
  with the kept answer, the source is asked again when it is older than `FRESH` (or on `force`), and
  `show` runs again only if the answer changed, so `show` callbacks must be safe to run twice.
  `what` must be in `answers.READS`; a new read method of the source goes there. Kept in
  `~/.cache/haltia-music/data.json` (latest `KEEP`); `reset()` on logout drops it and what is in flight.
- After a change on the service (a like), `forget()` the affected keys.
- `Covers` decodes in worker pools (disk and network separate) and keeps `PIXBUFS` decoded covers in
  an LRU; the GTK thread never decodes images.
- In `sources/yandex.py`, `_api()` shares one connect between concurrent callers; keep new calls
  going through it.

### Playback

`self.session` (`playback.Session`) owns the queue, the radio, its growth, start/finish/skip
feedback; `Music` only calls it (`play_list`, `play_radio`, `jump`, the bar's
buttons) and draws its events (`on_track`, `on_grew`, `on_playing`, `say`). The player reports to
it (`on_end` → `ended()`, `on_error` → `ended(text)`, `on_pause` → `paused`). Change playback rules there, with a test in `tests/test_playback.py`.

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
- MPRIS: `self.mpris` owns `org.mpris.MediaPlayer2.<APP_ID>` on the application's bus
  (`DesktopEntry` = `APP_ID`, by which the Haltia shell maps it to the panel button, marks ▶/‖ and
  offers «Пауза»/«Стоп»). `PlaybackStatus` is `Session.state` («playing» also while the next track
  is fetched or a broken one gives way, so the mark does not flicker); `on_track` and `on_playing`
  call `mpris.changed()`. Its tests (`tests/test_mpris.py`) run on a bus of their own and need
  `dbus-daemon` (the APKBUILD's `checkdepends`), skipped without it.
- The machine stays awake while the player plays and is not paused (the kit's logind
  inhibitor; it registers only for a process inside the graphical session). A track that gives way
  stops the player, so nothing holds the machine meanwhile.
- Closing the window (the shell's «Закрыть» sends a toplevel close) stops the music and quits; music
  keeps playing only while the window is open behind other programs. This replaced an earlier
  hide-on-close, which left music playing after «Закрыть».

### Layout constraint

Everything under the search row lives inside one `ScrolledWindow`. Anything tall outside it makes the
window taller than the room the on-screen keyboard leaves and hides the top row (see `show_main`).

## Decisions

`docs/adr/` records what was weighed and turned down; read it before proposing a restructuring.

## Conventions

- Comments and docstrings are terse plain English describing behaviour from the user's side
  ("A radio plays on and on"); UI strings are Russian.
- Every file starts with `# SPDX-License-Identifier: GPL-2.0`.
- Commit subjects are a full sentence ending with a period, describing the effect
  (e.g. "Keep the window within the room the on-screen keyboard leaves.").
- A release is a `vX.Y.Z` tag equal to the APKBUILD's `pkgver` and the newest `<release>` in the
  metainfo; CI builds the signed apk from it. Every `<release>` carries a `<description>` in
  Russian (`<p>` or `<ul><li>`) saying what the person will notice: the shell's updater shows it
  under «Что нового» before installing.
