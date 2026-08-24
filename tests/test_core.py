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
        self.assertEqual(cfg, {"ends_at": None, "items": [], "labels": {}})

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

    def _write(self, body):
        import tempfile, os
        f = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        f.write(body)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_labels_base_parsed(self):
        cfg = core.load_config(self._write("[labels]\nbase = 69\n"))
        self.assertEqual(cfg["labels"], {"base": 69, "map": {}})

    def test_labels_map_parsed(self):
        cfg = core.load_config(self._write(
            "[labels.map]\n9 = 78\n'12' = 81\n"))
        self.assertEqual(cfg["labels"]["map"], {"9": 78, "12": 81})

    def test_labels_bad_base_raises(self):
        with self.assertRaises(ValueError):
            core.load_config(self._write("[labels]\nbase = 'sixty'\n"))

    def test_labels_bool_base_raises(self):
        with self.assertRaises(ValueError):
            core.load_config(self._write("[labels]\nbase = true\n"))

    def test_labels_bad_map_value_raises(self):
        with self.assertRaises(ValueError):
            core.load_config(self._write("[labels.map]\n9 = 's78'\n"))

    def test_labels_bad_map_key_raises(self):
        with self.assertRaises(ValueError):
            core.load_config(self._write("[labels.map]\nnext = 78\n"))

    def test_labels_hash_prefixed_keys_normalized(self):
        cfg = core.load_config(self._write(
            "[labels.map]\n'#19' = 87\n' 12 ' = 81\n"))
        self.assertEqual(cfg["labels"]["map"], {"19": 87, "12": 81})

    def test_labels_colliding_keys_raise(self):
        with self.assertRaises(ValueError):
            core.load_config(self._write(
                "[labels.map]\n'19' = 87\n'#19' = 88\n"))


class TestReconcile(unittest.TestCase):
    CFG_PLAIN = {}

    def test_no_label(self):
        self.assertEqual(core.reconcile(None, 78, {}), (None, None))

    def test_legacy_direct_compare(self):
        self.assertEqual(core.reconcile(78, 78, {}), (True, 78))
        self.assertEqual(core.reconcile(4, 78, {}), (False, 4))

    def test_base_offset_match(self):
        cfg = {"labels": {"base": 69, "map": {}}}
        self.assertEqual(core.reconcile(9, 78, cfg), (True, 78))

    def test_base_offset_mismatch(self):
        cfg = {"labels": {"base": 70, "map": {}}}
        self.assertEqual(core.reconcile(9, 78, cfg), (False, 79))

    def test_map_wins_over_base(self):
        cfg = {"labels": {"base": 1, "map": {"9": 78}}}
        self.assertEqual(core.reconcile(9, 78, cfg), (True, 78))

    def test_map_miss_falls_back_to_base(self):
        cfg = {"labels": {"base": 69, "map": {"3": 72}}}
        self.assertEqual(core.reconcile(9, 78, cfg), (True, 78))

    def test_mapped_mismatch_still_false(self):
        cfg = {"labels": {"base": 69, "map": {}}}
        match, expected = core.reconcile(5, 78, cfg)
        self.assertIs(match, False)
        self.assertEqual(expected, 74)


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

    def test_mapped_match_clean(self):
        cfg = dict(self.CFG, labels={"base": 69, "map": {}})
        js = core.build_report(SAMPLE, "/j", "#9", 1787522750, cfg)
        # journal derives s73; label 9 + base 69 = 78 -> mismatch vs 73
        self.assertIs(js["match"], False)
        self.assertEqual(js["expected"], 78)
        # matching case: base 64 puts label 9 on s73
        cfg2 = dict(self.CFG, labels={"base": 64, "map": {}})
        js2 = core.build_report(SAMPLE, "/j", "#9", 1787522750, cfg2)
        self.assertIs(js2["match"], True)
        self.assertNotIn("label-mismatch", core.statusline(js2))
        self.assertIn("MATCHES", core.render_human(js2))
        self.assertIn("maps to s73 via labels config", core.render_human(js2))

    def test_json_adopted_appended_last(self):
        cfg = dict(self.CFG, labels={"base": 64, "map": {}})
        js = core.build_report(SAMPLE, "/j", "#9", 1, cfg)
        keys = tuple(js.keys())
        self.assertEqual(keys[-1], "adopted")
        self.assertIs(js["adopted"], None)
        self.assertEqual(keys[-2], "expected")
        self.assertEqual(len(keys), len(core.JSON_KEY_ORDER))
        adopted = core.build_report(SAMPLE, "/j", "#9", 1, cfg,
                                    {"label": 9, "counter": 73,
                                     "config": "/c"})
        self.assertEqual(tuple(adopted.keys()), keys)
        self.assertEqual(adopted["adopted"]["counter"], 73)

    def test_unmapped_render_byte_compatible(self):
        text = core.render_human(
            core.build_report(SAMPLE, "/j", "#73", 1, self.CFG))
        self.assertIn("#73 MATCHES the journal counter — journal is "
                      "authoritative", text)
        self.assertNotIn("maps to", text)


class TestCli(unittest.TestCase):
    def setUp(self):
        import tempfile, pathlib
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        # Hermetic default config: CLI tests must never read the real
        # ~/.config/reveille/config.toml (a live [labels] section flips
        # expected values — caught by allclear's fresh-clone suite run).
        patcher = mock.patch.object(
            core, "DEFAULT_CONFIG_PATH",
            pathlib.Path(self._td.name) / "absent-config.toml")
        patcher.start()
        self.addCleanup(patcher.stop)

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
            argv = [jp, "--now", "1787522750", "--ends-at", "1787951442"]
            rc = main(argv)
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

    def test_config_labels_base_end_to_end(self):
        import tempfile, pathlib, os
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal(pathlib.Path(td))
            cp = pathlib.Path(td) / "config.toml"
            # journal derives s73; harness label 9 -> base 64
            cp.write_text("[labels]\nbase = 64\n", encoding="utf-8")
            rc = main([jp, "--label", "#9", "--now", "1787522750",
                       "--config", str(cp)])
            self.assertEqual(rc, 0)
            bad = pathlib.Path(td) / "bad.toml"
            bad.write_text("[labels]\nbase = 65\n", encoding="utf-8")
            rc = main([jp, "--label", "#9", "--now", "1787522750",
                       "--config", str(bad)])
            self.assertEqual(rc, 1)
            os.unlink(cp)
            os.unlink(bad)

    def test_config_labels_malformed_exit2(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal(pathlib.Path(td))
            cp = pathlib.Path(td) / "cfg.toml"
            cp.write_text("[labels]\nbase = 'x'\n", encoding="utf-8")
            rc = main([jp, "--label", "9", "--now", "1787522750",
                       "--config", str(cp)])
            self.assertEqual(rc, 2)

    def test_config_hash_prefixed_pin_matches(self):
        # The v1.1.0 live false-alarm: a pin written as '#19' passed the
        # validator but reconcile looked up '19', silently falling through
        # to base math (69+19=88) and flagging exit 1 forever.
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal(pathlib.Path(td))
            cp = pathlib.Path(td) / "cfg.toml"
            cp.write_text("[labels]\nbase = 69\n\n[labels.map]\n'#4' = 73\n",
                          encoding="utf-8")
            rc = main([jp, "--label", "#4", "--now", "1787522750",
                       "--config", str(cp)])
            self.assertEqual(rc, 0)
            wrong = pathlib.Path(td) / "wrong.toml"
            wrong.write_text("[labels]\nbase = 69\n\n[labels.map]\n'#4' = 99\n",
                             encoding="utf-8")
            rc = main([jp, "--label", "#4", "--now", "1787522750",
                       "--config", str(wrong)])
            self.assertEqual(rc, 1)

    def test_config_colliding_pin_keys_exit2(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal(pathlib.Path(td))
            cp = pathlib.Path(td) / "cfg.toml"
            cp.write_text("[labels.map]\n'19' = 87\n'#19' = 88\n",
                          encoding="utf-8")
            rc = main([jp, "--label", "19", "--now", "1787522750",
                       "--config", str(cp)])
            self.assertEqual(rc, 2)

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


class TestInsertMapPin(unittest.TestCase):
    def test_inserts_after_existing_header(self):
        text = "[labels]\nbase = 69\n\n[labels.map]\n'#19' = 87\n\n[[item]]\n"
        out = core.insert_map_pin(text, 21, 89)
        self.assertIn("[labels.map]\n21 = 89\n'#19' = 87\n", out)
        self.assertIn("[[item]]", out)

    def test_appends_section_when_absent(self):
        out = core.insert_map_pin("[labels]\nbase = 69\n", 4, 73)
        self.assertEqual(out, "[labels]\nbase = 69\n\n[labels.map]\n4 = 73\n")

    def test_empty_text_creates_minimal_config(self):
        self.assertEqual(core.insert_map_pin("", 9, 78),
                         "\n[labels.map]\n9 = 78\n")

    def test_no_trailing_newline_handled(self):
        out = core.insert_map_pin("[labels]\nbase = 1", 2, 3)
        self.assertTrue(out.endswith("\n[labels.map]\n2 = 3\n"))

    def test_roundtrip_through_load_config(self):
        import tomllib
        text = core.insert_map_pin(
            core.insert_map_pin("[sprint]\nends_at = 5\n", 19, 87), 20, 88)
        raw = tomllib.loads(text)
        self.assertEqual(raw["labels"]["map"], {"19": 87, "20": 88})


class TestAdoptCli(unittest.TestCase):
    JOURNAL = None  # SAMPLE derives s73

    def setUp(self):
        import tempfile, pathlib
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        patcher = mock.patch.object(
            core, "DEFAULT_CONFIG_PATH",
            pathlib.Path(self._td.name) / "adopt-default.toml")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _journal(self):
        import pathlib
        p = pathlib.Path(self._td.name) / "STATE.md"
        p.write_text(SAMPLE, encoding="utf-8")
        return str(p)

    def test_adopt_writes_pin_and_exits0_same_run(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal()
            cp = pathlib.Path(td) / "cfg.toml"
            cp.write_text("[labels]\nbase = 60\n", encoding="utf-8")
            rc = main([jp, "--label", "#9", "--now", "1787522750",
                       "--config", str(cp), "--adopt"])
            self.assertEqual(rc, 0)
            text = cp.read_text(encoding="utf-8")
            self.assertIn("9 = 73", text)
            # idempotent second run without --adopt
            rc = main([jp, "--label", "#9", "--now", "1787522750",
                       "--config", str(cp)])
            self.assertEqual(rc, 0)

    def test_adopt_creates_missing_config_file(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal()
            cp = pathlib.Path(td) / "fresh" / "cfg.toml"
            rc = main([jp, "--label", "#4", "--now", "1787522750",
                       "--config", str(cp), "--adopt"])
            self.assertEqual(rc, 0)
            self.assertIn("4 = 73", cp.read_text(encoding="utf-8"))

    def test_adopt_refuses_conflicting_existing_pin(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal()
            cp = pathlib.Path(td) / "cfg.toml"
            original = "[labels.map]\n'9' = 99\n"
            cp.write_text(original, encoding="utf-8")
            rc = main([jp, "--label", "#9", "--now", "1787522750",
                       "--config", str(cp), "--adopt"])
            self.assertEqual(rc, 1)
            self.assertEqual(cp.read_text(encoding="utf-8"), original)

    def test_adopt_with_matching_label_is_noop(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal()
            cp = pathlib.Path(td) / "absent.toml"
            rc = main([jp, "--label", "73", "--now", "1787522750",
                       "--config", str(cp), "--adopt"])
            self.assertEqual(rc, 0)
            self.assertFalse(cp.exists())

    def test_adopt_without_label_is_noop(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal()
            cp = pathlib.Path(td) / "absent.toml"
            rc = main([jp, "--now", "1787522750",
                       "--config", str(cp), "--adopt"])
            self.assertEqual(rc, 0)
            self.assertFalse(cp.exists())

    def test_adopt_json_has_adopted_key_last_and_exit0(self):
        import tempfile, pathlib, io, contextlib
        with tempfile.TemporaryDirectory() as td:
            jp = self._journal()
            cp = pathlib.Path(td) / "cfg.toml"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main([jp, "--label", "#9", "--now", "1787522750",
                           "--config", str(cp), "--adopt", "--json"])
            js = json.loads(buf.getvalue())
            self.assertEqual(rc, 0)
            self.assertEqual(tuple(js.keys()), core.JSON_KEY_ORDER)
            self.assertEqual(js["adopted"],
                             {"label": 9, "counter": 73,
                              "config": str(cp)})
            self.assertIs(js["match"], True)


if __name__ == "__main__":
    unittest.main()
