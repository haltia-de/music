# No id codec in the Yandex source

Date: 2026-10-18. Status: accepted.

## Context

`sources/yandex.py` builds item ids with prefixes (`playlist:<uid>:<kind>`, `album:<id>`,
`artist:<id>`, `stations:<type>`, `tag:<slug>`, `picks:<cat>`, `artist_tracks:<id>`, radio
`…#<mode>`) in its item helpers and parses them back in if-chains in `browse()`, `tracks()` and
`radio_next()`. An architecture review proposed a codec module (`make`/`parse`) with a
round-trip test.

## Decision

Keep the if-chains; no codec module.

## Why

- A codec would be shallow: parsing is `split(":", 1)`, so `make`/`parse` would be about as large
  as what it hides.
- The only test worth having ("every id `browse`/`home_row` hands out opens in `browse`/`tracks`")
  needs a fake `yandex_music.ClientAsync` returning its playlist, album, station, tag and landing
  objects: a large fake of a library we do not own, brittle across its versions.
- The bug it would catch (a mistyped prefix opens an empty folder) has not happened.

Revisit when a second source repeats the same prefix scheme, or when such a bug shows up.
