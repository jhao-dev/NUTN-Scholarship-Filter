"""抓取與判斷規則的測試（不連網）。執行：python -m unittest discover tests"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
sys.argv = ["test", str(ROOT / "app.py")]  # scrape.py 匯入時會讀這個路徑

import external  # noqa: E402
import health  # noqa: E402
import notify  # noqa: E402
import scrape  # noqa: E402


def obj(title="", detail="", residency="未偵測"):
    return types.SimpleNamespace(title=title, detail=detail, attachment_text="", residency_requirement=residency)


class Residency(unittest.TestCase):
    def test_short_names(self):
        o = obj(detail="設籍高雄及台南之清寒學生")
        scrape.add_short_residency(o)
        self.assertIn("高雄市", o.residency_requirement)

    def test_no_restriction(self):
        o = obj(detail="全國大專院校學生皆可申請")
        scrape.add_short_residency(o)
        self.assertEqual(o.residency_requirement, "未偵測")


class Notices(unittest.TestCase):
    def test_notice_excluded(self):
        for title in ["財政查核結果通知", "獎學金說明會", "115-1 就學貸款公告"]:
            self.assertTrue(scrape.is_notice_only(obj(title=title)), title)

    def test_scholarship_kept(self):
        self.assertFalse(scrape.is_notice_only(obj(title="【自行申請】清寒優秀學生獎學金")))


class Dates(unittest.TestCase):
    def test_roc_date(self):
        self.assertEqual(external.roc_date("115-11-30"), "2026-11-30")
        self.assertIsNone(external.roc_date("隨時"))


class Health(unittest.TestCase):
    def run_check(self, nutn, ext, ext_errors):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "scholarships.json").write_text(json.dumps({"errors": []}), encoding="utf-8")
            Path(d, "external.json").write_text(json.dumps({"errors": ext_errors}), encoding="utf-8")
            return health.problems(nutn, ext, d)

    def test_ok(self):
        self.assertEqual(self.run_check("success", "success", []), [])

    def test_failures(self):
        self.assertEqual(len(self.run_check("success", "failure", [])), 1)
        self.assertEqual(len(self.run_check("success", "success", ["青年署活動: timeout"])), 1)
        self.assertEqual(len(self.run_check("skipped", "skipped", [])), 2)


class Notify(unittest.TestCase):
    PROFILE = {"city": "新竹市", "dept": "資訊工程學系", "gpa": 80, "conduct": 85}

    def item(self, no, residency="未偵測"):
        return {"board_no": no, "title": f"@someone 公告{no}", "url": f"https://example.test/{no}", "deadline_iso": "2999-01-01",
                "with_att": {"residency_requirement": residency}}

    def build(self, old, new):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            if old is not None:
                Path(a, "scholarships.json").write_text(json.dumps({"items": old}), encoding="utf-8")
            Path(b, "scholarships.json").write_text(json.dumps({"items": new}), encoding="utf-8")
            return notify.build(a, b, self.PROFILE, notify.load_rules(), "2026-11-26")

    def test_only_new_and_matching(self):
        body = self.build([self.item("1")], [self.item("1"), self.item("2"), self.item("3", "高雄市")])
        self.assertIn("公告2", body)
        self.assertNotIn("公告1", body)
        self.assertNotIn("公告3", body)
        self.assertNotIn("@", body)
        self.assertNotIn("新竹", body)

    def test_no_old_data_no_notice(self):
        self.assertEqual(self.build(None, [self.item("1")]), "")


if __name__ == "__main__":
    unittest.main()
