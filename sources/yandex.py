# SPDX-License-Identifier: GPL-2.0
"""Яндекс Музыка through yandex-music (MarshalX) and, for signing in,
ya-passport-auth (the OAuth device flow: a short code entered at
ya.ru/device; the refresh token it brings renews the access silently).

Both libraries are asyncio; they run on one event loop in a thread of
their own, and every method here waits for its result, so the program
calls them from worker threads like any blocking source.

The account is kept in ~/.local/share/b8k-music/yandex.json (mode 600).
Streams are the plain (not encrypted) AAC or MP3 of /get-file-info.
"""
import asyncio
import json
import os
import threading

ACCOUNT = os.path.expanduser("~/.local/share/b8k-music/yandex.json")
WAVE = "user:onyourwave"
# The normal quality: AAC around 192 kbit/s, MP3 where there is no AAC.
QUALITY = "nq"
CODECS = ["aac-mp4", "aac", "mp3", "he-aac", "he-aac-mp4"]
LIST_MAX = 100


class _Loop:
    """One asyncio loop in a daemon thread; run(coro) waits for the result."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, coro, timeout=120):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


def _track(t):
    if t is None or not getattr(t, "available", True):
        return None
    artists = ", ".join(a.name for a in (t.artists or []) if a.name)
    cover = ""
    if t.cover_uri:
        cover = "https://" + t.cover_uri.replace("%%", "200x200")
    return {
        "source": "yandex",
        "id": str(t.id),
        "title": t.title or "",
        "artist": artists,
        "duration": (t.duration_ms or 0) / 1000 or None,
        "cover": cover,
    }


class Yandex:
    id = "yandex"
    label = "Яндекс Музыка"

    def __init__(self):
        self._loop = None
        self._client = None
        self._session = None  # the device-code login in progress
        self._batch = {}  # radio station -> batch id, for feedback

    # --- the account ------------------------------------------------------
    @staticmethod
    def _saved():
        try:
            with open(ACCOUNT, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _save(data):
        os.makedirs(os.path.dirname(ACCOUNT), mode=0o700, exist_ok=True)
        fd = os.open(ACCOUNT + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(ACCOUNT + ".new", ACCOUNT)

    def _run(self, coro):
        if self._loop is None:
            self._loop = _Loop()
        return self._loop.run(coro)

    def logged_in(self):
        saved = self._saved()
        return bool(saved and saved.get("x_token"))

    def account(self):
        saved = self._saved() or {}
        return saved.get("login") or ""

    def login_start(self):
        from ya_passport_auth import PassportClient

        async def start():
            async with PassportClient.create() as client:
                return await client.start_device_login(device_name="B8000-H")

        self._session = self._run(start())
        return {"code": self._session.user_code, "url": self._session.verification_url}

    def login_wait(self):
        from ya_passport_auth import PassportClient

        session = self._session
        if session is None:
            return False

        async def wait():
            async with PassportClient.create() as client:
                creds = await client.poll_device_until_confirmed(session)
                login = ""
                try:
                    info = await client.fetch_account_info(creds.x_token)
                    login = info.display_login or ""
                except Exception:
                    pass
                return creds, login

        creds, login = self._run(wait())
        self._save({
            "x_token": creds.x_token.get_secret(),
            "music_token": creds.music_token.get_secret() if creds.music_token else "",
            "refresh_token": creds.refresh_token.get_secret() if creds.refresh_token else "",
            "uid": creds.uid,
            "login": login or creds.display_login or "",
        })
        self._session = None
        self._client = None
        return True

    def logout(self):
        try:
            os.unlink(ACCOUNT)
        except OSError:
            pass
        self._client = None

    async def _renew(self, saved):
        """A new music token from the x_token, or a new x_token first from
        the refresh token when the x_token itself has run out."""
        from ya_passport_auth import Credentials, PassportClient, SecretStr

        async with PassportClient.create() as client:
            try:
                music = await client.refresh_music_token(SecretStr(saved["x_token"]))
                saved["music_token"] = music.get_secret()
            except Exception:
                if not saved.get("refresh_token"):
                    raise
                creds = await client.refresh_credentials(Credentials(
                    x_token=SecretStr(saved["x_token"]),
                    refresh_token=SecretStr(saved["refresh_token"])))
                saved["x_token"] = creds.x_token.get_secret()
                if creds.refresh_token:
                    saved["refresh_token"] = creds.refresh_token.get_secret()
                saved["music_token"] = (creds.music_token.get_secret() if creds.music_token
                                        else (await client.refresh_music_token(creds.x_token))
                                        .get_secret())
        self._save(saved)
        return saved

    async def _api(self):
        if self._client is not None:
            return self._client
        from yandex_music import ClientAsync
        from yandex_music.exceptions import UnauthorizedError

        saved = self._saved()
        if not saved:
            raise RuntimeError("not signed in")
        if not saved.get("music_token"):
            saved = await self._renew(saved)
        try:
            self._client = await ClientAsync(saved["music_token"], report_unknown_fields=False).init()
        except UnauthorizedError:
            saved = await self._renew(saved)
            self._client = await ClientAsync(saved["music_token"], report_unknown_fields=False).init()
        return self._client

    # --- music ---------------------------------------------------------------
    def collections(self):
        async def get():
            api = await self._api()
            out = [{"id": WAVE, "title": "Моя волна", "radio": True},
                   {"id": "likes", "title": "Мне нравится", "radio": False}]
            for pl in await api.users_playlists_list() or []:
                out.append({"id": "playlist:%s" % pl.kind, "title": pl.title, "radio": False})
            return out

        return self._run(get())

    def tracks(self, collection_id):
        async def get():
            api = await self._api()
            ids = []
            if collection_id == "likes":
                likes = await api.users_likes_tracks()
                ids = [t.track_id for t in (likes.tracks if likes else [])[:LIST_MAX]]
            elif collection_id.startswith("playlist:"):
                pl = await api.users_playlists(collection_id.split(":", 1)[1])
                ids = [t.track_id for t in (pl.tracks or [])[:LIST_MAX]] if pl else []
            if not ids:
                return []
            return [x for x in map(_track, await api.tracks(ids)) if x]

        return self._run(get())

    def radio_next(self, collection_id, last_track):
        async def get():
            api = await self._api()
            res = await api.rotor_station_tracks(
                collection_id, settings2=True, queue=last_track["id"] if last_track else None)
            if not res:
                return []
            if collection_id not in self._batch:
                try:
                    await api.rotor_station_feedback_radio_started(
                        collection_id, "b8k-music", batch_id=res.batch_id)
                except Exception:
                    pass
            self._batch[collection_id] = res.batch_id
            return [x for x in (_track(s.track) for s in res.sequence or []) if x]

        return self._run(get())

    def search(self, query):
        async def get():
            api = await self._api()
            res = await api.search(query, type_="track")
            found = res.tracks.results if res and res.tracks else []
            return [x for x in map(_track, found[:40]) if x]

        return self._run(get())

    def stream_url(self, track):
        async def get():
            api = await self._api()
            info = await api.tracks_file_info(track["id"], quality=QUALITY, codecs=CODECS,
                                              transport="raw")
            if not info or not info.download_info or not info.download_info.url:
                raise RuntimeError("no stream for this track")
            if getattr(info.download_info, "key", None):
                raise RuntimeError("the stream is encrypted")
            return info.download_info.url

        return self._run(get())

    def feedback(self, collection_id, event, track, seconds):
        if collection_id != WAVE:
            return

        async def send():
            api = await self._api()
            batch = self._batch.get(collection_id)
            if event == "start":
                await api.rotor_station_feedback_track_started(collection_id, track["id"],
                                                               batch_id=batch)
            elif event == "finish":
                await api.rotor_station_feedback_track_finished(collection_id, track["id"],
                                                                seconds, batch_id=batch)
            elif event == "skip":
                await api.rotor_station_feedback_skip(collection_id, track["id"], seconds,
                                                      batch_id=batch)

        try:
            self._run(send())
        except Exception:
            pass  # feedback only tunes the recommendations


SOURCE = Yandex()
