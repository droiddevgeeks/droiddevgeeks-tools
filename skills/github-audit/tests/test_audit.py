"""Tests for backlog, PR-size, ref-parsing, portfolio, and author aggregation."""

import unittest
from datetime import datetime, timezone, date

from scripts import audit


def _pr(number, *, state="MERGED", created=None, updated=None,
        additions=0, deletions=0, changed=0):
    return {
        "number": number,
        "state": state,
        "createdAt": created,
        "updatedAt": updated,
        "additions": additions,
        "deletions": deletions,
        "changedFiles": changed,
    }


NOW = datetime(2026, 6, 26, tzinfo=timezone.utc)


class SizeDistributionTests(unittest.TestCase):
    def test_buckets_one_pr_per_band(self):
        prs = [
            _pr(1, additions=5, deletions=0),     # 5    -> XS
            _pr(2, additions=20, deletions=10),   # 30   -> S
            _pr(3, additions=60, deletions=40),   # 100  -> M
            _pr(4, additions=200, deletions=100), # 300  -> L
            _pr(5, additions=500, deletions=300), # 800  -> XL
        ]
        out = audit.size_distribution(prs)
        counts = {b["label"]: b["count"] for b in out["buckets"]}
        self.assertEqual(counts, {"XS": 1, "S": 1, "M": 1, "L": 1, "XL": 1})

    def test_boundaries_are_lower_inclusive(self):
        prs = [_pr(1, additions=9), _pr(2, additions=10), _pr(3, additions=50),
               _pr(4, additions=200), _pr(5, additions=500)]
        counts = {b["label"]: b["count"] for b in audit.size_distribution(prs)["buckets"]}
        self.assertEqual(counts, {"XS": 1, "S": 1, "M": 1, "L": 1, "XL": 1})

    def test_median_and_p90(self):
        prs = [_pr(i, additions=v) for i, v in enumerate([5, 30, 100, 300, 800])]
        out = audit.size_distribution(prs)
        self.assertEqual(out["median_lines"], 100)
        self.assertEqual(out["p90_lines"], 800)

    def test_largest_pr_reported(self):
        prs = [_pr(1, additions=5), _pr(2, additions=500, deletions=300)]
        out = audit.size_distribution(prs)
        self.assertEqual(out["largest"]["number"], 2)
        self.assertEqual(out["largest"]["lines"], 800)

    def test_empty_is_safe(self):
        out = audit.size_distribution([])
        self.assertEqual(out["median_lines"], 0)
        self.assertEqual(out["p90_lines"], 0)
        self.assertIsNone(out["largest"])
        self.assertEqual(sum(b["count"] for b in out["buckets"]), 0)


class BacklogTests(unittest.TestCase):
    def test_only_open_prs_counted(self):
        prs = [
            _pr(1, state="OPEN", created="2026-06-24T00:00:00Z", updated="2026-06-24T00:00:00Z"),
            _pr(2, state="MERGED", created="2026-06-24T00:00:00Z", updated="2026-06-24T00:00:00Z"),
            _pr(3, state="CLOSED", created="2026-06-24T00:00:00Z", updated="2026-06-24T00:00:00Z"),
        ]
        self.assertEqual(audit.backlog(prs, NOW)["open_total"], 1)

    def test_age_buckets(self):
        prs = [
            _pr(1, state="OPEN", created="2026-06-24T00:00:00Z", updated="2026-06-24T00:00:00Z"),
            _pr(2, state="OPEN", created="2026-06-10T00:00:00Z", updated="2026-06-25T00:00:00Z"),
            _pr(3, state="OPEN", created="2026-04-01T00:00:00Z", updated="2026-06-25T00:00:00Z"),
            _pr(4, state="OPEN", created="2026-01-01T00:00:00Z", updated="2026-06-25T00:00:00Z"),
        ]
        counts = {b["label"]: b["count"] for b in audit.backlog(prs, NOW)["age_buckets"]}
        self.assertEqual(counts, {"<7d": 1, "7-30d": 1, "30-90d": 1, ">90d": 1})

    def test_stale_count(self):
        prs = [
            _pr(1, state="OPEN", created="2026-01-01T00:00:00Z", updated="2026-06-25T00:00:00Z"),
            _pr(2, state="OPEN", created="2026-01-01T00:00:00Z", updated="2026-04-01T00:00:00Z"),
        ]
        self.assertEqual(audit.backlog(prs, NOW)["stale_30d"], 1)

    def test_oldest_days(self):
        prs = [
            _pr(1, state="OPEN", created="2026-06-24T00:00:00Z", updated="2026-06-24T00:00:00Z"),
            _pr(2, state="OPEN", created="2026-01-01T00:00:00Z", updated="2026-06-25T00:00:00Z"),
        ]
        out = audit.backlog(prs, NOW)
        self.assertEqual(out["oldest_days"],
                         (NOW.date() - audit.parse_dt("2026-01-01T00:00:00Z").date()).days)

    def test_empty_is_safe(self):
        out = audit.backlog([], NOW)
        self.assertEqual(out["open_total"], 0)
        self.assertEqual(out["stale_30d"], 0)
        self.assertIsNone(out["oldest_days"])


class NormalizeRepoTests(unittest.TestCase):
    def test_bare_owner_name_unchanged(self):
        self.assertEqual(audit.normalize_repo("cli/cli"), "cli/cli")

    def test_https_url(self):
        self.assertEqual(
            audit.normalize_repo("https://github.com/danielsogl/awesome-cordova-plugins"),
            "danielsogl/awesome-cordova-plugins")

    def test_https_url_with_git_suffix_and_slash(self):
        self.assertEqual(audit.normalize_repo("https://github.com/cli/cli.git/"), "cli/cli")

    def test_scp_ssh_form(self):
        self.assertEqual(audit.normalize_repo("git@github.com:cli/cli.git"), "cli/cli")

    def test_ssh_url_scheme(self):
        self.assertEqual(audit.normalize_repo("ssh://git@github.com/cli/cli.git"), "cli/cli")

    def test_deep_link_truncated_to_repo(self):
        self.assertEqual(audit.normalize_repo("https://github.com/cli/cli/pull/42"), "cli/cli")

    def test_host_without_scheme(self):
        self.assertEqual(audit.normalize_repo("github.com/cli/cli"), "cli/cli")

    def test_repo_name_with_dot_preserved(self):
        self.assertEqual(audit.normalize_repo("https://github.com/foo/bar.js"), "foo/bar.js")

    def test_surrounding_whitespace(self):
        self.assertEqual(audit.normalize_repo("  cli/cli \n"), "cli/cli")

    def test_missing_name_raises(self):
        with self.assertRaises(ValueError):
            audit.normalize_repo("https://github.com/cli")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            audit.normalize_repo("   ")


class NormalizeOwnerTests(unittest.TestCase):
    def test_bare_owner(self):
        self.assertEqual(audit.normalize_owner("cashfree-tech"), "cashfree-tech")

    def test_owner_from_url(self):
        self.assertEqual(audit.normalize_owner("https://github.com/cashfree-tech"), "cashfree-tech")

    def test_owner_from_repo_url(self):
        self.assertEqual(audit.normalize_owner("https://github.com/cli/cli"), "cli")

    def test_owner_trailing_slash(self):
        self.assertEqual(audit.normalize_owner("github.com/torvalds/"), "torvalds")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            audit.normalize_owner("   ")


class TransientDetectionTests(unittest.TestCase):
    def test_502_is_transient(self):
        self.assertTrue(audit._is_transient("HTTP 502: 502 Bad Gateway"))

    def test_timeout_is_transient(self):
        self.assertTrue(audit._is_transient("dial tcp: i/o timeout"))

    def test_404_is_not_transient(self):
        self.assertFalse(audit._is_transient("HTTP 404: Not Found"))

    def test_auth_is_not_transient(self):
        self.assertFalse(audit._is_transient("authentication required"))


def _report(repo, *, opened=0, merged=0, closed=0, hotfix=0, revert=0,
            contribs=None, open_total=0, stale=0, oldest=None, median=0, p90=0):
    return {
        "repo": repo,
        "totals": {"opened": opened, "merged": merged, "closed": closed,
                   "hotfix": hotfix, "revert": revert,
                   "contributors": len(contribs or [])},
        "contributors": [{"login": l, "count": c} for l, c in (contribs or {}).items()]
            if isinstance(contribs, dict) else (contribs or []),
        "backlog": {"open_total": open_total, "stale_30d": stale, "oldest_days": oldest},
        "size": {"median_lines": median, "p90_lines": p90},
    }


def _entry(report, **meta):
    base = {"stars": 0, "isFork": False, "isArchived": False, "pushedAt": None, "limit_hit": False}
    base.update(meta)
    return {"meta": base, "report": report}


class BuildPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            _entry(_report("o/quiet", opened=0, merged=0, contribs={"alice": 0})),
            _entry(_report("o/busy", opened=20, merged=15, closed=18,
                           contribs={"alice": 8, "app/dependabot": 12},
                           open_total=5, stale=3, oldest=120, median=80, p90=400),
                   stars=300),
            _entry(_report("o/mid", opened=5, merged=4, closed=4,
                           contribs={"bob": 5}, open_total=2, stale=1, median=40),
                   stars=50, isFork=True),
        ]

    def test_org_totals_summed(self):
        p = audit.build_portfolio("o", self.entries, NOW, 4, 3)
        self.assertEqual(p["totals"]["opened"], 25)
        self.assertEqual(p["totals"]["merged"], 19)
        self.assertEqual(p["totals"]["open_backlog"], 7)
        self.assertEqual(p["totals"]["stale"], 4)
        self.assertEqual(p["totals"]["repos"], 3)
        self.assertEqual(p["totals"]["active_repos"], 2)

    def test_unique_contributors_union(self):
        p = audit.build_portfolio("o", self.entries, NOW, 4, 3)
        self.assertEqual(p["totals"]["contributors"], 3)

    def test_org_top_contributors_summed_and_sorted(self):
        p = audit.build_portfolio("o", self.entries, NOW, 4, 3)
        top = p["contributors"]
        self.assertEqual(top[0]["login"], "app/dependabot")
        self.assertEqual(top[0]["count"], 12)
        alice = next(c for c in top if c["login"] == "alice")
        self.assertEqual(alice["count"], 8)

    def test_repos_ranked_by_activity(self):
        p = audit.build_portfolio("o", self.entries, NOW, 4, 3)
        self.assertEqual([r["repo"] for r in p["repos"]], ["o/busy", "o/mid", "o/quiet"])

    def test_repo_meta_carried_through(self):
        p = audit.build_portfolio("o", self.entries, NOW, 4, 3)
        mid = next(r for r in p["repos"] if r["repo"] == "o/mid")
        self.assertTrue(mid["isFork"])
        self.assertEqual(mid["stars"], 50)

    def test_empty_portfolio_safe(self):
        p = audit.build_portfolio("o", [], NOW, 4, 3)
        self.assertEqual(p["totals"]["repos"], 0)
        self.assertEqual(p["totals"]["contributors"], 0)
        self.assertEqual(p["repos"], [])


def _spr(number, state, created, closed, repo, updated=None):
    return {
        "number": number, "state": state,
        "createdAt": created, "closedAt": closed or "0001-01-01T00:00:00Z",
        "updatedAt": updated or created,
        "repository": {"nameWithOwner": repo},
    }


class AuthorPRNormTests(unittest.TestCase):
    def test_merged_maps_to_mergedAt(self):
        n = audit._author_pr(_spr(1, "merged", "2026-05-01T00:00:00Z", "2026-05-03T00:00:00Z", "org/a"))
        self.assertEqual(n["mergedAt"], "2026-05-03T00:00:00Z")
        self.assertIsNone(n["closedAt"])
        self.assertEqual(n["repo"], "org/a")
        self.assertEqual(n["owner"], "org")

    def test_closed_unmerged_maps_to_closedAt(self):
        n = audit._author_pr(_spr(2, "closed", "2026-05-01T00:00:00Z", "2026-05-02T00:00:00Z", "org/a"))
        self.assertIsNone(n["mergedAt"])
        self.assertEqual(n["closedAt"], "2026-05-02T00:00:00Z")

    def test_open_has_neither(self):
        n = audit._author_pr(_spr(3, "open", "2026-05-01T00:00:00Z", None, "org/a"))
        self.assertIsNone(n["mergedAt"])
        self.assertIsNone(n["closedAt"])
        self.assertEqual(n["state"], "open")


class AuthorBreakdownTests(unittest.TestCase):
    def setUp(self):
        self.norm = [audit._author_pr(p) for p in [
            _spr(1, "merged", "2026-05-01T00:00:00Z", "2026-05-03T00:00:00Z", "cashfree/sdk"),
            _spr(2, "merged", "2026-05-05T00:00:00Z", "2026-05-06T00:00:00Z", "cashfree/sdk"),
            _spr(3, "closed", "2026-05-02T00:00:00Z", "2026-05-04T00:00:00Z", "cashfree/sdk"),
            _spr(4, "open", "2026-05-10T00:00:00Z", None, "cashfree-tech/api"),
            _spr(5, "merged", "2026-04-10T00:00:00Z", "2026-04-12T00:00:00Z", "personal/toy"),
            _spr(6, "merged", "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z", "old/repo"),
        ]]
        self.since = date(2026, 4, 1)

    def test_repo_grouping_and_counts(self):
        repos, _ = audit.author_breakdown(self.norm, self.since)
        sdk = next(r for r in repos if r["repo"] == "cashfree/sdk")
        self.assertEqual(sdk["opened"], 3)
        self.assertEqual(sdk["merged"], 2)
        self.assertEqual(sdk["closed"], 1)

    def test_org_grouping(self):
        _, orgs = audit.author_breakdown(self.norm, self.since)
        owners = {o["owner"]: o for o in orgs}
        self.assertIn("cashfree", owners)
        self.assertIn("cashfree-tech", owners)
        self.assertEqual(owners["cashfree-tech"]["open"], 1)

    def test_before_window_excluded(self):
        repos, _ = audit.author_breakdown(self.norm, self.since)
        self.assertNotIn("old/repo", [r["repo"] for r in repos])

    def test_repos_ranked_by_activity(self):
        repos, _ = audit.author_breakdown(self.norm, self.since)
        self.assertEqual(repos[0]["repo"], "cashfree/sdk")


class BuildAuthorReportTests(unittest.TestCase):
    def setUp(self):
        self.prs = [
            _spr(1, "merged", "2026-06-02T00:00:00Z", "2026-06-04T00:00:00Z", "cashfree/sdk"),
            _spr(2, "closed", "2026-06-03T00:00:00Z", "2026-06-05T00:00:00Z", "cashfree/sdk"),
            _spr(3, "open", "2026-06-01T00:00:00Z", None, "cashfree-tech/api", updated="2026-06-01T00:00:00Z"),
        ]

    def test_totals(self):
        r = audit.build_author_report(self.prs, "me", NOW, 4, 3)
        self.assertEqual(r["totals"]["opened"], 3)
        self.assertEqual(r["totals"]["merged"], 1)
        self.assertEqual(r["totals"]["closed"], 1)
        self.assertEqual(r["totals"]["repos"], 2)
        self.assertEqual(r["totals"]["orgs"], 2)
        self.assertEqual(r["totals"]["merge_rate"], 33)

    def test_has_flow_and_backlog(self):
        r = audit.build_author_report(self.prs, "me", NOW, 4, 3)
        self.assertIn("weekly", r)
        self.assertIn("monthly", r)
        self.assertEqual(r["backlog"]["open_total"], 1)
        self.assertEqual(r["author"], "me")

    def test_empty_safe(self):
        r = audit.build_author_report([], "me", NOW, 4, 3)
        self.assertEqual(r["totals"]["opened"], 0)
        self.assertEqual(r["totals"]["merge_rate"], 0)
        self.assertEqual(r["repos"], [])


class ReportIntegrationTests(unittest.TestCase):
    def test_report_includes_backlog_and_size(self):
        prs = [
            _pr(1, state="OPEN", created="2026-06-24T00:00:00Z", updated="2026-06-24T00:00:00Z", additions=5),
            _pr(2, state="MERGED", created="2026-06-10T00:00:00Z", updated="2026-06-11T00:00:00Z", additions=600),
        ]
        report = audit.build_report(prs, "owner/name", NOW)
        self.assertIn("backlog", report)
        self.assertIn("size", report)
        self.assertEqual(report["backlog"]["open_total"], 1)


if __name__ == "__main__":
    unittest.main()
