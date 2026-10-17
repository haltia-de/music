# Pages stay dicts

Date: 2026-10-18. Status: accepted.

## Context

A page (`view`) in `b8k-music` is a dict: `make_page` puts its widgets in it (`page`, `list`,
`note`, `play`, `more`, `shown`, `hearts`, `alive`), and some kinds add their own keys (`rows`,
`sections`, `shows` for home; `choices` for settings; `focus`). An architecture review proposed
a class per page kind that owns its widgets and drops late answers itself.

## Decision

Keep the dicts. Callbacks that outlive what they fill check for it themselves (`alive`, and
`_home_row` checks that its section is still the row's).

## Why

- Pages live in GTK, so classes would add no tests; the playback, answers and likes modules,
  where the rules are, already have theirs.
- A class would mostly move the same widget code, so it would not get much deeper.
- The one real bug it pointed at (a home row filling a section destroyed when the rows changed)
  is a one-line check.

Revisit when the page kinds grow enough that a key set per kind is hard to keep in mind, or GTK
tests become possible.
