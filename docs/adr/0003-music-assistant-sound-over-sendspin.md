# Music Assistant's sound over Sendspin

Date: 2026-10-20. Status: accepted.

## Context

Music Assistant gives a full track's audio only to one of its players: `/single/` and `/flow/`
URLs exist for a queue item of a registered player, and `/preview` is 30 seconds. Музыка needs
the sound on the device it runs on. Two ways were weighed:

- the program becomes an MA player over Sendspin, MA's own playback protocol (as MA's desktop
  app, Ensemble and MassDroid do);
- a Haltia player provider installed into MA, in the manner of ma-provider-msx-bridge, handing
  the program per-track `/single/` URLs with an HMAC token, so mpv plays them as it plays Яндекс.

## Decision

Sendspin, with the provider kept as the fallback if the spike fails on the tablet.

## Why

- Музыка ships as Flatpak and deb for anyone, and anyone has a stock MA server. A third-party MA
  provider has no store: it is copied into the server's code, or must be accepted upstream.
- The provider would keep mpv and leave the tablet little work, but every person would install
  and update server code for one client.
- Sendspin costs the program a client (`aiosendspin`, Python ≥ 3.12, cryptography) and feeding
  its stream to the speakers; the spike measures that on the tablet.

Revisit if the spike shows the tablet cannot keep up, or Sendspin's "technical preview" breaks
clients between MA releases.
