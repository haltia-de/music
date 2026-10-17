# SPDX-License-Identifier: GPL-2.0
"""Яндекс Музыка through yandex-music (MarshalX) and, for signing in,
ya-passport-auth: a QR code scanned with the phone, or a short code entered
at ya.ru/device (the OAuth device flow, whose refresh token renews the
access silently), whichever is confirmed first.

Both libraries are asyncio; they run on one event loop in a thread of
their own, and every method here waits for its result, so the program
calls them from worker threads like any blocking source.

The first page and the folders follow the Yandex Music provider of Music
Assistant: Моя волна and its modes, Для вас, the chart, new releases and
playlists, picks by mood and activity; the folders hold the collection,
the radio stations by genre, mood, activity and era, and the picks.
A radio is a rotor session: its seeds are the station and, for a mode of
Моя волна, the mode's setting.

The account is kept in ~/.local/share/b8k-music/yandex.json (mode 600).
Streams are the plain (not encrypted) AAC or MP3 of /get-file-info, in the
quality chosen in the settings: the same levels as the Music Assistant
provider has.
"""
import asyncio
import datetime
import json
import os
import threading

ACCOUNT = os.path.expanduser("~/.local/share/b8k-music/yandex.json")
WAVE = "user:onyourwave"
# Stream qualities: id -> (/get-file-info quality, codecs it may choose).
QUALITY = {
    "low": ("lq", ["he-aac-mp4", "he-aac", "aac-mp4", "aac", "mp3"]),
    "normal": ("nq", ["aac-mp4", "aac", "mp3", "he-aac", "he-aac-mp4"]),
    "high": ("lossless", ["mp3"]),
}
LIST_MAX = 100
ROW_MAX = 20
# Playlists the service keeps by itself that are no use here.
SEARCH_LISTS = 10  # playlists a search shows
SEARCH_FIRST = 3  # tracks shown before them, unless a playlist is the best match
HIDDEN = {"Распознано"}

# The modes of Моя волна: id after "#", name, the rotor seed it adds, its sign.
MODES = [
    ("favorite", "Любимое", "settingDiversity:favorite", "♥"),
    ("discover", "Незнакомое", "settingDiversity:discover", "✦"),
    ("popular", "Популярное", "settingDiversity:popular", "★"),
    ("active", "Бодрое", "settingMoodEnergy:active", "⚡"),
    ("fun", "Весёлое", "settingMoodEnergy:fun", "☺"),
    ("calm", "Спокойное", "settingMoodEnergy:calm", "☾"),
    ("sad", "Грустное", "settingMoodEnergy:sad", "☂"),
    ("russian", "Русское", "settingLanguage:russian", "Ру"),
    ("not_russian", "Иностранное", "settingLanguage:not-russian", "En"),
    ("without_words", "Без слов", "settingLanguage:without-words", "♫"),
]
SEEDS = {m[0]: m[2] for m in MODES}

# Station kinds of the radio folder, in order.
STATIONS = [("genre", "Жанры"), ("mood", "Настроение"), ("activity", "Занятие"),
            ("epoch", "Эпоха")]

# Playlist tags (the picks), by category.
TAGS = [
    ("mood", "Настроение", [("chill", "Чилл"), ("sad", "Грусть"), ("romantic", "Романтика"),
                            ("party", "Вечеринка"), ("relax", "Отдых"),
                            ("in the mood", "В настроении")]),
    ("activity", "Занятие", [("workout", "Тренировка"), ("focus", "Сосредоточиться"),
                             ("morning", "Утро"), ("evening", "Вечер"),
                             ("driving", "За рулём"), ("background", "Фоном")]),
    ("era", "Эпоха", [("80s", "80-е"), ("90s", "90-е"), ("2000s", "2000-е"),
                      ("retro", "Ретро")]),
    ("genres", "Жанры", [("rock", "Рок"), ("jazz", "Джаз"), ("classical", "Классика"),
                         ("electronic", "Электроника"), ("rnb", "R&B"),
                         ("hiphop", "Хип-хоп"), ("top", "Лучшее"),
                         ("newbies", "Новые имена")]),
]
TAG_NAMES = {slug: name for _c, _n, tags in TAGS for slug, name in tags}
SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
SEASON_NAMES = {"winter": "Зима", "spring": "Весна", "summer": "Лето", "autumn": "Осень"}


class _Loop:
    """One asyncio loop in a daemon thread; run(coro) waits for the result."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, coro, timeout=120):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


def _cover(uri):
    return "https://" + uri.replace("%%", "200x200") if uri else ""


def _track(t):
    if t is None or not getattr(t, "available", True):
        return None
    artists = ", ".join(a.name for a in (t.artists or []) if a.name)
    return {
        "kind": "track",
        "source": "yandex",
        "id": str(t.id),
        "title": t.title or "",
        "artist": artists,
        "duration": (t.duration_ms or 0) / 1000 or None,
        "cover": _cover(t.cover_uri),
    }


def _tracks(found):
    return [x for x in map(_track, found) if x]


def _item(kind, id_, title, subtitle="", cover="", glyph=""):
    item = {"kind": kind, "id": id_, "title": title, "subtitle": subtitle, "cover": cover}
    if glyph:
        item["glyph"] = glyph
    return item


def _count(n):
    """1 трек, 2 трека, 5 треков."""
    if n % 10 == 1 and n % 100 != 11:
        word = "трек"
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        word = "трека"
    else:
        word = "треков"
    return "%d %s" % (n, word)


def _playlist(pl):
    if pl is None or (pl.title or "") in HIDDEN:
        return None
    uid = pl.owner.uid if pl.owner else pl.uid
    cover = pl.cover
    uri = (getattr(cover, "uri", None) or (getattr(cover, "items_uri", None) or [None])[0]
           if cover else None) or pl.og_image
    count = _count(pl.track_count) if pl.track_count else ""
    return _item("list", "playlist:%s:%s" % (uid, pl.kind), pl.title or "", count, _cover(uri))


def _album(a):
    if a is None:
        return None
    artists = ", ".join(x.name for x in (a.artists or []) if x.name)
    sub = " · ".join(str(x) for x in (artists, a.year) if x)
    return _item("list", "album:%s" % a.id, a.title or "", sub, _cover(a.cover_uri))


def _artist(a):
    if a is None:
        return None
    return _item("folder", "artist:%s" % a.id, a.name or "", "",
                 _cover(a.cover.uri if a.cover else None))


def _some(items):
    return [x for x in items if x]


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


class Yandex:
    id = "yandex"
    label = "Яндекс Музыка"
    likes_list = "likes"
    qualities = [
        ("low", "Экономное", "HE-AAC около 64 кбит/с: меньше всего трафика"),
        ("normal", "Обычное", "AAC около 192 кбит/с"),
        ("high", "Высокое", "MP3 до 320 кбит/с, если позволяет подписка"),
    ]

    def __init__(self):
        self._loop = None
        self._client = None
        self._connecting = None  # the client being made, for all who need it
        self._device = None  # the device-code login in progress
        self._qr = None  # the QR login in progress: (PassportClient, QrSession)
        self._radio = {}  # radio id -> {"session", "batch"} of its rotor session
        self._stations = None

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

    def _run(self, coro, timeout=120):
        if self._loop is None:
            self._loop = _Loop()
        return self._loop.run(coro, timeout)

    def logged_in(self):
        saved = self._saved()
        return bool(saved and saved.get("x_token"))

    def account(self):
        saved = self._saved() or {}
        return saved.get("login") or ""

    def login_start(self):
        from ya_passport_auth import PassportClient

        async def start():
            await self._drop_qr()
            device = qr = None
            try:
                async with PassportClient.create() as client:
                    device = await client.start_device_login(device_name="B8000-H")
            except Exception:
                pass
            # The QR session lives in the client's cookies: it stays open
            # until login_wait is done with it.
            client = PassportClient()
            try:
                qr = (client, await client.start_qr_login())
            except Exception:
                await client.close()
            if device is None and qr is None:
                raise RuntimeError("no way to sign in")
            return device, qr

        self._device, self._qr = self._run(start())
        out = {"code": "", "url": "", "qr": ""}
        if self._device:
            out["code"], out["url"] = self._device.user_code, self._device.verification_url
        if self._qr:
            out["qr"] = self._qr[1].qr_url
        return out

    async def _drop_qr(self):
        if self._qr:
            await self._qr[0].close()
            self._qr = None

    def login_wait(self):
        from ya_passport_auth import PassportClient

        device, qr = self._device, self._qr
        if device is None and qr is None:
            return False

        async def by_device():
            async with PassportClient.create() as client:
                return await client.poll_device_until_confirmed(device)

        async def wait():
            tasks = []
            if device:
                tasks.append(asyncio.ensure_future(by_device()))
            if qr:
                tasks.append(asyncio.ensure_future(
                    qr[0].poll_qr_until_confirmed(qr[1], total_timeout=600)))
            creds = None
            try:
                while tasks and creds is None:
                    done, pending = await asyncio.wait(tasks,
                                                       return_when=asyncio.FIRST_COMPLETED)
                    tasks = list(pending)
                    for task in done:
                        if creds is None and not task.exception():
                            creds = task.result()
                if creds is None:
                    raise RuntimeError("not confirmed")
            finally:
                for task in tasks:
                    task.cancel()
                await self._drop_qr()
            login = ""
            try:
                async with PassportClient.create() as client:
                    info = await client.fetch_account_info(creds.x_token)
                    login = info.display_login or ""
            except Exception:
                pass
            return creds, login

        try:
            creds, login = self._run(wait(), timeout=700)
        finally:
            self._device = None
        self._save({
            "x_token": creds.x_token.get_secret(),
            "music_token": creds.music_token.get_secret() if creds.music_token else "",
            "refresh_token": creds.refresh_token.get_secret() if creds.refresh_token else "",
            "uid": creds.uid,
            "login": login or creds.display_login or "",
        })
        self._client = None
        return True

    def logout(self):
        try:
            os.unlink(ACCOUNT)
        except OSError:
            pass
        self._client = None
        self._radio = {}

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
        """The client, made once however many ask for it at the same time."""
        if self._client is not None:
            return self._client
        if self._connecting is None:
            self._connecting = asyncio.ensure_future(self._connect())
        try:
            return await self._connecting
        finally:
            self._connecting = None

    async def _connect(self):
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

    # --- what there is to play ---------------------------------------------
    @staticmethod
    def _mix(category):
        """This day's tag of a category, a different one each day."""
        tags = next(t for c, _n, t in TAGS if c == category)
        return tags[datetime.date.today().toordinal() % len(tags)]

    def home(self):
        mood, activity = self._mix("mood"), self._mix("activity")
        season = SEASONS[datetime.date.today().month]
        return [
            {"id": "wave", "title": "Моя волна"},
            {"id": "mine", "title": "Моя коллекция"},
            {"id": "feed", "title": "Для вас"},
            {"id": "chart", "title": "Чарт", "list": "chart"},
            {"id": "new_releases", "title": "Новые релизы"},
            {"id": "new_playlists", "title": "Новые плейлисты"},
            {"id": "tag:top", "title": "Лучшее"},
            {"id": "tag:" + mood[0], "title": "Настроение: " + mood[1]},
            {"id": "tag:" + activity[0], "title": "Занятие: " + activity[1]},
            {"id": "tag:" + season, "title": "Сезон: " + SEASON_NAMES[season]},
        ]

    def home_row(self, row_id):
        if row_id == "wave":
            return self._waves()
        if row_id == "mine":
            return [_item("list", self.likes_list, "Мне нравится", glyph="♥")] + self._run(self._mine())
        if row_id == "chart":
            return self.tracks("chart")[:ROW_MAX]
        return self.browse(row_id)[:ROW_MAX]

    @staticmethod
    def _waves():
        return [_item("radio", WAVE, "Моя волна")] + [
            _item("radio", "%s#%s" % (WAVE, mode), name, glyph=sign)
            for mode, name, _s, sign in MODES]

    async def _playlists_of_mine(self):
        """One's own playlists, then the ones one likes."""
        api = await self._api()
        own, likes = await asyncio.gather(api.users_playlists_list(),
                                          api.users_likes_playlists())
        own, liked = own or [], [like.playlist for like in likes or []]
        return _some(map(_playlist, own + liked))

    async def _albums_of_mine(self):
        api = await self._api()
        return _some(_album(like.album) for like in await api.users_likes_albums() or [])

    def _mine(self):
        async def get():
            playlists, albums = await asyncio.gather(self._playlists_of_mine(),
                                                     self._albums_of_mine())
            return playlists + albums

        return get()

    async def _playlists(self, ids):
        api = await self._api()
        return _some(map(_playlist, await api.playlists_list(ids) or [])) if ids else []

    async def _station_list(self):
        if self._stations is None:
            api = await self._api()
            self._stations = await api.rotor_stations_list("ru") or []
        return self._stations

    def browse(self, folder_id):
        async def get():
            api = await self._api()
            if not folder_id:
                return [_item("radio", WAVE, "Моя волна"),
                        _item("folder", "modes", "Режимы волны", glyph="≋"),
                        _item("folder", "feed", "Для вас", glyph="★"),
                        _item("folder", "collection", "Коллекция", glyph="♥"),
                        _item("folder", "radio", "Радио", glyph="◉"),
                        _item("folder", "picks", "Подборки", glyph="☰")]
            if folder_id == "modes":
                return self._waves()[1:]
            if folder_id == "feed":
                feed = await api.feed()
                return _some(_playlist(g.data) for g in (feed.generated_playlists or [])
                             if g.ready and g.data) if feed else []
            if folder_id == "collection":
                return [_item("list", self.likes_list, "Мне нравится", glyph="♥"),
                        _item("folder", "playlists", "Мои плейлисты"),
                        _item("folder", "albums", "Мои альбомы", glyph="◎"),
                        _item("folder", "artists", "Мои исполнители", glyph="☻")]
            if folder_id == "playlists":
                return await self._playlists_of_mine()
            if folder_id == "albums":
                return await self._albums_of_mine()
            if folder_id == "artists":
                return _some(_artist(like.artist)
                             for like in await api.users_likes_artists() or [])
            if folder_id == "radio":
                return [_item("folder", "stations:" + kind, name) for kind, name in STATIONS]
            if folder_id.startswith("stations:"):
                kind = folder_id.split(":", 1)[1]
                out = []
                for res in await self._station_list():
                    st = res.station
                    if not st or not st.id or st.id.type != kind or st.parent_id:
                        continue
                    icon = st.full_image_url or (st.icon.image_url if st.icon else None)
                    out.append(_item("radio", "%s:%s" % (kind, st.id.tag), st.name or st.id.tag,
                                     "", _cover(icon)))
                return out
            if folder_id == "picks":
                return [_item("folder", "picks:" + c, name) for c, name, _t in TAGS]
            if folder_id.startswith("picks:"):
                category = folder_id.split(":", 1)[1]
                tags = next((t for c, _n, t in TAGS if c == category), [])
                return [_item("folder", "tag:" + slug, name) for slug, name in tags]
            if folder_id.startswith("tag:"):
                res = await api.tags(folder_id.split(":", 1)[1])
                ids = ["%s:%s" % (p.uid, p.kind) for p in (res.ids if res else [])]
                return await self._playlists(ids[:LIST_MAX])
            if folder_id == "new_releases":
                res = await api.new_releases()
                ids = [str(x) for x in (res.new_releases if res else [])[:ROW_MAX]]
                return _some(map(_album, await api.albums(ids) or [])) if ids else []
            if folder_id == "new_playlists":
                res = await api.new_playlists()
                ids = ["%s:%s" % (p.uid, p.kind)
                       for p in (res.new_playlists if res else [])[:ROW_MAX]]
                return await self._playlists(ids)
            if folder_id.startswith("artist:"):
                artist = folder_id.split(":", 1)[1]
                res = await api.artists_direct_albums(artist, page_size=50)
                return ([_item("list", "artist_tracks:" + artist, "Популярные треки")]
                        + _some(map(_album, res.albums if res else [])))
            return []

        return self._run(get())

    def tracks(self, collection_id):
        async def get():
            api = await self._api()
            ids = []
            if collection_id == self.likes_list:
                likes = await api.users_likes_tracks()
                ids = [t.track_id for t in (likes.tracks if likes else [])[:LIST_MAX]]
            elif collection_id == "chart":
                res = await api.chart()
                return _tracks(t.track for t in (res.chart.tracks or [])[:LIST_MAX]
                               if t.track) if res and res.chart else []
            elif collection_id.startswith("playlist:"):
                uid, kind = collection_id.split(":")[1:3]
                pl = await api.users_playlists(kind, user_id=uid)
                short = (pl.tracks or [])[:LIST_MAX] if pl else []
                if short and all(t.track for t in short):
                    return _tracks(t.track for t in short)  # they came with the list
                ids = [t.track_id for t in short]
            elif collection_id.startswith("album:"):
                album = await api.albums_with_tracks(collection_id.split(":", 1)[1])
                return _tracks(t for volume in (album.volumes or []) for t in volume) if album else []
            elif collection_id.startswith("artist_tracks:"):
                res = await api.artists_tracks(collection_id.split(":", 1)[1], page_size=LIST_MAX)
                return _tracks(res.tracks if res else [])
            if not ids:
                return []
            return _tracks(await api.tracks(ids))

        return self._run(get())

    def radio_next(self, collection_id, last_track):
        async def get():
            api = await self._api()
            state = self._radio.get(collection_id)
            res = None
            if state and last_track:
                try:
                    res = await api.rotor_session_tracks(state["session"],
                                                         queue=[last_track["id"]])
                except Exception:
                    res = None  # the session is gone: a new one follows
            if not res or not res.sequence:
                station, _, mode = collection_id.partition("#")
                seeds = [station] + ([SEEDS[mode]] if mode in SEEDS else [])
                res = await api.rotor_session_new(
                    seeds, queue=[last_track["id"]] if last_track else None,
                    include_tracks_in_response=True, include_wave_model=True, interactive=True)
                if not res or not res.radio_session_id:
                    return []
                state = self._radio[collection_id] = {"session": res.radio_session_id,
                                                      "batch": res.batch_id}
                await self._event(api, state, "radioStarted")
            if res.batch_id:
                state["batch"] = res.batch_id
            return _tracks(s.track for s in res.sequence or [])

        return self._run(get())

    def search(self, query):
        """Tracks and playlists. Playlists come first when the service takes
        one for the best match, else after the first few tracks."""
        async def get():
            api = await self._api()
            res, more = await asyncio.gather(api.search(query, type_="all"),
                                             api.search(query, type_="playlist"))
            tracks = _tracks(res.tracks.results if res and res.tracks else [])
            found = more.playlists.results if more and more.playlists else []
            playlists = _some(_playlist(p) for p in found[:SEARCH_LISTS])
            if res and res.best and res.best.type == "playlist":
                return playlists + tracks
            return tracks[:SEARCH_FIRST] + playlists + tracks[SEARCH_FIRST:]

        return self._run(get())

    def stream_url(self, track, quality="low"):
        quality, codecs = QUALITY.get(quality, QUALITY["low"])

        async def get():
            api = await self._api()
            info = await api.tracks_file_info(track["id"], quality=quality, codecs=codecs,
                                              transport="raw")
            if not info or not info.download_info or not info.download_info.url:
                raise RuntimeError("no stream for this track")
            if getattr(info.download_info, "key", None):
                raise RuntimeError("the stream is encrypted")
            return info.download_info.url

        return self._run(get())

    # --- what one likes ------------------------------------------------------
    def liked(self):
        async def get():
            api = await self._api()
            likes = await api.users_likes_tracks()
            return {str(t.id) for t in (likes.tracks if likes else [])}

        return self._run(get())

    def like(self, track, on):
        async def send():
            api = await self._api()
            if on:
                await api.users_likes_tracks_add(track["id"])
            else:
                await api.users_likes_tracks_remove(track["id"])

        self._run(send())

    @staticmethod
    async def _event(api, state, kind, track=None, seconds=None):
        from yandex_music import SessionEvent

        event = SessionEvent(type=kind, timestamp=_now(),
                             track_id=track["id"] if track else None,
                             total_played_seconds=int(seconds) if seconds is not None else None)
        try:
            await api.rotor_session_feedback(state["session"], event, batch_id=state["batch"])
        except Exception:
            pass  # feedback only tunes the recommendations

    def feedback(self, collection_id, event, track, seconds):
        state = self._radio.get(collection_id)
        kind = {"start": "trackStarted", "finish": "trackFinished", "skip": "skip"}.get(event)
        if not state or not kind:
            return

        async def send():
            api = await self._api()
            await self._event(api, state, kind, track, None if event == "start" else seconds)

        try:
            self._run(send())
        except Exception:
            pass


SOURCE = Yandex()
