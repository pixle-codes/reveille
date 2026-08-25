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
| `--adopt` | on mismatch, write pin `label -> journal counter` into `[labels.map]`, re-check same run; refuses on disagreeing existing pin |
| `--prune-stale` | remove pins that invert the label→counter order (retired-epoch leftovers); runs before `--adopt` |
| `--record FILE` | history ledger: append one JSON line per EFFECTIVE mutation (prune/adopt); best-effort — a broken path warns to stderr and never changes a verdict |
| `--history FILE` | read a ledger back instead of auditing: mutation count, newest age, per-label rollup (`#9 adopt -> s73` / `#5 pruned (=s62)`) |
| `--max-age-hours N` | with `--history`: exit 1 when the newest mutation is older than N hours (strictly-greater boundary); an EMPTY or missing-ledger run is never fresh |
| `--json` | machine output, fixed key order (`expected` v1.1.0, `adopted` v1.3.0, `pruned` v1.4.0 — each appended last) |
| `--statusline` | one-liner: `reveille s73 · 4d 23h left · standing: none` |

### Config

```toml
# ~/.config/reveille/config.toml
[sprint]
ends_at = 1787951442        # unix epoch

[labels]
base = 69                   # optional: journal counter = base + harness label

[labels.map]                # optional explicit pins, win over base
9 = 78
'#12' = 81                  # a leading # is tolerated (normalized at load)

[[item]]                     # fires when UTC date >= after (inclusive)
name = "assistout-post"
after = "2026-08-27"
note = "API died Aug 26 — post-deadline dogfood first"
```

No config file = defaults (no sprint clock, no items). Missing journal file or
malformed TOML = exit 2 — a broken input never fakes clean.

#### Label reconciliation

By default an injected label must equal the derived counter directly. That
breaks the moment your harness restarts its numbering (fresh epoch starts at
`#1` while your journal continues at s70+): every session would mismatch
forever and the alarm becomes noise. Configure `[labels] base = N` once per
harness epoch — label `#9` then reconciles against `s(N+9)` — or pin exact
pairs under `[labels.map]`. Pin keys may be written bare (`19 = 87`) or
`#`-prefixed (`'#19' = 87`); both forms are the same pin, and two keys that
normalize to the same label are a config error (exit 2), never a silent
pick. A mapped match is clean (exit 0); a wrong label,
wrong offset, or missing mapping still mismatches (exit 1), so the signal only
fires when something is genuinely off.

When the mismatch is just a missing pin (harness skipped numbers by dying
unlogged — the usual case), `--adopt` closes the loop in the same run: it
writes `<label> = <journal counter>` into `[labels.map]` (comments and other
sections preserved), re-checks, and exits 0 only if the adopted pin actually
reconciles. It refuses — exit 1, config untouched — when a pin for that label
already exists but disagrees, because overwriting it would fake the count;
resolve those by hand. Without a mismatch or a label it is a no-op.

```sh
python3 -m reveille --label "#23" --adopt   # writes 23 = 89, re-checks, exit 0
```

#### Retired-epoch pins (`--prune-stale`)

Pins are only meaningful inside ONE harness numbering epoch. If your harness
restarts its labels, pins from the retired epoch stay in `[labels.map]` and —
the moment the new epoch reissues those label numbers — block `--adopt`
forever with a refusal you can only resolve by archaeology. The mechanical
signature: within a live epoch, sorted by label, pin counters never decrease
(gaps are normal; decreases are impossible). A decrease proves the pin came
from a retired epoch.

- Every refusal on an existing pin now names how many pins invert that order
  and points at this flag.
- `--prune-stale` removes exactly the inverting pins (section-scoped,
  text-level edit — comments and other sections byte-preserved) and reports
  what was cut; it removes nothing else. Combined with `--adopt` a reused
  label re-adopts to the journal counter in one run (POST-state exit).
- A single non-inverted pin that merely disagrees is NOT stale: prune leaves
  it and adopt still refuses — genuine disagreement stays a human decision.

```sh
python3 -m reveille --label "#19" --adopt --prune-stale
# -> pruned 1 stale pin(s): #19=s87 ... pin adopted: #19 -> s103
```

`--json` appends `"pruned"` last when the flag is used; the statusline gains
a `N stale pruned` segment only when something was actually cut.

#### History ledger (`--record` / `--history`)

Adoptions and prunes are config mutations worth remembering: a point-in-time
briefing cannot say WHEN a pin was last touched or whether the map has gone
stale. `--record FILE.jsonl` appends one JSON line per EFFECTIVE mutation
(fixed key order — `ts/ts_utc/action/label/counter/config` for adopts,
`ts/ts_utc/action/removed/config` for prunes; prune-then-adopt in one run
writes two lines in that order). Refused adoptions and no-op runs record
nothing. The append is best-effort: an unwritable path warns
`could not write record` on stderr and never changes a verdict or exit code.

`reveille --history FILE.jsonl` reads the ledger back: mutation count,
newest-mutation age, and a per-label rollup (each label's LAST touching
event wins). Malformed/foreign lines are skipped and counted on stderr,
never fatal.

```sh
python3 -m reveille --history ~/.local/share/reveille/history.jsonl \
    --max-age-hours 168 --statusline
# -> reveille HISTORY: 12 mutation(s), newest 6.1h ago   (exit 0)
# -> reveille STALE: last mutation 200.4h ago            (exit 1)
```

Without `--max-age-hours` history is informational (exit 0). With it, the
boundary is strictly-greater and an empty ledger counts as NOT fresh —
absence of evidence is not health.

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
