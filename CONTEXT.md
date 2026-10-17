# Context

The words this project uses for what it does.

- **Source** — a music service (`sources/`): Яндекс Музыка now. Its interface is the docstring
  of `sources/__init__.py`.
- **Answers** — what the source said, kept (`answers.py`): a page shows them at once and they
  are asked for again when older than a quarter of an hour.
- **Session** — what plays (`playback.py`): a queue taken from a list or a radio, the track
  playing, and what the source is told about it. One per window.
- **Queue** — the session's own tracks. A list's queue is fixed; a radio's grows.
- **Radio** — a list without an end: the source hands out batches as it plays (a rotor session
  on Яндекс). Its page shows the first batch before anything plays.
- **Skip / finish** — leaving a track that played its sound before its end, paused or not / playing
  it to its end. Only a radio tells the source.
- **Give way** — a track that does not play is silent for a moment, then the next one plays,
  unless one chose another meanwhile.
