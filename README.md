# reveille

Session-start briefing compiler for journal-driven agent loops. One command
answers the three questions every session wastes minutes re-deriving by hand:

1. **Which session number am I really?** Harness briefing labels drift from the
   journal's own counter (`session #4` when the journal says s73). reveille
   reads your append-only markdown journal, takes MAX(session)+1 from block
   heads, and tells you if an injected label disagrees.
2. **How long until the sprint ends?** A human-readable countdown from a unix
   epoch in config or `--ends-at`.
3. **Do any date-gated standing directives fire today?** Conditional rules like
   "if we're past Aug 27, do X first" move out of prose into config that
   evaluates itself.

```
$ python3 -m reveille --label "#4" --now 1787522750 --ends-at 1787951442
next session: s73 (last logged s72)
briefing label #4 MISMATCHES the journal counter — journal is authoritative
sprint time left: 4d 23h
standing items: none fire today
$ echo $?
1
```

## Why

In five consecutive sessions of one real autonomous-build loop, the harness
injected a session label that disagreed with the journal counter, and each
session burned paragraphs of prose just proving which number it was. Labels
skip, reset, and lag; a hand-maintained journal is the source of truth — but
only if something computes it deterministically instead of archaeology every
start. Existing agent-session tools either mint their own counters for journals
they create or export transcript snapshots; none reconciles YOUR existing
journal against externally injected labels.

## Install

No dependencies. Python 3.13+ (stdlib only).

```sh
git clone https://github.com/pixle-codes/reveille.git
cd reveille
python3 -m reveille            # reads ~/journal/STATE.md by default
```

## Usage

```sh
python3 -m reveille [JOURNAL ...] [options]
```

| Flag | Meaning |
|---|---|
| `JOURNAL ...` | journal files (default `~/journal/STATE.md`; multiple are merged) |
| `--label N` | briefing label to reconcile (`#4` or `4`) |
| `--ends-at EPOCH` | sprint end unix seconds (overrides config) |
| `--config FILE` | TOML config (default `~/.config/reveille/config.toml`) |
| `--now EPOCH` | inject current time (tests/cron determinism) |
| `--json` | machine output, fixed key order |
| `--statusline` | one-liner: `reveille s73 · 4d 23h left · standing: none` |

### Config

```toml
# ~/.config/reveille/config.toml
[sprint]
ends_at = 1787951442        # unix epoch

[[item]]                     # fires when UTC date >= after (inclusive)
name = "assistout-post"
after = "2026-08-27"
note = "API died Aug 26 — post-deadline dogfood first"
```

No config file = defaults (no sprint clock, no items). Missing journal file or
malformed TOML = exit 2 — a broken input never fakes clean.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | clean (or no label given to reconcile) |
| 1 | label mismatch vs journal counter (alertable — cron/hook friendly) |
| 2 | usage error, missing/unreadable journal, malformed config |

### Session-number semantics

Only block heads matching `- **sNN` count (Completed-section style entries).
Inline references — `SHIPPED s71`, `NEXT-ME (s73)` — never count. Next =
**max + 1**, never count + 1: real journals develop gaps from numbering events,
and max survives them.

## Testing

```sh
python3 -m unittest discover -s tests -t .
```

## License

MIT
