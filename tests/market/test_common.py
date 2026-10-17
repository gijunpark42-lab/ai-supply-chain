"""market.common: per-company web files (company_file_names, write_company_split) and the ADD-only history."""
import json
import os
import unittest

import market.common as common
from tests.market.helpers import TempDataTestCase


class CompanyFileNames(unittest.TestCase):
    def test_plain_names(self):
        names = common.company_file_names(["SK Hynix", "TSMC", "Eli Lilly"])
        self.assertEqual(names, {"SK Hynix": "sk-hynix.json", "TSMC": "tsmc.json", "Eli Lilly": "eli-lilly.json"})

    def test_same_names_in_any_order(self):
        ids = ["SK Hynix", "AMD", "amd", "삼성전자", "Nan Ya Plastics"]
        self.assertEqual(common.company_file_names(ids), common.company_file_names(list(reversed(ids))))

    def test_collisions_get_a_hash(self):
        names = common.company_file_names(["AMD", "amd"])
        self.assertNotEqual(names["AMD"], names["amd"])
        for name in names.values():
            self.assertRegex(name, r"^amd-[0-9a-f]{8}\.json$")

    def test_non_latin_id_gets_a_hash(self):
        name = common.company_file_names(["삼성전자"])["삼성전자"]
        self.assertRegex(name, r"^[0-9a-f]{8}\.json$")
        self.assertEqual(name, common.company_file_names(["삼성전자"])["삼성전자"])    # stable between runs


class WriteCompanySplit(TempDataTestCase):
    """write_company_split writes graph/<name>_index.json + graph/<name>/<file> (here in a temp graph folder)."""

    ROWS_A = [{"date": "2026-10-16", "x": 1}, {"date": "2026-10-01", "x": 2}]
    ROWS_B = [{"date": "2026-09-30", "x": 3}]

    def test_files_and_index(self):
        index = common.write_company_split("demo", "2026-10-17", [], {"SK Hynix": self.ROWS_A, "TSMC": self.ROWS_B})
        self.assertEqual(index["SK Hynix"], {"file": "sk-hynix.json", "count": 2, "latest": "2026-10-16"})
        saved = self.read_graph("demo/sk-hynix.json")
        self.assertEqual(saved, {"company": "SK Hynix", "rows": self.ROWS_A})
        self.assertEqual(self.read_graph("demo_index.json")["companies"], index)

    def test_unchanged_file_is_not_rewritten(self):
        companies = {"SK Hynix": self.ROWS_A, "TSMC": self.ROWS_B}
        common.write_company_split("demo", "2026-10-16", [], companies)
        path = self.graph / "demo" / "sk-hynix.json"
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))          # mark the file with an old time stamp
        changed = {"SK Hynix": self.ROWS_A, "TSMC": self.ROWS_B + [{"date": "2026-10-17", "x": 4}]}
        common.write_company_split("demo", "2026-10-17", [], changed)
        self.assertEqual(path.stat().st_mtime_ns, 1_000_000_000)    # untouched: same rows as before
        self.assertEqual(len(self.read_graph("demo/tsmc.json")["rows"]), 2)   # the changed company was rewritten

    def test_stale_files_and_legacy_file_are_removed(self):
        (self.graph / "demo.json").write_text("{}", encoding="utf-8")          # the old single-file feed
        common.write_company_split("demo", "2026-10-16", [], {"SK Hynix": self.ROWS_A, "TSMC": self.ROWS_B})
        common.write_company_split("demo", "2026-10-17", [], {"SK Hynix": self.ROWS_A})
        self.assertEqual(sorted(p.name for p in (self.graph / "demo").glob("*.json")), ["sk-hynix.json"])
        self.assertFalse((self.graph / "demo.json").exists())
        self.assertEqual(list(self.read_graph("demo_index.json")["companies"]), ["SK Hynix"])


class AppendHistory(TempDataTestCase):
    """append_history is ADD-only: a row whose key is already recorded is skipped (so a re-run adds nothing)."""

    def test_rerun_adds_nothing(self):
        rows = [{"date": "2026-10-16", "id": "a", "v": 1}, {"date": "2026-10-16", "id": "b", "v": 2}]
        self.assertEqual(common.append_history("demo", rows, ("date", "id")), 2)
        self.assertEqual(common.append_history("demo", rows, ("date", "id")), 0)
        newer = [{"date": "2026-10-16", "id": "a", "v": 99}, {"date": "2026-10-17", "id": "a", "v": 3}]
        self.assertEqual(common.append_history("demo", newer, ("date", "id")), 1)    # the old row is never replaced
        lines = (self.history / "demo.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(x)["v"] for x in lines], [1, 2, 3])
        self.assertEqual(len(common.read_history("demo")), 3)


if __name__ == "__main__":
    unittest.main()
