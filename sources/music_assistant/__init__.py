# SPDX-License-Identifier: GPL-2.0
"""Music Assistant: a server of one's own that brings many services (Яндекс,
Spotify, Tidal, files, radio) into one library and plays to any player.
Here the program is one of its players: what it plays is the server's queue
of this device (see queue.py), its sound comes over Sendspin (sound.py).

Signing in is a form: the server's address (servers found on the network
are offered), then a name and password, from which a token that lasts a
year is made, or a token made in the server's settings. The address, the
token and the device's Sendspin key are kept by vault.py (the keyring, or
~/.local/share/haltia-music/music_assistant.json).

The home page is the server's own (music/recommendations, the rows it shows
by default); Обзор its browse tree with Избранное (the favourite tracks)
first; hearts are its favourites, which it passes on to the service where
it can. Everything runs on the sources' loop through one connection
(client.py), which comes back by itself after a drop.
"""
import asyncio
import base64
import os
import socket

from gi.repository import GLib

import vault

from .. import loop
from . import items

# Without aiohttp, or without Sendspin's libraries, there is no SOURCE: the
# source is left out.
try:
    from . import client
except ImportError:
    client = None
try:
    import aiosendspin.client  # noqa: F401  the sound needs it
    SENDSPIN = True
except ImportError:
    SENDSPIN = False

ACCOUNT = os.path.join(GLib.get_user_data_dir(), "haltia-music", "music_assistant.json")
VAULT = vault.Vault("music_assistant", ACCOUNT,
                    vault.keyring("io.github.haltia_de.Music", "Музыка"))
LIKES = "favorites"
# A favourite the library lacks is added to it first, which may take the
# server more than a minute (it looks the track up).
LIKE_TIMEOUT = 300
LIST_MAX = 500
SEARCH_MAX = 20
FIND_SECONDS = 2  # how long the network is listened to for servers


def _name():
    return "Музыка (%s)" % (socket.gethostname() or "Haltia")


def _address(text):
    text = (text or "").strip().rstrip("/")
    if text and "://" not in text:
        text = "http://" + text
    return text


def found_servers(seconds=FIND_SECONDS):
    """[(address, name)] of the Music Assistant servers that answer on the
    local network (mDNS _mass._tcp); [] without zeroconf."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:
        return []
    found = {}

    class Listener:
        def add_service(self, zc, kind, name):
            info = zc.get_service_info(kind, name, timeout=1000)
            if not info:
                return
            props = {k.decode(): (v or b"").decode(errors="replace")
                     for k, v in (info.properties or {}).items()}
            addresses = info.parsed_addresses()
            url = props.get("base_url") or (
                "http://%s:%d" % (addresses[0], info.port) if addresses else "")
            if url:
                found[url] = props.get("name") or name.split(".")[0]

        def update_service(self, *_a):
            pass

        def remove_service(self, *_a):
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, "_mass._tcp.local.", Listener())
        GLib.usleep(int(seconds * 1000000))
    finally:
        zc.close()
    return sorted(found.items())


class MusicAssistant:
    id, label = items.SOURCE_ID, "Music Assistant"
    likes_list = LIKES
    experimental = True
    device_name = staticmethod(_name)

    def session(self, events, work, player):
        """What plays from here: the server's queue of this device (queue.py)."""
        from .queue import Queue
        return Queue(self, events, work, player)

    def __init__(self):
        self._client = None
        self._starting = None
        self._listeners = []  # event(name, object_id, data), on the loop's thread
        self._library = {}  # a favourite track's URIs -> its library id

    # --- the account ------------------------------------------------------
    @staticmethod
    def _saved():
        saved = VAULT.load()
        return dict(saved) if saved else None

    def logged_in(self):
        saved = self._saved()
        return bool(saved and saved.get("token") and saved.get("url"))

    def account(self):
        saved = self._saved() or {}
        host = saved.get("url", "").split("://")[-1]
        return " — ".join(p for p in (saved.get("user"), host) if p)

    @property
    def url(self):
        return (self._saved() or {}).get("url", "")

    def key(self):
        """The device's Sendspin private key, made once and kept with the account."""
        saved = self._saved() or {}
        if saved.get("key"):
            return base64.b64decode(saved["key"])
        raw = os.urandom(32)
        if saved:
            saved["key"] = base64.b64encode(raw).decode()
            VAULT.save(saved)
        return raw

    def login_start(self):
        saved = self._saved() or {}
        return {"kind": "form", "note": "", "fields": [
            {"id": "url", "label": "Адрес сервера", "secret": False,
             "value": saved.get("url", ""),
             "choices": [(url, name) for url, name in found_servers()]},
            {"id": "login", "label": "Имя пользователя", "secret": False, "value": ""},
            {"id": "password", "label": "Пароль", "secret": True, "value": ""},
            {"id": "token", "label": "или токен из настроек сервера", "secret": True,
             "value": ""}]}

    def login_next(self, values):
        url = _address(values.get("url"))
        if not url:
            raise ValueError("Укажите адрес сервера.")
        token = (values.get("token") or "").strip()
        try:
            if not token:
                if not values.get("login") or not values.get("password"):
                    raise ValueError("Укажите имя и пароль или токен.")
                token = loop.run(client.sign_in(url, values["login"], values["password"],
                                                _name()))
            user = loop.run(self._try(url, token))
        except client.Refused:
            raise PermissionError("Токен не подходит." if values.get("token")
                                  else "Неверное имя или пароль.")
        except (ConnectionError, OSError):
            raise ConnectionError("Нет связи с сервером %s." % url)
        loop.run(self._drop())
        old = self._saved() or {}
        VAULT.save({"url": url, "token": token, "user": user,
                    "key": old.get("key") if old.get("url") == url else None})
        return True

    @staticmethod
    async def _try(url, token):
        c = client.Client(url, token)
        try:
            await c.start()
            return c.user
        finally:
            await c.close()

    def logout(self):
        loop.run(self._drop())
        VAULT.delete()
        self._library = {}

    # --- the connection -----------------------------------------------------
    def listen(self, func):
        """func(name, object_id, data) for each of the server's events."""
        self._listeners.append(func)

    def _event(self, name, object_id, data):
        for func in list(self._listeners):
            func(name, object_id, data)

    def _state(self, on):
        self._event("connection", None, on)

    async def api(self):
        """The connection, made once however many ask at the same time."""
        if self._client is not None:
            return self._client
        if self._starting is None:
            saved = self._saved()
            if not saved:
                raise RuntimeError("not signed in")
            c = client.Client(saved["url"], saved["token"], self._event, self._state)

            async def start():
                try:
                    await c.start()
                except BaseException:
                    await c.close()
                    raise
                finally:
                    self._starting = None
                self._client = c
                return c
            self._starting = asyncio.ensure_future(start())
        # One caller giving up does not give up for the others.
        return await asyncio.shield(self._starting)

    async def _drop(self):
        if self._client is not None:
            await self._client.close()
            self._client = None

    def call(self, command, timeout=client.TIMEOUT if client else 60, **args):
        async def go():
            return await (await self.api()).call(command, timeout=timeout, **args)
        return loop.run(go(), timeout + 10)

    def base(self):
        return self.url

    # --- what there is to play ---------------------------------------------
    def home(self):
        rows = self.call("music/recommendations")
        return [{"id": "%s|%s" % (r["provider"], r["item_id"]), "title": r.get("name") or ""}
                for r in rows or [] if r.get("enabled_by_default")]

    def home_row(self, row_id):
        provider, _sep, item_id = row_id.partition("|")
        found = self.call("music/recommendations/items", provider=provider, item_id=item_id)
        return items.items(found, self.base())

    def browse(self, folder_id):
        found = items.items(self.call("music/browse", path=folder_id or None), self.base())
        if not folder_id:
            found.insert(0, {"kind": "list", "id": LIKES, "title": "Избранное",
                             "subtitle": "", "cover": "", "glyph": "♥"})
        return found

    def tracks(self, list_id):
        if list_id == LIKES:
            found = self.call("music/tracks/library_items", favorite=True, limit=LIST_MAX)
        else:
            provider, kind, item_id = items.uri(list_id)
            command = {"playlist": "music/playlists/playlist_tracks",
                       "album": "music/albums/album_tracks",
                       "artist": "music/artists/artist_tracks"}.get(kind)
            if command is None:
                return []
            args = {"item_id": item_id, "provider_instance_id_or_domain": provider}
            if kind == "playlist":
                args["limit"] = LIST_MAX
            found = self.call(command, **args)
        return [items.track(t, self.base()) for t in found or []
                if t.get("media_type") == "track"]

    def radio_next(self, radio_id, last_track):
        """A radio's first tracks, to show its page; the server's queue then
        grows by itself, so later batches are none."""
        if last_track is not None:
            return []
        _provider, kind, _item_id = items.uri(radio_id)
        if kind == "playlist":
            return self.tracks(radio_id)[:30]
        found = self.call("music/item_by_uri", uri=radio_id)
        return [{"kind": "track", "source": self.id, "id": radio_id,
                 "title": found.get("name") or "", "artist": "", "duration": None,
                 "cover": items.image(found, self.base())}]

    def search(self, query):
        found = self.call("music/search", search_query=query, limit=SEARCH_MAX,
                          media_types=["track", "playlist", "album", "artist", "radio"])
        base = self.base()
        out = []
        for kind in ("tracks", "playlists", "albums", "artists", "radio"):
            out.extend(items.items((found or {}).get(kind), base))
        return out

    def stream_url(self, track, quality=""):
        return ""  # the server plays to this device itself

    # --- what one likes -----------------------------------------------------
    def liked(self):
        found = self.call("music/tracks/library_items", favorite=True, limit=LIST_MAX)
        library = {}
        for t in found or []:
            library[t["uri"]] = t["item_id"]
            for m in t.get("provider_mappings") or []:
                library["%s://track/%s" % (m.get("provider_instance"), m.get("item_id"))] = \
                    t["item_id"]
        self._library = library
        return set(library)

    def like(self, track, on):
        uri = track["id"]
        if on:
            self.call("music/favorites/add_item", item=uri, timeout=LIKE_TIMEOUT)
            return
        library_id = self._library.get(uri)
        if library_id is None:
            self.liked()  # liked elsewhere since
            library_id = self._library.get(uri)
        if library_id is None:
            raise RuntimeError("not among the favourites")
        self.call("music/favorites/remove_item", media_type="track",
                  library_item_id=library_id)


SOURCE = MusicAssistant() if client and SENDSPIN else None
