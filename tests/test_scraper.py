"""抓取與判斷規則的測試（不連網）。執行：python -m unittest discover tests"""
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime
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


class Deadlines(unittest.TestCase):
    def check(self, title, expected, detail="", posted=datetime(2026, 9, 1)):
        got = scrape.find_deadline(title, detail, posted)
        self.assertEqual(got and got.strftime("%Y-%m-%d"), expected, title or detail)

    def test_title_wording(self):
        self.check("張榮發基金會清寒學生助學金。(※10/12 中午12點截止)", "2026-10-12")
        self.check("轉知115-1屏東縣清寒優秀學生獎學金(9/29 中午截止)", "2026-09-29")
        self.check("有意者請於115年10月27日(二)前繳交申請資料", "2026-10-27")
        self.check("有意申請者請於9月30日（星期三）前繳交", "2026-09-30")
        self.check("115-1學產基金助學金，申請至10/6(星期二)截止。", "2026-10-06")
        self.check("嘉義西區扶輪社第22屆獎學金。(11/2~12/21)", "2026-12-21")

    def test_detail_period(self):
        self.check("學雜費預先減免開放申請", "2026-12-31", "二、申請期間及路徑： 115年12月1日至12月31日止")

    def test_request_sentence(self):
        got = scrape.find_request_deadline("自行申請：請於115年10月28日(三)前郵寄。學校送件：請於115年10月19日(一)前", datetime(2026, 10, 1))
        self.assertEqual(got, datetime(2026, 10, 28))

    def test_next_year(self):
        self.check("獎學金(1/15截止)", "2027-01-15", posted=datetime(2026, 12, 1))

    def test_no_date(self):
        self.check("轉知115-1清寒獎學金", None, "低收入戶證明有效期限至12月31日")


class Cleanup(unittest.TestCase):
    def test_security_alert_excluded(self):
        self.assertTrue(scrape.is_notice_only(obj(title="【漏洞預警】Cisco 高風險安全漏洞")))

    def test_duplicates(self):
        items = [{"title": "(再次公告)【重要】★學產基金助學金", "deadline_iso": "2026-10-06"},
                 {"title": "【重要】★學產基金助學金", "deadline_iso": "2026-10-06"},
                 {"title": "【重要】★學產基金助學金", "deadline_iso": "2027-03-06"}]
        self.assertEqual(scrape.drop_duplicates(items), [items[0], items[2]])


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
