# SPDX-License-Identifier: GPL-2.0
"""Writes python3-requirements.yml, the Flatpak module of the Python
libraries of requirements.txt, from PyPI: python3 packaging/flatpak/requirements.py
"""
import json
import os
import urllib.request

SKIP = {"python-mpv"}  # haltia-kit's module brings it
SDIST = {"aiohttp", "PySocks"}  # aiohttp without its C parts; PySocks has a py27 wheel only
# Built ones (Rust or C): the runtime's Python's x86_64 wheels, the only
# arch the Flatpak is built for.
BINARY = {"cryptography", "cffi", "orjson", "zeroconf"}
PYTHON = "cp314"
# zeroconf 0.147 has no wheel for the runtime's Python 3.14: a later one.
VERSION = {"zeroconf": "0.151.5"}
HERE = os.path.dirname(os.path.abspath(__file__))
reqs = [l.split("#")[0].strip() for l in open(os.path.join(HERE, "..", "..", "requirements.txt"))]
reqs = [r for r in reqs if r and "@" not in r]
names, sources = [], []
for r in reqs:
    name, ver = r.split("==")
    name = name.split("[")[0]
    if name in SKIP:
        continue
    ver = VERSION.get(name, ver)
    d = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json"))
    if name in SDIST:
        def want(u):
            return u["packagetype"] == "sdist"
    elif name in BINARY:
        def want(u):
            f = u["filename"]
            return (f.endswith(".whl") and "manylinux" in f and "x86_64" in f
                    and (f"-{PYTHON}-{PYTHON}-" in f or "-abi3-" in f))
    else:
        def want(u):
            return u["filename"].endswith("-none-any.whl")
    u = next(u for u in d["urls"] if want(u))
    names.append(name)
    sources.append((u["url"], u["digests"]["sha256"]))
out = ["# The Python libraries of requirements.txt (but python-mpv, which comes",
       "# with haltia-kit): aiohttp and PySocks from their source (aiohttp without",
       "# its C parts), cryptography, cffi, orjson and zeroconf as x86_64 wheels",
       "# for the runtime's Python, the rest as their py3-none-any wheels. Written",
       "# by requirements.py; run it again when requirements.txt changes.",
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
