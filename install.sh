#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Install haltia-music (Музыка): sh install.sh [ROOT] [PREFIX]
# ROOT empty or / for this system; PREFIX /usr/local unless given (a
# package passes /usr). It needs Python 3 with PyGObject (GTK 3),
# the kit (github.com/haltia-de/kit), python-mpv with libmpv, aiohttp,
# aiofiles, yarl, requests, typing-extensions, libsecret (the keyring, if
# any), and qrcode for signing in by
# a QR code; the Yandex libraries come as pinned wheels (below). The
# .desktop file shows it in any desktop's launcher; the Haltia shell puts
# it on its home screen (X-B8K-Home).
set -eu
root=${1:-}
root=${root%/}
prefix=${2:-/usr/local}
here=$(cd "$(dirname "$0")" && pwd)
share=$root$prefix/share
app=io.github.haltia_de.Music
old=io.github.trudenboy.Music  # b8k-music before 2.0
install -D -m 755 "$here/haltia-music" "$root$prefix/bin/haltia-music"
# The old command, until 3.0.
ln -sf haltia-music "$root$prefix/bin/b8k-music"
lib=$root$prefix/lib/haltia-music
rm -rf "$lib"
for f in answers likes mpris playback vault; do
	install -D -m 644 "$here/$f.py" "$lib/$f.py"
done
for f in "$here"/sources/*.py; do
	install -D -m 644 "$f" "$lib/sources/${f##*/}"
done
install -D -m 644 "$here/data/$app.desktop" "$share/applications/$app.desktop"
install -D -m 644 "$here/data/$app.svg" "$share/icons/hicolor/scalable/apps/$app.svg"
install -D -m 644 "$here/data/$app.metainfo.xml" "$share/metainfo/$app.metainfo.xml"
# The old id's .desktop file, hidden until 3.0: pins and links to it still
# start the program.
install -D -m 644 "$here/data/$old.desktop" "$share/applications/$old.desktop"
# What b8k-music (before 2.0) installed under this prefix, and the shell's
# old entry for it from before the .desktop file.
rm -rf "$root$prefix/lib/b8k-music" \
	"$share/icons/hicolor/scalable/apps/$old.svg" "$share/metainfo/$old.metainfo.xml" \
	"$root/usr/local/share/b8k/apps.d/music.conf" "$root/usr/local/share/b8k/music.svg"
# yandex-music (LGPL-3.0, MarshalX) and ya-passport-auth (MIT): the pinned
# wheels from PyPI, checked against their sha256 and unpacked next to the
# sources. HALTIA_CACHE (B8K_CACHE until 3.0) keeps the downloads between
# builds. HALTIA_WHEELS=no leaves them to the package (Flatpak installs
# them with pip).
[ "${HALTIA_WHEELS:-}" = no ] && exit 0
cache=${HALTIA_CACHE:-${B8K_CACHE:-$here/.cache}}
mkdir -p "$cache"
while read -r sum url; do
	whl=${url##*/}
	[ -f "$cache/$whl" ] || wget -q -O "$cache/$whl" "$url"
	echo "$sum  $cache/$whl" | sha256sum -c -
	unzip -q -o "$cache/$whl" -d "$lib" -x '*.dist-info/*'
done <<'WHEELS'
f13f42125d10eab5e8e488bbaf1efd4b3bd9c2cc4d62a82280b6e4db8184c4a8 https://files.pythonhosted.org/packages/9a/06/b777ad29f3d5a8b6c7a4a337670569bf12e0b1f1975489a1041e8ed006af/yandex_music-3.2.1-py3-none-any.whl
1fb62ad7a01194b74013138d2c73be5342ac3875bbed862041fa1da7c29ed301 https://files.pythonhosted.org/packages/bc/f6/23b7d8559bdf841f171f94008113e88fc286d3965fdb925c6692c7701655/ya_passport_auth-1.8.0-py3-none-any.whl
WHEELS
