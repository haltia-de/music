# SPDX-License-Identifier: GPL-2.0
"""Writes python3-requirements.yml, the Flatpak module of the Python
libraries of requirements.txt, from PyPI: python3 packaging/flatpak/requirements.py
"""
import json
import os
import urllib.request

SKIP = {"python-mpv"}  # haltia-kit's module brings it
SDIST = {"aiohttp", "PySocks"}  # aiohttp without its C parts; PySocks has a py27 wheel only
HERE = os.path.dirname(os.path.abspath(__file__))
reqs = [l.split("#")[0].strip() for l in open(os.path.join(HERE, "..", "..", "requirements.txt"))]
reqs = [r for r in reqs if r and "@" not in r]
names, sources = [], []
for r in reqs:
    name, ver = r.split("==")
    name = name.split("[")[0]
    if name in SKIP:
        continue
    d = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json"))
    want = (lambda u: u["packagetype"] == "sdist") if name in SDIST else \
        (lambda u: u["filename"].endswith("-none-any.whl"))
    u = next(u for u in d["urls"] if want(u))
    names.append(name)
    sources.append((u["url"], u["digests"]["sha256"]))
out = ["# The Python libraries of requirements.txt (but python-mpv, which comes",
       "# with haltia-kit), pure Python: aiohttp and PySocks from their source (aiohttp",
       "# without its C parts), the rest as their py3-none-any wheels. Written by",
       "# requirements.py; run it again when requirements.txt changes.",
       "name: python3-requirements",
       "buildsystem: simple",
       "build-options:",
       "  env:",
       "    AIOHTTP_NO_EXTENSIONS: '1'",
       "build-commands:",
       "  - pip3 install --verbose --exists-action=i --no-index --find-links=\"file://${PWD}\"",
       "    --prefix=${FLATPAK_DEST} --no-build-isolation --no-deps " + " ".join(names),
       "sources:"]
for url, sha in sources:
    out += ["  - type: file", "    url: " + url, "    sha256: " + sha]
with open(os.path.join(HERE, "python3-requirements.yml"), "w") as fh:
    fh.write("\n".join(out) + "\n")
