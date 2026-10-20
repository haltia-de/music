# Music Assistant holds its queue

Date: 2026-10-20. Status: accepted.

## Context

`playback.Session` owns the queue: the tracks, the index, a radio's growth, start/finish/skip
feedback to the source, giving way. For Music Assistant the first proposal kept that, handing MA
one track at a time (a queue replaced by a single track) and growing radios from
`similar_tracks`.

## Decision

For Music Assistant the queue is MA's: the program sends `player_queues/*` commands and mirrors
the queue from its events. `Session` gets two kinds behind one interface; the program's own stays
for Яндекс.

## Why

- MA does what `Session` would redo, better: radio as a managed pool
  (`radio_playlist://`, the services' stations) with recency and artist spacing, Autoplay after a
  list, the services' feedback from its own providers (`on_played`; the Яндекс provider sends the
  rotor's), gapless, crossfade, smart shuffle, resume.
- One track at a time loses gapless and crossfade, and leaves MA's queue, which other clients
  (MA's web UI) show and change, out of step with the program.
- A queue that changes from outside is MA's normal case; the program shows what the events say.

Revisit if MA's queue cannot be mirrored well enough (events too coarse for the radio page), or a
second queue-holding service appears and the two kinds should become one.
