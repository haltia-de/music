# SPDX-License-Identifier: GPL-2.0
"""Music Assistant's media items as the program's items and tracks (see the
sources contract). No network: the shapes are those of the server's API.

An item's id is its MA URI (provider://type/id), a folder's its browse
path, a home row's "<provider>|<item_id>"; the source parses them back with
uri(). A dynamic playlist (the services' stations) and a radio station are
radios; a playlist, an album and an artist are lists; the rest the program
cannot play (podcasts, audiobooks) is left out.

image(item, base)       a cover URL for an item, or ""
track(item, base)       a track dict
item(item, base)        an item dict, a track, or None to leave it out
uri(text)               (provider, media type, item id) of an MA URI
uris(item)              every URI of an item: its own and its services' (a
                        library track is the same as its Яндекс one)
"""
from urllib.parse import quote

SOURCE_ID = "music_assistant"
SIZE = 256  # pixels the server's image proxy makes a cover
YANDEX_SIZE = 400  # pixels of a cover from Яндекс's own server


def image(item, base):
    found = item.get("image")
    if not found:
        images = (item.get("metadata") or {}).get("images") or []
        found = next((i for i in images if i.get("type") == "thumb"), images[0] if images else None)
    if not found:
        album = item.get("album") or {}
        found = album.get("image") if isinstance(album, dict) else None
    if not found:
        return ""
    if found.get("remotely_accessible") and found.get("path", "").startswith("http"):
        # Яндекс's covers come at 1000x1000; the service makes any size.
        if "avatars.yandex.net/" in found["path"]:
            return found["path"].replace("/1000x1000", "/%dx%d" % (YANDEX_SIZE, YANDEX_SIZE))
        return found["path"]
    if found.get("proxy_id"):
        return "%s/imageproxy/%s?size=%d" % (base.rstrip("/"), quote(found["proxy_id"]), SIZE)
    return ""


def _artists(item):
    return ", ".join(a.get("name", "") for a in item.get("artists") or [] if a.get("name"))


def track(item, base):
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    return {"kind": "track", "source": SOURCE_ID, "id": item["uri"],
            "title": item.get("name") or "", "artist": _artists(item),
            "album": album.get("name") or "", "duration": item.get("duration") or None,
            "cover": image(item, base)}


def _count(n):
    if not n:
        return ""
    if n % 10 == 1 and n % 100 != 11:
        return "%d трек" % n
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "%d трека" % n
    return "%d треков" % n


def item(found, base):
    kind = found.get("media_type")
    if kind == "track":
        return track(found, base)
    entry = {"title": found.get("name") or "", "cover": image(found, base), "subtitle": ""}
    if kind == "folder":
        if found.get("name") == "..":
            return None  # the way up: the program has ← for it
        entry.update(kind="folder", id=found.get("path") or found.get("uri") or "")
        entry["subtitle"] = found.get("subtitle") or ""
    elif kind == "playlist":
        dynamic = found.get("is_dynamic")
        entry.update(kind="radio" if dynamic else "list", id=found["uri"])
        entry["subtitle"] = ((found.get("metadata") or {}).get("description") or ""
                             if dynamic else found.get("owner") or "")
        if dynamic:
            entry["glyph"] = "∞"
    elif kind == "radio":
        entry.update(kind="radio", id=found["uri"], glyph="📻")
    elif kind == "album":
        entry.update(kind="list", id=found["uri"], subtitle=_artists(found))
    elif kind == "artist":
        entry.update(kind="list", id=found["uri"], glyph="♪")
    else:
        return None
    return entry


def items(found, base):
    out = [item(i, base) for i in found or []]
    return [i for i in out if i is not None]


def uris(found):
    out = {found.get("uri")}
    kind = found.get("media_type") or "track"
    for m in found.get("provider_mappings") or []:
        out.add("%s://%s/%s" % (m.get("provider_instance"), kind, m.get("item_id")))
    out.discard(None)
    return out


def uri(text):
    """(provider, media type, item id) of provider://type/id."""
    provider, _sep, rest = text.partition("://")
    kind, _sep, item_id = rest.partition("/")
    return provider, kind, item_id
