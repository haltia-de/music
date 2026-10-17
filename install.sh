#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Install b8k-music into a root file system: sh install.sh [ROOT]
# (ROOT empty or / for this system). The tablet shell's build runs it for
# its image. It needs Python 3 with PyGObject (GTK 3), python-mpv with
# libmpv, aiohttp, aiofiles, yarl, requests and typing-extensions.
set -eu
root=${1:-}
root=${root%/}
here=$(cd "$(dirname "$0")" && pwd)
lib=$root/usr/local/lib/b8k-music
install -D -m 755 "$here/b8k-music" "$root/usr/local/bin/b8k-music"
rm -rf "$lib"
for f in "$here"/sources/*.py; do
	install -D -m 644 "$f" "$lib/sources/${f##*/}"
done
install -D -m 644 "$here/music.svg" "$root/usr/local/share/b8k/music.svg"
install -D -m 644 "$here/music.conf" "$root/usr/local/share/b8k/apps.d/music.conf"
# yandex-music (LGPL-3.0, MarshalX) and ya-passport-auth (MIT): the pinned
# wheels from PyPI, checked against their sha256 and unpacked next to the
# sources. B8K_CACHE keeps the downloads between builds.
cache=${B8K_CACHE:-$here/.cache}
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
