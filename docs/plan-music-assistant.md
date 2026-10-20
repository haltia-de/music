# Plan: Music Assistant as a second source

Date: 2026-10-20. Settled with the user in an architecture review; terms as in `CONTEXT.md`.

Музыка plays Яндекс Музыка only, and the app assumes one source throughout: `self.src` is
`min(self.sources)`, `Answers`, `Likes`, `Session` and the quality are built around it, and
`track["source"]` is never read. Music Assistant (MA) differs from Яндекс in three ways that shape
the plan: it gives no full-track URL to a client that is not its player (`/preview` is 30 s), its
sign-in is a server address and an account, and it holds the queue, the radio and the services'
feedback itself.

## Decisions

Sources
- One Source shown at a time: the home page, Обзор and search show the shown source; a header
  button with its name switches to the next switched-on one (as Видео's scope button), visible only
  when more than one is on. The shown one is kept (`source = yandex`); missing or off, the first
  switched-on one in a fixed order, Яндекс first.
- Sources are switched on and off in the settings, a card each as in Видео: a switch, the account,
  sign-in and «Выйти». Switching one off keeps its sign-in and answers and lets what plays play on.
  With none on, the home page says to switch one on. Signed out of the shown one, the home page
  says «Войдите в …» with a button to its card.
- Several Sources may be signed in at once.
- Every track, kept answer and heart belongs to one Source; playing and liking go to the track's
  own. One Answers file per Source (`data-<id>.json`; today's `data.json` becomes
  `data-yandex.json`) and one Likes per Source; logging out drops only that Source's answers.
  Settings per Source in `[music]` as `<key>.<id>` (`quality` becomes `quality.yandex`).
- A module without GTK holds the Sources and what each keeps apart (its Answers, Likes, switched
  on or off, quality, the shown one, moving old settings): `Sources` in `sources/__init__.py`,
  tested with two fake sources.

What plays
- `Session` gets two kinds behind one interface, the one the window and MPRIS use today (play a
  list from a track, play a radio, jump, pause/go on, next, previous, seek, stop, state, the
  current track and index, position; events: track changed, queue grew, playing, a message):
  - the program's own (`playback.py` as it is, mpv through the kit's `Player`), for Яндекс;
  - a mirror of the MA queue of this device's player: commands go to `player_queues/*`, the
    `queue_updated`, `queue_items_updated` and `queue_time_updated` events say what plays
    (position counted from `elapsed_time` and `elapsed_time_last_updated`); the server does the
    radio (`radio_playlist://playlist/<seed>` and the services' stations), continuing after a list
    (its own Autoplay setting, left alone), feedback to the services (its providers' `on_played`),
    gapless and crossfade.
- One Session plays at a time: a track of another Source stops the one playing (mpv stop, or
  `player_queues/stop`; the MA queue stays on the server).
- MPRIS asks the Session for the position, not its player.
- A list plays from a track by `play_media(queue, list, option="replace", start_item=track)`;
  no «next» or «add to the queue» at first, no queue page (a radio or list page mirrors the queue
  as now, growing on `queue_items_updated`), and MA plays on this device only (choosing another MA
  player and `transfer` later).

Sound from MA (ADR 0003)
- The program is an MA player over Sendspin (`aiosendspin` client, dialling the authenticated
  proxy `ws://host:8095/sendspin`): MA plays the queue into it, FLAC (PCM if the tablet cannot
  decode it in time), no quality choice at first. How the stream reaches the speakers (fed to mpv
  through python-mpv's stream protocol, or GStreamer) and how the server admits a new device
  (pairing PIN or approval) are settled by the spike.

Signing in
- A Source describes its sign-in steps and the window draws them: Яндекс shows a QR code and a
  code as now; MA asks for a server address and a login and password, or a token. Found servers
  (mDNS `_mass._tcp`, looked up by the program) are offered above the form.
- MA: `auth/login`, then `auth/token/create` for a long-lived token named «Музыка (<host>)»; the
  address and token kept by `vault.Vault`, the password never.

Connection
- An MA client of our own on aiohttp (`ws://host:8095/ws`: the server's info, `auth` with the
  token, commands by `message_id` with partial results, events), not `music-assistant-client`
  (it needs Python ≥ 3.13, Ubuntu 24.04 has 3.12, and it pins one `music_assistant_models`).
  Tested against a fake server.
- It runs on the asyncio loop thread the Sources share, moved out of `sources/yandex.py` (`_Loop`,
  `_run`, the shared connect of `_api`) when the second user comes.
- On a dropped connection it reconnects by itself (1 s to 30 s apart); meanwhile the bar says
  «Нет связи с Music Assistant» and its buttons are off; after it, the queue is read again
  (`player_queues/get`, `items`).

Catalog
- Home: `music/recommendations` rows (their items by `music/recommendations/items`). Обзор:
  `music/browse`. Search: `music/search`. Lists: `music/playlists/playlist_tracks`,
  `music/albums/album_tracks`. Radios: the services' stations and `radio_playlist://` from a
  track, album, artist or playlist. Hearts: MA favourites (`music/favorites/add_item`,
  `remove_item`; the server passes them on to the service where it can). Ids are MA URIs, so
  ADR 0001 stays as it is.

## Steps

1. **2.4.0, Sources** (Яндекс only): `Sources`; Answers, Likes, Session and quality per Source by
   `track["source"]`; moving `data.json` and `quality`; the «Источники» section with the Яндекс
   card (switch, account, sign-in, «Выйти»); the home page's «Войдите» leading there; tests with
   two fake sources. On the tablet before release: the kept answers, sign-in and quality survive.
2. **Alongside, the spike** (a script outside the repository, with the user's MA address and
   token): register over Sendspin, play two or three tracks through mpv; measure the delay to
   sound, the gap between tracks, CPU here and on the tablet; try `auth/login` and the device's
   admission. Failing, fall back to the plan of ADR 0003's rejected option and spike that.
3. **2.5.0, seams**: sign-in steps in the source contract (code/QR or a form); the shared loop
   thread; `Session`'s interface, the program's own kind behind it; MPRIS position from it;
   `stream_url`, `radio_next` and `qualities` required only of a Source playing through the
   program's own Session.
4. **3.0.0, Music Assistant**: the client, the queue mirror, Sendspin sound, finding servers,
   the MA card and form, packages (`aiosendspin` and its dependencies in `requirements.txt`, the
   APKBUILD, `debian/control`, the Flatpak's modules); dropping the `b8k` names due at 3.0.

## Spike results (2026-10-20, this PC, MA schema 96)

A script outside the repository played the user's MA as a Sendspin player: to PipeWire on the host,
and through libmpv inside the Flatpak (Python 3.14). The tablet is still to try.

- Connecting: `wss://<host>/ws` (server info, then `auth` with the token) and `wss://<host>/sendspin`,
  whose first message is `{"type": "auth", "token", "client_id": <Sendspin peer id>}`, answered
  `{"type": "auth_ok"}`; the Sendspin handshake follows on the same socket. `aiosendspin`'s
  `SendspinClient.connect` dials by itself, so the spike opened the socket and used the library's
  internals (`SendspinConnection`); the program wants a small wrapper or an upstream hook.
- The device must say it is an app (`DeviceInfo.product_name` one of "Web Browser", "Web Player",
  "Mobile Application", "PWA": a heuristic MA marks as a TODO) to become a standalone player of
  its own, private to the user, its id the Sendspin peer id. Otherwise MA wraps it as a Sendspin
  output of a new "universal player" (`up…`) and it plays nothing it is asked.
- Guest access (`unpaired_access_enabled` in the client's pairing config) is approved by itself
  for playback: no PIN. The identity (an X25519 key) must be kept, or every start makes a new
  player on the server; keep it with the account (`Vault`).
- `buffer_capacity` must be small (200 kB ≈ 1 s of PCM): with 2 MB the server ran ~10 s ahead and
  next, pause and stop came 10 s late.
- Timings: `play_media` to sound 0.7 s; `next` 0.4 s; pause and play at once (the stream ends
  and starts again); a new stream per track, no gap over 0.5 s at track changes.
- CPU: 2 % (PCM to PipeWire on the host), 12 % in the Flatpak with libmpv playing one endless
  `python://` stream as `rawaudio` s16le 48 kHz. On a new stream mpv's own buffer must be dropped
  (a fresh load), or what it holds plays after a next or a pause.
- `players/get` says idle while it plays; the queue (`queue_updated`) is what is true.
- Python wheels: `aiosendspin` 9.1.1 needs cryptography, cffi, orjson, zeroconf, mashumaro,
  cpace, noiseprotocol (the last three pure Python).

## References

- MA server `/mnt/data/Projects/mass/ma-server`: `controllers/player_queues/README.md` (the queue
  model, radio, feedback), `controllers/webserver/` (`auth.py`, `websocket_client.py`,
  `sendspin_proxy.py`), `providers/sendspin/README.md`.
- [ma-provider-web-kiosk](https://github.com/trudenboy/ma-provider-web-kiosk): a browser as an MA
  player, Sendspin by default. [ma-provider-msx-bridge](https://github.com/trudenboy/ma-provider-msx-bridge):
  per-track `/single/` URLs with an HMAC token (the rejected option of ADR 0003).
- Clients that play over Sendspin: MA Companion (Tauri), sendspin-cli (Python), Ensemble
  (Flutter), MassDroid; the Home Assistant integration only controls MA players.
