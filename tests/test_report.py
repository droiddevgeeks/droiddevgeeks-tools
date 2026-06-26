import unittest
from datetime import datetime, timezone
from scripts.audit import (
    parse_dt, week_start, month_key,
    bucket_by_week, bucket_by_month, contributors, build_report,
)

# Fixed "now": Friday 2026-06-26. Current ISO week starts Mon 2026-06-22.
NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)


def mkpr(login, created, closed=None, merged=None, branch="feature/x",
         title="x", labels=None):
    return {
        "author": {"login": login} if login else None,
        "createdAt": created, "closedAt": closed, "mergedAt": merged,
        "headRefName": branch, "title": title, "labels": labels or [],
    }


class TestHelpers(unittest.TestCase):
    def test_parse_dt_z(self):
        self.assertEqual(parse_dt("2026-06-26T00:00:00Z").year, 2026)

    def test_parse_dt_none(self):
        self.assertIsNone(parse_dt(None))
        self.assertIsNone(parse_dt(""))

    def test_week_start_is_monday(self):
        self.assertEqual(week_start(datetime(2026, 6, 26).date()).isoformat(), "2026-06-22")

    def test_month_key(self):
        self.assertEqual(month_key(datetime(2026, 6, 26).date()), "2026-06")


class TestBuckets(unittest.TestCase):
    def test_weekly_opened_closed_merged(self):
        prs = [mkpr("a", "2026-06-23T00:00:00Z", "2026-06-24T00:00:00Z", "2026-06-24T00:00:00Z")]
        wk = bucket_by_week(prs, NOW, weeks=4)
        self.assertEqual(len(wk), 4)
        self.assertEqual(wk[-1]["week_start"], "2026-06-22")
        self.assertEqual(wk[-1]["opened"], 1)
        self.assertEqual(wk[-1]["closed"], 1)
        self.assertEqual(wk[-1]["merged"], 1)

    def test_flow_not_cohort(self):
        # opened in oldest week, merged in newest week -> counted separately
        prs = [mkpr("a", "2026-06-01T00:00:00Z", "2026-06-24T00:00:00Z", "2026-06-24T00:00:00Z")]
        wk = bucket_by_week(prs, NOW, weeks=4)
        self.assertEqual(wk[0]["opened"], 1)
        self.assertEqual(wk[0]["merged"], 0)
        self.assertEqual(wk[-1]["merged"], 1)

    def test_outside_window_excluded(self):
        prs = [mkpr("a", "2026-01-01T00:00:00Z")]
        wk = bucket_by_week(prs, NOW, weeks=4)
        self.assertEqual(sum(b["opened"] for b in wk), 0)

    def test_monthly(self):
        prs = [mkpr("a", "2026-05-10T00:00:00Z")]
        mo = bucket_by_month(prs, NOW, months=3)
        self.assertEqual([m["month"] for m in mo], ["2026-04", "2026-05", "2026-06"])
        self.assertEqual(mo[1]["opened"], 1)


class TestContributors(unittest.TestCase):
    def test_counts_and_sort(self):
        prs = [mkpr("a", "2026-06-23T00:00:00Z"),
               mkpr("b", "2026-06-23T00:00:00Z"),
               mkpr("a", "2026-06-23T00:00:00Z")]
        c = contributors(prs)
        self.assertEqual(c[0], {"login": "a", "count": 2})
        self.assertEqual(c[1], {"login": "b", "count": 1})

    def test_null_author(self):
        c = contributors([mkpr(None, "2026-06-23T00:00:00Z")])
        self.assertEqual(c[0]["login"], "(unknown)")


class TestBuildReport(unittest.TestCase):
    def test_shape_and_totals(self):
        prs = [
            mkpr("a", "2026-06-23T00:00:00Z", "2026-06-24T00:00:00Z", "2026-06-24T00:00:00Z",
                 branch="hotfix/x"),
            mkpr("b", "2026-06-23T00:00:00Z", title='Revert "y"'),
        ]
        r = build_report(prs, "owner/name", NOW)
        self.assertEqual(r["repo"], "owner/name")
        self.assertEqual(r["totals"]["opened"], 2)
        self.assertEqual(r["totals"]["closed"], 1)
        self.assertEqual(r["totals"]["merged"], 1)
        self.assertEqual(r["totals"]["hotfix"], 1)
        self.assertEqual(r["totals"]["revert"], 1)
        self.assertEqual(r["totals"]["contributors"], 2)
        self.assertIn("weekly", r)
        self.assertIn("monthly", r)
        self.assertIn("since", r["window"])

    def test_empty_input(self):
        r = build_report([], "owner/name", NOW)
        self.assertEqual(r["totals"]["opened"], 0)
        self.assertEqual(r["contributors"], [])


if __name__ == "__main__":
    unittest.main()
