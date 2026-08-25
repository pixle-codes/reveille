"""History ledger: --record appends one JSON line per EFFECTIVE mutation;
--history PATH reads the ledger back (freshness, per-label rollup)."""

from reveille import core
from reveille.cli import main

import io
import json
import contextlib
import pathlib
import tempfile
import unittest
from unittest import mock

from .test_core import SAMPLE  # derives next=s73


class LedgerBase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        patcher = mock.patch.object(
            core, "DEFAULT_CONFIG_PATH",
            pathlib.Path(self._td.name) / "default.toml")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _journal(self):
        p = pathlib.Path(self._td.name) / "STATE.md"
        p.write_text(SAMPLE, encoding="utf-8")
        return str(p)


class TestRecord(LedgerBase):
    def test_adopt_appends_one_line_fixed_key_order(self):
        cp = pathlib.Path(self._td.name) / "cfg.toml"
        cp.write_text("[labels]\nbase = 60\n", encoding="utf-8")
        rp = pathlib.Path(self._td.name) / "hist.jsonl"
        rc = main([self._journal(), "--label", "#9", "--now", "1787522750",
                   "--config", str(cp), "--adopt", "--record", str(rp)])
        self.assertEqual(rc, 0)
        lines = rp.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(list(rec), ["ts", "ts_utc", "action", "label",
                                     "counter", "config"])
        self.assertEqual(rec["ts"], 1787522750)
        self.assertEqual(rec["action"], "adopt")
        self.assertEqual(rec["label"], 9)
        self.assertEqual(rec["counter"], 73)
        self.assertTrue(str(rec["config"]).endswith("cfg.toml"))

    def test_prune_then_adopt_two_lines_in_order(self):
        cp = pathlib.Path(self._td.name) / "cfg.toml"
        cp.write_text("[labels]\nbase = 60\n[labels.map]\n'2' = 90\n"
                      "'3' = 70\n", encoding="utf-8")
        rp = pathlib.Path(self._td.name) / "hist.jsonl"
        rc = main([self._journal(), "--label", "#9", "--now", "1787522750",
                   "--config", str(cp), "--prune-stale", "--adopt",
                   "--record", str(rp)])
        self.assertEqual(rc, 0)
        recs = [json.loads(l) for l in
                rp.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["action"] for r in recs], ["prune", "adopt"])
        self.assertEqual(list(recs[0]), ["ts", "ts_utc", "action", "removed",
                                         "config"])
        self.assertEqual(recs[0]["removed"],
                         [{"label": 3, "counter": 70}])
        self.assertEqual(recs[1]["counter"], 73)

    def test_noop_runs_record_nothing(self):
        jp = self._journal()
        cp = pathlib.Path(self._td.name) / "cfg.toml"
        cp.write_text("[labels]\nbase = 60\n", encoding="utf-8")
        rp = pathlib.Path(self._td.name) / "hist.jsonl"
        rc = main([jp, "--label", "#9", "--now", "1787522750",
                   "--config", str(cp), "--record", str(rp)])
        self.assertEqual(rc, 1)  # plain mismatch, no --adopt
        self.assertFalse(rp.exists())
        # clean match run also records nothing (base 60 + label 13 = s73)
        rc = main([jp, "--label", "#13", "--now", "1787522750",
                   "--config", str(cp), "--record", str(rp)])
        self.assertEqual(rc, 0)
        self.assertFalse(rp.exists())

    def test_refused_adoption_records_nothing(self):
        cp = pathlib.Path(self._td.name) / "cfg.toml"
        cp.write_text("[labels.map]\n9 = 50\n", encoding="utf-8")
        rp = pathlib.Path(self._td.name) / "hist.jsonl"
        rc = main([self._journal(), "--label", "#9", "--now", "1787522750",
                   "--config", str(cp), "--adopt", "--record", str(rp)])
        self.assertEqual(rc, 1)
        self.assertFalse(rp.exists())

    def test_broken_record_path_warns_never_changes_verdict(self):
        cp = pathlib.Path(self._td.name) / "cfg.toml"
        rp = pathlib.Path(self._td.name) / "no-such-dir" / "hist.jsonl"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = main([self._journal(), "--label", "#4", "--now",
                       "1787522750", "--config", str(cp), "--adopt",
                       "--record", str(rp)])
        self.assertEqual(rc, 0)
        self.assertIn("could not write record", err.getvalue())


NOW = 1790000000


def _seed(path, recs):
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")


class TestHistory(LedgerBase):
    def _rec(self, ts, action, **kw):
        r = {"ts": ts,
             "ts_utc": core.utc_iso(ts),
             "action": action}
        r.update(kw)
        return r

    def test_human_json_and_bad_lines(self):
        rp = pathlib.Path(self._td.name) / "hist.jsonl"
        _seed(rp, [
            self._rec(NOW - 86400 * 3, "prune",
                      removed=[{"label": 3, "counter": 70}],
                      config="/x/cfg.toml"),
            self._rec(NOW - 360, "adopt", label=14, counter=117,
                      config="/x/cfg.toml"),
            {"garbage": True},
            "not json",
        ])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            rc = main(["--history", str(rp), "--now", str(NOW)])
        self.assertEqual(rc, 0)
        self.assertIn("reveille HISTORY: 2 mutation(s)", out.getvalue())
        self.assertIn("#14 adopt -> s117", out.getvalue())
        self.assertIn("#3 pruned (=s70)", out.getvalue())
        self.assertIn("2 unparseable line(s) skipped", err.getvalue())

        jsbuf = io.StringIO()
        with contextlib.redirect_stdout(jsbuf):
            rc = main(["--history", str(rp), "--now", str(NOW), "--json"])
        self.assertEqual(rc, 0)
        js = json.loads(jsbuf.getvalue())
        self.assertEqual(list(js), ["mutations", "bad_lines", "newest_ts_utc",
                                    "newest_age_hours", "labels"])
        self.assertEqual(js["mutations"], 2)
        self.assertEqual(js["bad_lines"], 2)
        self.assertEqual(js["newest_ts_utc"], core.utc_iso(NOW - 360))
        labels = js["labels"]
        self.assertEqual([l["label"] for l in labels], [3, 14])
        self.assertEqual(labels[1]["last_action"], "adopt")
        self.assertEqual(labels[1]["session"], 117)
        self.assertEqual(labels[0]["last_action"], "pruned")
        self.assertEqual(labels[0]["session"], 70)

    def test_max_age_boundary_strictly_greater(self):
        rp = pathlib.Path(self._td.name) / "hist.jsonl"
        _seed(rp, [self._rec(NOW - 3 * 3600, "adopt", label=2, counter=70,
                             config="/x")])
        # exactly 3.0h old against N=3: fresh (strictly-greater boundary)
        rc = main(["--history", str(rp), "--now", str(NOW),
                   "--max-age-hours", "3"])
        self.assertEqual(rc, 0)
        # 3.1h old against N=3: stale
        _seed(rp, [self._rec(NOW - int(3.1 * 3600), "adopt", label=2,
                             counter=70, config="/x")])
        sl = io.StringIO()
        with contextlib.redirect_stdout(sl):
            rc = main(["--history", str(rp), "--now", str(NOW),
                       "--max-age-hours", "3", "--statusline"])
        self.assertEqual(rc, 1)
        self.assertIn("reveille STALE:", sl.getvalue())

    def test_empty_ledger_is_not_fresh(self):
        rp = pathlib.Path(self._td.name) / "hist.jsonl"
        rp.write_text("", encoding="utf-8")
        rc = main(["--history", str(rp), "--now", str(NOW),
                   "--max-age-hours", "3"])
        self.assertEqual(rc, 1)

    def test_missing_file_exit2_negative_n_exit2_exclusivity(self):
        missing = pathlib.Path(self._td.name) / "nope.jsonl"
        self.assertEqual(main(["--history", str(missing), "--now", str(NOW)]), 2)
        rp = pathlib.Path(self._td.name) / "hist.jsonl"
        rp.write_text("", encoding="utf-8")
        self.assertEqual(main(["--history", str(rp), "--now", str(NOW),
                               "--max-age-hours", "-1"]), 2)
        self.assertEqual(main(["--history", str(rp), "--adopt"]), 2)


if __name__ == "__main__":
    unittest.main()
