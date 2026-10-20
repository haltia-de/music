# Context

The words this project uses for what it does.

- **Source** — a music service (`sources/`): Яндекс Музыка, Music Assistant planned. Its
  interface is the docstring of `sources/__init__.py`. Every track, kept answer and heart
  belongs to one; playing and liking go to the track's own Source.
- **Switched on / off** — whether a Source is offered at all, set in the settings as in Видео.
  Switching one off keeps its sign-in and answers.
- **Shown source** — the one switched-on Source the home page, Обзор and search show; one at a
  time, changed from the header. Signing in is per Source, several at once.
- **Sources** — the Sources with what each keeps apart (`sources/__init__.py`): its Answers and
  Likes, switched on or off, its quality, and which is shown. One Answers file and one Likes per
  Source.
- **Answers** — what the source said, kept (`answers.py`): a page shows them at once and they
  are asked for again when older than a quarter of an hour.
- **Likes** — the tracks one likes (`likes.py`); a heart shows the last tap at once and the
  service is told after.
- **Session** — what plays: one per window, and the window and MPRIS talk only to the one
  playing. Two kinds behind one interface: the program's own (`playback.py`: a queue taken from
  a list or a radio, the track playing, and what the source is told about it), used for
  Яндекс; and a mirror of a Music Assistant queue, where the server holds the queue, the radio
  and the service's feedback, commands go to it and its events say what plays.
- **Queue** — the session's tracks (on Music Assistant, the server's queue of this device's
  player, which other clients may change too). A list's queue is fixed; a radio's grows.
- **Radio** — a list without an end: the source hands out batches as it plays (a rotor session
  on Яндекс). Its page shows the first batch before anything plays.
- **Skip / finish** — leaving a track that played its sound before its end, paused or not / playing
  it to its end. Only a radio tells the source.
- **Give way** — a track that does not play is silent for a moment, then the next one plays,
  unless one chose another meanwhile.
