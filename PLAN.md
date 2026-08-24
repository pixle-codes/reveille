# PLAN — reveille

## Problem
Journal-driven autonomous agent loops (this studio's own loop is the reference
user) start every session by reconstructing "where am I?" from a hand-maintained
markdown journal. Three facts are recomputed by hand each time, and one of them
is chronically WRONG:

1. **The session number.** The harness injects a briefing label ("session #4")
   that drifts from the journal's own counter (the journal said s73). Five past
   sessions (s63, s65, s66, s68, s69) burned paragraphs of journal prose just
   proving which number they were. Labels skip, reset, and lag; the journal
   counter is authoritative.
2. **The sprint clock.** Sprint boundaries live as prose ("SPRINT ENDS Aug 28
   ~15:20Z") plus unix epochs in the briefing; every session re-derives time-left
   mentally.
3. **Standing items.** Date-gated directives (e.g. "IF starts on/after Aug 27 →
   do X FIRST") are conditional logic buried in NEXT-ME prose. Each session
   re-evaluates the condition by hand.

## Why existing solutions fail
- **campsite** mints its own per-day S1/S2 counters for journals it creates —
  it does not reconcile an EXISTING append-only journal against externally
  injected labels.
- **tbc-agent / agent-harness / session-continuity** track turn/goal state in
  files they own; none computes "next session number" from a prose journal or
  compares it to a harness-supplied label.
- **agent-handoff** exports transcript snapshots for resume; numbering is not
  its concern.
- Hand-derivation (status quo): proven failure mode — five documented miscounts,
  each costing journal bytes and session minutes.

## Your edge
Reads the journal you ALREADY maintain; nothing new to write at session end.
MAX+1 semantics (not count+1) survive real-world gaps caused by numbering
events. Label reconciliation turns "which number am I?" from archaeology into
a one-line check with an alertable exit code. Standing items move date-gated
directives out of prose into config that evaluates itself.

## Architecture
- Pure stdlib Python 3.13. `python3 -m reveille [JOURNAL...]` (default
  `~/journal/STATE.md`).
- `core.scan_heads(text)` — Completed-block heads only: regex anchored on
  `^- \*\*s(\d{1,3})\b`. Inline refs ("SHIPPED s71", "NEXT-ME (s73…)") never
  count. Next = max+1; no heads → next 1, last None.
- `--label "#4"` (or bare int) → match/mismatch vs computed current session.
- Sprint clock: `[sprint] ends_at = <unix epoch>` in TOML config, overridable
  `--ends-at`. Human format `4d 3h` / `2h 5m` / `0m`.
- Standing items: `[[item]] name/after(YYYY-MM-DD)/note` fire when UTC date of
  `--now` ≥ after (inclusive). Config default path
  `~/.config/reveille/config.toml`; missing file = defaults.
- Output: human block / `--json` (fixed key order) / `--statusline`
  ("reveille s74 · 4d 3h left · standing: none[ · label-mismatch]").
- Exit contract (family convention): 0 clean · 1 label mismatch · 2 usage /
  missing journal / malformed config. A broken input never fakes clean.

## Milestones
- [x] M1 v1.0.0 — scan+next (max+1), label reconciliation, sprint clock,
      standing items, json/statusline, exit contract, tests, publish.
- [x] M2 v1.1.0 — label reconciliation config: `[labels] base = N` (journal =
      base + label) + `[labels.map]` explicit pins (win over base). Motivation:
      once the harness restarted numbering mid-journal ("#1" vs s70+), the
      direct compare mismatched EVERY session — a permanent exit 1 trains the
      owner to ignore the alarm (same false-block class as daybreak v1.4.0's
      line-scoped claim binding). Mapped match = clean exit 0; wrong label or
      offset still exits 1; malformed labels config exits 2. JSON appends
      "expected" last (fixed-order consumers safe); human output notes which
      mapping resolved ("maps to s78 via labels config"); statusline drops the
      label-mismatch tail only on real matches. cli cfg-rebuild gotcha fixed:
      the override path rebuilt cfg with two keys and would have silently
      dropped any new section.
- [x] M3 v1.2.0 — pin-key normalization. Found LIVE at s87: a pin written in
      the natural `'#19' = 87` form passed load_config's own validator (which
      strips `#` when checking) but reconcile looked up the bare key, so the
      pin silently never matched and base math produced a false exit-1 alarm —
      exactly the permanent-wolf failure v1.1.0 was built to kill, surviving
      inside its own feature. Fix: map keys normalized at load (strip
      whitespace + leading `#`), so both forms are one pin; two keys that
      normalize to the same label now raise (exit 2) instead of silently
      picking whichever TOML kept. Lesson: when a validator and a consumer
      share a format contract, normalize ONCE at the boundary where data
      enters — validating one spelling while looking up another is a bug the
      first real-world use of the feature will find.
- [x] M4 v1.3.0 — `--adopt` self-adoption of missing pins. Salvaged from an
      unlogged dead session (#21/#22 both hand-wrote pins then died before any
      journal write — the 8th consecutive session needing label archaeology).
      On mismatch with no existing pin for that label: insert
      `<label> = <counter>` after the [labels.map] header via text-level edit
      (comments preserved; bare integer keys are valid TOML and normalize like
      '#N'), reload, re-check in the SAME run — POST-state exit per the salve
      precedent. Refuses (exit 1, untouched) on a disagreeing existing pin:
      journal counter stays authoritative, adoption never fakes it. JSON gains
      "adopted" LAST (append-only growth of the fixed key order). GOTCHA hit
      twice while finishing the salvage: multiline `$` matches BEFORE the
      newline (inserting at m.end() glues the pin onto the header line — skip
      past the line terminator first), and the fixture-arithmetic class struck
      AGAIN (base=64 + label 9 = s73 accidentally matched, so adopt never
      fired; derive expected values, never eyeball them).
- [x] M5 v1.4.0 — `--prune-stale` + retired-epoch diagnosis. Hit LIVE at
      s103: the sprint epoch (labels #2.. since ~s91) finally reissued a
      label that existed in the pre-s91 pin set (`#19`=87) and adopt
      refused — resolution required hand-editing TOML with no mechanical
      way to tell stale pins from live ones. Signature: within one epoch,
      sorted by label, pin counters never decrease; a decrease proves a
      retired-epoch leftover. Refusals now name inversion counts and point
      at the flag; `--prune-stale` cuts exactly the inverting pins
      (section-scoped text edit, everything else byte-preserved) and pairs
      with `--adopt` for one-run heal (POST-state exit). A non-inverted
      disagreeing pin is never touched — genuine disagreement stays human.
      GOTCHA: bare `#20 = 51` in [labels.map] is a TOML COMMENT, not a pin
      (that is why quoted '#19' spellings exist); fixture gotcha re-hit.
- NEXT only on demand: multiple-journal merge reporting, label history ledger,
  per-epoch base history (auto-suggest base when unmapped mismatch streaks).
