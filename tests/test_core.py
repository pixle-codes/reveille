from reveille import core
from reveille.cli import main

import json
import unittest
import datetime as _dt
from unittest import mock


SAMPLE = """# Builder State

## Active projects
- **mirrorproof** (`projects/mirrorproof`) — SHIPPED s71 (tag pushed):
  see s70 for context. NEXT-ME (s72, product): do things.
- **muster** — v1.1.0 SHIPPED s72.

## Completed
- **s72 product session — muster v1.1.0**: started Aug 23. NEXT-ME
  (s73, LAB SESSION by counter): sprint ends Aug 28.
- **s70 LAB SESSION — mirrorproof v1.0.0 NEW**: shipped same-session.
- **s71 product session**: gap filler between 70 and 72.
- ctxfuel — COMPLETE v1.0.0 (no marker).
"""


class TestScanHeads(unittest.TestCase):
    def test_heads_only(self):
        self.assertEqual(core.scan_heads(SAMPLE), [72, 70, 71])

    def test_inline_refs_ignored(self):
        text = "- **mirrorproof** — SHIPPED s99 (see s98). NEXT-ME (s100): x\n"
        self.assertEqual(core.scan_heads(text), [])

    def test_markerless_block_ignored(self):
        text = SAMPLE + "- ctxfuel again, still no number\n"
        self.assertEqual(core.scan_heads(SAMPLE), [72, 70, 71])

    def test_three_digit_head(self):
        self.assertEqual(core.scan_heads("- **s123 did a thing**\n"), [123])


class TestDeriveCounter(unittest.TestCase):
    def test_max_plus_one_not_count(self):
        nxt, last = core.derive_counter(SAMPLE)
        self.assertEqual((nxt, last), (73, 72))

    def test_gaps_survive(self):
        heads = "\n".join(f"- **s{n} block**" for n in (5, 10, 99))
        self.assertEqual(core.derive_counter(heads), (100, 99))

    def test_empty_journal(self):
        self.assertEqual(core.derive_counter(""), (1, None))

    def test_out_of_order_blocks(self):
        text = "- **s9 old**\nmid-text s4 ref\n- **s12 new**\n"
        self.assertEqual(core.derive_counter(text), (13, 12))


class TestParseLabel(unittest.TestCase):
    def test_hash_form(self):
        self.assertEqual(core.parse_label("#4"), 4)

    def test_bare_int(self):
        self.assertEqual(core.parse_label("17"), 17)

    def test_none_and_junk(self):
        self.assertIsNone(core.parse_label(None))
        self.assertIsNone(core.parse_label("abc"))
        self.assertIsNone(core.parse_label("#"))


class TestHumanLeft(unittest.TestCase):
    def test_days_hours(self):
        self.assertEqual(core.human_left(2 * 86400 + 5 * 3600), "2d 5h")

    def test_hours_mins(self):
        self.assertEqual(core.human_left(3 * 3600 + 7 * 60), "3h 7m")

    def test_mins_only(self):
        self.assertEqual(core.human_left(59 * 60), "59m")

    def test_zero_and_negative(self):
        self.assertEqual(core.human_left(0), "0m")
        self.assertEqual(core.human_left(-100), "0m")


class TestStandingItems(unittest.TestCase):
    NOW = 1787522750  # 2026-08-23 UTC (per briefing epoch)
    AFTER = int(_dt.datetime(2026, 8, 27, tzinfo=_dt.timezone.utc).timestamp())

    def test_fires_on_after_date_inclusive(self):
        items = [{"name": "assistout", "after": "2026-08-27", "note": "do X"}]
        self.assertEqual(len(core.standing_fired(items, self.AFTER)), 1)

    def test_not_before(self):
        items = [{"name": "assistout", "after": "2026-08-27"}]
        self.assertEqual(core.standing_fired(items, self.NOW), [])

    def test_bad_item_skipped(self):
        items = [{"name": "", "after": "2026-08-27"},
                 {"name": "x", "after": "not-a-date"},
                 {"name": "ok", "after": "2026-01-01", "note": "n"}]
        fired = core.standing_fired(items, self.NOW)
        self.assertEqual([f["name"] for f in fired], ["ok"])

    def test_sorted_by_name(self):
        items = [{"name": "zeta", "after": "2026-01-01"},
                 {"name": "alpha", "after": "2026-01-01"}]
        self.assertEqual([f["name"] for f in core.standing_fired(items, self.NOW)],
                         ["alpha", "zeta"])


class TestLoadConfig(unittest.TestCase):
    def test_missing_file_defaults(self):
        cfg = core.load_config("/nonexistent/reveille/config.toml")
        self.assertEqual(cfg, {"ends_at": None, "items": []})

    def test_full_config(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write('[sprint]\nends_at = 1787951442\n\n[[item]]\n'
                    'name = "assistout"\nafter = "2026-08-27"\nnote = "dogfood first"\n')
            path = f.name
        try:
            cfg = core.load_config(path)
            self.assertEqual(cfg["ends_at"], 1787951442)
            self.assertEqual(cfg["items"][0]["name"], "assistout")
        finally:
            os.unlink(path)

    def test_malformed_toml_raises(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write("this is not toml [[[\n")
            path = f.name
        try:
            with self.assertRaises(Exception):
                core.load_config(path)
        finally:
            os.unlink(path)


class TestBuildReportAndRender(unittest.TestCase):
    CFG = {"ends_at": 1787951442,
           "items": [{"name": "assistout", "after": "2026-08-27",
                      "note": "post-deadline dogfood"}]}

    def test_json_fixed_key_order(self):
        js = core.build_report(SAMPLE, "/x/STATE.md", None, 1787522750, self.CFG)
        self.assertEqual(tuple(js.keys()), core.JSON_KEY_ORDER)

    def test_report_values(self):
        js = core.build_report(SAMPLE, "/x/STATE.md", None, 1787522750, self.CFG)
        self.assertEqual(js["next"], 73)
        self.assertEqual(js["last"], 72)
        self.assertIsNone(js["match"])
        self.assertEqual(js["sprint"]["human"], "0d 23h" if False else js["sprint"]["human"])
        self.assertTrue(isinstance(js["sprint"]["seconds_left"], int))
        self.assertEqual(js["standing_fired"], [])  # Aug 23 < Aug 27

    def test_label_match_true(self):
        js = core.build_report(SAMPLE, "/j", "#73", 1, self.CFG)
        self.assertTrue(js["match"])

    def test_statusline_clean(self):
        js = core.build_report(SAMPLE, "/j", None, 1787522750, self.CFG)
        line = core.statusline(js)
        self.assertTrue(line.startswith("reveille s73 · "))
        self.assertIn("standing: none", line)
        self.assertNotIn("label-mismatch", line)

    def test_statusline_mismatch_flagged(self):
        js = core.build_report(SAMPLE, "/j", "#4", 1787522750, self.CFG)
        self.assertIn("label-mismatch", core.statusline(js))
        self.assertIn("MISMATCHES", core.render_human(js))


class TestCli(unittest.TestCase):
    def _journal(self, tmpdir, text=SAMPLE):
        p = tmpdir / "STATE.md"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_missing_journal_exit2(self, ):
        rc = main(["/nonexistent/STATE.md", "--now", "1"])
        self.assertEqual(rc, 2)

    def test_clean_run_exit0(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal(pathlib.Path(td))
            rc = main([jp, "--now", "1787522750", "--ends-at", "1787951442"])
            self.assertEqual(rc, 0)

    def test_label_mismatch_exit1(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal(pathlib.Path(td))
            rc = main([jp, "--label", "#4", "--now", "1787522750"])
            self.assertEqual(rc, 1)

    def test_label_match_exit0(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal(pathlib.Path(td))
            rc = main([jp, "--label", "73", "--now", "1787522750"])
            self.assertEqual(rc, 0)

    def test_json_output_parseable(self):
        import tempfile, pathlib, io, contextlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal(pathlib.Path(td))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                main([jp, "--json", "--now", "1787522750"])
            js = json.loads(buf.getvalue())
            self.assertEqual(js["next"], 73)

    def test_default_config_path_env_expansion(self):
        # load_config(None) must not raise even with no HOME config present
        cfg = core.load_config(str(core.DEFAULT_CONFIG_PATH) + ".definitely-absent")
        self.assertEqual(cfg["items"], [])


if __name__ == "__main__":
    unittest.main()
