# 10. Stable window ids across server restarts

**Status:** done. Ids are now hashed from `(pid, object path)`; see the decision in `docs/design/wayland.md`. No agent integration caches ids (checked `agents/`), but a client that kept an id across a restart was the real risk: with a counter, id 1 could name a different window afterwards.
**Depends on:** nothing

## Goal
Decide whether Wayland window ids should survive a server restart. Today they are
per-session counters keyed by `(pid, AT-SPI object path)`.

## Options
- Keep per-session ids. Clients already call `list_windows` after connecting. Simplest.
- Derive ids from a hash of `(pid, object path)`. These are stable while the app
  runs, but large numbers and collisions are possible.
- Persist the mapping in the session dir. More state, little gain.

## Steps
1. Check whether any agent integration (`src/python/linux_computer_use/agents/`)
   caches window ids across reconnects.
2. Decide, record it in the design doc, and implement if needed, with unit tests in `tests/unit/test_wayland.py`.

## Done when
The decision is recorded, and the code matches it.
