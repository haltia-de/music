#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Install haltia-music (Музыка): sh install.sh [ROOT] [PREFIX]
# ROOT empty or / for this system; PREFIX /usr/local unless given (a
# package passes /usr). It needs Python 3 with PyGObject (GTK 3),
# the kit (github.com/haltia-de/kit), python-mpv with libmpv, aiohttp,
# aiofiles, yarl, requests, typing-extensions, libsecret (the keyring, if
# any), and qrcode for signing in by a QR code; for Music Assistant also
# cryptography, orjson and zeroconf (without them that source is left out).
# The Yandex libraries and Music Assistant's pure Python ones come as
# pinned wheels (below). The
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
lib=$root$prefix/lib/haltia-music
rm -rf "$lib"
for f in answers likes mpris playback vault; do
	install -D -m 644 "$here/$f.py" "$lib/$f.py"
done
for f in "$here"/sources/*.py "$here"/sources/*/*.py; do
	install -D -m 644 "$f" "$lib/sources/${f#"$here"/sources/}"
done
install -D -m 644 "$here/data/$app.desktop" "$share/applications/$app.desktop"
install -D -m 644 "$here/data/$app.svg" "$share/icons/hicolor/scalable/apps/$app.svg"
install -D -m 644 "$here/data/$app.metainfo.xml" "$share/metainfo/$app.metainfo.xml"
# What b8k-music (before 2.0) installed under this prefix, the names kept
# for it until 3.0, and the shell's old entry from before the .desktop file.
rm -rf "$root$prefix/lib/b8k-music" "$root$prefix/bin/b8k-music" \
	"$share/applications/$old.desktop" \
	"$share/icons/hicolor/scalable/apps/$old.svg" "$share/metainfo/$old.metainfo.xml" \
	"$root/usr/local/share/b8k/apps.d/music.conf" "$root/usr/local/share/b8k/music.svg"
# yandex-music (LGPL-3.0, MarshalX) and ya-passport-auth (MIT), and for Music
# Assistant aiosendspin (Apache-2.0), cpace (MIT), noiseprotocol (MIT) and
# mashumaro (Apache-2.0): the pinned wheels from PyPI, checked against their sha256 and unpacked next to the
# sources. HALTIA_CACHE keeps the downloads between
# builds. HALTIA_WHEELS=no leaves them to the package (Flatpak installs
# them with pip).
[ "${HALTIA_WHEELS:-}" = no ] && exit 0
cache=${HALTIA_CACHE:-$here/.cache}
mkdir -p "$cache"
while read -r sum url; do
	whl=${url##*/}
	[ -f "$cache/$whl" ] || wget -q -O "$cache/$whl" "$url"
	echo "$sum  $cache/$whl" | sha256sum -c -
	unzip -q -o "$cache/$whl" -d "$lib" -x '*.dist-info/*' 'examples/*'
done <<'WHEELS'
f13f42125d10eab5e8e488bbaf1efd4b3bd9c2cc4d62a82280b6e4db8184c4a8 https://files.pythonhosted.org/packages/9a/06/b777ad29f3d5a8b6c7a4a337670569bf12e0b1f1975489a1041e8ed006af/yandex_music-3.2.1-py3-none-any.whl
1fb62ad7a01194b74013138d2c73be5342ac3875bbed862041fa1da7c29ed301 https://files.pythonhosted.org/packages/bc/f6/23b7d8559bdf841f171f94008113e88fc286d3965fdb925c6692c7701655/ya_passport_auth-1.8.0-py3-none-any.whl
cb7227f70a8c6cfea450fb92ad26ed6fe3d86e883620700e2cde9372ad8c995b https://files.pythonhosted.org/packages/f4/c8/e6bb6ece16ef74a3867543675a153cb09b10eb907025e8d77ac4db547bc4/aiosendspin-9.1.1-py3-none-any.whl
9fabb60a711a85934225be4081b3f5994e1ca4cd1335c5b9171770c8f1a2fda3 https://files.pythonhosted.org/packages/fa/e8/949c45844ad0d65d0112c2c4fa11cc8a7c4359fe2a20667e00c930860bef/cpace-0.1.0-py3-none-any.whl
2e1a603a38439636cf0ffd8b3e8b12cee27d368a28b41be7dbe568b2abb23111 https://files.pythonhosted.org/packages/9d/e1/76e4694201d67b93a6f1644b2588b4a3d965419fe189416e3496cf415db5/noiseprotocol-0.3.1-py3-none-any.whl
a671279ce93119d41c54adcd767753ae68adb32b9473de2f9d5d1720d2376231 https://files.pythonhosted.org/packages/4e/eb/2c5e2b0df54c9c979d45bfa4820687ab24797fe1ad42d4fdfc0c8ece59f1/mashumaro-3.23-py3-none-any.whl
WHEELS
