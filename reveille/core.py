"""Core derivation logic: session counter, label reconciliation, sprint clock,
standing items. Pure functions wherever possible."""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

HEAD_RE = re.compile(r"^-\s\*\*s(\d{1,3})\b")

JSON_KEY_ORDER = (
    "next",
    "last",
    "label",
    "match",
    "sprint",
    "standing_fired",
    "journal",
    "expected",
    "adopted",
)


def scan_heads(text: str) -> list[int]:
    """Session numbers from block heads only (`- **sNN ...`)."""
    found = []
    for line in text.splitlines():
        m = HEAD_RE.match(line)
        if m:
            found.append(int(m.group(1)))
    return found


def derive_counter(text: str) -> tuple[int, int | None]:
    """(next, last). MAX+1, never count+1 — gaps from numbering events are real."""
    heads = scan_heads(text)
    if not heads:
        return 1, None
    last = max(heads)
    return last + 1, last


def parse_label(raw: str | None) -> int | None:
    """'#4' / '4' -> 4; anything else -> None."""
    if raw is None:
        return None
    s = raw.strip().lstrip("#").strip()
    if not s.isdigit():
        return None
    return int(s)


def reconcile(label: int | None, nxt: int, cfg: dict) -> tuple[bool | None,
                                                               int | None]:
    """(match, expected) — the counter this label maps to.

    Without a [labels] config the comparison is direct (legacy). With
    labels.map, an explicit pin wins; with labels.base, journal counter =
    base + label. Harnesses that restart numbering between epochs would
    otherwise mismatch every session forever and train the owner to ignore
    the alarm."""
    if label is None:
        return None, None
    lbl = cfg.get("labels") or {}
    m = lbl.get("map") or {}
    key = str(label)
    if key in m:
        expected = int(m[key])
    elif isinstance(lbl.get("base"), int):
        expected = lbl["base"] + label
    else:
        expected = label
    return (expected == nxt), expected


def human_left(seconds: int) -> str:
    if seconds <= 0:
        return "0m"
    days, rem = divmod(seconds, 86400)
    hours, rem2 = divmod(rem, 3600)
    mins = rem2 // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def sprint_block(now: int, ends_at: int | None) -> dict:
    if ends_at is None:
        return {"ends_at": None, "seconds_left": None, "human": None}
    left = ends_at - now
    return {
        "ends_at": ends_at,
        "seconds_left": left,
        "human": human_left(left),
    }


def _utc_date(epoch: int) -> _dt.date:
    return _dt.datetime.fromtimestamp(int(epoch), _dt.timezone.utc).date()


def parse_iso_date(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s.strip())


def standing_fired(items: list[dict], now: int) -> list[dict]:
    """Items whose `after` date (inclusive) has arrived by UTC now."""
    today = _utc_date(now)
    fired = []
    for it in items:
        try:
            after = parse_iso_date(str(it.get("after", "")))
            name = str(it.get("name", "")).strip()
        except ValueError:
            continue
        if not name:
            continue
        if today >= after:
            fired.append({"name": name, "after": after.isoformat(),
                          "note": str(it.get("note", ""))})
    fired.sort(key=lambda d: d["name"])
    return fired


DEFAULT_CONFIG_PATH = Path("~/.config/reveille/config.toml")


def load_config(path: str | Path | None) -> dict:
    """Returns {'ends_at': int|None, 'items': [..], 'labels': {...}}.
    Missing file = defaults. Malformed TOML raises ValueError (caller turns
    that into exit 2)."""
    p = Path(path).expanduser() if path else DEFAULT_CONFIG_PATH.expanduser()
    if not p.is_file():
        return {"ends_at": None, "items": [], "labels": {}}
    import tomllib

    with open(p, "rb") as f:
        raw = tomllib.load(f)
    ends_at = raw.get("sprint", {}).get("ends_at")
    if ends_at is not None and not isinstance(ends_at, int):
        raise ValueError("sprint.ends_at must be an integer unix epoch")
    items = list(raw.get("item", []))

    lbl_raw = raw.get("labels", {})
    if lbl_raw is None:
        lbl_raw = {}
    if not isinstance(lbl_raw, dict):
        raise ValueError("[labels] must be a table")
    labels: dict = {"base": None, "map": {}}
    base = lbl_raw.get("base")
    if base is not None:
        if isinstance(base, bool) or not isinstance(base, int):
            raise ValueError("labels.base must be an integer offset")
        labels["base"] = base
    mapping = lbl_raw.get("map")
    if mapping is not None:
        if not isinstance(mapping, dict):
            raise ValueError("labels.map must be a table of label = counter")
        normalized: dict = {}
        seen: dict = {}
        for k, v in mapping.items():
            key = k.strip().lstrip("#")
            if not key.isdigit():
                raise ValueError(f"labels.map key {k!r} is not a label number")
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError(f"labels.map[{k!r}] must be an integer "
                                 "journal counter")
            if key in seen:
                raise ValueError(f"labels.map keys {seen[key]!r} and {k!r} "
                                 f"both resolve to label {key}")
            seen[key] = k
            normalized[key] = v
        labels["map"] = normalized
    return {"ends_at": ends_at, "items": items, "labels": labels}


def insert_map_pin(text: str, label: int, counter: int) -> str:
    """Config text with `label = counter` added under [labels.map].

    Inserts directly after the existing [labels.map] header when present
    (key order inside a TOML table carries no meaning); otherwise appends
    a new [labels.map] section at the end of the file. Bare integer keys
    are valid TOML and normalize to the same pin as '#21' spellings."""
    line = f"{label} = {counter}"
    pat = re.compile(r"^[ \t]*\[labels\.map\][^\n]*$", re.MULTILINE)
    m = pat.search(text)
    if not m:
        sep = "" if (not text or text.endswith("\n")) else "\n"
        return f"{text}{sep}\n[labels.map]\n{line}\n"
    ins = m.end()
    if text[ins:ins + 2] == "\r\n":
        ins += 2
    elif text[ins:ins + 1] == "\n":
        ins += 1
    return text[:ins] + f"{line}\n" + text[ins:]


def statusline(js: dict) -> str:
    parts = [f"reveille s{js['next']}"]
    sp = js["sprint"]
    if sp["human"] is not None:
        parts.append(f"{sp['human']} left")
    names = ",".join(i["name"] for i in js["standing_fired"]) or "none"
    parts.append(f"standing: {names}")
    if js["match"] is False:
        parts.append("label-mismatch")
    if js.get("adopted"):
        parts.append("pin adopted")
    return " · ".join(parts)


def build_report(text: str, journal_path: str, label_raw: str | None,
                 now: int, cfg: dict, adopted: dict | None = None) -> dict:
    nxt, last = derive_counter(text)
    label = parse_label(label_raw)
    match, expected = reconcile(label, nxt, cfg)
    js = {
        "next": nxt,
        "last": last,
        "label": label,
        "match": match,
        "sprint": sprint_block(now, cfg["ends_at"]),
        "standing_fired": standing_fired(cfg["items"], now),
        "journal": journal_path,
        "expected": expected,
        "adopted": adopted,
    }
    return {k: js[k] for k in JSON_KEY_ORDER}


def render_human(js: dict) -> str:
    lines = []
    counter = f"next session: s{js['next']}"
    if js["last"] is not None:
        counter += f" (last logged s{js['last']})"
    lines.append(counter)
    if js["label"] is not None:
        verdict = "MATCHES" if js["match"] else "MISMATCHES"
        line = f"briefing label #{js['label']} {verdict} the journal counter"
        if js["expected"] is not None and js["expected"] != js["label"]:
            line += f" (maps to s{js['expected']} via labels config)"
        line += " — journal is authoritative"
        lines.append(line)
    sp = js["sprint"]
    if sp["human"] is not None:
        lines.append(f"sprint time left: {sp['human']}"
                     + (" (PAST END)" if sp["seconds_left"] <= 0 else ""))
    for it in js["standing_fired"]:
        note = f" — {it['note']}" if it["note"] else ""
        lines.append(f"standing item FIRES: {it['name']} (since {it['after']}){note}")
    if not js["standing_fired"]:
        lines.append("standing items: none fire today")
    if js.get("adopted"):
        ad = js["adopted"]
        lines.append(f"pin adopted: #{ad['label']} -> s{ad['counter']} "
                     f"(written to {ad['config']})")
    return "\n".join(lines)
